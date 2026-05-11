from __future__ import annotations

import math
import random
from typing import Iterable

Vector = list[float]


def kmeans_representative_indices(
    vectors: list[Vector],
    k: int,
    *,
    max_iterations: int = 25,
    seed: int | None = None,
) -> list[int]:
    """Run k-means over `vectors` and return one representative index per cluster
    (the input vector closest to each final centroid).

    Returns at most k indices; fewer if the input is shorter than k. The result
    is sorted ascending so callers get deterministic ordering for downstream
    serialization.

    Implementation notes:
    - Lloyd's algorithm with k-means++ initialization.
    - Empty clusters are handled by leaving the centroid in place; the
      representative index is the original seed point for that cluster.
    - For L2-normalized embedding vectors (which OpenAI text-embedding-3-small
      returns), Euclidean distance ranks identically to cosine distance, so
      the centroid items are also the most cosine-similar items per cluster.
    """
    if k <= 0 or not vectors:
        return []
    if len(vectors) <= k:
        return list(range(len(vectors)))

    rng = random.Random(seed)
    dimensions = len(vectors[0])
    if dimensions == 0:
        return []

    centroid_indices = _kmeans_pp_init(vectors, k, rng)
    centroids: list[Vector] = [list(vectors[index]) for index in centroid_indices]
    seed_indices = list(centroid_indices)
    assignments = [0] * len(vectors)

    for _ in range(max_iterations):
        changed = False
        for point_index, vector in enumerate(vectors):
            best_cluster = _argmin_distance(vector, centroids)
            if assignments[point_index] != best_cluster:
                assignments[point_index] = best_cluster
                changed = True
        if not changed:
            break

        for cluster_index in range(k):
            members = [
                vectors[index]
                for index, assigned in enumerate(assignments)
                if assigned == cluster_index
            ]
            if not members:
                continue
            centroids[cluster_index] = _mean_vector(members, dimensions)

    representative_indices: list[int] = []
    for cluster_index in range(k):
        members_with_indices = [
            (index, vectors[index])
            for index, assigned in enumerate(assignments)
            if assigned == cluster_index
        ]
        if not members_with_indices:
            representative_indices.append(seed_indices[cluster_index])
            continue
        best_index, _ = min(
            members_with_indices,
            key=lambda pair: _squared_distance(pair[1], centroids[cluster_index]),
        )
        representative_indices.append(best_index)

    deduplicated = sorted(set(representative_indices))
    return deduplicated


def _kmeans_pp_init(vectors: list[Vector], k: int, rng: random.Random) -> list[int]:
    first_index = rng.randrange(len(vectors))
    chosen_indices: list[int] = [first_index]
    chosen_set = {first_index}
    distances_squared = [_squared_distance(v, vectors[first_index]) for v in vectors]

    while len(chosen_indices) < k:
        total_weight = sum(distances_squared)
        if total_weight <= 0.0:
            # All remaining points coincide with chosen centroids; fill the
            # rest with arbitrary unused indices.
            remaining = [i for i in range(len(vectors)) if i not in chosen_set]
            chosen_indices.extend(remaining[: k - len(chosen_indices)])
            break

        threshold = rng.random() * total_weight
        cumulative = 0.0
        next_index = len(vectors) - 1
        for index, weight in enumerate(distances_squared):
            cumulative += weight
            if cumulative >= threshold and index not in chosen_set:
                next_index = index
                break

        chosen_indices.append(next_index)
        chosen_set.add(next_index)
        for index, vector in enumerate(vectors):
            new_distance = _squared_distance(vector, vectors[next_index])
            if new_distance < distances_squared[index]:
                distances_squared[index] = new_distance

    return chosen_indices


def _argmin_distance(vector: Vector, centroids: Iterable[Vector]) -> int:
    best_cluster = 0
    best_distance = math.inf
    for cluster_index, centroid in enumerate(centroids):
        distance = _squared_distance(vector, centroid)
        if distance < best_distance:
            best_distance = distance
            best_cluster = cluster_index
    return best_cluster


def _squared_distance(a: Vector, b: Vector) -> float:
    if len(a) != len(b):
        return math.inf
    return sum((value_a - value_b) ** 2 for value_a, value_b in zip(a, b))


def _mean_vector(vectors: list[Vector], dimensions: int) -> Vector:
    if not vectors:
        return [0.0] * dimensions
    accumulator = [0.0] * dimensions
    for vector in vectors:
        if len(vector) != dimensions:
            continue
        for index, value in enumerate(vector):
            accumulator[index] += value
    return [value / len(vectors) for value in accumulator]
