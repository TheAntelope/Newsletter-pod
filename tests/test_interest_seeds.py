from __future__ import annotations

from typing import Optional

import pytest

from newsletter_pod.embeddings import DeterministicFakeEmbeddingProvider
from newsletter_pod.interest_seeds import (
    SEED_KIND_FORWARDED,
    SEED_KIND_SUBSTACK,
    SEED_KIND_VOICE,
    is_user_forwarded_mail,
    seed_user_interest,
)
from newsletter_pod.user_repository import InMemoryControlPlaneRepository


class _CapturingRepo(InMemoryControlPlaneRepository):
    """In-memory repo we can introspect after a seeding call."""


def test_is_user_forwarded_mail_case_insensitive_match():
    assert is_user_forwarded_mail("Vince@example.com", "vince@example.com")
    assert is_user_forwarded_mail("  vince@example.com  ", "vince@example.com")
    assert not is_user_forwarded_mail("vince@example.com", "stranger@example.com")
    assert not is_user_forwarded_mail(None, "vince@example.com")
    assert not is_user_forwarded_mail("vince@example.com", None)


def test_seed_user_interest_writes_one_swipe_per_item():
    repo = _CapturingRepo()
    embeddings = DeterministicFakeEmbeddingProvider()
    written = seed_user_interest(
        repository=repo,
        embeddings=embeddings,
        user_id="u1",
        kind=SEED_KIND_VOICE,
        items=[("AI compute", "AI compute and Anthropic"), ("Premier League", "")],
    )
    assert written == 2
    swipes = repo.list_user_swipes("u1")
    assert len(swipes) == 2
    titles = {swipe.title for swipe in swipes}
    assert titles == {"AI compute", "Premier League"}
    for swipe in swipes:
        assert swipe.direction == 1
        assert swipe.seed_kind == SEED_KIND_VOICE
        assert swipe.source_item_dedupe_key.startswith("seed:voice_intake:")
        assert swipe.embedding  # non-empty embedding


def test_seed_dedupe_key_is_deterministic_for_same_text():
    repo = _CapturingRepo()
    embeddings = DeterministicFakeEmbeddingProvider()
    seed_user_interest(
        repository=repo,
        embeddings=embeddings,
        user_id="u1",
        kind=SEED_KIND_SUBSTACK,
        items=[("Stratechery", "Stratechery by Ben Thompson")],
    )
    keys_after_first = {swipe.source_item_dedupe_key for swipe in repo.list_user_swipes("u1")}
    # Re-running the same seed should land on the same dedupe key — the swipe
    # row itself gets a new uuid, but the dedupe key identifies "this idea".
    seed_user_interest(
        repository=repo,
        embeddings=embeddings,
        user_id="u1",
        kind=SEED_KIND_SUBSTACK,
        items=[("Stratechery", "Stratechery by Ben Thompson")],
    )
    keys_after_second = {swipe.source_item_dedupe_key for swipe in repo.list_user_swipes("u1")}
    assert keys_after_first == keys_after_second  # same dedupe key both times


def test_seed_user_interest_rejects_unknown_kind():
    repo = _CapturingRepo()
    embeddings = DeterministicFakeEmbeddingProvider()
    with pytest.raises(ValueError):
        seed_user_interest(
            repository=repo,
            embeddings=embeddings,
            user_id="u1",
            kind="freestyle",
            items=[("x", "y")],
        )


def test_seed_user_interest_empty_items_is_noop():
    repo = _CapturingRepo()
    embeddings = DeterministicFakeEmbeddingProvider()
    written = seed_user_interest(
        repository=repo,
        embeddings=embeddings,
        user_id="u1",
        kind=SEED_KIND_FORWARDED,
        items=[],
    )
    assert written == 0
    assert repo.list_user_swipes("u1") == []


def test_seed_skips_items_whose_embedding_failed():
    """When the embedding provider returns None for an entry, that seed is
    dropped silently — never persisted with a missing vector."""

    class _PartiallyFailingEmbeddings(DeterministicFakeEmbeddingProvider):
        def embed_texts(self, texts: list[str]) -> list[Optional[list[float]]]:
            vectors = super().embed_texts(texts)
            # Drop the second one.
            if len(vectors) >= 2:
                vectors[1] = None
            return vectors

    repo = _CapturingRepo()
    written = seed_user_interest(
        repository=repo,
        embeddings=_PartiallyFailingEmbeddings(),
        user_id="u1",
        kind=SEED_KIND_VOICE,
        items=[("topic-a", "topic-a"), ("topic-b", "topic-b")],
    )
    assert written == 1
    swipes = repo.list_user_swipes("u1")
    assert [swipe.title for swipe in swipes] == ["topic-a"]
