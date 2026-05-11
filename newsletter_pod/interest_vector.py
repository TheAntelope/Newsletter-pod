from __future__ import annotations

import math
from typing import Optional

from .user_models import SwipeRecord


def compute_user_vector(swipes: list[SwipeRecord]) -> Optional[list[float]]:
    """Centroid of right-swipe embeddings minus centroid of left-swipe embeddings,
    L2-normalized. Returns None when the user has no swipes (or all swipe
    embeddings are zero-length / inconsistent).

    Mixing embedding models is undefined — callers should ideally restrict
    inputs to swipes with the same embedding_model. For Phase 2 we trust the
    caller; if a model swap happens later the centroid quality degrades
    gracefully but doesn't crash.
    """
    if not swipes:
        return None

    right_vectors = [swipe.embedding for swipe in swipes if swipe.direction > 0 and swipe.embedding]
    left_vectors = [swipe.embedding for swipe in swipes if swipe.direction < 0 and swipe.embedding]

    if not right_vectors and not left_vectors:
        return None

    dimensions = len(right_vectors[0]) if right_vectors else len(left_vectors[0])
    if dimensions == 0:
        return None

    right_mean = _mean_vector(right_vectors, dimensions)
    left_mean = _mean_vector(left_vectors, dimensions)

    centroid = [right_mean[i] - left_mean[i] for i in range(dimensions)]
    return _l2_normalize(centroid)


def _mean_vector(vectors: list[list[float]], dimensions: int) -> list[float]:
    if not vectors:
        return [0.0] * dimensions
    accumulator = [0.0] * dimensions
    counted = 0
    for vector in vectors:
        if len(vector) != dimensions:
            continue
        for index, value in enumerate(vector):
            accumulator[index] += value
        counted += 1
    if counted == 0:
        return [0.0] * dimensions
    return [value / counted for value in accumulator]


def _l2_normalize(vector: list[float]) -> Optional[list[float]]:
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0.0:
        return None
    return [value / norm for value in vector]
