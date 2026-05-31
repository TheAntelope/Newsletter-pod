from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from typing import Callable, Optional
from zoneinfo import ZoneInfo

from ..utils import utc_now
from .models import BroadcastEpisodeRecord, BroadcastLoopRecord
from .publisher import DEFAULT_FEEDBACK_PROMPT, BroadcastPublisher, PublishResult
from .repository import BroadcastRepository
from .service import BroadcastService
from .topic_picker import BroadcastTopicPicker

logger = logging.getLogger(__name__)


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
        run_date_factory: Callable[[BroadcastLoopRecord], date] = None,
    ) -> None:
        self._repository = repository
        self._topic_picker = topic_picker
        self._broadcast_service = broadcast_service
        self._publisher = publisher
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
            topic=topic, title=generated.title
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
    def _default_tweet_text(*, topic: str, title: str) -> str:
        # Twitter limit is 280; topic is the load-bearing portion, so
        # we shape around it and leave room for the implicit video card.
        prefix = "New episode: "
        cta = " — replies welcome 🎙️"
        budget = 280 - len(prefix) - len(cta)
        return f"{prefix}{topic[:budget].rstrip()}{cta}"


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
