"""Tests for the next-episode candidate queue spike.

Covers:
- Source-poll job: flag gating, source-dedupe across users, cursor advancement.
- Per-user candidates view: flag gating, pin/exclude reflection, "likely
  to be included" pill from ranker + chronological fallback.
- Pin / exclude / clear lifecycle including the per-user cap.
- End-to-end pin honoring in `process_user_generation` and consumed_at
  stamping on publish.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from newsletter_pod.candidate_queue import CandidateQueueService
from newsletter_pod.ingestion import IngestionResult
from newsletter_pod.models import (
    NextEpisodeOverrideRecord,
    SourceItem,
    SourceItemRecord,
)
from newsletter_pod.source_persistence import SourceItemPersistenceService
from newsletter_pod.user_models import UserSourceRecord
from newsletter_pod.user_repository import InMemoryControlPlaneRepository


# --- shared fixtures --------------------------------------------------------


class _SettingsStub:
    """Mimics enough of Settings for the service to read what it needs."""

    candidate_queue_enabled = True
    podcast_bootstrap_max_items_per_source = 3
    next_episode_max_pins = 3
    next_episode_candidates_lookback_days = 14
    next_episode_candidates_limit = 50
    swipe_ranker_enabled = True
    swipe_ranker_min_swipes = 3


def _make_service(settings=None) -> tuple[CandidateQueueService, InMemoryControlPlaneRepository]:
    repo = InMemoryControlPlaneRepository()
    settings = settings or _SettingsStub()
    persistence = SourceItemPersistenceService(repository=repo, embeddings=None)
    service = CandidateQueueService(
        settings=settings,
        repository=repo,
        source_item_persistence=persistence,
    )
    return service, repo


def _now() -> datetime:
    return datetime(2026, 5, 24, 10, 0, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def _freeze_candidate_queue_clock(monkeypatch):
    """Pin the candidate-queue clock to `_now()` so the 14-day lookback window
    is computed relative to the fixtures' fixed seed time, not the wall clock.
    Without this the candidates tests go red whenever the real date drifts more
    than the lookback past the hardcoded `_now()` (they did, from 2026-06-08)."""
    monkeypatch.setattr("newsletter_pod.candidate_queue.utc_now", _now)


def _user_source(
    user_id: str, source_id: str, *, rss_url: str = "https://example.com/rss"
) -> UserSourceRecord:
    return UserSourceRecord(
        id=f"{user_id}:{source_id}",
        user_id=user_id,
        source_id=source_id,
        name=f"Source {source_id}",
        rss_url=rss_url,
        created_at=_now(),
        updated_at=_now(),
    )


def _seed_item(
    repo: InMemoryControlPlaneRepository,
    *,
    dedupe_key: str,
    source_id: str,
    published_at: datetime | None = None,
    embedding: list[float] | None = None,
) -> SourceItemRecord:
    published_at = published_at or _now()
    record = SourceItemRecord(
        dedupe_key=dedupe_key,
        source_id=source_id,
        source_name=f"Source {source_id}",
        guid=dedupe_key,
        link=f"https://example.com/{dedupe_key}",
        title=f"Title {dedupe_key}",
        summary="summary body",
        published_at=published_at,
        first_seen_at=published_at,
        last_seen_at=published_at,
        embedding=embedding,
        embedding_model="fake" if embedding is not None else None,
        embedded_at=published_at if embedding is not None else None,
    )
    repo.upsert_source_items([record])
    return record


# --- poll job ---------------------------------------------------------------


def test_run_poll_skipped_when_flag_disabled():
    service, _ = _make_service()
    service.settings.candidate_queue_enabled = False
    result = service.run_poll(now_utc=_now())
    assert result == {"status": "skipped", "reason": "candidate_queue_disabled"}


def test_run_poll_returns_zero_counts_when_no_users_attached():
    service, _ = _make_service()
    result = service.run_poll(now_utc=_now())
    assert result["status"] == "ok"
    assert result["sources_polled"] == 0
    assert result["items_ingested"] == 0


def test_run_poll_dedupes_sources_across_users(monkeypatch):
    """Two users attached to the same source should produce a single feed
    fetch, not one per user — that's the whole point of the global poll."""
    service, repo = _make_service()
    repo.replace_user_sources("u-1", [_user_source("u-1", "shared-src")])
    repo.replace_user_sources("u-2", [_user_source("u-2", "shared-src")])
    repo.replace_user_sources("u-2", [_user_source("u-2", "shared-src"), _user_source("u-2", "u2-only")])

    fetch_calls: list[list[str]] = []

    class FakeIngestion:
        def __init__(self, repository, bootstrap_max_items_per_source):
            self._repo = repository

        def fetch_new_items(self, sources):
            fetch_calls.append([s.id for s in sources])
            now = _now()
            return IngestionResult(
                items=[
                    SourceItem(
                        source_id=sources[0].id,
                        source_name=sources[0].name,
                        guid=f"{sources[0].id}-item",
                        link=f"https://example.com/{sources[0].id}",
                        title="title",
                        summary="summary",
                        published_at=now,
                        dedupe_key=f"{sources[0].id}-item",
                    )
                ],
                cursor_updates={sources[0].id: now},
            )

    monkeypatch.setattr(
        "newsletter_pod.candidate_queue.RSSIngestionService", FakeIngestion
    )

    result = service.run_poll(now_utc=_now())

    # Two distinct sources expected: shared-src (one fetch only) + u2-only.
    polled_ids = {ids[0] for ids in fetch_calls}
    assert polled_ids == {"shared-src", "u2-only"}
    assert result["sources_polled"] == 2
    assert result["items_ingested"] == 2

    # Cursor was upserted for both sources.
    assert repo.get_source_polling_state("shared-src") is not None
    assert repo.get_source_polling_state("u2-only") is not None


def test_run_poll_records_per_source_error_without_failing_batch(monkeypatch):
    service, repo = _make_service()
    repo.replace_user_sources("u-1", [_user_source("u-1", "good-src"), _user_source("u-1", "bad-src")])

    class FakeIngestion:
        def __init__(self, repository, bootstrap_max_items_per_source):
            pass

        def fetch_new_items(self, sources):
            if sources[0].id == "bad-src":
                raise RuntimeError("DNS exploded")
            now = _now()
            return IngestionResult(
                items=[
                    SourceItem(
                        source_id="good-src",
                        source_name="ok",
                        guid="good-item",
                        link="https://example.com/g",
                        title="t",
                        summary="s",
                        published_at=now,
                        dedupe_key="good-item",
                    )
                ],
                cursor_updates={"good-src": now},
            )

    monkeypatch.setattr(
        "newsletter_pod.candidate_queue.RSSIngestionService", FakeIngestion
    )

    result = service.run_poll(now_utc=_now())

    assert result["sources_polled"] == 2
    assert result["items_ingested"] == 1
    per_source = {entry["source_id"]: entry for entry in result["per_source"]}
    assert "error" in per_source["bad-src"]
    assert per_source["good-src"]["items"] == 1

    bad_state = repo.get_source_polling_state("bad-src")
    assert bad_state is not None and bad_state.last_error == "DNS exploded"


# --- candidates view --------------------------------------------------------


def test_list_candidates_returns_empty_when_user_has_no_sources():
    service, _ = _make_service()
    result = service.list_candidates("u-empty", per_episode_cap=10)
    assert result["candidates"] == []
    assert result["pins_remaining"] == service.settings.next_episode_max_pins


def test_list_candidates_surfaces_recent_items_from_user_sources():
    service, repo = _make_service()
    repo.replace_user_sources("u-1", [_user_source("u-1", "src-a")])
    _seed_item(repo, dedupe_key="a-1", source_id="src-a", published_at=_now())
    _seed_item(repo, dedupe_key="a-2", source_id="src-a", published_at=_now() - timedelta(days=1))
    # Item from a source the user hasn't attached — must not surface.
    _seed_item(repo, dedupe_key="other", source_id="src-other", published_at=_now())

    result = service.list_candidates("u-1", per_episode_cap=10)
    keys = [c["dedupe_key"] for c in result["candidates"]]
    assert set(keys) == {"a-1", "a-2"}
    # Newest first.
    assert keys == ["a-1", "a-2"]


def test_list_candidates_survives_source_fetch_failure(monkeypatch):
    """A failure fetching the broad source-candidate list must not 500 the
    endpoint: pins and shared items are resolved separately and must still
    render. Regression for the source query streaming the full history of every
    source and blowing the Firestore stream deadline for users with many
    high-volume sources (which surfaced as an opaque 500 and an empty queue)."""
    from newsletter_pod.shared_items import build_shared_item

    service, repo = _make_service()
    repo.replace_user_sources("u-1", [_user_source("u-1", "src-a")])

    # An item the user explicitly pushed via the share extension.
    shared = build_shared_item(
        user_id="u-1",
        title="Shared note",
        body_text="something the user shared",
        article_url="https://example.com/shared",
        received_at=_now(),
    )
    repo.save_inbound_item(shared)

    # Simulate the broad source query failing (e.g. stream deadline exceeded).
    def boom(*args, **kwargs):
        raise RuntimeError("firestore stream deadline exceeded")

    monkeypatch.setattr(repo, "list_source_items_by_source_published_since", boom)

    result = service.list_candidates("u-1", per_episode_cap=10)
    keys = [c["dedupe_key"] for c in result["candidates"]]
    assert keys == [f"inbound:{shared.id}"]
    assert result["candidates"][0]["shared"] is True


def test_list_candidates_drops_excluded_items_from_view():
    service, repo = _make_service()
    repo.replace_user_sources("u-1", [_user_source("u-1", "src-a")])
    _seed_item(repo, dedupe_key="a-1", source_id="src-a")
    _seed_item(repo, dedupe_key="a-2", source_id="src-a")
    repo.save_next_episode_override(
        NextEpisodeOverrideRecord(
            user_id="u-1",
            source_item_dedupe_key="a-2",
            kind="exclude",
            created_at=_now(),
        )
    )
    result = service.list_candidates("u-1", per_episode_cap=10)
    assert [c["dedupe_key"] for c in result["candidates"]] == ["a-1"]


def test_list_candidates_includes_pinned_items_even_outside_lookback_window():
    """Pinned items survive lookback expiry — the user committed to them, the
    UI should keep showing them until generation consumes the pin."""
    service, repo = _make_service()
    repo.replace_user_sources("u-1", [_user_source("u-1", "src-a")])
    # Recent item — within lookback.
    _seed_item(repo, dedupe_key="recent", source_id="src-a", published_at=_now())
    # Old item — outside the 14-day window. Source isn't even on the list
    # (could be a since-detached source) but the pin keeps it visible.
    old = _now() - timedelta(days=60)
    _seed_item(repo, dedupe_key="ancient", source_id="src-gone", published_at=old)
    repo.save_next_episode_override(
        NextEpisodeOverrideRecord(
            user_id="u-1",
            source_item_dedupe_key="ancient",
            kind="pin",
            created_at=_now(),
        )
    )

    result = service.list_candidates("u-1", per_episode_cap=10)
    by_key = {c["dedupe_key"]: c for c in result["candidates"]}
    assert "ancient" in by_key and by_key["ancient"]["pinned"] is True
    assert by_key["ancient"]["likely_included"] is True
    assert "recent" in by_key


def test_list_candidates_marks_likely_via_chronological_when_below_min_swipes():
    """User with no swipes hits the chronological fallback. With cap=2 and
    three items, the two most-recent should be marked likely_included."""
    service, repo = _make_service()
    service.settings.swipe_ranker_min_swipes = 3
    repo.replace_user_sources("u-1", [_user_source("u-1", "src-a")])
    _seed_item(repo, dedupe_key="a", source_id="src-a", published_at=_now() - timedelta(hours=2))
    _seed_item(repo, dedupe_key="b", source_id="src-a", published_at=_now() - timedelta(hours=1))
    _seed_item(repo, dedupe_key="c", source_id="src-a", published_at=_now())

    result = service.list_candidates("u-1", per_episode_cap=2)
    likely = {c["dedupe_key"] for c in result["candidates"] if c["likely_included"]}
    assert likely == {"b", "c"}
    assert result["ranker_used"] is False


# --- pin / exclude / clear --------------------------------------------------


def test_pin_item_writes_override_and_reports_remaining_capacity():
    service, repo = _make_service()
    _seed_item(repo, dedupe_key="k1", source_id="src-a")
    result = service.pin_item("u-1", "k1")
    assert result["status"] == "pinned"
    assert result["pins_remaining"] == service.settings.next_episode_max_pins - 1

    overrides = repo.list_next_episode_overrides("u-1", kind="pin")
    assert [o.source_item_dedupe_key for o in overrides] == ["k1"]


def test_pin_item_is_idempotent():
    service, repo = _make_service()
    _seed_item(repo, dedupe_key="k1", source_id="src-a")
    first = service.pin_item("u-1", "k1")
    second = service.pin_item("u-1", "k1")
    assert first["pins_remaining"] == second["pins_remaining"]
    assert len(repo.list_next_episode_overrides("u-1", kind="pin")) == 1


def test_pin_item_rejects_unknown_item():
    service, _ = _make_service()
    from newsletter_pod.candidate_queue import CandidateQueueError

    with pytest.raises(CandidateQueueError, match="Unknown source item"):
        service.pin_item("u-1", "ghost")


def test_pin_item_rejects_when_cap_reached():
    service, repo = _make_service()
    service.settings.next_episode_max_pins = 2
    _seed_item(repo, dedupe_key="k1", source_id="src-a")
    _seed_item(repo, dedupe_key="k2", source_id="src-a")
    _seed_item(repo, dedupe_key="k3", source_id="src-a")
    service.pin_item("u-1", "k1")
    service.pin_item("u-1", "k2")

    from newsletter_pod.candidate_queue import CandidateQueueError

    with pytest.raises(CandidateQueueError, match="cap reached"):
        service.pin_item("u-1", "k3")


def test_exclude_item_then_clear_round_trip():
    service, repo = _make_service()
    _seed_item(repo, dedupe_key="k1", source_id="src-a")
    service.exclude_item("u-1", "k1")
    assert (
        repo.list_next_episode_overrides("u-1", kind="exclude")[0].source_item_dedupe_key
        == "k1"
    )
    cleared = service.clear_override("u-1", "k1")
    assert cleared["status"] == "cleared"
    assert repo.list_next_episode_overrides("u-1") == []


def test_pin_then_exclude_replaces_kind_not_duplicates():
    """The (user, dedupe_key) pair is a single override row — flipping
    pin → exclude should overwrite, not stack."""
    service, repo = _make_service()
    _seed_item(repo, dedupe_key="k1", source_id="src-a")
    service.pin_item("u-1", "k1")
    service.exclude_item("u-1", "k1")
    all_overrides = repo.list_next_episode_overrides("u-1")
    assert len(all_overrides) == 1
    assert all_overrides[0].kind == "exclude"


# --- end-to-end: pin honored in process_user_generation ---------------------


def test_pinned_item_force_included_in_episode_and_stamped_consumed(monkeypatch):
    """End-to-end: with the queue enabled, a pinned item that would have
    been dropped by the ranker still lands in the published episode, and
    its override row is marked consumed afterwards."""
    from tests.test_control_plane_api import (
        FakeAppleVerifier,
        FakePodcastClient,
        _auth_headers,
        _build_app,
    )

    container, client = _build_app()
    _, headers = _auth_headers(
        client, FakeAppleVerifier("pin-honor-user", "ph@example.com")
    )
    container.control_plane.podcast_client = FakePodcastClient()
    container.control_plane.settings.candidate_queue_enabled = True
    container.control_plane.settings.next_episode_max_pins = 5
    # Force the per-tier item cap to 1 so we know the pin has to displace
    # a more-recent / better-ranked item.
    container.control_plane.settings.free_max_items_per_episode = 1
    container.control_plane.settings.swipe_ranker_enabled = False

    user_id = list(container.control_repository._users.values())[0].id

    # Two items from a source the user has attached. The "fresh" one is the
    # one chronological fallback would pick; the "stale" one is what we'll
    # pin to force it in instead.
    container.control_repository.replace_user_sources(
        user_id, [_user_source(user_id, "src-a")]
    )
    base = _now()
    _seed_item(
        container.control_repository,
        dedupe_key="stale",
        source_id="src-a",
        published_at=base - timedelta(days=2),
    )
    _seed_item(
        container.control_repository,
        dedupe_key="fresh",
        source_id="src-a",
        published_at=base,
    )

    container.control_plane.pin_next_episode_item(user_id, "stale")

    # Stub ingestion so the run uses the already-persisted items as candidates.
    fresh_record = container.control_repository.get_source_item("fresh")
    stale_record = container.control_repository.get_source_item("stale")
    assert fresh_record and stale_record
    candidate_items = [
        SourceItem(
            source_id=r.source_id,
            source_name=r.source_name,
            guid=r.guid,
            link=r.link,
            title=r.title,
            summary=r.summary,
            published_at=r.published_at,
            dedupe_key=r.dedupe_key,
        )
        for r in (stale_record, fresh_record)
    ]

    def fake_fetch(self, sources):
        return IngestionResult(items=candidate_items, cursor_updates={})

    monkeypatch.setattr(
        "newsletter_pod.control_plane.RSSIngestionService.fetch_new_items", fake_fetch
    )

    result = container.control_plane.process_user_generation(user_id, force=True)
    episode = result["episode"]
    refs = episode["source_item_refs"]
    assert len(refs) == 1
    assert refs[0]["title"] == "Title stale", (
        "pinned 'stale' item should have displaced the more-recent 'fresh' item"
    )

    overrides = container.control_repository.list_next_episode_overrides(
        user_id, only_unconsumed=False
    )
    assert len(overrides) == 1
    assert overrides[0].consumed_at is not None, (
        "honored pin should be stamped consumed after the episode publishes"
    )


def test_excluded_item_filtered_out_of_generation(monkeypatch):
    from tests.test_control_plane_api import (
        FakeAppleVerifier,
        FakePodcastClient,
        _auth_headers,
        _build_app,
    )

    container, client = _build_app()
    _, headers = _auth_headers(
        client, FakeAppleVerifier("excl-user", "ex@example.com")
    )
    container.control_plane.podcast_client = FakePodcastClient()
    container.control_plane.settings.candidate_queue_enabled = True
    container.control_plane.settings.free_max_items_per_episode = 5
    container.control_plane.settings.swipe_ranker_enabled = False

    user_id = list(container.control_repository._users.values())[0].id
    container.control_repository.replace_user_sources(
        user_id, [_user_source(user_id, "src-a")]
    )
    base = _now()
    _seed_item(
        container.control_repository,
        dedupe_key="keep",
        source_id="src-a",
        published_at=base,
    )
    _seed_item(
        container.control_repository,
        dedupe_key="drop",
        source_id="src-a",
        published_at=base - timedelta(hours=1),
    )
    container.control_plane.exclude_next_episode_item(user_id, "drop")

    keep = container.control_repository.get_source_item("keep")
    drop = container.control_repository.get_source_item("drop")
    candidate_items = [
        SourceItem(
            source_id=r.source_id,
            source_name=r.source_name,
            guid=r.guid,
            link=r.link,
            title=r.title,
            summary=r.summary,
            published_at=r.published_at,
            dedupe_key=r.dedupe_key,
        )
        for r in (drop, keep)
    ]

    def fake_fetch(self, sources):
        return IngestionResult(items=candidate_items, cursor_updates={})

    monkeypatch.setattr(
        "newsletter_pod.control_plane.RSSIngestionService.fetch_new_items", fake_fetch
    )

    result = container.control_plane.process_user_generation(user_id, force=True)
    titles = [ref["title"] for ref in result["episode"]["source_item_refs"]]
    assert "Title keep" in titles
    assert "Title drop" not in titles
