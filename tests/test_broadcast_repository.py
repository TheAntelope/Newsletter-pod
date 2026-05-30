from __future__ import annotations

from datetime import date, datetime, timezone

import pytest

from newsletter_pod.broadcast.models import BroadcastEpisodeRecord, BroadcastLoopRecord
from newsletter_pod.broadcast.repository import (
    InMemoryBroadcastRepository,
    validate_loop_id,
)


def _make_loop(loop_id: str = "us-morning", active: bool = True) -> BroadcastLoopRecord:
    return BroadcastLoopRecord(
        loop_id=loop_id,
        region="US",
        timezone="America/Los_Angeles",
        audience_persona="indie founders",
        seed_topics=["x", "y"],
        active=active,
        created_at=datetime(2026, 5, 30, tzinfo=timezone.utc),
        updated_at=datetime(2026, 5, 30, tzinfo=timezone.utc),
    )


def _make_episode(
    episode_id: str,
    loop_id: str = "us-morning",
    run_date: date = date(2026, 5, 30),
    created_at: datetime = datetime(2026, 5, 30, tzinfo=timezone.utc),
) -> BroadcastEpisodeRecord:
    return BroadcastEpisodeRecord(
        episode_id=episode_id,
        loop_id=loop_id,
        run_date=run_date,
        topic_used="topic",
        title="t",
        show_notes="n",
        audio_object_name=f"broadcast/{episode_id}.mp3",
        video_object_name=f"broadcast/{episode_id}.mp4",
        created_at=created_at,
    )


def test_validate_loop_id_accepts_lowercase_alphanum_dashes_underscores():
    assert validate_loop_id("us-morning") == "us-morning"
    assert validate_loop_id("US-Morning") == "us-morning"
    assert validate_loop_id("a") == "a"
    assert validate_loop_id("loop_42") == "loop_42"


def test_validate_loop_id_rejects_bad_inputs():
    for bad in ["", " ", "loop/with/slash", "with space", "-leading-dash", "x" * 49]:
        with pytest.raises(ValueError):
            validate_loop_id(bad)


def test_save_and_get_loop_round_trip():
    repo = InMemoryBroadcastRepository()
    loop = _make_loop()
    repo.save_loop(loop)
    assert repo.get_loop("us-morning") == loop


def test_get_loop_returns_none_when_missing():
    assert InMemoryBroadcastRepository().get_loop("missing") is None


def test_list_loops_active_only_filter():
    repo = InMemoryBroadcastRepository()
    repo.save_loop(_make_loop("a", active=True))
    repo.save_loop(_make_loop("b", active=False))
    repo.save_loop(_make_loop("c", active=True))

    assert [l.loop_id for l in repo.list_loops()] == ["a", "b", "c"]
    assert [l.loop_id for l in repo.list_loops(active_only=True)] == ["a", "c"]


def test_delete_loop_idempotent():
    repo = InMemoryBroadcastRepository()
    repo.save_loop(_make_loop("x"))
    assert repo.delete_loop("x") is True
    assert repo.delete_loop("x") is False
    assert repo.get_loop("x") is None


def test_get_latest_episode_for_loop_orders_by_date_then_created_at():
    repo = InMemoryBroadcastRepository()
    repo.save_episode(_make_episode("aaaaaaaaaaaaaaaa", run_date=date(2026, 5, 29)))
    # Latest by run_date wins, even if created_at is older
    repo.save_episode(_make_episode(
        "bbbbbbbbbbbbbbbb",
        run_date=date(2026, 5, 30),
        created_at=datetime(2026, 5, 30, 1, tzinfo=timezone.utc),
    ))
    # Same run_date but later created_at → wins
    repo.save_episode(_make_episode(
        "cccccccccccccccc",
        run_date=date(2026, 5, 30),
        created_at=datetime(2026, 5, 30, 12, tzinfo=timezone.utc),
    ))

    latest = repo.get_latest_episode_for_loop("us-morning")
    assert latest is not None
    assert latest.episode_id == "cccccccccccccccc"


def test_get_latest_episode_for_loop_isolates_by_loop_id():
    repo = InMemoryBroadcastRepository()
    repo.save_episode(_make_episode("aaaaaaaaaaaaaaaa", loop_id="us-morning"))
    repo.save_episode(_make_episode("bbbbbbbbbbbbbbbb", loop_id="eu-morning"))

    assert repo.get_latest_episode_for_loop("us-morning").episode_id == "aaaaaaaaaaaaaaaa"
    assert repo.get_latest_episode_for_loop("eu-morning").episode_id == "bbbbbbbbbbbbbbbb"
    assert repo.get_latest_episode_for_loop("apac-morning") is None


def test_list_episodes_respects_limit():
    repo = InMemoryBroadcastRepository()
    for i in range(5):
        repo.save_episode(_make_episode(
            f"{i:016x}",
            created_at=datetime(2026, 5, 30, i, tzinfo=timezone.utc),
        ))

    assert len(repo.list_episodes_for_loop("us-morning", limit=3)) == 3
    # Sorted newest first
    episodes = repo.list_episodes_for_loop("us-morning", limit=100)
    assert episodes[0].created_at > episodes[-1].created_at
