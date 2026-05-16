"""LLM-generated brief summaries for swipe-deck cards.

Raw RSS `summary` text is often unstripped HTML, marketing boilerplate, or a
truncated first paragraph that reads badly on a swipe card. This module turns
each source item's title + raw summary into a clean 1-2 sentence pitch that
fits the card chrome.

The pass is lazy and cached: card summaries are written back to the
`source_items` Firestore doc the first time they're computed, so subsequent
deck reads are free. Items already carrying a summary are skipped.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Optional, Protocol

import requests

from .models import SourceItemRecord
from .utils import utc_now

logger = logging.getLogger(__name__)

_OPENAI_CHAT_ENDPOINT = "https://api.openai.com/v1/chat/completions"
_DEFAULT_TIMEOUT_SECONDS = 30
_MAX_INPUT_CHARS_PER_ITEM = 1200
_MAX_BATCH_SIZE = 12
_HTML_TAG_PATTERN = re.compile(r"<[^>]+>")
_WHITESPACE_PATTERN = re.compile(r"\s+")


class CardSummarizer(Protocol):
    @property
    def model(self) -> str: ...

    def summarize(self, items: list[tuple[str, str]]) -> list[Optional[str]]:
        """Summarize a batch of (title, raw_summary) pairs.

        Returns one summary per input, in the same order. Entries that the
        provider couldn't summarize return None — callers should leave the
        existing record untouched in that case (no negative caching).
        """
        ...


class _CardSummaryRepository(Protocol):
    def upsert_source_items(self, records: list[SourceItemRecord]) -> None: ...


def _clean_input(raw: str) -> str:
    """Best-effort sanitize a raw RSS summary before showing it to the LLM."""
    without_tags = _HTML_TAG_PATTERN.sub(" ", raw or "")
    collapsed = _WHITESPACE_PATTERN.sub(" ", without_tags).strip()
    if len(collapsed) > _MAX_INPUT_CHARS_PER_ITEM:
        collapsed = collapsed[:_MAX_INPUT_CHARS_PER_ITEM].rsplit(" ", 1)[0]
    return collapsed


class CardSummaryService:
    """Fills in missing `card_summary` fields on source-item records and
    writes the results back to the persistence layer.

    Construction is cheap; the summarizer + repository are the I/O boundaries.
    `ensure_summaries` is idempotent: items that already carry a summary are
    skipped without an LLM call.
    """

    def __init__(
        self,
        repository: _CardSummaryRepository,
        summarizer: Optional[CardSummarizer],
    ) -> None:
        self._repository = repository
        self._summarizer = summarizer

    def ensure_summaries(self, records: list[SourceItemRecord]) -> list[SourceItemRecord]:
        if not records or self._summarizer is None:
            return records
        missing = [record for record in records if not record.card_summary]
        if not missing:
            return records

        all_updated: list[SourceItemRecord] = []
        for batch_start in range(0, len(missing), _MAX_BATCH_SIZE):
            batch = missing[batch_start : batch_start + _MAX_BATCH_SIZE]
            inputs = [(record.title, _clean_input(record.summary)) for record in batch]
            try:
                summaries = self._summarizer.summarize(inputs)
            except Exception:  # pragma: no cover — best-effort
                logger.warning(
                    "Card-summary LLM call failed for %d items",
                    len(batch),
                    exc_info=True,
                )
                continue
            now = utc_now()
            written_now: list[SourceItemRecord] = []
            for record, summary in zip(batch, summaries):
                cleaned = (summary or "").strip()
                if not cleaned:
                    continue
                record.card_summary = cleaned
                record.card_summary_model = self._summarizer.model
                record.card_summarized_at = now
                written_now.append(record)
            if written_now:
                try:
                    self._repository.upsert_source_items(written_now)
                except Exception:  # pragma: no cover — write-back is best-effort
                    logger.warning(
                        "Failed to persist %d card summaries; in-memory only",
                        len(written_now),
                        exc_info=True,
                    )
                all_updated.extend(written_now)
        if all_updated:
            logger.info(
                "Card summaries written: %d (model=%s)",
                len(all_updated),
                self._summarizer.model,
            )
        return records


_SYSTEM_PROMPT = (
    "You write very short summaries of news articles for a swipe-deck card "
    "where the reader will decide in a second whether to dig in. Output is "
    "shown directly below the headline."
)

_USER_PROMPT_TEMPLATE = """For each item below, write a 1-2 sentence summary (<= 220 characters total).

Rules:
- Plain prose. No emojis, no markdown, no quoted phrases, no trailing call-to-action.
- Lead with the substance, not the publication or author.
- If the source summary is empty or boilerplate, summarize the headline.
- Skip hedge phrases like "discusses", "explores", "talks about".

Return JSON shaped exactly:
{{"summaries": [
  {{"id": 0, "summary": "..."}},
  ...
]}}

Items:
{items_json}"""


class OpenAICardSummarizer:
    """OpenAI chat-completions implementation. JSON mode keeps responses
    machine-readable; the prompt caps total characters so we don't pay for
    runaway outputs even on adversarial inputs.
    """

    def __init__(
        self,
        api_key: str,
        model: str = "gpt-4o-mini",
        endpoint: str = _OPENAI_CHAT_ENDPOINT,
        timeout_seconds: int = _DEFAULT_TIMEOUT_SECONDS,
    ) -> None:
        if not api_key:
            raise ValueError("OpenAICardSummarizer requires an api_key")
        self._api_key = api_key
        self._model = model
        self._endpoint = endpoint
        self._timeout_seconds = timeout_seconds

    @property
    def model(self) -> str:
        return self._model

    def summarize(self, items: list[tuple[str, str]]) -> list[Optional[str]]:
        if not items:
            return []
        payload_items = [
            {"id": index, "title": title, "summary": body}
            for index, (title, body) in enumerate(items)
        ]
        body = {
            "model": self._model,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": _USER_PROMPT_TEMPLATE.format(
                        items_json=json.dumps(payload_items, ensure_ascii=False)
                    ),
                },
            ],
            "temperature": 0.3,
        }
        try:
            response = requests.post(
                self._endpoint,
                json=body,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "Content-Type": "application/json",
                },
                timeout=self._timeout_seconds,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            logger.warning("Card-summary HTTP call failed: %s", exc)
            return [None] * len(items)
        choices = response.json().get("choices") or []
        if not choices:
            return [None] * len(items)
        content = (choices[0].get("message") or {}).get("content") or ""
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            logger.warning("Card-summary returned non-JSON: %r", content[:200])
            return [None] * len(items)
        return _coerce_summaries(parsed, expected=len(items))


def _coerce_summaries(payload: dict, *, expected: int) -> list[Optional[str]]:
    summaries: list[Optional[str]] = [None] * expected
    entries = payload.get("summaries") if isinstance(payload, dict) else None
    if not isinstance(entries, list):
        return summaries
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        index = entry.get("id")
        text = entry.get("summary")
        if not isinstance(index, int) or not 0 <= index < expected:
            continue
        if not isinstance(text, str):
            continue
        cleaned = text.strip()
        if not cleaned:
            continue
        if len(cleaned) > 260:
            cleaned = cleaned[:260].rsplit(" ", 1)[0].rstrip(",;:") + "…"
        summaries[index] = cleaned
    return summaries


class _NoopRepository:
    """Used when callers want to skip persistence (tests, dry runs)."""

    def upsert_source_items(self, records: list[SourceItemRecord]) -> None:  # pragma: no cover
        return None
