from __future__ import annotations

import secrets
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional
from uuid import uuid4
from zoneinfo import ZoneInfo

import feedparser
import requests

from .auth import AppleIdentityVerifier, SessionManager
from .config import Settings, load_sources
from .costing import estimate_generation_cost
from .ingestion import RSSIngestionService
from .mailer import Mailer
from .models import PodcastUxConfig, PublishStatus, SourceDefinition, SourceItemRef
from .podcast_api import PodcastApiClient
from .prompting import build_digest_prompt
from .storage import AudioStorage
from .user_models import (
    BillingEventRecord,
    CostRecord,
    DeliveryScheduleRecord,
    FeedTokenRecord,
    PodcastProfileRecord,
    SubscriptionRecord,
    UserEntitlements,
    UserEpisodeRecord,
    UserRecord,
    UserRunRecord,
    UserSourceRecord,
)
from .user_repository import ControlPlaneRepository
from .utils import link_hash, utc_now

COMPLETED_RUN_STATUSES = {PublishStatus.PUBLISHED.value, PublishStatus.NO_CONTENT.value}
WEEKDAY_NAMES = [
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
]


class ControlPlaneError(RuntimeError):
    pass


@dataclass
class TaskEnqueuer:
    def enqueue_user_generation(self, user_id: str, force: bool = False) -> dict[str, Any]:
        raise NotImplementedError


@dataclass
class InMemoryTaskEnqueuer(TaskEnqueuer):
    jobs: list[dict[str, Any]] = field(default_factory=list)

    def enqueue_user_generation(self, user_id: str, force: bool = False) -> dict[str, Any]:
        job = {"user_id": user_id, "force": force}
        self.jobs.append(job)
        return job


@dataclass
class CloudTasksEnqueuer(TaskEnqueuer):
    queue_path: str
    service_url: str
    service_account_email: Optional[str]
    job_trigger_token: Optional[str]
    client: Any = None

    def enqueue_user_generation(self, user_id: str, force: bool = False) -> dict[str, Any]:
        if self.client is None:
            from google.cloud import tasks_v2

            self.client = tasks_v2.CloudTasksClient()
        from google.cloud import tasks_v2

        headers = {"Content-Type": "application/json"}
        if self.job_trigger_token:
            headers["X-Job-Trigger-Token"] = self.job_trigger_token

        task: dict[str, Any] = {
            "http_request": {
                "http_method": tasks_v2.HttpMethod.POST,
                "url": f"{self.service_url.rstrip('/')}/jobs/process-user-podcast",
                "headers": headers,
                "body": f'{{"user_id":"{user_id}","force":{str(force).lower()}}}'.encode("utf-8"),
            }
        }
        if self.service_account_email:
            task["http_request"]["oidc_token"] = {"service_account_email": self.service_account_email}

        created = self.client.create_task(parent=self.queue_path, task=task)
        return {"name": created.name, "user_id": user_id, "force": force}


class _UserCursorRepositoryAdapter:
    def __init__(self, repository: ControlPlaneRepository, user_id: str) -> None:
        self._repository = repository
        self._user_id = user_id

    def get_source_cursor(self, source_id: str) -> Optional[datetime]:
        return self._repository.get_user_source_cursor(self._user_id, source_id)

    def update_source_cursors(self, cursors: dict[str, datetime]) -> None:
        self._repository.update_user_source_cursors(self._user_id, cursors)


@dataclass
class ControlPlaneService:
    settings: Settings
    repository: ControlPlaneRepository
    storage: AudioStorage
    podcast_client: PodcastApiClient
    mailer: Mailer
    session_manager: SessionManager
    apple_identity_verifier: AppleIdentityVerifier
    task_enqueuer: TaskEnqueuer

    def __post_init__(self) -> None:
        self._catalog = {source.id: source for source in load_sources(self.settings.sources_file)}

    def authenticate_with_apple(self, identity_token: str) -> dict[str, Any]:
        identity = self.apple_identity_verifier.verify(identity_token)
        existing_user = self.repository.get_user_by_apple_subject(identity.subject)
        is_new = existing_user is None
        user = existing_user or self._create_default_user(identity.subject, identity.email)
        if existing_user is None:
            self._persist_default_records(user)

        token, session = self.session_manager.issue(user.id)
        return {
            "session_token": token,
            "session": session.model_dump(mode="json"),
            "is_new_user": is_new,
            "user": user.model_dump(mode="json"),
            "subscription": self._get_subscription(user.id).model_dump(mode="json"),
        }

    def get_authenticated_user(self, session_token: str) -> UserRecord:
        session = self.session_manager.verify(session_token)
        user = self.repository.get_user(session.user_id)
        if not user:
            raise ControlPlaneError("User not found")
        return user

    def get_me(self, user_id: str) -> dict[str, Any]:
        user = self._require_user(user_id)
        subscription = self._get_subscription(user_id)
        entitlements = self._entitlements_for(subscription)
        return {
            "user": user.model_dump(mode="json"),
            "profile": self._get_profile(user_id).model_dump(mode="json"),
            "schedule": self._get_schedule(user_id).model_dump(mode="json"),
            "subscription": subscription.model_dump(mode="json"),
            "entitlements": entitlements.model_dump(mode="json"),
        }

    def update_me(self, user_id: str, display_name: Optional[str], timezone_name: Optional[str]) -> dict[str, Any]:
        user = self._require_user(user_id)
        if display_name is not None:
            user.display_name = display_name.strip() or user.display_name
        if timezone_name is not None:
            _validate_timezone(timezone_name)
            user.timezone = timezone_name
        user.updated_at = utc_now()
        self.repository.save_user(user)

        schedule = self._get_schedule(user_id)
        if timezone_name is not None and schedule.timezone != timezone_name:
            schedule.timezone = timezone_name
            schedule.updated_at = utc_now()
            self.repository.save_schedule(schedule)

        return self.get_me(user_id)

    def get_source_catalog(self) -> list[dict[str, Any]]:
        return [
            {
                "source_id": source.id,
                "name": source.name,
                "rss_url": source.rss_url,
                "enabled": source.enabled,
            }
            for source in self._catalog.values()
        ]

    def validate_custom_source(self, rss_url: str) -> dict[str, Any]:
        return self._build_custom_source_from_url(rss_url).model_dump(mode="json")

    def list_user_sources(self, user_id: str) -> dict[str, Any]:
        subscription = self._get_subscription(user_id)
        entitlements = self._entitlements_for(subscription)
        return {
            "sources": [source.model_dump(mode="json") for source in self.repository.list_user_sources(user_id)],
            "entitlements": entitlements.model_dump(mode="json"),
        }

    def replace_user_sources(self, user_id: str, requested_sources: list[dict[str, Any]]) -> dict[str, Any]:
        entitlements = self._entitlements_for(self._get_subscription(user_id))
        resolved: list[UserSourceRecord] = []
        seen_keys: set[str] = set()

        for item in requested_sources:
            source_id = (item.get("source_id") or "").strip()
            rss_url = (item.get("rss_url") or "").strip()
            is_custom = bool(item.get("is_custom"))

            if source_id and not is_custom:
                catalog_source = self._catalog.get(source_id)
                if not catalog_source:
                    raise ControlPlaneError(f"Unknown catalog source: {source_id}")
                source = UserSourceRecord(
                    id=f"{user_id}:{catalog_source.id}",
                    user_id=user_id,
                    source_id=catalog_source.id,
                    name=catalog_source.name,
                    rss_url=catalog_source.rss_url,
                    is_custom=False,
                    enabled=True,
                    validated_at=utc_now(),
                    created_at=utc_now(),
                    updated_at=utc_now(),
                )
            else:
                if not rss_url:
                    raise ControlPlaneError("Custom sources require rss_url")
                source = self._build_custom_source_from_url(rss_url, user_id=user_id)
                if item.get("name"):
                    source.name = item["name"].strip() or source.name

            dedupe_key = f"{source.source_id}:{source.rss_url}"
            if dedupe_key in seen_keys:
                continue
            seen_keys.add(dedupe_key)
            resolved.append(source)

        if len(resolved) > entitlements.max_sources:
            raise ControlPlaneError(f"Plan limit exceeded: max {entitlements.max_sources} sources")

        self.repository.replace_user_sources(user_id, resolved)
        return self.list_user_sources(user_id)

    def get_podcast_config(self, user_id: str) -> dict[str, Any]:
        return {
            "profile": self._get_profile(user_id).model_dump(mode="json"),
            "entitlements": self._entitlements_for(self._get_subscription(user_id)).model_dump(mode="json"),
        }

    def update_podcast_config(
        self,
        user_id: str,
        title: Optional[str],
        format_preset: Optional[str],
        host_primary_name: Optional[str],
        host_secondary_name: Optional[str],
        guest_names: Optional[list[str]],
        desired_duration_minutes: Optional[int],
    ) -> dict[str, Any]:
        profile = self._get_profile(user_id)
        entitlements = self._entitlements_for(self._get_subscription(user_id))

        if title is not None:
            profile.title = title.strip() or profile.title
        if format_preset is not None:
            _validate_format_preset(format_preset)
            profile.format_preset = format_preset
        if host_primary_name is not None:
            profile.host_primary_name = host_primary_name.strip() or profile.host_primary_name
        if host_secondary_name is not None:
            profile.host_secondary_name = host_secondary_name.strip() or None
        if guest_names is not None:
            profile.guest_names = [guest.strip() for guest in guest_names if guest.strip()]
        if desired_duration_minutes is not None:
            if not (entitlements.min_duration_minutes <= desired_duration_minutes <= entitlements.max_duration_minutes):
                raise ControlPlaneError(
                    f"Duration must be between {entitlements.min_duration_minutes} and "
                    f"{entitlements.max_duration_minutes} minutes"
                )
            profile.desired_duration_minutes = desired_duration_minutes

        self._validate_profile(profile)
        profile.updated_at = utc_now()
        self.repository.save_profile(profile)
        return self.get_podcast_config(user_id)

    def get_schedule_config(self, user_id: str) -> dict[str, Any]:
        return {
            "schedule": self._get_schedule(user_id).model_dump(mode="json"),
            "entitlements": self._entitlements_for(self._get_subscription(user_id)).model_dump(mode="json"),
        }

    def update_schedule(self, user_id: str, timezone_name: Optional[str], weekdays: Optional[list[str]]) -> dict[str, Any]:
        schedule = self._get_schedule(user_id)
        entitlements = self._entitlements_for(self._get_subscription(user_id))

        if timezone_name is not None:
            _validate_timezone(timezone_name)
            schedule.timezone = timezone_name
        if weekdays is not None:
            normalized = [_normalize_weekday(day) for day in weekdays]
            if len(normalized) > entitlements.max_delivery_days:
                raise ControlPlaneError(
                    f"Plan limit exceeded: max {entitlements.max_delivery_days} delivery days"
                )
            if not normalized:
                raise ControlPlaneError("At least one delivery day is required")
            schedule.weekdays = normalized

        schedule.updated_at = utc_now()
        self.repository.save_schedule(schedule)
        return self.get_schedule_config(user_id)

    def get_feed_details(self, user_id: str) -> dict[str, Any]:
        token_record = self._get_or_create_feed_token(user_id)
        latest_episode = next(iter(self.repository.list_recent_user_episodes(user_id, limit=1)), None)
        latest_run = self._latest_run_for_user(user_id)
        subscription = self._get_subscription(user_id)
        return {
            "feed_url": f"{self.settings.app_base_url.rstrip('/')}/feeds/{token_record.token}.xml",
            "token": token_record.token,
            "latest_episode": latest_episode.model_dump(mode="json") if latest_episode else None,
            "latest_run": latest_run.model_dump(mode="json") if latest_run else None,
            "subscription": subscription.model_dump(mode="json"),
            "entitlements": self._entitlements_for(subscription).model_dump(mode="json"),
        }

    def apply_app_store_notification(self, payload: dict[str, Any]) -> dict[str, Any]:
        event = BillingEventRecord(
            id=uuid4().hex,
            user_id=(payload.get("user_id") or payload.get("app_account_token")),
            notification_type=payload.get("notification_type") or payload.get("notificationType") or "unknown",
            subtype=payload.get("subtype"),
            product_id=payload.get("product_id") or payload.get("productId"),
            raw_payload=payload,
            created_at=utc_now(),
        )
        self.repository.save_billing_event(event)

        if event.user_id:
            subscription = self._get_subscription(event.user_id)
            if event.product_id in {
                self.settings.app_store_monthly_product_id,
                self.settings.app_store_annual_product_id,
            }:
                subscription.tier = "paid"
                subscription.status = "active"
                subscription.product_id = event.product_id
            if payload.get("status") in {"expired", "revoked"}:
                subscription.tier = "free"
                subscription.status = payload.get("status")
                subscription.product_id = None
            expires_at = payload.get("expires_at")
            if expires_at:
                subscription.expires_at = _parse_client_datetime(expires_at)
            subscription.updated_at = utc_now()
            self.repository.save_subscription(subscription)

        return {
            "accepted": True,
            "event_id": event.id,
        }

    def dispatch_due_users(self, now_utc: Optional[datetime] = None) -> dict[str, Any]:
        now_utc = now_utc or utc_now()
        due_users: list[str] = []
        enqueued: list[dict[str, Any]] = []
        for schedule in self.repository.list_schedules():
            if not schedule.enabled:
                continue
            if not self._is_due(schedule, now_utc):
                continue
            if not self._should_attempt_user(schedule.user_id, schedule, now_utc):
                continue
            due_users.append(schedule.user_id)
            enqueued.append(self.task_enqueuer.enqueue_user_generation(schedule.user_id, force=False))

        return {
            "status": "ok",
            "due_user_ids": due_users,
            "enqueued_count": len(enqueued),
            "enqueued": enqueued,
        }

    def process_user_generation(
        self,
        user_id: str,
        now_utc: Optional[datetime] = None,
        force: bool = False,
    ) -> dict[str, Any]:
        now_utc = now_utc or utc_now()
        user = self._require_user(user_id)
        schedule = self._get_schedule(user_id)
        subscription = self._get_subscription(user_id)
        entitlements = self._entitlements_for(subscription)
        profile = self._get_profile(user_id)
        sources = [source for source in self.repository.list_user_sources(user_id) if source.enabled]
        local_date = now_utc.astimezone(ZoneInfo(schedule.timezone)).date()
        run_id = uuid4().hex

        if not force and not self._should_attempt_user(user_id, schedule, now_utc):
            run = UserRunRecord(
                id=run_id,
                user_id=user_id,
                local_run_date=local_date,
                started_at=now_utc,
                completed_at=now_utc,
                status=PublishStatus.SKIPPED.value,
                message="Run skipped by retry policy",
            )
            self.repository.save_user_run(run)
            return run.model_dump(mode="json")

        if not sources:
            run = UserRunRecord(
                id=run_id,
                user_id=user_id,
                local_run_date=local_date,
                started_at=now_utc,
                completed_at=now_utc,
                status=PublishStatus.NO_CONTENT.value,
                message="No configured sources",
            )
            self.repository.save_user_run(run)
            return run.model_dump(mode="json")

        source_defs = [
            SourceDefinition(id=source.source_id, name=source.name, rss_url=source.rss_url, enabled=source.enabled)
            for source in sources
        ]
        cursor_repo = _UserCursorRepositoryAdapter(self.repository, user_id)
        ingestion_service = RSSIngestionService(
            repository=cursor_repo,
            bootstrap_max_items_per_source=self.settings.podcast_bootstrap_max_items_per_source,
        )
        ingestion = ingestion_service.fetch_new_items(source_defs)
        candidate_count = len(ingestion.items)
        if candidate_count == 0:
            self.repository.update_user_source_cursors(user_id, ingestion.cursor_updates)
            run = UserRunRecord(
                id=run_id,
                user_id=user_id,
                local_run_date=local_date,
                started_at=now_utc,
                completed_at=utc_now(),
                status=PublishStatus.NO_CONTENT.value,
                message="No new source items",
                candidate_count=0,
            )
            self.repository.save_user_run(run)
            return run.model_dump(mode="json")

        items = ingestion.items
        dropped_count = 0
        cap_hit = False
        if len(items) > entitlements.max_items_per_episode:
            cap_hit = True
            dropped_count = len(items) - entitlements.max_items_per_episode
            items = items[-entitlements.max_items_per_episode :]

        guest_name = self._current_guest_name(profile, user_id)
        ux = self._build_user_ux(profile, guest_name)
        prompt = build_digest_prompt(items, run_date=local_date, ux=ux)
        title_hint = f"{local_date.isoformat()} weekly briefing"
        generated = self.podcast_client.generate(prompt=prompt, title=title_hint)

        episode_id = f"{user_id[:8]}-{local_date.isoformat()}-{uuid4().hex[:8]}"
        object_name, size_bytes = self.storage.upload_audio(
            episode_id=episode_id,
            audio_bytes=generated.audio_bytes,
            mime_type=generated.mime_type,
        )
        show_notes = self._build_show_notes(generated.show_notes, items, cap_hit, dropped_count)
        episode = UserEpisodeRecord(
            id=episode_id,
            user_id=user_id,
            title=generated.episode_title,
            description=show_notes,
            published_at=utc_now(),
            audio_object_name=object_name,
            audio_mime_type=generated.mime_type,
            audio_size_bytes=size_bytes,
            source_item_refs=[
                SourceItemRef(
                    source_id=item.source_id,
                    source_name=item.source_name,
                    title=item.title,
                    link=item.link,
                    guid=item.guid,
                )
                for item in items
            ],
            duration_seconds=generated.duration_seconds,
            processed_item_count=len(items),
            dropped_item_count=dropped_count,
            cap_hit=cap_hit,
            guest_name=guest_name,
        )
        self.repository.save_user_episode(episode)
        self.repository.update_user_source_cursors(user_id, ingestion.cursor_updates)

        transcript_text = generated.transcript or "\n\n".join(
            f"{segment.speaker}: {segment.text}" for segment in generated.audio_segments
        )
        cost_estimate = estimate_generation_cost(
            prompt_text=prompt,
            transcript_text=transcript_text,
            show_notes_text=generated.show_notes,
            duration_seconds=generated.duration_seconds,
        )
        self.repository.save_cost_record(
            CostRecord(
                run_id=run_id,
                user_id=user_id,
                text_input_tokens_estimate=cost_estimate.text_input_tokens_estimate,
                text_output_tokens_estimate=cost_estimate.text_output_tokens_estimate,
                tts_input_tokens_estimate=cost_estimate.tts_input_tokens_estimate,
                tts_output_minutes_estimate=cost_estimate.tts_output_minutes_estimate,
                openai_cost_usd=cost_estimate.openai_cost_usd,
                infra_reserve_cost_usd=cost_estimate.infra_reserve_cost_usd,
                total_cost_usd=cost_estimate.total_cost_usd,
                recorded_at=utc_now(),
            )
        )

        run = UserRunRecord(
            id=run_id,
            user_id=user_id,
            local_run_date=local_date,
            started_at=now_utc,
            completed_at=utc_now(),
            status=PublishStatus.PUBLISHED.value,
            message="Episode published",
            candidate_count=candidate_count,
            processed_item_count=len(items),
            dropped_item_count=dropped_count,
            cap_hit=cap_hit,
            published_episode_id=episode.id,
        )
        self.repository.save_user_run(run)

        return {
            "run": run.model_dump(mode="json"),
            "episode": episode.model_dump(mode="json"),
            "cost": cost_estimate.__dict__,
            "feed_url": self.get_feed_details(user_id)["feed_url"],
            "user": user.model_dump(mode="json"),
        }

    def _create_default_user(self, subject: str, email: Optional[str]) -> UserRecord:
        now = utc_now()
        display_name = email.split("@", maxsplit=1)[0] if email else "Listener"
        return UserRecord(
            id=uuid4().hex,
            apple_subject=subject,
            email=email,
            display_name=display_name,
            timezone="UTC",
            created_at=now,
            updated_at=now,
        )

    def _persist_default_records(self, user: UserRecord) -> None:
        now = utc_now()
        self.repository.save_user(user)
        self.repository.save_profile(
            PodcastProfileRecord(
                user_id=user.id,
                title="mycast",
                format_preset="two_hosts",
                host_primary_name="Elena",
                host_secondary_name="Marcus",
                guest_names=[],
                desired_duration_minutes=self.settings.free_default_duration_minutes,
                created_at=now,
                updated_at=now,
            )
        )
        self.repository.save_schedule(
            DeliveryScheduleRecord(
                user_id=user.id,
                timezone=user.timezone,
                weekdays=[
                    "monday", "tuesday", "wednesday", "thursday",
                    "friday", "saturday", "sunday",
                ],
                local_time=self.settings.weekly_target_local,
                cutoff_time=self.settings.weekly_cutoff_local,
                enabled=True,
                created_at=now,
                updated_at=now,
            )
        )
        self.repository.save_subscription(
            SubscriptionRecord(
                user_id=user.id,
                tier="free",
                status="active",
                updated_at=now,
            )
        )
        self._get_or_create_feed_token(user.id)

    def _build_custom_source_from_url(self, rss_url: str, user_id: str = "preview") -> UserSourceRecord:
        response = requests.get(rss_url, timeout=20)
        response.raise_for_status()
        parsed = feedparser.parse(response.text)
        entries = list(parsed.entries)
        if not entries:
            raise ControlPlaneError("Feed did not contain any entries")
        title = parsed.feed.get("title") or rss_url
        now = utc_now()
        source_hash = link_hash(rss_url)[:12]
        return UserSourceRecord(
            id=f"{user_id}:custom-{source_hash}",
            user_id=user_id,
            source_id=f"custom-{source_hash}",
            name=title,
            rss_url=rss_url,
            is_custom=True,
            enabled=True,
            validated_at=now,
            created_at=now,
            updated_at=now,
        )

    def _entitlements_for(self, subscription: SubscriptionRecord) -> UserEntitlements:
        if subscription.tier == "paid" and subscription.status not in {"expired", "revoked"}:
            return UserEntitlements(
                tier="paid",
                max_sources=self.settings.paid_max_sources,
                max_delivery_days=self.settings.paid_max_delivery_days,
                min_duration_minutes=self.settings.paid_min_duration_minutes,
                max_duration_minutes=self.settings.paid_max_duration_minutes,
                max_items_per_episode=self.settings.paid_max_items_per_episode,
            )
        return UserEntitlements(
            tier="free",
            max_sources=self.settings.free_max_sources,
            max_delivery_days=self.settings.free_max_delivery_days,
            min_duration_minutes=self.settings.free_min_duration_minutes,
            max_duration_minutes=self.settings.free_max_duration_minutes,
            max_items_per_episode=self.settings.free_max_items_per_episode,
        )

    def _get_subscription(self, user_id: str) -> SubscriptionRecord:
        subscription = self.repository.get_subscription(user_id)
        if subscription:
            return subscription
        subscription = SubscriptionRecord(user_id=user_id, tier="free", status="active", updated_at=utc_now())
        self.repository.save_subscription(subscription)
        return subscription

    def _get_profile(self, user_id: str) -> PodcastProfileRecord:
        profile = self.repository.get_profile(user_id)
        if not profile:
            now = utc_now()
            profile = PodcastProfileRecord(
                user_id=user_id,
                title="mycast",
                desired_duration_minutes=self.settings.free_default_duration_minutes,
                created_at=now,
                updated_at=now,
            )
            self.repository.save_profile(profile)
        return profile

    def _get_schedule(self, user_id: str) -> DeliveryScheduleRecord:
        schedule = self.repository.get_schedule(user_id)
        if not schedule:
            now = utc_now()
            schedule = DeliveryScheduleRecord(
                user_id=user_id,
                timezone=self._require_user(user_id).timezone,
                weekdays=["monday"],
                local_time=self.settings.weekly_target_local,
                cutoff_time=self.settings.weekly_cutoff_local,
                enabled=True,
                created_at=now,
                updated_at=now,
            )
            self.repository.save_schedule(schedule)
        return schedule

    def _require_user(self, user_id: str) -> UserRecord:
        user = self.repository.get_user(user_id)
        if not user:
            raise ControlPlaneError("User not found")
        return user

    def _get_or_create_feed_token(self, user_id: str) -> FeedTokenRecord:
        token = self.repository.get_feed_token(user_id)
        if token:
            return token
        token = FeedTokenRecord(
            token=secrets.token_hex(32),
            user_id=user_id,
            created_at=utc_now(),
        )
        self.repository.save_feed_token(token)
        return token

    def _validate_profile(self, profile: PodcastProfileRecord) -> None:
        _validate_format_preset(profile.format_preset)
        if profile.format_preset == "solo_host":
            if not profile.host_primary_name:
                raise ControlPlaneError("Solo host format requires a primary host name")
            profile.host_secondary_name = None
            profile.guest_names = []
        elif profile.format_preset == "two_hosts":
            if not profile.host_primary_name or not profile.host_secondary_name:
                raise ControlPlaneError("Two-host format requires primary and secondary host names")
            profile.guest_names = []
        elif profile.format_preset == "rotating_guest":
            if not profile.host_primary_name:
                raise ControlPlaneError("Rotating guest format requires a primary host name")
            if len(profile.guest_names) < 2 or len(profile.guest_names) > 4:
                raise ControlPlaneError("Rotating guest format requires 2 to 4 guest names")
            profile.host_secondary_name = None

    def _build_user_ux(self, profile: PodcastProfileRecord, guest_name: Optional[str]) -> PodcastUxConfig:
        duration = profile.desired_duration_minutes
        secondary = profile.host_secondary_name or guest_name or ""
        return PodcastUxConfig(
            host_primary_name=profile.host_primary_name,
            host_secondary_name=secondary,
            format=profile.format_preset,
            tone="calm_analyst",
            target_minutes=duration,
            max_minutes=duration,
            thin_day_minutes=min(5, duration),
        )

    def _current_guest_name(self, profile: PodcastProfileRecord, user_id: str) -> Optional[str]:
        if profile.format_preset != "rotating_guest" or not profile.guest_names:
            return None
        episode_count = self.repository.count_user_episodes(user_id)
        return profile.guest_names[episode_count % len(profile.guest_names)]

    def _build_show_notes(
        self,
        generated_notes: str,
        items: list,
        cap_hit: bool,
        dropped_count: int,
    ) -> str:
        lines: list[str] = []
        notes = (generated_notes or "").strip()
        if notes:
            lines.append(notes)
            lines.append("")
        if cap_hit:
            lines.append(
                f"Note: This episode hit the per-episode item cap. {dropped_count} additional source item(s) were omitted."
            )
            lines.append("")
        lines.append("Sources")
        seen: set[str] = set()
        for item in items:
            if item.link in seen:
                continue
            seen.add(item.link)
            lines.append(f"- {item.source_name}: {item.link}")
        return "\n".join(lines)

    def _latest_run_for_user(self, user_id: str) -> Optional[UserRunRecord]:
        schedule = self.repository.get_schedule(user_id)
        if not schedule:
            return None
        local_date = utc_now().astimezone(ZoneInfo(schedule.timezone)).date()
        runs = self.repository.list_user_runs_for_date(user_id, local_date)
        if not runs:
            return None
        runs.sort(key=lambda run: run.completed_at, reverse=True)
        return runs[0]

    def _is_due(self, schedule: DeliveryScheduleRecord, now_utc: datetime) -> bool:
        local_now = now_utc.astimezone(ZoneInfo(schedule.timezone))
        weekday = WEEKDAY_NAMES[local_now.weekday()]
        if weekday not in schedule.weekdays:
            return False
        local_hhmm = local_now.strftime("%H:%M")
        return schedule.local_time <= local_hhmm <= schedule.cutoff_time

    def _should_attempt_user(self, user_id: str, schedule: DeliveryScheduleRecord, now_utc: datetime) -> bool:
        local_date = now_utc.astimezone(ZoneInfo(schedule.timezone)).date()
        runs = self.repository.list_user_runs_for_date(user_id, local_date)
        if any(run.status in COMPLETED_RUN_STATUSES for run in runs):
            return False
        if not runs:
            return True
        last_attempt = max(run.completed_at for run in runs)
        return (now_utc - last_attempt).total_seconds() >= self.settings.dispatch_interval_minutes * 60


def build_task_enqueuer(settings: Settings) -> TaskEnqueuer:
    if not settings.cloud_tasks_queue:
        return InMemoryTaskEnqueuer()

    project_id = settings.cloud_tasks_project_id or settings.google_cloud_project
    if not project_id or not settings.cloud_tasks_location:
        raise RuntimeError("Cloud Tasks requires project id and location")

    from google.cloud import tasks_v2

    queue_path = tasks_v2.CloudTasksClient.queue_path(
        project_id,
        settings.cloud_tasks_location,
        settings.cloud_tasks_queue,
    )
    return CloudTasksEnqueuer(
        queue_path=queue_path,
        service_url=settings.app_base_url,
        service_account_email=settings.cloud_tasks_service_account,
        job_trigger_token=settings.job_trigger_token,
    )


def _validate_timezone(timezone_name: str) -> None:
    try:
        ZoneInfo(timezone_name)
    except Exception as exc:  # pragma: no cover
        raise ControlPlaneError(f"Unknown timezone: {timezone_name}") from exc


def _normalize_weekday(value: str) -> str:
    normalized = value.strip().lower()
    if normalized not in WEEKDAY_NAMES:
        raise ControlPlaneError(f"Invalid weekday: {value}")
    return normalized


def _validate_format_preset(value: str) -> None:
    if value not in {"solo_host", "two_hosts", "rotating_guest"}:
        raise ControlPlaneError(f"Invalid format preset: {value}")


def _parse_client_datetime(value: Any) -> Optional[datetime]:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
