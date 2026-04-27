from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

from newsletter_pod.ingestion import RSSIngestionService
from newsletter_pod.models import SourceDefinition


class StubCursorRepository:
    def __init__(self, cursors: Optional[dict[str, datetime]] = None) -> None:
        self._cursors = dict(cursors or {})

    def get_source_cursor(self, source_id: str) -> Optional[datetime]:
        return self._cursors.get(source_id)


def test_ingestion_dedupes_by_guid_then_link_hash(monkeypatch):
    repository = StubCursorRepository(
        {
            "source-a": datetime(2026, 3, 8, 0, 0, tzinfo=timezone.utc),
            "source-b": datetime(2026, 3, 8, 0, 0, tzinfo=timezone.utc),
        }
    )

    sources = [
        SourceDefinition(id="source-a", name="Source A", rss_url="a", enabled=True),
        SourceDefinition(id="source-b", name="Source B", rss_url="b", enabled=True),
    ]

    service = RSSIngestionService(repository=repository)

    feed_entries = {
        "a": [
            {
                "id": "same-guid",
                "link": "https://news.example.com/a",
                "title": "A1",
                "summary": "summary-a1",
                "published": "Mon, 09 Mar 2026 05:10:00 GMT",
            },
            {
                "link": "https://news.example.com/shared?id=7&utm_source=rss",
                "title": "A2",
                "summary": "summary-a2",
                "published": "Mon, 09 Mar 2026 05:20:00 GMT",
            },
        ],
        "b": [
            {
                "id": "same-guid",
                "link": "https://news.example.com/b",
                "title": "B1",
                "summary": "summary-b1",
                "published": "Mon, 09 Mar 2026 05:15:00 GMT",
            },
            {
                "link": "https://news.example.com/shared?utm_medium=email&id=7",
                "title": "B2",
                "summary": "summary-b2",
                "published": "Mon, 09 Mar 2026 05:25:00 GMT",
            },
        ],
    }

    monkeypatch.setattr(service, "_fetch_entries", lambda url: feed_entries[url])

    result = service.fetch_new_items(sources)

    assert len(result.items) == 2
    assert sorted(item.title for item in result.items) == ["A1", "A2"]


def test_first_run_bootstraps_latest_items_per_source_and_sets_cursor(monkeypatch):
    repository = StubCursorRepository()
    sources = [
        SourceDefinition(
            id="source-a",
            name="Source A",
            rss_url="a",
            enabled=True,
        )
    ]

    service = RSSIngestionService(repository=repository)

    monkeypatch.setattr(
        service,
        "_fetch_entries",
        lambda _: [
            {
                "id": "guid-1",
                "link": "https://example.com/item-1",
                "title": "Historical item 1",
                "summary": "Old item 1",
                "updated": "Mon, 09 Mar 2026 04:00:00 GMT",
            },
            {
                "id": "guid-2",
                "link": "https://example.com/item-2",
                "title": "Historical item 2",
                "summary": "Old item 2",
                "updated": "Mon, 09 Mar 2026 05:00:00 GMT",
            },
            {
                "id": "guid-3",
                "link": "https://example.com/item-3",
                "title": "Historical item 3",
                "summary": "Old item 3",
                "updated": "Mon, 09 Mar 2026 06:00:00 GMT",
            },
            {
                "id": "guid-4",
                "link": "https://example.com/item-4",
                "title": "Historical item 4",
                "summary": "Old item 4",
                "updated": "Mon, 09 Mar 2026 07:00:00 GMT",
            },
        ],
    )

    result = service.fetch_new_items(sources)

    assert [item.title for item in result.items] == [
        "Historical item 2",
        "Historical item 3",
        "Historical item 4",
    ]
    assert "source-a" in result.cursor_updates
    assert result.cursor_updates["source-a"].tzinfo is not None
