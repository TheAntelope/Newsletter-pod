"""Polymarket prediction-market context for the daily briefing.

Mirrors ``weather.py``: a best-effort external fetch with a process-local
per-day cache, all errors swallowed (returns ``[]`` / ``None`` so a flaky API
never fails an episode). Markets are matched to the episode's story items by
embedding cosine similarity (reusing the existing embeddings + ranker code) so
odds only surface on a genuinely related story, capped per episode.

Uses the keyless Polymarket Gamma API. Field names (``question``,
``outcomePrices``, ``outcomes``, ``volumeNum``, ``slug``, ``endDate``) are parsed
defensively — Gamma returns the price/outcome arrays as JSON-encoded strings.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from datetime import date
from typing import Optional

import requests

from .embeddings import EmbeddingProvider
from .models import SourceItem
from .ranker import cosine_similarity

logger = logging.getLogger(__name__)

GAMMA_MARKETS_URL = "https://gamma-api.polymarket.com/markets"


@dataclass(frozen=True)
class MarketSnapshot:
    question: str
    yes_price: Optional[float]  # implied probability of "Yes", 0..1
    volume: Optional[float]
    url: str
    closes_at: Optional[str] = None


# Process-local cache keyed by date — many users in one dispatch sweep share it.
_cache: dict[date, list[MarketSnapshot]] = {}


def fetch_open_markets(
    *,
    limit: int = 60,
    today: Optional[date] = None,
    timeout_seconds: float = 3.0,
) -> list[MarketSnapshot]:
    """Return the most-active open markets, or ``[]`` on any failure."""
    today = today or date.today()
    if today in _cache:
        return _cache[today]
    try:
        markets = _fetch(limit, timeout_seconds)
    except Exception:  # noqa: BLE001 — never let market data break generation
        markets = []
    _cache[today] = markets
    return markets


def _fetch(limit: int, timeout_seconds: float) -> list[MarketSnapshot]:
    response = requests.get(
        GAMMA_MARKETS_URL,
        params={
            "active": "true",
            "closed": "false",
            "limit": max(1, min(limit, 200)),
            "order": "volumeNum",
            "ascending": "false",
        },
        timeout=timeout_seconds,
    )
    if response.status_code != 200:
        return []
    data = response.json() or []
    if not isinstance(data, list):
        return []
    out: list[MarketSnapshot] = []
    for raw in data:
        snap = _parse_market(raw)
        if snap is not None:
            out.append(snap)
    return out


def _parse_market(raw: object) -> Optional[MarketSnapshot]:
    if not isinstance(raw, dict):
        return None
    question = str(raw.get("question") or "").strip()
    if not question:
        return None
    slug = raw.get("slug")
    url = f"https://polymarket.com/event/{slug}" if slug else "https://polymarket.com"
    return MarketSnapshot(
        question=question,
        yes_price=_yes_price(raw),
        volume=_to_float(raw.get("volumeNum") if raw.get("volumeNum") is not None else raw.get("volume")),
        url=url,
        closes_at=raw.get("endDate") or raw.get("end_date_iso"),
    )


def _to_float(value: object) -> Optional[float]:
    try:
        return float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _as_list(value: object) -> list:
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, list) else []
        except json.JSONDecodeError:
            return []
    return []


def _yes_price(raw: dict) -> Optional[float]:
    prices = _as_list(raw.get("outcomePrices"))
    outcomes = _as_list(raw.get("outcomes"))
    if not prices:
        return None
    # Prefer the price aligned with the "Yes" outcome; fall back to the first.
    idx = 0
    for i, outcome in enumerate(outcomes):
        if str(outcome).strip().casefold() == "yes":
            idx = i
            break
    if idx >= len(prices):
        idx = 0
    price = _to_float(prices[idx])
    if price is None or not (0.0 <= price <= 1.0):
        return None
    return price


def _format_hint(item: SourceItem, market: MarketSnapshot) -> str:
    if market.yes_price is not None:
        odds = f"Polymarket puts YES at about {round(market.yes_price * 100)}%"
    else:
        odds = "trading on Polymarket"
    return f'- Story "{item.title}" relates to the market "{market.question}" ({odds}).'


def relevant_market_hints(
    markets: list[MarketSnapshot],
    items: list[SourceItem],
    embedding_provider: Optional[EmbeddingProvider],
    *,
    max_mentions: int,
    min_relevance: float,
) -> list[str]:
    """Return up to ``max_mentions`` prompt hint lines pairing a story with a
    relevance-matched market. Returns ``[]`` when embeddings are unavailable, no
    market clears ``min_relevance``, or inputs are empty — never raises.
    """
    if embedding_provider is None or max_mentions <= 0 or not markets or not items:
        return []

    market_texts = [m.question for m in markets]
    item_texts = [f"{it.title}. {it.summary}" for it in items]
    try:
        vectors = embedding_provider.embed_texts(market_texts + item_texts)
    except Exception:  # noqa: BLE001 — degrade to no hints
        logger.warning("Polymarket relevance embedding failed", exc_info=True)
        return []

    market_vecs = vectors[: len(markets)]
    item_vecs = vectors[len(markets) :]

    candidates: list[tuple[float, int, int]] = []  # (score, market_idx, item_idx)
    for mi, mvec in enumerate(market_vecs):
        if not mvec:
            continue
        best_score = 0.0
        best_item = -1
        for ii, ivec in enumerate(item_vecs):
            if not ivec:
                continue
            score = cosine_similarity(mvec, ivec)
            if score > best_score:
                best_score = score
                best_item = ii
        if best_item >= 0 and best_score >= min_relevance:
            candidates.append((best_score, mi, best_item))

    candidates.sort(key=lambda c: c[0], reverse=True)

    hints: list[str] = []
    used_items: set[int] = set()
    for _score, market_idx, item_idx in candidates:
        if item_idx in used_items:
            continue  # one market per story
        used_items.add(item_idx)
        hints.append(_format_hint(items[item_idx], markets[market_idx]))
        if len(hints) >= max_mentions:
            break
    return hints


def _reset_cache_for_tests() -> None:
    _cache.clear()
