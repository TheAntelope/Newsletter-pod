from __future__ import annotations

from datetime import datetime, timezone

from newsletter_pod.embeddings import DeterministicFakeEmbeddingProvider
from newsletter_pod.models import SourceItem
from newsletter_pod.source_persistence import SourceItemPersistenceService
from newsletter_pod.user_repository import InMemoryControlPlaneRepository


def _item(dedupe_key: str, *, title: str = "Title", summary: str = "Summary") -> SourceItem:
    return SourceItem(
        source_id="src-1",
        source_name="Source 1",
        guid=dedupe_key,
        link=f"https://example.com/{dedupe_key}",
        title=title,
        summary=summary,
        published_at=datetime(2026, 5, 11, 12, 0, tzinfo=timezone.utc),
        dedupe_key=dedupe_key,
    )


def test_persist_inserts_records_and_embeds_when_provider_supplied():
    repo = InMemoryControlPlaneRepository()
    provider = DeterministicFakeEmbeddingProvider(dimensions=8)
    service = SourceItemPersistenceService(repository=repo, embeddings=provider)

    persisted = service.persist([_item("k1"), _item("k2")])

    assert len(persisted) == 2
    stored_k1 = repo.get_source_item("k1")
    stored_k2 = repo.get_source_item("k2")
    assert stored_k1 is not None
    assert stored_k2 is not None
    assert stored_k1.embedding is not None
    assert len(stored_k1.embedding) == 8
    assert stored_k1.embedding_model == provider.model
    assert stored_k1.embedded_at is not None
    assert stored_k1.first_seen_at == stored_k1.last_seen_at


def test_persist_without_provider_stores_records_with_no_embedding():
    repo = InMemoryControlPlaneRepository()
    service = SourceItemPersistenceService(repository=repo, embeddings=None)

    service.persist([_item("k1")])

    stored = repo.get_source_item("k1")
    assert stored is not None
    assert stored.embedding is None
    assert stored.embedding_model is None
    assert stored.embedded_at is None


def test_reupsert_preserves_first_seen_at_and_existing_embedding():
    repo = InMemoryControlPlaneRepository()
    provider = DeterministicFakeEmbeddingProvider(dimensions=8)
    embed_service = SourceItemPersistenceService(repository=repo, embeddings=provider)
    embed_service.persist([_item("k1", title="Original title")])
    first_record = repo.get_source_item("k1")
    assert first_record is not None
    original_first_seen = first_record.first_seen_at
    original_embedding = first_record.embedding

    # Re-fetch the same dedupe key with refreshed metadata, this time without
    # an embedding provider — existing embedding must survive the re-upsert.
    no_embed_service = SourceItemPersistenceService(repository=repo, embeddings=None)
    no_embed_service.persist([_item("k1", title="Updated title")])

    refreshed = repo.get_source_item("k1")
    assert refreshed is not None
    assert refreshed.first_seen_at == original_first_seen
    assert refreshed.last_seen_at >= original_first_seen
    assert refreshed.title == "Updated title"
    assert refreshed.embedding == original_embedding
    assert refreshed.embedding_model == provider.model


def test_persist_skips_embedding_for_records_already_embedded():
    repo = InMemoryControlPlaneRepository()
    call_count = {"n": 0}

    class CountingProvider:
        @property
        def model(self) -> str:
            return "counting-fake"

        def embed_texts(self, texts: list[str]):
            call_count["n"] += 1
            return [[float(idx)] for idx in range(len(texts))]

    service = SourceItemPersistenceService(repository=repo, embeddings=CountingProvider())
    service.persist([_item("k1")])
    first_call_count = call_count["n"]
    # Re-upsert the same item; the existing embedding should short-circuit
    # the provider call (the targets list is empty).
    service.persist([_item("k1")])
    assert call_count["n"] == first_call_count


def test_persist_empty_input_returns_empty_list():
    repo = InMemoryControlPlaneRepository()
    service = SourceItemPersistenceService(repository=repo, embeddings=None)
    assert service.persist([]) == []
