from __future__ import annotations

import logging
from typing import Optional, Protocol

from .embeddings import EmbeddingProvider
from .models import SourceItem, SourceItemRecord
from .utils import utc_now

logger = logging.getLogger(__name__)


class SourceItemRepository(Protocol):
    def upsert_source_items(self, records: list[SourceItemRecord]) -> None: ...

    def get_source_items(self, dedupe_keys: list[str]) -> list[SourceItemRecord]: ...


class SourceItemPersistenceService:
    """Persist freshly-fetched SourceItems to the source_items collection and
    embed any that don't already have an embedding.

    Phase 1 of the swipe-based interest learning workstream — items become
    first-class so that future ranker steps and swipe logging have stable
    docs to reference. Selection behavior is unchanged: callers still feed
    the in-memory item list to the existing prompt-builder.
    """

    def __init__(
        self,
        repository: SourceItemRepository,
        embeddings: Optional[EmbeddingProvider] = None,
    ) -> None:
        self._repository = repository
        self._embeddings = embeddings

    def persist(self, items: list[SourceItem]) -> list[SourceItemRecord]:
        if not items:
            return []

        now = utc_now()
        existing_by_key = {
            record.dedupe_key: record
            for record in self._repository.get_source_items([item.dedupe_key for item in items])
        }
        records: list[SourceItemRecord] = []
        for item in items:
            existing = existing_by_key.get(item.dedupe_key)
            records.append(
                SourceItemRecord(
                    dedupe_key=item.dedupe_key,
                    source_id=item.source_id,
                    source_name=item.source_name,
                    guid=item.guid,
                    link=item.link,
                    title=item.title,
                    summary=item.summary,
                    published_at=item.published_at,
                    first_seen_at=existing.first_seen_at if existing else now,
                    last_seen_at=now,
                    kind=item.kind,
                    audio_url=item.audio_url,
                    audio_duration_seconds=item.audio_duration_seconds,
                    embedding=existing.embedding if existing else None,
                    embedding_model=existing.embedding_model if existing else None,
                    embedded_at=existing.embedded_at if existing else None,
                )
            )

        if self._embeddings is not None:
            self._embed_missing(records)

        self._repository.upsert_source_items(records)
        return records

    def _embed_missing(self, records: list[SourceItemRecord]) -> None:
        provider = self._embeddings
        assert provider is not None
        targets = [record for record in records if record.embedding is None]
        if not targets:
            return
        inputs = [_build_embedding_input(record) for record in targets]
        vectors = provider.embed_texts(inputs)
        embedded_at = utc_now()
        for record, vector in zip(targets, vectors):
            if vector is None:
                continue
            record.embedding = vector
            record.embedding_model = provider.model
            record.embedded_at = embedded_at


def _build_embedding_input(record: SourceItemRecord) -> str:
    title = (record.title or "").strip()
    summary = (record.summary or "").strip()
    if title and summary:
        return f"{title}\n\n{summary}"
    return title or summary or " "
