from __future__ import annotations

import math
from datetime import datetime, timezone

from newsletter_pod.interest_vector import compute_user_vector
from newsletter_pod.user_models import SwipeRecord


def _swipe(direction: int, embedding: list[float], *, swipe_id: str = "s") -> SwipeRecord:
    return SwipeRecord(
        id=swipe_id,
        user_id="u1",
        source_item_dedupe_key="k",
        direction=direction,
        title="t",
        link="https://example.com/x",
        source_id="src",
        source_name="Source",
        embedding=embedding,
        embedding_model="fake",
        swiped_at=datetime(2026, 5, 11, 12, 0, tzinfo=timezone.utc),
    )


def test_returns_none_when_no_swipes():
    assert compute_user_vector([]) is None


def test_returns_none_when_all_embeddings_empty():
    swipes = [_swipe(1, []), _swipe(-1, [])]
    assert compute_user_vector(swipes) is None


def test_right_swipes_only_produce_unit_norm_vector():
    swipes = [
        _swipe(1, [1.0, 0.0, 0.0], swipe_id="s1"),
        _swipe(1, [0.0, 1.0, 0.0], swipe_id="s2"),
    ]
    vector = compute_user_vector(swipes)
    assert vector is not None
    assert len(vector) == 3
    norm_squared = sum(value * value for value in vector)
    assert abs(norm_squared - 1.0) < 1e-9
    # Direction is correct: right-swipes pull the vector positive on the
    # axes they cover, leaving the unused axis at zero.
    assert vector[0] > 0.0 and vector[1] > 0.0
    assert abs(vector[2]) < 1e-9


def test_left_swipes_pull_centroid_in_opposite_direction():
    swipes = [
        _swipe(1, [1.0, 0.0], swipe_id="s1"),
        _swipe(-1, [0.0, 1.0], swipe_id="s2"),
    ]
    vector = compute_user_vector(swipes)
    assert vector is not None
    # right=[1,0] minus left=[0,1] => [1,-1] then L2-normalized => [1/sqrt(2), -1/sqrt(2)]
    assert math.isclose(vector[0], 1.0 / math.sqrt(2), abs_tol=1e-9)
    assert math.isclose(vector[1], -1.0 / math.sqrt(2), abs_tol=1e-9)


def test_returns_none_when_left_and_right_centroids_cancel():
    swipes = [
        _swipe(1, [1.0, 0.0], swipe_id="s1"),
        _swipe(-1, [1.0, 0.0], swipe_id="s2"),
    ]
    assert compute_user_vector(swipes) is None


def test_inconsistent_dimension_swipes_are_skipped():
    swipes = [
        _swipe(1, [1.0, 0.0, 0.0], swipe_id="s1"),
        _swipe(1, [9.9], swipe_id="s2"),  # wrong dim, ignored by mean
    ]
    vector = compute_user_vector(swipes)
    assert vector is not None
    assert len(vector) == 3
    # First-swipe dimensionality wins; the malformed swipe is silently dropped
    # rather than crashing the centroid.
    assert vector[0] > 0.0
