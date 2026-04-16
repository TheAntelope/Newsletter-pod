from __future__ import annotations

from datetime import date, datetime, timezone

from newsletter_pod.models import PublishStatus, RunRecord
from newsletter_pod.repository import FirestoreRepository


class _FakeDocument:
    def __init__(self) -> None:
        self.payload = None

    def set(self, payload) -> None:
        self.payload = payload


class _FakeCollection:
    def __init__(self) -> None:
        self.doc = _FakeDocument()

    def document(self, _doc_id: str) -> _FakeDocument:
        return self.doc


def test_firestore_save_run_serializes_run_date_to_string():
    repository = FirestoreRepository.__new__(FirestoreRepository)
    repository._runs = _FakeCollection()

    run = RunRecord(
        id="run-1",
        run_date=date(2026, 4, 15),
        started_at=datetime(2026, 4, 15, 10, 0, tzinfo=timezone.utc),
        completed_at=datetime(2026, 4, 15, 10, 5, tzinfo=timezone.utc),
        status=PublishStatus.PUBLISHED,
        message="Episode published",
    )

    repository.save_run(run)

    assert repository._runs.doc.payload["run_date"] == "2026-04-15"
    assert repository._runs.doc.payload["run_date_iso"] == "2026-04-15"
