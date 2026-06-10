"""Unit coverage for the Firestore `list_recent_source_items_for_sources`
bounded scan. Guards the regression where this method `.stream()`d every doc
for up to 30 sources per chunk with no `.limit()`, blowing the Firestore
deadline (→ 500s) once onboarding selected every topic.

There is no Firestore emulator in the suite, so we bypass `__init__` (which
constructs a real `firestore.Client()`) and inject a tiny fake collection that
mimics `order_by(...).limit(...).stream()` and records the applied limit.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from newsletter_pod.models import SourceItemRecord
from newsletter_pod.user_repository import FirestoreControlPlaneRepository

_BASE = datetime(2026, 6, 1, 12, 0, tzinfo=timezone.utc)


def _record(
    key: str,
    *,
    source_id: str,
    embedded_minutes: int = 0,
    last_seen_minutes: int = 0,
    embedding: list[float] | None = (1.0,),
    embedded: bool = True,
) -> SourceItemRecord:
    return SourceItemRecord(
        dedupe_key=key,
        source_id=source_id,
        source_name=f"Name {source_id}",
        guid=key,
        link=f"https://example.com/{key}",
        title=f"Title {key}",
        summary="summary",
        published_at=_BASE,
        first_seen_at=_BASE,
        last_seen_at=_BASE + timedelta(minutes=last_seen_minutes),
        embedding=list(embedding) if embedding is not None else None,
        embedding_model="fake" if embedding is not None else None,
        embedded_at=_BASE + timedelta(minutes=embedded_minutes) if embedded else None,
    )


class _FakeDoc:
    def __init__(self, data: dict) -> None:
        self._data = data

    def to_dict(self) -> dict:
        return self._data


class _FakeQuery:
    """Minimal stand-in for a Firestore collection/query. Sorting drops docs
    missing the order field, mirroring Firestore's order_by null-exclusion."""

    def __init__(self, docs, *, order_field=None, limit_n=None, calls=None) -> None:
        self._docs = docs
        self._order_field = order_field
        self._limit_n = limit_n
        self.calls = calls if calls is not None else {}

    def order_by(self, field, direction=None):
        self.calls["order_by"] = field
        return _FakeQuery(
            self._docs, order_field=field, limit_n=self._limit_n, calls=self.calls
        )

    def limit(self, n):
        self.calls["limit"] = n
        return _FakeQuery(
            self._docs, order_field=self._order_field, limit_n=n, calls=self.calls
        )

    def stream(self):
        docs = self._docs
        if self._order_field:
            docs = [d for d in docs if d.get(self._order_field) is not None]
            docs = sorted(docs, key=lambda d: d[self._order_field], reverse=True)
        if self._limit_n is not None:
            docs = docs[: self._limit_n]
        return [_FakeDoc(d) for d in docs]


def _repo(records: list[SourceItemRecord]):
    repo = FirestoreControlPlaneRepository.__new__(FirestoreControlPlaneRepository)
    calls: dict = {}
    docs = [r.model_dump(mode="python") for r in records]
    repo._source_items = _FakeQuery(docs, calls=calls)
    return repo, calls


def test_query_is_bounded_by_an_explicit_limit():
    # The core regression guard: the scan must apply a `.limit()` rather than
    # streaming the whole collection.
    repo, calls = _repo([_record(f"k{i}", source_id="src-1") for i in range(5)])
    repo.list_recent_source_items_for_sources(
        source_ids=["src-1"], lookback_days=14, limit=10
    )
    assert calls.get("order_by") == "embedded_at"
    assert calls.get("limit") == max(10 * 4, 50)


def test_returns_only_items_from_the_requested_sources():
    records = [
        _record("a", source_id="src-1"),
        _record("b", source_id="src-2"),
        _record("c", source_id="src-3"),
    ]
    repo, _ = _repo(records)
    result = repo.list_recent_source_items_for_sources(
        source_ids=["src-1", "src-2"], lookback_days=14, limit=10
    )
    assert {r.source_id for r in result} == {"src-1", "src-2"}


def test_orders_by_last_seen_desc_and_respects_limit():
    records = [
        _record("old", source_id="src-1", last_seen_minutes=0),
        _record("mid", source_id="src-1", last_seen_minutes=30),
        _record("new", source_id="src-1", last_seen_minutes=60),
    ]
    repo, _ = _repo(records)
    result = repo.list_recent_source_items_for_sources(
        source_ids=["src-1"], lookback_days=14, limit=2
    )
    assert [r.dedupe_key for r in result] == ["new", "mid"]


def test_excludes_unembedded_and_stale_items():
    records = [
        _record("fresh", source_id="src-1"),
        _record("unembedded", source_id="src-1", embedding=None, embedded=False),
        # Far outside the lookback window.
        _record("stale", source_id="src-1", last_seen_minutes=-60 * 24 * 365),
    ]
    repo, _ = _repo(records)
    result = repo.list_recent_source_items_for_sources(
        source_ids=["src-1"], lookback_days=14, limit=10
    )
    assert [r.dedupe_key for r in result] == ["fresh"]


def test_empty_inputs_short_circuit():
    repo, calls = _repo([_record("a", source_id="src-1")])
    assert repo.list_recent_source_items_for_sources([], lookback_days=14, limit=10) == []
    assert repo.list_recent_source_items_for_sources(
        ["src-1"], lookback_days=14, limit=0
    ) == []
    # Neither path should have issued a query.
    assert calls == {}
