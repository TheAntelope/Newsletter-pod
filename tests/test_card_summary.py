from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import pytest

from newsletter_pod.card_summary import (
    CardSummaryService,
    _clean_input,
    _coerce_summaries,
)
from newsletter_pod.models import SourceItemRecord


def _record(dedupe_key: str, *, summary: str = "raw", card_summary: Optional[str] = None) -> SourceItemRecord:
    now = datetime(2026, 5, 16, 12, 0, tzinfo=timezone.utc)
    return SourceItemRecord(
        dedupe_key=dedupe_key,
        source_id="src",
        source_name="Source",
        link=f"https://example.com/{dedupe_key}",
        title=f"Title {dedupe_key}",
        summary=summary,
        published_at=now,
        first_seen_at=now,
        last_seen_at=now,
        card_summary=card_summary,
    )


class _CapturingRepository:
    def __init__(self) -> None:
        self.upserts: list[SourceItemRecord] = []

    def upsert_source_items(self, records: list[SourceItemRecord]) -> None:
        self.upserts.extend(records)


class _StubSummarizer:
    """Returns a deterministic summary per input; tracks call shape."""

    def __init__(self, response_map: dict[str, str] | None = None) -> None:
        self._response_map = response_map or {}
        self.calls: list[list[tuple[str, str]]] = []
        self.model = "stub-v1"

    def summarize(self, items: list[tuple[str, str]]) -> list[Optional[str]]:
        self.calls.append(list(items))
        return [self._response_map.get(title) for title, _body in items]


def test_clean_input_strips_html_and_collapses_whitespace():
    raw = "<p>The   <b>quick</b> brown\n\nfox</p> jumps."
    assert _clean_input(raw) == "The quick brown fox jumps."


def test_clean_input_truncates_word_boundary():
    long = "word " * 400  # 2000 chars; well over the 1200 limit
    cleaned = _clean_input(long)
    assert len(cleaned) <= 1200
    assert not cleaned.endswith(" ")


def test_coerce_summaries_drops_bad_entries_and_truncates_long():
    payload = {
        "summaries": [
            {"id": 0, "summary": "Short and sharp."},
            {"id": 1, "summary": "x" * 400},
            {"id": 99, "summary": "Out of range — ignore."},
            {"id": "nope", "summary": "Bad id type."},
            "garbage",
            {"id": 2, "summary": ""},
        ]
    }
    out = _coerce_summaries(payload, expected=3)
    assert out[0] == "Short and sharp."
    assert out[1] is not None and len(out[1]) <= 261 and out[1].endswith("…")
    assert out[2] is None


def test_coerce_summaries_normalizes_leaked_markup():
    """The LLM is told 'no markdown' but leaks it anyway — _coerce_summaries
    must strip markdown/LaTeX/entities, not just trim."""
    payload = {
        "summaries": [
            {"id": 0, "summary": "**Big news** for AT&amp;T &#39;customers&#39;."},
            {"id": 1, "summary": r"The proof uses $E=mc^2$ and \(x^2\)."},
        ]
    }
    out = _coerce_summaries(payload, expected=2)
    assert out[0] == "Big news for AT&T 'customers'."
    assert out[1] == "The proof uses and ."


def test_ensure_summaries_normalizes_llm_output():
    repo = _CapturingRepository()
    summarizer = _StubSummarizer(response_map={"Title a": "## Heading &amp; **bold**"})
    service = CardSummaryService(repository=repo, summarizer=summarizer)

    records = [_record("a")]
    service.ensure_summaries(records)

    assert records[0].card_summary == "Heading & bold"


def test_ensure_summaries_skips_items_that_already_have_one():
    repo = _CapturingRepository()
    summarizer = _StubSummarizer(response_map={"Title b": "new b"})
    service = CardSummaryService(repository=repo, summarizer=summarizer)

    records = [
        _record("a", card_summary="already done"),
        _record("b"),
    ]
    service.ensure_summaries(records)

    # Only the missing record went to the LLM.
    assert summarizer.calls == [[("Title b", "raw")]]
    # The cached one stays untouched.
    assert records[0].card_summary == "already done"
    # The new one was populated + persisted.
    assert records[1].card_summary == "new b"
    assert records[1].card_summary_model == "stub-v1"
    assert records[1].card_summarized_at is not None
    assert {r.dedupe_key for r in repo.upserts} == {"b"}


def test_ensure_summaries_noop_when_summarizer_is_none():
    repo = _CapturingRepository()
    service = CardSummaryService(repository=repo, summarizer=None)
    records = [_record("a")]
    out = service.ensure_summaries(records)
    assert out is records
    assert records[0].card_summary is None
    assert repo.upserts == []


def test_ensure_summaries_handles_partial_results_without_negative_caching():
    """When the LLM returns None for an item (couldn't summarize), the record
    is left as-is — so a future call can retry without a special flag."""
    repo = _CapturingRepository()
    summarizer = _StubSummarizer(response_map={"Title a": "got a"})
    # b is intentionally absent from response_map -> returns None
    service = CardSummaryService(repository=repo, summarizer=summarizer)

    records = [_record("a"), _record("b")]
    service.ensure_summaries(records)

    assert records[0].card_summary == "got a"
    assert records[1].card_summary is None  # not negatively cached
    assert [r.dedupe_key for r in repo.upserts] == ["a"]
