from __future__ import annotations

import math
from datetime import datetime, timezone

from newsletter_pod.models import SourceItem
from newsletter_pod.ranker import cosine_similarity, rank_items


def _item(key: str, *, minutes_offset: int = 0) -> SourceItem:
    return SourceItem(
        source_id="src",
        source_name="Source",
        guid=key,
        link=f"https://example.com/{key}",
        title=f"Title {key}",
        summary="summary",
        published_at=datetime(2026, 5, 11, 12, minutes_offset, tzinfo=timezone.utc),
        dedupe_key=key,
    )


def test_cosine_returns_zero_for_empty_or_mismatched_vectors():
    assert cosine_similarity([], [1.0]) == 0.0
    assert cosine_similarity([1.0, 0.0], [1.0]) == 0.0
    assert cosine_similarity([0.0, 0.0], [1.0, 0.0]) == 0.0


def test_cosine_orthogonal_and_parallel():
    assert math.isclose(cosine_similarity([1.0, 0.0], [0.0, 1.0]), 0.0)
    assert math.isclose(cosine_similarity([1.0, 0.0], [2.0, 0.0]), 1.0)
    assert math.isclose(cosine_similarity([1.0, 0.0], [-1.0, 0.0]), -1.0)


def test_rank_items_orders_by_similarity_then_restores_chronology():
    items = [_item("a", minutes_offset=0), _item("b", minutes_offset=10), _item("c", minutes_offset=20)]
    embeddings = {
        "a": [0.0, 1.0],   # negative similarity to user_vector
        "b": [1.0, 0.0],   # max similarity
        "c": [-1.0, 0.0],  # min similarity
    }
    user_vector = [1.0, 0.0]
    ranked = rank_items(items, user_vector, embeddings.get, top_n=2)
    # Top scorers are b and a; output is re-sorted chronologically (a before b).
    assert [item.dedupe_key for item in ranked] == ["a", "b"]


def test_rank_items_keeps_unscored_items_below_positively_scored_ones():
    items = [_item("a"), _item("b"), _item("c")]
    embeddings = {
        "a": [1.0, 0.0],   # +1 score
        # "b" has no embedding (lookup returns None) → score 0
        "c": [-1.0, 0.0],  # -1 score
    }
    user_vector = [1.0, 0.0]
    ranked = rank_items(items, user_vector, embeddings.get, top_n=2)
    # a (score 1) wins; the second slot goes to b (score 0) over c (score -1).
    # Restored chronology preserves a-then-b.
    assert [item.dedupe_key for item in ranked] == ["a", "b"]


def test_rank_items_handles_top_n_greater_than_corpus():
    items = [_item("a"), _item("b")]
    user_vector = [1.0, 0.0]
    ranked = rank_items(items, user_vector, lambda key: [1.0, 0.0], top_n=10)
    assert [item.dedupe_key for item in ranked] == ["a", "b"]


def test_rank_items_returns_empty_for_zero_top_n_or_no_items():
    assert rank_items([_item("a")], [1.0], lambda key: [1.0], top_n=0) == []
    assert rank_items([], [1.0], lambda key: [1.0], top_n=5) == []
