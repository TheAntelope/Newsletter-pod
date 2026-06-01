from __future__ import annotations

import itertools
import json
import logging
from typing import Optional, Protocol

import requests

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
        if self._proposer is not None:
            topic = self._proposer.propose(
                audience_persona=loop.audience_persona,
                prior_feedback_summary=prior_feedback,
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
            # 1-minute episodes: the eu-morning X account is on a tier
            # that caps video uploads at 2 minutes (HTTP 403 above), and
            # an LLM asked for "2 minutes" routinely produces 2:10-2:30.
            # Asking for 1 minute pushes realized length to ~1:00-1:30,
            # comfortably under the cap. video.py also enforces a 110s
            # hard ceiling at encode time as a safety net.
            desired_minutes=1,
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
