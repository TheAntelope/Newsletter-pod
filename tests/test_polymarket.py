from __future__ import annotations

from datetime import date, datetime, timezone

import newsletter_pod.polymarket as pm
from newsletter_pod.embeddings import DeterministicFakeEmbeddingProvider
from newsletter_pod.models import SourceItem
from newsletter_pod.polymarket import (
    MarketSnapshot,
    fetch_open_markets,
    relevant_market_hints,
)


class FakeResp:
    def __init__(self, status_code=200, json_data=None):
        self.status_code = status_code
        self._json = json_data

    def json(self):
        return self._json


def _market(question, outcomes, prices, slug="will-x", vol=1000.0):
    return {
        "question": question,
        "slug": slug,
        "volumeNum": vol,
        "endDate": "2026-12-31",
        "outcomes": outcomes,
        "outcomePrices": prices,
    }


def test_fetch_parses_yes_price_from_json_string_arrays(monkeypatch):
    pm._reset_cache_for_tests()
    payload = [
        _market('Will X happen?', '["Yes", "No"]', '["0.62", "0.38"]'),
        _market('Will Y happen?', '["No", "Yes"]', '["0.30", "0.70"]', slug="will-y"),
    ]
    monkeypatch.setattr(pm.requests, "get", lambda *a, **k: FakeResp(json_data=payload))

    markets = fetch_open_markets(today=date(2026, 7, 1))
    assert markets[0].question == "Will X happen?"
    assert markets[0].yes_price == 0.62
    assert "will-x" in markets[0].url
    assert markets[0].volume == 1000.0
    # "Yes" is the second outcome here -> 0.70
    assert markets[1].yes_price == 0.70


def test_fetch_returns_empty_on_error(monkeypatch):
    pm._reset_cache_for_tests()

    def boom(*a, **k):
        raise RuntimeError("network down")

    monkeypatch.setattr(pm.requests, "get", boom)
    assert fetch_open_markets(today=date(2026, 7, 2)) == []


def test_fetch_returns_empty_on_non_200(monkeypatch):
    pm._reset_cache_for_tests()
    monkeypatch.setattr(pm.requests, "get", lambda *a, **k: FakeResp(status_code=503))
    assert fetch_open_markets(today=date(2026, 7, 3)) == []


def _item(title, summary, key) -> SourceItem:
    return SourceItem(
        source_id="s",
        source_name="Src",
        link="https://e.com",
        title=title,
        summary=summary,
        published_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
        dedupe_key=key,
    )


def _snap(question, yes=0.6):
    return MarketSnapshot(question=question, yes_price=yes, volume=1.0, url="https://polymarket.com")


def test_relevance_matches_only_above_floor():
    provider = DeterministicFakeEmbeddingProvider()
    items = [
        _item("Fed rate decision", "Will the Fed cut?", "k1"),
        _item("Local sports recap", "The team won.", "k2"),
    ]
    # The deterministic fake gives identical vectors for identical text, so a
    # market whose question equals an item's "title. summary" scores 1.0.
    markets = [
        _snap("Fed rate decision. Will the Fed cut?", yes=0.62),
        _snap("An utterly unrelated market question", yes=0.5),
    ]
    hints = relevant_market_hints(
        markets, items, provider, max_mentions=3, min_relevance=0.99
    )
    assert len(hints) == 1
    assert "Fed rate decision" in hints[0]
    assert "62%" in hints[0]


def test_relevance_respects_max_mentions_cap():
    provider = DeterministicFakeEmbeddingProvider()
    items = [
        _item("Story A", "alpha", "k1"),
        _item("Story B", "beta", "k2"),
    ]
    markets = [_snap("Story A. alpha"), _snap("Story B. beta")]
    hints = relevant_market_hints(
        markets, items, provider, max_mentions=1, min_relevance=0.99
    )
    assert len(hints) == 1


def test_relevance_no_hints_without_embeddings():
    items = [_item("Story A", "alpha", "k1")]
    markets = [_snap("Story A. alpha")]
    assert relevant_market_hints(markets, items, None, max_mentions=2, min_relevance=0.3) == []


def test_relevance_empty_when_nothing_clears_floor():
    provider = DeterministicFakeEmbeddingProvider()
    items = [_item("Story A", "alpha", "k1")]
    markets = [_snap("Completely different topic entirely")]
    assert relevant_market_hints(markets, items, provider, max_mentions=2, min_relevance=0.999) == []
