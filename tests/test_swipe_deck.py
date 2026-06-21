from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from newsletter_pod.models import SourceItemRecord
from newsletter_pod.swipe_deck import (
    COLD_START_DECK_ID,
    SwipeDeckService,
    topic_deck_id,
)
from newsletter_pod.user_models import SwipeRecord
from newsletter_pod.user_repository import InMemoryControlPlaneRepository
from newsletter_pod.utils import utc_now

# Anchor fixtures to "now" (computed once per run) rather than a hardcoded
# calendar date. The recent-deck filters items by a lookback window relative to
# the wall clock, so a fixed past date silently ages out of the window over time
# and turns these tests red on their own. Items sit one day in the past —
# comfortably inside every lookback the suite uses — and offsets preserve
# deterministic ordering.
_NOW = utc_now()


@dataclass
class _Config:
    cold_start_deck_size: int = 5
    cold_start_deck_ttl_hours: int = 168
    cold_start_corpus_limit: int = 5000
    topic_deck_ttl_hours: int = 24
    recent_deck_size: int = 5
    recent_deck_lookback_days: int = 14
    recent_deck_exploration_ratio: float = 0.0


def _record(
    key: str,
    *,
    embedding: list[float] | None = None,
    source_id: str = "src-1",
    last_seen_offset_minutes: int = 0,
) -> SourceItemRecord:
    base = _NOW - timedelta(days=1)
    return SourceItemRecord(
        dedupe_key=key,
        source_id=source_id,
        source_name=f"Name {source_id}",
        guid=key,
        link=f"https://example.com/{key}",
        title=f"Title {key}",
        summary="summary",
        published_at=base,
        first_seen_at=base,
        last_seen_at=base + timedelta(minutes=last_seen_offset_minutes),
        embedding=embedding,
        embedding_model="fake" if embedding is not None else None,
        embedded_at=base if embedding is not None else None,
    )


def _swipe(user_id: str, dedupe_key: str) -> SwipeRecord:
    return SwipeRecord(
        id=f"sw-{dedupe_key}",
        user_id=user_id,
        source_item_dedupe_key=dedupe_key,
        direction=1,
        title="t",
        link="https://example.com/x",
        source_id="src-1",
        source_name="Name src-1",
        embedding=[1.0, 0.0],
        embedding_model="fake",
        swiped_at=_NOW - timedelta(days=1),
    )


def test_cold_start_deck_returns_empty_when_corpus_empty():
    repo = InMemoryControlPlaneRepository()
    service = SwipeDeckService(repository=repo, config=_Config(cold_start_deck_size=5))
    assert service.get_cold_start_deck("u1") == []


def test_cold_start_deck_computes_caches_and_serves_centroid_items():
    repo = InMemoryControlPlaneRepository()
    # Three obvious 2D clusters so k=3 will pick one item per cluster.
    repo.upsert_source_items(
        [_record(f"a{i}", embedding=[1.0 + 0.01 * i, 1.0]) for i in range(4)]
        + [_record(f"b{i}", embedding=[-1.0 - 0.01 * i, -1.0]) for i in range(4)]
        + [_record(f"c{i}", embedding=[5.0 + 0.01 * i, -5.0]) for i in range(4)]
    )

    service = SwipeDeckService(repository=repo, config=_Config(cold_start_deck_size=3))
    first = service.get_cold_start_deck("u1")
    assert len(first) == 3
    cached_deck = repo.get_swipe_deck(COLD_START_DECK_ID)
    assert cached_deck is not None
    assert len(cached_deck.dedupe_keys) == 3

    # Second call inside the TTL window should hit the cache (not recompute).
    second = service.get_cold_start_deck("u1")
    assert [r.dedupe_key for r in first] == [r.dedupe_key for r in second]


def test_cold_start_deck_filters_out_items_user_already_swiped():
    repo = InMemoryControlPlaneRepository()
    records = [_record(f"k{i}", embedding=[float(i), 0.0]) for i in range(6)]
    repo.upsert_source_items(records)
    service = SwipeDeckService(repository=repo, config=_Config(cold_start_deck_size=4))

    deck = service.get_cold_start_deck("u1")
    assert len(deck) == 4
    swiped_key = deck[0].dedupe_key
    repo.save_swipe(_swipe("u1", swiped_key))

    deck_after_swipe = service.get_cold_start_deck("u1")
    assert swiped_key not in {r.dedupe_key for r in deck_after_swipe}
    assert len(deck_after_swipe) == 3


def test_cold_start_deck_recomputes_after_ttl_expires():
    repo = InMemoryControlPlaneRepository()
    repo.upsert_source_items([_record(f"k{i}", embedding=[float(i), 0.0]) for i in range(6)])

    service = SwipeDeckService(
        repository=repo,
        config=_Config(cold_start_deck_size=3, cold_start_deck_ttl_hours=0),
    )
    first = service.get_cold_start_deck("u1")
    cached = repo.get_swipe_deck(COLD_START_DECK_ID)
    assert cached is not None
    first_computed_at = cached.computed_at

    # TTL=0 means every call recomputes; the second computed_at should advance.
    service.get_cold_start_deck("u1")
    cached_after = repo.get_swipe_deck(COLD_START_DECK_ID)
    assert cached_after is not None
    assert cached_after.computed_at >= first_computed_at
    # Even after recomputation the deck content should still be sensible.
    assert len(first) == 3


def test_refresh_cold_start_deck_recomputes_even_when_fresh():
    repo = InMemoryControlPlaneRepository()
    repo.upsert_source_items(
        [_record(f"k{i}", embedding=[float(i), 0.0]) for i in range(6)]
    )
    # Long TTL — lazy refresh would *not* fire, but explicit refresh must.
    service = SwipeDeckService(
        repository=repo,
        config=_Config(cold_start_deck_size=3, cold_start_deck_ttl_hours=168),
    )
    service.get_cold_start_deck("u1")
    first_cached = repo.get_swipe_deck(COLD_START_DECK_ID)
    assert first_cached is not None
    first_computed_at = first_cached.computed_at

    deck = service.refresh_cold_start_deck()
    assert deck is not None
    after = repo.get_swipe_deck(COLD_START_DECK_ID)
    assert after is not None
    assert after.computed_at >= first_computed_at


def test_refresh_cold_start_deck_returns_none_when_corpus_empty():
    repo = InMemoryControlPlaneRepository()
    service = SwipeDeckService(repository=repo, config=_Config(cold_start_deck_size=5))
    assert service.refresh_cold_start_deck() is None
    assert repo.get_swipe_deck(COLD_START_DECK_ID) is None


def test_topic_seeded_deck_prefers_items_from_topic_sources():
    repo = InMemoryControlPlaneRepository()
    repo.upsert_source_items(
        [_record(f"tech-{i}", embedding=[1.0], source_id="techcrunch") for i in range(6)]
        + [_record(f"other-{i}", embedding=[1.0], source_id="src-other") for i in range(6)]
    )
    service = SwipeDeckService(
        repository=repo,
        config=_Config(cold_start_deck_size=4, recent_deck_lookback_days=3650),
    )
    deck = service.get_topic_seeded_deck("u1", source_ids=["techcrunch"])
    assert len(deck) == 4
    assert all(record.source_id == "techcrunch" for record in deck)


def test_topic_seeded_deck_round_robins_across_topic_groups():
    # A high-cadence topic (6 fresh items) and a low-cadence one (2 older
    # items). Pure recency would fill the 4-card deck entirely from the
    # high-cadence source; round-robin must surface the low-cadence topic.
    repo = InMemoryControlPlaneRepository()
    repo.upsert_source_items(
        [
            _record(f"tech-{i}", embedding=[1.0], source_id="techcrunch",
                    last_seen_offset_minutes=10 + i)
            for i in range(6)
        ]
        + [
            _record(f"sport-{i}", embedding=[1.0], source_id="espn",
                    last_seen_offset_minutes=i)
            for i in range(2)
        ]
    )
    service = SwipeDeckService(
        repository=repo,
        config=_Config(cold_start_deck_size=4, recent_deck_lookback_days=3650),
    )
    deck = service.get_topic_seeded_deck(
        "u1",
        source_ids=["techcrunch", "espn"],
        source_id_groups=[["techcrunch"], ["espn"]],
    )
    sources = {record.source_id for record in deck}
    assert "espn" in sources
    assert "techcrunch" in sources


def test_topic_seeded_deck_backfills_from_cold_start_when_topic_thin():
    repo = InMemoryControlPlaneRepository()
    # Only two items from the picked topic's source; the rest of the corpus is
    # elsewhere, so the diverse cold-start deck must backfill the empty slots.
    repo.upsert_source_items(
        [_record(f"tech-{i}", embedding=[float(i), 0.0], source_id="techcrunch") for i in range(2)]
        + [_record(f"fill-{i}", embedding=[10.0 + i, -5.0], source_id="src-other") for i in range(6)]
    )
    service = SwipeDeckService(
        repository=repo,
        config=_Config(cold_start_deck_size=5, recent_deck_lookback_days=3650),
    )
    deck = service.get_topic_seeded_deck("u1", source_ids=["techcrunch"])
    assert len(deck) == 5
    keys = {record.dedupe_key for record in deck}
    # Both topic items lead; cold-start diversity fills the remainder.
    assert {"tech-0", "tech-1"}.issubset(keys)
    assert any(record.source_id == "src-other" for record in deck)


def test_topic_seeded_deck_filters_swiped_items():
    repo = InMemoryControlPlaneRepository()
    repo.upsert_source_items(
        [_record(f"tech-{i}", embedding=[1.0], source_id="techcrunch") for i in range(5)]
    )
    repo.save_swipe(_swipe("u1", "tech-0"))
    service = SwipeDeckService(
        repository=repo,
        config=_Config(cold_start_deck_size=10, recent_deck_lookback_days=3650),
    )
    deck = service.get_topic_seeded_deck("u1", source_ids=["techcrunch"])
    assert "tech-0" not in {record.dedupe_key for record in deck}


def test_topic_seeded_deck_empty_topics_falls_back_to_cold_start():
    repo = InMemoryControlPlaneRepository()
    repo.upsert_source_items([_record(f"k{i}", embedding=[float(i), 0.0]) for i in range(6)])
    service = SwipeDeckService(
        repository=repo,
        config=_Config(cold_start_deck_size=3, recent_deck_lookback_days=3650),
    )
    seeded = service.get_topic_seeded_deck("u1", source_ids=[])
    cold = service.get_cold_start_deck("u1")
    assert [r.dedupe_key for r in seeded] == [r.dedupe_key for r in cold]


def test_refresh_topic_decks_writes_records_and_returns_baked_union():
    repo = InMemoryControlPlaneRepository()
    repo.upsert_source_items(
        [_record(f"tech-{i}", embedding=[1.0], source_id="techcrunch") for i in range(3)]
        + [_record(f"sport-{i}", embedding=[1.0], source_id="espn") for i in range(2)]
    )
    service = SwipeDeckService(
        repository=repo,
        config=_Config(cold_start_deck_size=4, recent_deck_lookback_days=3650),
    )
    baked = service.refresh_topic_decks({"Tech": ["techcrunch"], "Sports": ["espn"]})
    assert repo.get_swipe_deck(topic_deck_id("Tech")) is not None
    assert repo.get_swipe_deck(topic_deck_id("Sports")) is not None
    assert {record.dedupe_key for record in baked} == {
        "tech-0", "tech-1", "tech-2", "sport-0", "sport-1",
    }


def test_refresh_topic_decks_skips_topic_with_no_recent_items():
    repo = InMemoryControlPlaneRepository()
    repo.upsert_source_items([_record("tech-0", embedding=[1.0], source_id="techcrunch")])
    service = SwipeDeckService(
        repository=repo,
        config=_Config(cold_start_deck_size=4, recent_deck_lookback_days=3650),
    )
    service.refresh_topic_decks({"Tech": ["techcrunch"], "Empty": ["no-such-source"]})
    assert repo.get_swipe_deck(topic_deck_id("Empty")) is None


def test_cached_topic_deck_serves_baked_keys_not_live_corpus():
    # Proves the request path reads the cached deck rather than re-scanning the
    # live corpus: an item ingested AFTER the bake must not appear.
    repo = InMemoryControlPlaneRepository()
    repo.upsert_source_items(
        [
            _record(f"tech-{i}", embedding=[1.0], source_id="techcrunch",
                    last_seen_offset_minutes=i)
            for i in range(6)
        ]
    )
    service = SwipeDeckService(
        repository=repo,
        config=_Config(cold_start_deck_size=4, recent_deck_lookback_days=3650),
    )
    service.refresh_topic_decks({"Tech": ["techcrunch"]})
    repo.upsert_source_items(
        [_record("tech-new", embedding=[1.0], source_id="techcrunch",
                 last_seen_offset_minutes=100)]
    )
    deck = service.get_topic_seeded_deck_cached("u1", [("Tech", ["techcrunch"])])
    assert len(deck) == 4
    assert "tech-new" not in {record.dedupe_key for record in deck}


def test_cached_topic_deck_falls_back_to_live_when_deck_missing():
    repo = InMemoryControlPlaneRepository()
    repo.upsert_source_items(
        [_record(f"tech-{i}", embedding=[1.0], source_id="techcrunch") for i in range(4)]
    )
    service = SwipeDeckService(
        repository=repo,
        config=_Config(cold_start_deck_size=4, recent_deck_lookback_days=3650),
    )
    # No refresh_topic_decks() call → no cached deck → bounded live fallback.
    deck = service.get_topic_seeded_deck_cached("u1", [("Tech", ["techcrunch"])])
    assert len(deck) == 4
    assert {record.source_id for record in deck} == {"techcrunch"}


def test_cached_topic_deck_falls_back_when_stale():
    repo = InMemoryControlPlaneRepository()
    repo.upsert_source_items(
        [
            _record(f"tech-{i}", embedding=[1.0], source_id="techcrunch",
                    last_seen_offset_minutes=i)
            for i in range(4)
        ]
    )
    service = SwipeDeckService(
        repository=repo,
        config=_Config(
            cold_start_deck_size=4,
            recent_deck_lookback_days=3650,
            topic_deck_ttl_hours=0,  # any baked deck is immediately stale
        ),
    )
    service.refresh_topic_decks({"Tech": ["techcrunch"]})
    repo.upsert_source_items(
        [_record("tech-new", embedding=[1.0], source_id="techcrunch",
                 last_seen_offset_minutes=100)]
    )
    deck = service.get_topic_seeded_deck_cached("u1", [("Tech", ["techcrunch"])])
    assert "tech-new" in {record.dedupe_key for record in deck}


def test_cached_topic_deck_round_robins_across_topics():
    repo = InMemoryControlPlaneRepository()
    repo.upsert_source_items(
        [
            _record(f"tech-{i}", embedding=[1.0], source_id="techcrunch",
                    last_seen_offset_minutes=10 + i)
            for i in range(6)
        ]
        + [
            _record(f"sport-{i}", embedding=[1.0], source_id="espn",
                    last_seen_offset_minutes=i)
            for i in range(2)
        ]
    )
    service = SwipeDeckService(
        repository=repo,
        config=_Config(cold_start_deck_size=4, recent_deck_lookback_days=3650),
    )
    service.refresh_topic_decks({"Tech": ["techcrunch"], "Sports": ["espn"]})
    deck = service.get_topic_seeded_deck_cached(
        "u1", [("Tech", ["techcrunch"]), ("Sports", ["espn"])]
    )
    sources = {record.source_id for record in deck}
    assert "espn" in sources
    assert "techcrunch" in sources


def test_cached_topic_deck_filters_swiped_items():
    repo = InMemoryControlPlaneRepository()
    repo.upsert_source_items(
        [_record(f"tech-{i}", embedding=[1.0], source_id="techcrunch") for i in range(5)]
    )
    repo.save_swipe(_swipe("u1", "tech-2"))
    service = SwipeDeckService(
        repository=repo,
        config=_Config(cold_start_deck_size=10, recent_deck_lookback_days=3650),
    )
    service.refresh_topic_decks({"Tech": ["techcrunch"]})
    deck = service.get_topic_seeded_deck_cached("u1", [("Tech", ["techcrunch"])])
    assert "tech-2" not in {record.dedupe_key for record in deck}


def test_cached_topic_deck_empty_groups_falls_back_to_cold_start():
    repo = InMemoryControlPlaneRepository()
    repo.upsert_source_items([_record(f"k{i}", embedding=[float(i), 0.0]) for i in range(6)])
    service = SwipeDeckService(
        repository=repo,
        config=_Config(cold_start_deck_size=3, recent_deck_lookback_days=3650),
    )
    cached = service.get_topic_seeded_deck_cached("u1", [])
    cold = service.get_cold_start_deck("u1")
    assert [r.dedupe_key for r in cached] == [r.dedupe_key for r in cold]


def test_recent_deck_returns_only_items_from_user_sources():
    repo = InMemoryControlPlaneRepository()
    repo.upsert_source_items(
        [
            _record("attached-1", embedding=[1.0], source_id="src-attached"),
            _record("attached-2", embedding=[1.0], source_id="src-attached", last_seen_offset_minutes=5),
            _record("other", embedding=[1.0], source_id="src-other"),
            _record("attached-noembed", embedding=None, source_id="src-attached"),
        ]
    )
    service = SwipeDeckService(
        repository=repo,
        config=_Config(recent_deck_size=10, recent_deck_lookback_days=30),
    )

    deck = service.get_recent_deck("u1", source_ids=["src-attached"])
    keys = {record.dedupe_key for record in deck}
    assert keys == {"attached-1", "attached-2"}


def test_recent_deck_filters_out_swiped_items_and_respects_size_cap():
    repo = InMemoryControlPlaneRepository()
    repo.upsert_source_items(
        [_record(f"k{i}", embedding=[float(i)], last_seen_offset_minutes=i) for i in range(10)]
    )
    repo.save_swipe(_swipe("u1", "k7"))

    service = SwipeDeckService(
        repository=repo,
        config=_Config(recent_deck_size=3, recent_deck_lookback_days=30),
    )
    deck = service.get_recent_deck("u1", source_ids=["src-1"])
    keys = [record.dedupe_key for record in deck]
    assert "k7" not in keys
    assert len(keys) == 3


def test_recent_deck_mixes_in_exploration_items_from_other_sources():
    repo = InMemoryControlPlaneRepository()
    # Plenty on both sides so the ratio is honored without backfill kicking in.
    repo.upsert_source_items(
        [_record(f"mine-{i}", embedding=[1.0], source_id="src-mine") for i in range(10)]
        + [_record(f"other-{i}", embedding=[1.0], source_id="src-other") for i in range(10)]
    )

    service = SwipeDeckService(
        repository=repo,
        config=_Config(
            recent_deck_size=10,
            recent_deck_lookback_days=30,
            recent_deck_exploration_ratio=0.3,
        ),
    )
    deck = service.get_recent_deck("u1", source_ids=["src-mine"])
    source_ids_in_deck = [record.source_id for record in deck]
    # 30% of 10 = 3 exploration slots expected.
    assert source_ids_in_deck.count("src-other") == 3
    assert source_ids_in_deck.count("src-mine") == 7


def test_recent_deck_returns_pure_attached_when_exploration_ratio_zero():
    repo = InMemoryControlPlaneRepository()
    repo.upsert_source_items(
        [_record(f"mine-{i}", embedding=[1.0], source_id="src-mine") for i in range(4)]
        + [_record(f"other-{i}", embedding=[1.0], source_id="src-other") for i in range(4)]
    )

    service = SwipeDeckService(
        repository=repo,
        config=_Config(
            recent_deck_size=4,
            recent_deck_lookback_days=30,
            recent_deck_exploration_ratio=0.0,
        ),
    )
    deck = service.get_recent_deck("u1", source_ids=["src-mine"])
    assert all(record.source_id == "src-mine" for record in deck)
    assert len(deck) == 4


def test_recent_deck_falls_back_to_pure_exploration_when_user_has_no_sources():
    repo = InMemoryControlPlaneRepository()
    repo.upsert_source_items(
        [_record(f"other-{i}", embedding=[1.0], source_id="src-other") for i in range(5)]
    )

    service = SwipeDeckService(
        repository=repo,
        config=_Config(
            recent_deck_size=3,
            recent_deck_lookback_days=30,
            recent_deck_exploration_ratio=0.3,
        ),
    )
    deck = service.get_recent_deck("u1", source_ids=[])
    # No attached sources → entire deck is exploration.
    assert len(deck) == 3
    assert all(record.source_id == "src-other" for record in deck)


def test_recent_deck_backfills_exploration_shortfall_from_attached():
    repo = InMemoryControlPlaneRepository()
    # Attached side has plenty; exploration side has only 1 item to offer.
    repo.upsert_source_items(
        [_record(f"mine-{i}", embedding=[1.0], source_id="src-mine") for i in range(8)]
        + [_record("other-0", embedding=[1.0], source_id="src-other")]
    )

    service = SwipeDeckService(
        repository=repo,
        config=_Config(
            recent_deck_size=5,
            recent_deck_lookback_days=30,
            recent_deck_exploration_ratio=0.4,
        ),
    )
    deck = service.get_recent_deck("u1", source_ids=["src-mine"])
    # Two exploration slots were requested but only one item exists; the
    # remaining slot backfills from attached so the deck still totals 5.
    assert len(deck) == 5
    sources = [r.source_id for r in deck]
    assert sources.count("src-other") == 1
    assert sources.count("src-mine") == 4
