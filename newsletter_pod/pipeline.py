from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from uuid import uuid4

from .ingestion import RSSIngestionService
from .mailer import Mailer
from .models import EpisodeRecord, PodcastUxConfig, PublishStatus, RunRecord, RunResult, SourceDefinition, SourceItemRef
from .podcast_api import PodcastApiClient, PodcastApiUnavailable
from .prompting import build_digest_prompt
from .repository import Repository
from .retry_policy import RetryPolicy
from .storage import AudioStorage
from .utils import utc_now


@dataclass
class DigestPipeline:
    sources: list[SourceDefinition]
    repository: Repository
    ingestion_service: RSSIngestionService
    podcast_client: PodcastApiClient
    storage: AudioStorage
    mailer: Mailer
    retry_policy: RetryPolicy
    podcast_ux: PodcastUxConfig = field(default_factory=PodcastUxConfig)
    app_base_url: str = "http://localhost:8000"
    feed_token: str = "change-me"
    publish_summary_email_enabled: bool = False

    def run_daily_digest(self, now_utc: datetime | None = None, force: bool = False) -> RunResult:
        now_utc = now_utc or utc_now()
        run_date = self.retry_policy.local_date(now_utc)
        day_state = self.repository.get_day_state(run_date)
        run_id = uuid4().hex

        decision = self.retry_policy.evaluate(now_utc, day_state, force=force)
        if not decision.should_attempt:
            alert_sent = False
            if decision.should_send_failure_alert:
                self._send_cutoff_alert(run_date)
                alert_sent = True

            run = RunRecord(
                id=run_id,
                run_date=run_date,
                started_at=now_utc,
                completed_at=now_utc,
                status=PublishStatus.SKIPPED,
                message=decision.reason,
                alert_sent=alert_sent,
            )
            self.repository.save_run(run)
            return RunResult(run_id=run_id, status=run.status, message=run.message)

        started_at = now_utc
        candidate_count = 0

        try:
            ingestion = self.ingestion_service.fetch_new_items(self.sources)
            candidate_count = len(ingestion.items)

            if candidate_count == 0:
                self.repository.update_source_cursors(ingestion.cursor_updates)
                run = RunRecord(
                    id=run_id,
                    run_date=run_date,
                    started_at=started_at,
                    completed_at=utc_now(),
                    status=PublishStatus.NO_CONTENT,
                    message="No new newsletter items",
                    candidate_count=0,
                )
                self.repository.save_run(run)
                return RunResult(run_id=run_id, status=run.status, message=run.message)

            prompt = build_digest_prompt(ingestion.items, run_date=run_date, ux=self.podcast_ux)
            title_hint = f"{run_date.isoformat()} daily briefing"

            try:
                generated = self.podcast_client.generate(prompt=prompt, title=title_hint)
            except PodcastApiUnavailable as exc:
                self.repository.update_source_cursors(ingestion.cursor_updates)
                msg = f"Podcast API unavailable: {exc}"
                self.mailer.send(
                    subject="Newsletter digest status: waiting for Podcast API access",
                    body=self._build_pre_access_email(ingestion.items, msg),
                )
                run = RunRecord(
                    id=run_id,
                    run_date=run_date,
                    started_at=started_at,
                    completed_at=utc_now(),
                    status=PublishStatus.PRE_ACCESS,
                    message=msg,
                    candidate_count=candidate_count,
                )
                self.repository.save_run(run)
                return RunResult(
                    run_id=run_id,
                    status=run.status,
                    message=run.message,
                    candidate_count=candidate_count,
                )

            episode_id = f"{run_date.isoformat()}-{uuid4().hex[:8]}"
            object_name, size_bytes = self.storage.upload_audio(
                episode_id=episode_id,
                audio_bytes=generated.audio_bytes,
                mime_type=generated.mime_type,
            )

            show_notes = self._build_show_notes(generated.show_notes, ingestion.items)
            source_refs = [
                SourceItemRef(
                    source_id=item.source_id,
                    source_name=item.source_name,
                    title=item.title,
                    link=item.link,
                    guid=item.guid,
                )
                for item in ingestion.items
            ]

            episode = EpisodeRecord(
                id=episode_id,
                title=generated.episode_title,
                description=show_notes,
                published_at=utc_now(),
                audio_object_name=object_name,
                audio_mime_type=generated.mime_type,
                audio_size_bytes=size_bytes,
                source_item_refs=source_refs,
                duration_seconds=generated.duration_seconds,
            )

            self.repository.save_episode(episode)
            self.repository.update_source_cursors(ingestion.cursor_updates)
            if self.publish_summary_email_enabled:
                self.mailer.send(
                    subject=f"Newsletter digest published: {episode.title}",
                    body=self._build_publish_summary_email(
                        episode=episode,
                        candidate_count=candidate_count,
                    ),
                )

            run = RunRecord(
                id=run_id,
                run_date=run_date,
                started_at=started_at,
                completed_at=utc_now(),
                status=PublishStatus.PUBLISHED,
                message="Episode published",
                candidate_count=candidate_count,
                published_episode_id=episode_id,
            )
            self.repository.save_run(run)

            return RunResult(
                run_id=run_id,
                status=run.status,
                message=run.message,
                episode_id=episode_id,
                candidate_count=candidate_count,
            )

        except Exception as exc:
            current_state = self.repository.get_day_state(run_date)
            alert_sent = False
            local_now = now_utc.astimezone(self.retry_policy.tz)
            if local_now.time() >= self.retry_policy.cutoff_local and not current_state.has_alert_sent:
                self._send_cutoff_alert(run_date)
                alert_sent = True

            run = RunRecord(
                id=run_id,
                run_date=run_date,
                started_at=started_at,
                completed_at=utc_now(),
                status=PublishStatus.FAILED,
                message=str(exc),
                candidate_count=candidate_count,
                alert_sent=alert_sent,
            )
            self.repository.save_run(run)

            return RunResult(
                run_id=run_id,
                status=run.status,
                message=run.message,
                candidate_count=candidate_count,
            )

    def _build_show_notes(self, generated_notes: str, items: list) -> str:
        lines: list[str] = []
        notes = (generated_notes or "").strip()
        if notes:
            lines.append(notes)
            lines.append("")

        lines.append("Sources")
        seen: set[str] = set()
        for item in items:
            if item.link in seen:
                continue
            seen.add(item.link)
            lines.append(f"- {item.source_name}: {item.link}")
        return "\n".join(lines)

    def _build_pre_access_email(self, items, detail: str) -> str:
        lines = [
            "Podcast API is unavailable, so no episode was published.",
            detail,
            "",
            f"Candidate newsletter items: {len(items)}",
            "",
            "Sources included:",
        ]
        for item in items:
            lines.append(f"- {item.source_name}: {item.title}")
        return "\n".join(lines)

    def _build_publish_summary_email(self, episode: EpisodeRecord, candidate_count: int) -> str:
        feed_url = f"{self.app_base_url.rstrip('/')}/feed/{self.feed_token}.xml"
        media_url = f"{self.app_base_url.rstrip('/')}/media/{self.feed_token}/{episode.id}.mp3"
        lines = [
            "A new newsletter digest was published.",
            "",
            f"Title: {episode.title}",
            f"Published at: {episode.published_at.isoformat()}",
            f"Candidate items processed: {candidate_count}",
        ]
        if episode.duration_seconds is not None:
            lines.append(f"Duration seconds: {episode.duration_seconds}")
        lines.extend(
            [
                "",
                "Delivery",
                f"- Private Apple Podcasts feed: {feed_url}",
                f"- Direct audio URL: {media_url}",
                "",
                "Show notes",
                episode.description,
            ]
        )
        return "\n".join(lines)

    def _send_cutoff_alert(self, run_date) -> None:
        subject = f"Newsletter digest failed before cutoff ({run_date.isoformat()})"
        body = (
            "No successful daily digest publish was completed before cutoff time. "
            "Please inspect Cloud Run logs and rerun POST /jobs/run-digest with force=true if needed."
        )
        self.mailer.send(subject=subject, body=body)
