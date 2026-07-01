from __future__ import annotations

from datetime import datetime, timezone

import newsletter_pod.control_plane as cp_mod
from newsletter_pod.blueprint import SectionDef, ShowBlueprint
from newsletter_pod.config import Settings
from newsletter_pod.embeddings import DeterministicFakeEmbeddingProvider
from newsletter_pod.main import _build_container
from newsletter_pod.models import PodcastUxConfig, SourceItem
from newsletter_pod.polymarket import MarketSnapshot


def _control_plane():
    settings = Settings.from_env()
    settings.use_inmemory_adapters = True
    settings.podcast_api_key = None
    settings.podcast_api_enabled = False
    settings.alert_email_enabled = False
    settings.publish_summary_email_enabled = False
    settings.feedback_digest_email_enabled = False
    return _build_container(settings).control_plane


def _items():
    return [
        SourceItem(
            source_id="s",
            source_name="Src",
            link="https://e.com",
            title="Fed rate decision",
            summary="Will the Fed cut?",
            published_at=datetime(2026, 7, 1, tzinfo=timezone.utc),
            dedupe_key="k1",
        )
    ]


def _ux(enabled: bool) -> PodcastUxConfig:
    bp = ShowBlueprint(sections=[SectionDef(kind="story_block"), SectionDef(kind="closing")])
    bp.predictions.enabled = enabled
    bp.predictions.min_relevance = 0.99
    bp.predictions.max_mentions = 2
    return PodcastUxConfig(blueprint=bp)


def test_market_hints_produced_when_enabled_with_embeddings(monkeypatch):
    cp = _control_plane()
    cp.embedding_provider = DeterministicFakeEmbeddingProvider()
    monkeypatch.setattr(
        cp_mod,
        "fetch_open_markets",
        lambda *a, **k: [
            MarketSnapshot(
                question="Fed rate decision. Will the Fed cut?",
                yes_price=0.62,
                volume=1.0,
                url="https://polymarket.com",
            )
        ],
    )
    hints = cp._market_hints(_items(), _ux(enabled=True))
    assert hints and "Fed rate decision" in hints[0]


def test_no_hints_when_predictions_disabled():
    cp = _control_plane()
    cp.embedding_provider = DeterministicFakeEmbeddingProvider()
    assert cp._market_hints(_items(), _ux(enabled=False)) is None


def test_no_hints_without_embeddings():
    cp = _control_plane()
    cp.embedding_provider = None
    assert cp._market_hints(_items(), _ux(enabled=True)) is None


def test_no_hints_when_fetch_kill_switch_off(monkeypatch):
    cp = _control_plane()
    cp.embedding_provider = DeterministicFakeEmbeddingProvider()
    cp.settings.polymarket_fetch_enabled = False
    called = {"n": 0}
    monkeypatch.setattr(
        cp_mod, "fetch_open_markets", lambda *a, **k: called.__setitem__("n", 1) or []
    )
    assert cp._market_hints(_items(), _ux(enabled=True)) is None
    assert called["n"] == 0  # never even fetched
