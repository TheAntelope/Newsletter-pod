from __future__ import annotations

import html
import logging
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional, Protocol

import feedparser
import requests

from .models import SourceDefinition, SourceItem
from .utils import guid_or_link_hash, parse_datetime, utc_now

logger = logging.getLogger(__name__)


class CursorRepository(Protocol):
    def get_source_cursor(self, source_id: str) -> Optional[datetime]:
        ...

HTML_TAG_PATTERN = re.compile(r"<[^>]+>")
RSS_USER_AGENT = (
    "Mozilla/5.0 (compatible; NewsletterPod/1.0; +https://newsletter-pod.app)"
)


@dataclass
class IngestionResult:
    items: list[SourceItem] = field(default_factory=list)
    cursor_updates: dict[str, datetime] = field(default_factory=dict)


class RSSIngestionService:
    def __init__(
        self,
        repository: CursorRepository,
        timeout_seconds: int = 20,
        bootstrap_max_items_per_source: int = 3,
    ) -> None:
        self._repository = repository
        self._timeout_seconds = timeout_seconds
        self._bootstrap_max_items_per_source = max(1, bootstrap_max_items_per_source)

    def fetch_new_items(self, sources: list[SourceDefinition]) -> IngestionResult:
        fetched_at = utc_now()
        all_items: list[SourceItem] = []
        cursor_updates: dict[str, datetime] = {}

        for source in sources:
            try:
                entries = self._fetch_entries(source.rss_url)
            except requests.RequestException as exc:
                logger.warning(
                    "Skipping source %s (%s): fetch failed: %s",
                    source.id,
                    source.rss_url,
                    exc,
                )
                continue
            if not entries:
                continue

            parsed_items = [self._entry_to_item(source, entry, fetched_at) for entry in entries]
            parsed_items = [item for item in parsed_items if item is not None]
            if not parsed_items:
                continue

            latest_item_time = max(item.published_at for item in parsed_items)
            current_cursor = self._repository.get_source_cursor(source.id)

            if current_cursor is None:
                bootstrap_items = self._select_bootstrap_items(parsed_items)
                if bootstrap_items:
                    all_items.extend(bootstrap_items)
                cursor_updates[source.id] = latest_item_time
                continue

            new_items = [item for item in parsed_items if item.published_at > current_cursor]
            if new_items:
                all_items.extend(new_items)

            if latest_item_time > current_cursor:
                cursor_updates[source.id] = latest_item_time

        deduped = self._dedupe_items(all_items)
        deduped.sort(key=lambda item: item.published_at)
        return IngestionResult(items=deduped, cursor_updates=cursor_updates)

    def _select_bootstrap_items(self, items: list[SourceItem]) -> list[SourceItem]:
        newest_first = sorted(items, key=lambda item: item.published_at, reverse=True)
        selected = newest_first[: self._bootstrap_max_items_per_source]
        selected.sort(key=lambda item: item.published_at)
        return selected

    def _fetch_entries(self, rss_url: str) -> list[dict]:
        response = requests.get(
            rss_url,
            timeout=self._timeout_seconds,
            headers={"User-Agent": RSS_USER_AGENT, "Accept": "application/rss+xml, application/atom+xml, application/xml;q=0.9, */*;q=0.8"},
        )
        response.raise_for_status()
        parsed = feedparser.parse(response.text)
        return list(parsed.entries)

    def _entry_to_item(self, source: SourceDefinition, entry: dict, fetched_at: datetime) -> SourceItem | None:
        link = entry.get("link")
        if not link:
            return None

        title = entry.get("title") or "Untitled newsletter"
        guid = entry.get("id") or entry.get("guid")

        raw_summary = ""
        if entry.get("summary"):
            raw_summary = entry.get("summary")
        elif entry.get("description"):
            raw_summary = entry.get("description")
        elif entry.get("content"):
            content = entry.get("content")
            if isinstance(content, list) and content:
                raw_summary = content[0].get("value", "")

        summary = _clean_summary(raw_summary)

        published = (
            parse_datetime(entry.get("published"))
            or parse_datetime(entry.get("updated"))
            or fetched_at
        )

        return SourceItem(
            source_id=source.id,
            source_name=source.name,
            guid=guid,
            link=link,
            title=title,
            summary=summary,
            published_at=published,
            dedupe_key=guid_or_link_hash(guid, link),
        )

    def _dedupe_items(self, items: list[SourceItem]) -> list[SourceItem]:
        deduped: list[SourceItem] = []
        seen: set[str] = set()

        for item in items:
            if item.dedupe_key in seen:
                continue
            seen.add(item.dedupe_key)
            deduped.append(item)

        return deduped


def _clean_summary(value: str) -> str:
    stripped = HTML_TAG_PATTERN.sub(" ", value)
    unescaped = html.unescape(stripped)
    squashed = re.sub(r"\s+", " ", unescaped).strip()
    return squashed[:1200]
