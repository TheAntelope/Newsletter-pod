from __future__ import annotations

import math
from typing import Callable, Optional

from .models import SourceItem

EmbeddingLookup = Callable[[str], Optional[list[float]]]


def cosine_similarity(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = 0.0
    norm_a = 0.0
    norm_b = 0.0
    for value_a, value_b in zip(a, b):
        dot += value_a * value_b
        norm_a += value_a * value_a
        norm_b += value_b * value_b
    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0
    return dot / (math.sqrt(norm_a) * math.sqrt(norm_b))


BiasLookup = Callable[[str], float]


def rank_items(
    items: list[SourceItem],
    user_vector: list[float],
    embedding_lookup: EmbeddingLookup,
    top_n: int,
    bias_lookup: Optional[BiasLookup] = None,
) -> list[SourceItem]:
    """Order items by similarity to user_vector (descending), take the top N,
    then restore chronological order for the downstream prompt builder.

    Items without a known embedding receive a neutral score of 0.0 — they
    rank below positively-scored items but above negatively-scored ones.

    `bias_lookup`, when provided, returns a float added to each item's
    score by dedupe_key. Used to boost high-intent content (e.g. inbound
    newsletter mail the user explicitly subscribed to) so it survives the
    cap against passively-attached RSS items at neutral similarity.
    """
    if top_n <= 0 or not items:
        return []

    scored: list[tuple[float, int, SourceItem]] = []
    for index, item in enumerate(items):
        embedding = embedding_lookup(item.dedupe_key)
        score = cosine_similarity(user_vector, embedding) if embedding else 0.0
        if bias_lookup is not None:
            score += bias_lookup(item.dedupe_key)
        scored.append((score, index, item))

    # Stable: ties fall back to original (chronological) order.
    scored.sort(key=lambda triple: (-triple[0], triple[1]))
    selected = scored[:top_n]
    selected.sort(key=lambda triple: triple[1])  # restore chronological order
    return [item for _, _, item in selected]
