from __future__ import annotations

import dataclasses
import logging
from dataclasses import dataclass
from datetime import date
from typing import Callable, Optional
from zoneinfo import ZoneInfo

from ..models import SourceItem
from ..utils import utc_now
from .models import BroadcastEpisodeRecord, BroadcastLoopRecord
from .publisher import DEFAULT_FEEDBACK_PROMPT, BroadcastPublisher, PublishResult
from .repository import BroadcastRepository
from .service import BroadcastService
from .topic_picker import BroadcastTopicPicker

# Static hashtags appended to the default tweet for discoverability. Short
# list — too many hashtags reads as spam. We keep them brand+category so
# they're meaningful across topics rather than topic-specific.
DEFAULT_TWEET_HASHTAGS = ["#ClawCast", "#AI", "#Tech", "#Podcast"]

# How many stories to surface as bullets in the post body. Higher values
# bloat the tweet without proportional discovery value; the script LLM
# only really riffs on the top few items anyway.
_MAX_STORIES_IN_POST = 4
# Per-bullet title cap. Long item titles get truncated mid-clause so the
# post stays scannable.
_MAX_STORY_TITLE_CHARS = 90

logger = logging.getLogger(__name__)


# Sourced items fetched per scheduled run. The provider returns recent
# items across the loop's curated source_ids; the runner threads them
# into the brief so the prompt builder can ground the script in actual
# newsletter content. `None` (or a no-op provider) keeps Phase-0
# behaviour — the LLM riffs on the topic alone.
SourceItemProvider = Callable[[list[str]], list[SourceItem]]


@dataclass(frozen=True)
class ScheduledRunResult:
    loop_id: str
    episode_id: str
    topic: str
    run_date: date
    audio_url: str
    video_url: str
    episode_tweet_id: Optional[str]
    episode_tweet_url: Optional[str]
    feedback_prompt_tweet_id: Optional[str]
    feedback_prompt_tweet_url: Optional[str]


class LoopInactive(RuntimeError):
    pass


class LoopNotFound(RuntimeError):
    pass


class ScheduledBroadcastRunner:
    """End-to-end daily run for one loop. Cloud Scheduler hits the
    endpoint, the endpoint calls .run(loop_id), and that's it.

    Tweet text is derived from the title + topic + a CTA. Callers can
    override via tweet_text_override when triggering manually (e.g.
    the Phase 1 generate-and-publish path). Steady-state automated
    runs use the default formatting.
    """

    def __init__(
        self,
        *,
        repository: BroadcastRepository,
        topic_picker: BroadcastTopicPicker,
        broadcast_service: BroadcastService,
        publisher: BroadcastPublisher,
        source_item_provider: Optional[SourceItemProvider] = None,
        run_date_factory: Callable[[BroadcastLoopRecord], date] = None,
    ) -> None:
        self._repository = repository
        self._topic_picker = topic_picker
        self._broadcast_service = broadcast_service
        self._publisher = publisher
        self._source_item_provider = source_item_provider
        # Default to "today" in the loop's local timezone — important
        # when Cloud Scheduler fires at 00:30 UTC for a Tokyo loop and
        # the local date is already "tomorrow".
        self._run_date_factory = run_date_factory or _default_run_date

    def run(
        self,
        loop_id: str,
        *,
        tweet_text_override: Optional[str] = None,
        feedback_prompt_override: Optional[str] = None,
    ) -> ScheduledRunResult:
        loop = self._repository.get_loop(loop_id)
        if loop is None:
            raise LoopNotFound(f"No broadcast loop with id={loop_id!r}")
        if not loop.active:
            raise LoopInactive(f"Loop {loop_id!r} is inactive — skipping run")

        topic, brief = self._topic_picker.pick(loop)
        logger.info(
            "Broadcast run picked topic loop_id=%s desired_minutes=%d topic=%r",
            loop.loop_id,
            brief.desired_minutes,
            topic,
        )

        # Ground the brief in recent items from the loop's configured
        # source list. Fails open: any provider error is logged and we
        # fall back to the un-grounded brief so the loop still runs.
        if self._source_item_provider is not None and loop.source_ids:
            try:
                items = self._source_item_provider(loop.source_ids)
            except Exception:
                logger.warning(
                    "Source item provider failed for loop_id=%s — falling back to "
                    "un-grounded brief",
                    loop.loop_id,
                    exc_info=True,
                )
                items = []
            if items:
                brief = dataclasses.replace(brief, source_items=items)
                logger.info(
                    "Broadcast run grounded brief loop_id=%s source_items=%d",
                    loop.loop_id,
                    len(items),
                )

        run_date = self._run_date_factory(loop)
        title = self._default_title(loop=loop, topic=topic, run_date=run_date)

        # The explicitly configured feedback prompt (run override wins, else the
        # loop's stored value) — passed into generation so the spoken feedback
        # line stays in sync with the feedback tweet copy resolved below.
        configured_feedback = (
            feedback_prompt_override
            if feedback_prompt_override is not None
            else loop.feedback_prompt_text
        )

        logger.info("Broadcast run generating episode loop_id=%s", loop.loop_id)
        generated = self._broadcast_service.generate_once(
            brief=brief,
            title=title,
            feedback_prompt_text=configured_feedback,
        )
        logger.info(
            "Broadcast run generated episode loop_id=%s episode_id=%s audio_bytes=%d video_bytes=%d",
            loop.loop_id,
            generated.episode_id,
            generated.audio_size_bytes,
            generated.video_size_bytes,
        )

        tweet_text = tweet_text_override or self._default_tweet_text(
            topic=topic,
            title=generated.title,
            stories=_extract_post_stories(brief.source_items),
            hashtags=DEFAULT_TWEET_HASHTAGS,
        )
        # Tri-state resolution for the feedback tweet copy, from the configured
        # value above: None ⇒ default copy, "" ⇒ suppress, else ⇒ verbatim.
        feedback_text = _normalize_feedback_intent(configured_feedback)

        logger.info(
            "Broadcast run publishing episode_id=%s loop_id=%s",
            generated.episode_id,
            loop.loop_id,
        )
        post: PublishResult = self._publisher.publish(
            episode_id=generated.episode_id,
            tweet_text=tweet_text,
            feedback_prompt_text=feedback_text,
        )
        logger.info(
            "Broadcast run published episode_id=%s tweet_id=%s",
            generated.episode_id,
            post.episode_tweet_id,
        )

        record = BroadcastEpisodeRecord(
            episode_id=generated.episode_id,
            loop_id=loop.loop_id,
            run_date=run_date,
            topic_used=topic,
            title=generated.title,
            show_notes=generated.show_notes,
            audio_object_name=generated.audio_object_name,
            video_object_name=generated.video_object_name,
            episode_tweet_id=post.episode_tweet_id,
            episode_tweet_url=post.episode_tweet_url,
            feedback_prompt_tweet_id=post.feedback_prompt_tweet_id,
            feedback_prompt_tweet_url=post.feedback_prompt_tweet_url,
            created_at=utc_now(),
        )
        self._repository.save_episode(record)

        return ScheduledRunResult(
            loop_id=loop.loop_id,
            episode_id=generated.episode_id,
            topic=topic,
            run_date=run_date,
            audio_url=generated.audio_url,
            video_url=generated.video_url,
            episode_tweet_id=post.episode_tweet_id,
            episode_tweet_url=post.episode_tweet_url,
            feedback_prompt_tweet_id=post.feedback_prompt_tweet_id,
            feedback_prompt_tweet_url=post.feedback_prompt_tweet_url,
        )

    @staticmethod
    def _default_title(*, loop: BroadcastLoopRecord, topic: str, run_date: date) -> str:
        # Keeps the per-episode RSS title human-readable in any context
        # where the broadcast feed gets listed (Apple Podcasts etc).
        return f"{run_date.isoformat()} · {topic[:80]}"

    @staticmethod
    def _default_tweet_text(
        *,
        topic: str,
        title: str,
        stories: Optional[list[str]] = None,
        hashtags: Optional[list[str]] = None,
    ) -> str:
        # Default broadcast tweet shape. X Premium accounts (which
        # @theclawcast is) can post up to ~25k chars via the v2 API, so
        # we no longer compress this into the 280-char ceiling — instead
        # we use the room for a stories bullet list (extracted from the
        # brief's source items) and a hashtag line for discovery.
        #
        # Sections, in order:
        #   1. "New episode: <topic>"
        #   2. (optional) stories list, bulleted
        #   3. App-Store CTA mirroring the spoken APP_CTA in framing.py
        #   4. (optional) hashtags on their own line
        #   5. "Replies welcome 🎙️"
        parts: list[str] = [f"New episode: {topic.strip()}"]

        if stories:
            bullet_lines = [f"• {s}" for s in stories]
            parts.append("📰 Stories covered:\n" + "\n".join(bullet_lines))

        parts.append(
            "Want your own podcast made just for you, from the writers and "
            "newsletters you actually follow? Get The Claw Cast on the App Store "
            "→ https://www.theclawcast.com/"
        )

        if hashtags:
            parts.append(" ".join(hashtags))

        parts.append("Replies welcome 🎙️")

        return "\n\n".join(parts)


def _extract_post_stories(source_items: list[SourceItem]) -> list[str]:
    """Build short "publication — title" bullets from the brief's grounding
    items. Picks the freshest items (newest first), capped at
    _MAX_STORIES_IN_POST, with per-source uniqueness so one prolific feed
    doesn't dominate the bullet list. Returns [] when the brief was
    un-grounded (no source items)."""
    if not source_items:
        return []
    ordered = sorted(source_items, key=lambda it: it.published_at, reverse=True)
    seen_sources: set[str] = set()
    bullets: list[str] = []
    for item in ordered:
        if item.source_id in seen_sources:
            continue
        seen_sources.add(item.source_id)
        title = (item.title or "").strip()
        if len(title) > _MAX_STORY_TITLE_CHARS:
            title = title[:_MAX_STORY_TITLE_CHARS].rsplit(" ", 1)[0] + "…"
        bullets.append(f"{item.source_name} — {title}")
        if len(bullets) >= _MAX_STORIES_IN_POST:
            break
    return bullets


def _normalize_feedback_intent(value: Optional[str]) -> Optional[str]:
    """Tri-state: None ⇒ default copy, "" ⇒ suppress, text ⇒ verbatim.

    Mirrors main._resolve_feedback_prompt but kept colocated with the
    runner so the runner is self-contained for testing.
    """
    if value is None:
        return DEFAULT_FEEDBACK_PROMPT
    stripped = value.strip()
    if not stripped:
        return None
    return stripped


def _default_run_date(loop: BroadcastLoopRecord) -> date:
    try:
        tz = ZoneInfo(loop.timezone)
    except Exception:
        logger.warning(
            "Loop %s has invalid timezone %r — falling back to UTC",
            loop.loop_id,
            loop.timezone,
        )
        return utc_now().date()
    return utc_now().astimezone(tz).date()
