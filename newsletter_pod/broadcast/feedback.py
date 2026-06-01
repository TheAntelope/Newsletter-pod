from __future__ import annotations

import json
import logging
from typing import Optional, Protocol

import requests

from .x_client import ReplyItem

logger = logging.getLogger(__name__)


def format_replies_as_feedback_text(replies: list[ReplyItem]) -> str:
    """Render fetched X replies in the multi-line shape the feedback
    summarizer prompt is designed for — one '@handle: text' block per
    reply, blank line between. Empty bodies are dropped so the summarizer
    isn't tripped by zero-content rows.

    Shared between the /poll-replies endpoint (manual one-shot) and the
    scheduled runner's pre-pick auto-poll so both produce identical raw
    text on the episode record."""
    lines: list[str] = []
    for reply in replies:
        text = reply.text.strip()
        if not text:
            continue
        handle = (reply.author_username or "").strip().lstrip("@") or "unknown"
        lines.append(f"@{handle}: {text}")
    return "\n\n".join(lines)

_OPENAI_CHAT_ENDPOINT = "https://api.openai.com/v1/chat/completions"
_DEFAULT_TIMEOUT_SECONDS = 30
_MAX_RAW_CHARS = 12000  # cap pasted input so a runaway paste doesn't burn tokens
_SYSTEM_PROMPT = (
    "You distill X (Twitter) replies into a short brief for tomorrow's podcast "
    "topic-picker. Capture what the audience seemed to want more of — angles, "
    "guests, follow-ups, complaints worth addressing. Discard spam, ads, and "
    "single-emoji reactions. Return JSON only."
)


class FeedbackSummarizer(Protocol):
    def summarize(self, *, replies_text: str, topic: str) -> Optional[str]:
        """Return a 1-3 sentence summary, or None when nothing useful
        was extracted (e.g. all replies were spam) or the API call fails.
        Returning None lets the caller persist the raw text without a
        summary; tomorrow's run will then fall back to round-robin seeds.
        """
        ...


class OpenAIFeedbackSummarizer:
    def __init__(self, *, api_key: str, model: str, timeout_seconds: int = _DEFAULT_TIMEOUT_SECONDS) -> None:
        self._api_key = api_key
        self._model = model
        self._timeout_seconds = timeout_seconds

    def summarize(self, *, replies_text: str, topic: str) -> Optional[str]:
        if not replies_text or not replies_text.strip():
            return None
        clipped = replies_text.strip()
        if len(clipped) > _MAX_RAW_CHARS:
            clipped = clipped[:_MAX_RAW_CHARS]

        user_content = (
            f"Today's episode was about: {topic}\n\n"
            "Replies from X (one per line or block, may include noise):\n"
            f"{clipped}\n\n"
            "Output JSON: {\"summary\": \"<1-3 sentences capturing what the "
            "audience wanted next, or empty string if nothing useful>\"}"
        )

        payload = {
            "model": self._model,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": user_content},
            ],
            "response_format": {"type": "json_object"},
            "temperature": 0.3,
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
            summary = (parsed.get("summary") or "").strip()
            return summary or None
        except Exception:
            logger.warning("OpenAI feedback summarizer failed", exc_info=True)
            return None
