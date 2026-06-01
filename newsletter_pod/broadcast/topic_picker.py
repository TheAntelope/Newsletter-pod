from __future__ import annotations

import itertools
import json
import logging
import re
from dataclasses import dataclass, field
from typing import Optional, Protocol, Union

import requests

from .models import BroadcastLoopRecord
from .prompting import BroadcastBrief
from .repository import BroadcastRepository

logger = logging.getLogger(__name__)

_OPENAI_CHAT_ENDPOINT = "https://api.openai.com/v1/chat/completions"
_DEFAULT_TIMEOUT_SECONDS = 30
_SYSTEM_PROMPT = (
    "You select a single specific topic for tomorrow's 5-minute podcast "
    "episode aimed at an X (Twitter) audience, AND surface the concrete "
    "entities the topic is about so the post can be tagged for discovery. "
    "Topics must be concrete (a specific story, announcement, or angle), "
    "not broad themes. Return JSON only."
)

# Sanitize/cap per-episode topic hashtags from the LLM. X allows
# alphanumeric + underscore; we strip everything else so a sloppy
# proposal can't break the post. Cap is small so the hashtag line stays
# scannable when combined with brand-static defaults.
_MAX_TOPIC_HASHTAGS = 3
_HASHTAG_BODY_RE = re.compile(r"[A-Za-z0-9_]+")


@dataclass(frozen=True)
class TopicProposal:
    """LLM proposal for the next episode. `hashtags` are entity-level
    (specific people, products, companies, events) and combine with the
    runner's brand-static set when building the tweet."""

    topic: str
    hashtags: list[str] = field(default_factory=list)


ProposerResult = Union["TopicProposal", str, None]


class TopicProposer(Protocol):
    def propose(
        self,
        *,
        audience_persona: str,
        prior_feedback_summary: Optional[str],
        seed_topics: list[str],
    ) -> ProposerResult:
        """Return a TopicProposal (topic + entity hashtags) or None.

        A bare topic string is also accepted for backward compatibility
        with simpler proposers — the picker normalizes both shapes.
        """
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
    ) -> Optional[TopicProposal]:
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
            "Output JSON: {"
            "\"topic\": \"<one specific topic, 80 chars or less>\", "
            "\"hashtags\": [\"#Entity\", \"#OtherEntity\"]"
            "}. "
            "hashtags: 0-3 PascalCase tags for the specific entities the "
            "topic is about — companies (#OpenAI, #Salesforce), products "
            "(#GPT5, #Claude), people (#SamAltman), or events "
            "(#WWDC). No #AI, #Tech, #Podcast — those are brand-static and "
            "added separately. Empty list when the topic is abstract."
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
            if not topic:
                return None
            raw_hashtags = parsed.get("hashtags") or []
            return TopicProposal(
                topic=topic,
                hashtags=_normalize_hashtags(raw_hashtags),
            )
        except Exception:
            logger.warning("OpenAI topic proposer failed", exc_info=True)
            return None


def _normalize_hashtags(raw: object) -> list[str]:
    """Coerce LLM output into a clean hashtag list. Drops anything that
    isn't a string, strips leading `#`s, keeps only alphanumeric/underscore
    bodies, re-prefixes a single `#`, dedupes case-insensitively, and caps
    at `_MAX_TOPIC_HASHTAGS`. Returns [] for any malformed input rather
    than failing the run.
    """
    if not isinstance(raw, list):
        return []
    out: list[str] = []
    seen: set[str] = set()
    for entry in raw:
        if not isinstance(entry, str):
            continue
        match = _HASHTAG_BODY_RE.search(entry)
        if not match:
            continue
        tag = f"#{match.group(0)}"
        key = tag.lower()
        if key in seen:
            continue
        seen.add(key)
        out.append(tag)
        if len(out) >= _MAX_TOPIC_HASHTAGS:
            break
    return out


class BroadcastTopicPicker:
    """Decides tomorrow's topic for a given loop.

    Decision order:
    1. Ask the LLM proposer, passing the prior episode's feedback_summary
       (when present) and the loop's seed_topics as context.
    2. If the proposer returns nothing (no key, API error), fall back to
       the next seed topic round-robin.
    3. If there are no seed topics either, fall back to the loop's
       audience_persona verbatim — guarantees the loop never stalls,
       even when misconfigured.
    """

    def __init__(self, *, proposer: Optional[TopicProposer], repository: BroadcastRepository) -> None:
        self._proposer = proposer
        self._repository = repository

    def pick(self, loop: BroadcastLoopRecord) -> tuple[str, BroadcastBrief]:
        prior = self._repository.get_latest_episode_for_loop(loop.loop_id)
        prior_feedback = prior.feedback_summary if prior else None

        topic: Optional[str] = None
        topic_hashtags: list[str] = []
        if self._proposer is not None:
            raw = self._proposer.propose(
                audience_persona=loop.audience_persona,
                prior_feedback_summary=prior_feedback,
                seed_topics=loop.seed_topics,
            )
            if isinstance(raw, TopicProposal):
                topic = raw.topic
                topic_hashtags = list(raw.hashtags)
            elif isinstance(raw, str) and raw.strip():
                # Backward-compat path for proposers that still return a
                # bare string (older fakes, custom proposers).
                topic = raw.strip()

        if not topic:
            topic = self._round_robin_seed(loop)
        if not topic:
            topic = loop.audience_persona

        brief = BroadcastBrief(
            topic=topic,
            audience_hint=loop.audience_persona,
            prior_feedback_summary=prior_feedback,
            # 1-minute episodes: the eu-morning X account is on a tier
            # that caps video uploads at 2 minutes (HTTP 403 above), and
            # an LLM asked for "2 minutes" routinely produces 2:10-2:30.
            # Asking for 1 minute pushes realized length to ~1:00-1:30,
            # comfortably under the cap. video.py also enforces a 110s
            # hard ceiling at encode time as a safety net.
            desired_minutes=1,
            topic_hashtags=topic_hashtags,
        )
        return topic, brief

    def _round_robin_seed(self, loop: BroadcastLoopRecord) -> Optional[str]:
        if not loop.seed_topics:
            return None
        # Index by the count of episodes already recorded for this loop —
        # deterministic, no extra state to track, and "skip-on-fail" if
        # the operator deletes episode rows.
        episodes = self._repository.list_episodes_for_loop(loop.loop_id, limit=1000)
        index = len(episodes) % len(loop.seed_topics)
        return loop.seed_topics[index]
