"""Voice-intake extraction: spoken brief -> structured personalization signal.

At onboarding the user records ~60 seconds of speech ("what's been on your
mind"). The iOS app transcribes on-device with Speech.framework and POSTs the
text to `/v1/me/voice-intake`. This module turns that transcript into:

  - topics: things the user wants to hear about (e.g. "AI compute", "Premier League")
  - named_entities: people, publications, companies, shows (e.g. "Anthropic", "Stratechery")
  - anchor_phrases: short, personal-feeling phrases the user actually used that
    would land as a name-check when echoed back in the podcast.
  - vibe_notes: optional one-sentence tone/style preference for the script.

Each topic / entity / anchor phrase becomes a synthetic positive swipe seeded
via `interest_seeds.seed_user_interest`, which pulls the user's interest
vector toward that content from day one. `vibe_notes` is appended to the
podcast profile's `custom_guidance` field so the script's voice matches what
the user volunteered.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import Optional, Protocol

import requests

logger = logging.getLogger(__name__)

_OPENAI_CHAT_ENDPOINT = "https://api.openai.com/v1/chat/completions"
_DEFAULT_TIMEOUT_SECONDS = 30
_MAX_TRANSCRIPT_CHARS = 4000


@dataclass
class ExtractedIntake:
    topics: list[str] = field(default_factory=list)
    named_entities: list[str] = field(default_factory=list)
    anchor_phrases: list[str] = field(default_factory=list)
    vibe_notes: Optional[str] = None

    def is_empty(self) -> bool:
        return (
            not self.topics
            and not self.named_entities
            and not self.anchor_phrases
            and not self.vibe_notes
        )


class IntakeExtractor(Protocol):
    def extract(self, transcript: str) -> ExtractedIntake: ...


_SYSTEM_PROMPT = (
    "You turn a user's spoken self-introduction into structured personalization "
    "data for a daily news podcast. The user is telling you what's on their mind: "
    "what they read, who they follow, what they want to hear more about. Your job "
    "is to extract clean, useful signal. Skip filler, hedging, anything the user "
    "didn't actually mention. Empty arrays are fine when the transcript is thin."
)

_USER_PROMPT_TEMPLATE = """Transcript:
\"\"\"
{transcript}
\"\"\"

Return ONLY a JSON object with this shape (no markdown, no commentary):
{{
  "topics": [...up to 8 short topic strings (1-4 words each), e.g. "AI compute", "Premier League", "longevity research"...],
  "named_entities": [...up to 8 specific names of people, publications, companies, shows the user mentioned, e.g. "Anthropic", "Stratechery", "Bryan Johnson"...],
  "anchor_phrases": [...up to 6 short phrases the user actually used that would feel personal if echoed back in their podcast, e.g. "chasing the Anthropic compute story", "what my wife keeps sending me"...],
  "vibe_notes": "<optional one-sentence preference about tone/style if the user hinted at one, else null>"
}}

Hard rules:
- Use only what's in the transcript. Do not invent topics, entities, or quotes.
- Topics should be the kind of thing a news ranker would filter on, not generic ("news" is too broad).
- anchor_phrases get name-checked once in the user's podcast; pick phrases that would feel personal, not generic.
- If the transcript is empty, nonsense, or unrelated, return all-empty arrays and null vibe_notes."""


@dataclass
class OpenAIIntakeExtractor:
    api_key: str
    model: str = "gpt-4o-mini"
    endpoint: str = _OPENAI_CHAT_ENDPOINT
    timeout_seconds: int = _DEFAULT_TIMEOUT_SECONDS

    def extract(self, transcript: str) -> ExtractedIntake:
        cleaned = (transcript or "").strip()
        if not cleaned:
            return ExtractedIntake()
        if len(cleaned) > _MAX_TRANSCRIPT_CHARS:
            cleaned = cleaned[:_MAX_TRANSCRIPT_CHARS]
        payload = {
            "model": self.model,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": _USER_PROMPT_TEMPLATE.format(transcript=cleaned)},
            ],
            "temperature": 0.2,
        }
        try:
            response = requests.post(
                self.endpoint,
                json=payload,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            logger.warning("Voice-intake extraction request failed: %s", exc)
            return ExtractedIntake()

        body = response.json()
        choices = body.get("choices") or []
        if not choices:
            return ExtractedIntake()
        content = (choices[0].get("message") or {}).get("content") or ""
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            logger.warning("Voice-intake extraction returned non-JSON content: %r", content[:200])
            return ExtractedIntake()
        return _coerce_extracted(parsed)


def _coerce_extracted(payload: dict) -> ExtractedIntake:
    """Best-effort normalize the LLM's JSON into ExtractedIntake. Anything off
    spec gets dropped silently — the extractor is allowed to underdeliver, but
    never to return garbage that crashes downstream."""
    return ExtractedIntake(
        topics=_clean_list(payload.get("topics"), max_items=8, max_chars=60),
        named_entities=_clean_list(payload.get("named_entities"), max_items=8, max_chars=80),
        anchor_phrases=_clean_list(payload.get("anchor_phrases"), max_items=6, max_chars=140),
        vibe_notes=_clean_optional_string(payload.get("vibe_notes"), max_chars=240),
    )


def _clean_list(value, *, max_items: int, max_chars: int) -> list[str]:
    if not isinstance(value, list):
        return []
    result: list[str] = []
    seen: set[str] = set()
    for entry in value:
        if not isinstance(entry, str):
            continue
        cleaned = entry.strip()
        if not cleaned:
            continue
        if len(cleaned) > max_chars:
            cleaned = cleaned[:max_chars].rstrip() + "…"
        key = cleaned.lower()
        if key in seen:
            continue
        seen.add(key)
        result.append(cleaned)
        if len(result) >= max_items:
            break
    return result


def _clean_optional_string(value, *, max_chars: int) -> Optional[str]:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    if not cleaned or cleaned.lower() in {"null", "none", "n/a"}:
        return None
    if len(cleaned) > max_chars:
        cleaned = cleaned[:max_chars].rstrip() + "…"
    return cleaned
