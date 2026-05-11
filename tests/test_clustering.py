from __future__ import annotations

import math
import random

from newsletter_pod.clustering import kmeans_representative_indices


def test_returns_empty_for_zero_k_or_no_vectors():
    assert kmeans_representative_indices([], k=3) == []
    assert kmeans_representative_indices([[1.0, 0.0]], k=0) == []


def test_returns_all_indices_when_corpus_smaller_than_k():
    vectors = [[1.0, 0.0], [0.0, 1.0]]
    assert kmeans_representative_indices(vectors, k=5) == [0, 1]


def test_picks_one_representative_per_obvious_cluster():
    # Three tight clusters in 2D space — k=3 should land on one item per cluster.
    cluster_a = [[1.0 + 0.01 * i, 1.0 + 0.01 * i] for i in range(5)]
    cluster_b = [[-1.0 + 0.01 * i, -1.0 + 0.01 * i] for i in range(5)]
    cluster_c = [[5.0 + 0.01 * i, -5.0 + 0.01 * i] for i in range(5)]
    vectors = cluster_a + cluster_b + cluster_c

    indices = kmeans_representative_indices(vectors, k=3, seed=42)

    assert len(indices) == 3
    # Each chosen index should belong to a different cluster.
    cluster_ids = []
    for index in indices:
        if 0 <= index < 5:
            cluster_ids.append("a")
        elif 5 <= index < 10:
            cluster_ids.append("b")
        else:
            cluster_ids.append("c")
    assert sorted(cluster_ids) == ["a", "b", "c"]


def test_results_are_sorted_for_deterministic_serialization():
    vectors = [[float(i), 0.0] for i in range(10)]
    indices = kmeans_representative_indices(vectors, k=3, seed=7)
    assert indices == sorted(indices)


def test_handles_duplicate_vectors_without_crashing():
    vectors = [[1.0, 0.0]] * 8 + [[0.0, 1.0]]
    indices = kmeans_representative_indices(vectors, k=3, seed=1)
    assert 1 <= len(indices) <= 3


def test_seed_makes_results_reproducible():
    rng = random.Random(99)
    vectors = [[rng.random(), rng.random()] for _ in range(40)]
    first = kmeans_representative_indices(vectors, k=5, seed=12345)
    second = kmeans_representative_indices(vectors, k=5, seed=12345)
    assert first == second
