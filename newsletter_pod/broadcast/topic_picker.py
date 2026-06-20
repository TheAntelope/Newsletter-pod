from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Optional, Protocol

import requests

from ..models import SourceItem
from .models import BroadcastLoopRecord
from .prompting import BroadcastBrief
from .repository import BroadcastRepository

logger = logging.getLogger(__name__)

_OPENAI_CHAT_ENDPOINT = "https://api.openai.com/v1/chat/completions"
_DEFAULT_TIMEOUT_SECONDS = 30
_SYSTEM_PROMPT = (
    "You select a single specific topic for tomorrow's 5-minute podcast episode "
    "aimed at an X (Twitter) audience. Topics must be concrete (a specific story, "
    "announcement, or angle), not broad themes. Return JSON only."
)
# Source-led selection (no audience feedback yet): the model reads today's
# actual RSS items and commits to ONE story to go deep on, rather than riffing
# on the persona.
_SOURCE_SYSTEM_PROMPT = (
    "You are the editor of a short daily podcast for an X (Twitter) audience. "
    "From the list of recent stories pulled from the show's own sources, pick "
    "the SINGLE most interesting, timely, and clippable story to build today's "
    "episode around — one story, gone deep, not a roundup. Prefer concrete, "
    "specific developments over evergreen explainers. Return JSON only."
)
# How many of the most-recent source items to put in front of the model. Past
# this it's a wall of text and the pick quality doesn't improve.
_MAX_ITEMS_FOR_SELECTION = 20
# Keep each item's blurb short so the selection prompt stays compact.
_MAX_SUMMARY_CHARS_FOR_SELECTION = 240


@dataclass(frozen=True)
class TopicProposal:
    """A topic chosen from the loop's source items. `source_dedupe_key`
    identifies which item was chosen so the caller can narrow the episode's
    grounding to that one story; None means the model named a topic but didn't
    pin it to a specific item."""

    topic: str
    source_dedupe_key: Optional[str] = None


class TopicProposer(Protocol):
    def propose(
        self,
        *,
        audience_persona: str,
        prior_feedback_summary: Optional[str],
        seed_topics: list[str],
    ) -> Optional[str]:
        """Return a one-line topic string, or None if the proposer
        couldn't ideate (e.g. no API key configured)."""
        ...

    def propose_from_sources(
        self,
        *,
        audience_persona: str,
        source_items: list[SourceItem],
    ) -> Optional[TopicProposal]:
        """Choose one story from recent source items to build the episode
        around. Returns None if the proposer couldn't ideate."""
        ...


class OpenAITopicProposer:
    def __init__(self, *, api_key: str, model: str, timeout_seconds: int = _DEFAULT_TIMEOUT_SECONDS) -> None:
        self._api_key = api_key
        self._model = model
        self._timeout_seconds = timeout_seconds

    def propose(
        self,
        *,
        audience_persona: str,
        prior_feedback_summary: Optional[str],
        seed_topics: list[str],
    ) -> Optional[str]:
        user_lines = [
            f"Audience: {audience_persona}",
        ]
        if prior_feedback_summary:
            user_lines.append(
                "Yesterday's audience signal (use as the dominant steer):"
                f"\n{prior_feedback_summary}"
            )
        if seed_topics:
            user_lines.append(
                "Backlog of seed topics (use one of these only if the audience "
                "signal is missing or thin):\n- "
                + "\n- ".join(seed_topics)
            )
        user_lines.append(
            "Output JSON: {\"topic\": \"<one specific topic, 80 chars or less>\"}"
        )

        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": "\n\n".join(user_lines)},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.7,
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        try:
            response = requests.post(
                _OPENAI_CHAT_ENDPOINT,
                json=payload,
                headers=headers,
                timeout=self._timeout_seconds,
            )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            parsed = json.loads(content)
            topic = (parsed.get("topic") or "").strip()
            return topic or None
        except Exception:
            logger.warning("OpenAI topic proposer failed", exc_info=True)
            return None

    def propose_from_sources(
        self,
        *,
        audience_persona: str,
        source_items: list[SourceItem],
    ) -> Optional[TopicProposal]:
        items = source_items[:_MAX_ITEMS_FOR_SELECTION]
        if not items:
            return None

        user_lines = [
            f"Audience: {audience_persona}",
            "",
            "Recent stories from the show's sources (newest first):",
            _format_items_for_selection(items),
            "",
            "Pick the single best story to build today's episode around. Output JSON: "
            '{"choice": <the number of the story you picked>, '
            '"topic": "<one specific, concrete topic/angle for that story, 80 chars or less>"}',
        ]
        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": _SOURCE_SYSTEM_PROMPT},
                {"role": "user", "content": "\n".join(user_lines)},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.6,
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        try:
            response = requests.post(
                _OPENAI_CHAT_ENDPOINT,
                json=payload,
                headers=headers,
                timeout=self._timeout_seconds,
            )
            response.raise_for_status()
            content = response.json()["choices"][0]["message"]["content"]
            parsed = json.loads(content)
            topic = (parsed.get("topic") or "").strip()
            if not topic:
                return None
            # Map the 1-based choice back to the item it refers to so the
            # caller can ground the episode on exactly that story. A missing or
            # out-of-range choice still yields a usable topic (just unpinned).
            dedupe_key: Optional[str] = None
            choice = parsed.get("choice")
            if isinstance(choice, int) and 1 <= choice <= len(items):
                dedupe_key = items[choice - 1].dedupe_key
            return TopicProposal(topic=topic, source_dedupe_key=dedupe_key)
        except Exception:
            logger.warning("OpenAI source-led topic selection failed", exc_info=True)
            return None


def _format_items_for_selection(items: list[SourceItem]) -> str:
    lines: list[str] = []
    for index, item in enumerate(items, start=1):
        summary = (item.summary or "").strip().replace("\n", " ")
        if len(summary) > _MAX_SUMMARY_CHARS_FOR_SELECTION:
            summary = summary[:_MAX_SUMMARY_CHARS_FOR_SELECTION].rstrip() + "…"
        blurb = f" — {summary}" if summary else ""
        lines.append(f"[{index}] ({item.source_name}) {item.title.strip()}{blurb}")
    return "\n".join(lines)


class BroadcastTopicPicker:
    """Decides tomorrow's topic for a given loop.

    Decision order:
    1. If the prior episode collected audience feedback, ask the LLM
       proposer to steer tomorrow's topic on that signal (and ground the
       episode broadly on recent source items).
    2. Otherwise (no feedback yet), pick ONE story straight from the loop's
       recent source items and build the episode around just that story —
       the source feed is the steer when the audience hasn't spoken.
    3. If there are no source items (or no proposer), fall back to the LLM
       proposer on the seed topics, then to the next seed round-robin, then
       to the loop's audience_persona verbatim — the loop never stalls.

    `source_items` are the recent items already fetched for grounding; passing
    them in lets topic selection and grounding share one fetch.
    """

    def __init__(self, *, proposer: Optional[TopicProposer], repository: BroadcastRepository) -> None:
        self._proposer = proposer
        self._repository = repository

    def pick(
        self,
        loop: BroadcastLoopRecord,
        *,
        source_items: Optional[list[SourceItem]] = None,
    ) -> tuple[str, BroadcastBrief]:
        prior = self._repository.get_latest_episode_for_loop(loop.loop_id)
        prior_feedback = prior.feedback_summary if prior else None
        items = source_items or []

        topic: Optional[str] = None
        # Default grounding: every recent item. Narrowed to a single story
        # below when the topic itself was chosen from the sources.
        grounding_items = items

        if prior_feedback:
            # Audience has spoken — let the feedback steer the topic.
            if self._proposer is not None:
                topic = self._proposer.propose(
                    audience_persona=loop.audience_persona,
                    prior_feedback_summary=prior_feedback,
                    seed_topics=loop.seed_topics,
                )
        else:
            # No feedback yet — choose one story from the source feed and go
            # deep on it.
            proposal = self._propose_from_sources(loop, items)
            if proposal is not None:
                topic = proposal.topic
                chosen = _select_item(items, proposal.source_dedupe_key)
                if chosen is not None:
                    grounding_items = [chosen]
            # No source-led topic (no items / proposer declined): fall back to
            # the proposer riffing on the loop's seed topics.
            if not topic and self._proposer is not None:
                topic = self._proposer.propose(
                    audience_persona=loop.audience_persona,
                    prior_feedback_summary=None,
                    seed_topics=loop.seed_topics,
                )

        if not topic:
            topic = self._round_robin_seed(loop)
        if not topic:
            topic = loop.audience_persona

        brief = BroadcastBrief(
            topic=topic,
            audience_hint=loop.audience_persona,
            prior_feedback_summary=prior_feedback,
            # Default 1-minute episodes: the eu-morning X account is on a tier
            # that caps video uploads at 2 minutes (HTTP 403 above), and
            # an LLM asked for "2 minutes" routinely produces 2:10-2:30.
            # Asking for 1 minute pushes realized length to ~1:00-1:30,
            # comfortably under the cap. video.py also enforces a 110s
            # hard ceiling at encode time as a safety net. A feed-only loop
            # (no X post, e.g. the website daily show) can override via
            # loop.desired_minutes for a fuller episode.
            desired_minutes=loop.desired_minutes or 1,
            source_items=grounding_items,
        )
        return topic, brief

    def _propose_from_sources(
        self, loop: BroadcastLoopRecord, items: list[SourceItem]
    ) -> Optional[TopicProposal]:
        if not items or self._proposer is None:
            return None
        # Tolerate proposers (older doubles, the None proposer) that don't
        # implement source-led selection.
        fn = getattr(self._proposer, "propose_from_sources", None)
        if not callable(fn):
            return None
        return fn(audience_persona=loop.audience_persona, source_items=items)

    def _round_robin_seed(self, loop: BroadcastLoopRecord) -> Optional[str]:
        if not loop.seed_topics:
            return None
        # Index by the count of episodes already recorded for this loop —
        # deterministic, no extra state to track, and "skip-on-fail" if
        # the operator deletes episode rows.
        episodes = self._repository.list_episodes_for_loop(loop.loop_id, limit=1000)
        index = len(episodes) % len(loop.seed_topics)
        return loop.seed_topics[index]


def _select_item(
    items: list[SourceItem], dedupe_key: Optional[str]
) -> Optional[SourceItem]:
    if not dedupe_key:
        return None
    for item in items:
        if item.dedupe_key == dedupe_key:
            return item
    return None
