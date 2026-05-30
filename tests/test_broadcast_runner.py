from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

import pytest

from newsletter_pod.broadcast.models import BroadcastLoopRecord
from newsletter_pod.broadcast.publisher import BroadcastPublisher
from newsletter_pod.broadcast.repository import InMemoryBroadcastRepository
from newsletter_pod.broadcast.runner import (
    LoopInactive,
    LoopNotFound,
    ScheduledBroadcastRunner,
)
from newsletter_pod.broadcast.service import BroadcastService, BroadcastSettings
from newsletter_pod.broadcast.topic_picker import BroadcastTopicPicker
from newsletter_pod.broadcast.x_client import XPostResult
from newsletter_pod.models import AudioSegment, GeneratedEpisode
from newsletter_pod.storage import InMemoryAudioStorage


class _FakePodcastClient:
    def generate(
        self,
        prompt,
        title,
        voice_id=None,
        secondary_voice_id=None,
        primary_speaker_name=None,
        secondary_speaker_name=None,
        ux=None,
        force_default_voice=False,
    ):
        return GeneratedEpisode(
            episode_title=title,
            audio_bytes=b"mp3",
            mime_type="audio/mpeg",
            show_notes="notes",
            audio_segments=[AudioSegment(role="primary", speaker="V", text="hi")],
            transcript="V: hi",
            duration_seconds=10,
        )


class _FakeXClient:
    def __init__(self) -> None:
        self.video_calls: list[dict] = []
        self.reply_calls: list[dict] = []

    def post_video_tweet(self, *, video_bytes, text, in_reply_to_tweet_id=None):
        self.video_calls.append({"text": text, "in_reply_to_tweet_id": in_reply_to_tweet_id})
        return XPostResult(tweet_id="100", tweet_url="https://x.com/i/status/100", media_id="m1")

    def post_reply(self, *, text, in_reply_to_tweet_id):
        self.reply_calls.append({"text": text, "in_reply_to_tweet_id": in_reply_to_tweet_id})
        return XPostResult(tweet_id="101", tweet_url="https://x.com/i/status/101")


class _FakeProposer:
    def __init__(self, *, topic: str = "Proposed topic") -> None:
        self.topic = topic

    def propose(self, *, audience_persona, prior_feedback_summary, seed_topics):
        return self.topic


def _loop(loop_id: str = "us-morning", active: bool = True) -> BroadcastLoopRecord:
    return BroadcastLoopRecord(
        loop_id=loop_id,
        region="US",
        timezone="America/Los_Angeles",
        audience_persona="builders",
        seed_topics=[],
        active=active,
        created_at=datetime(2026, 5, 30, tzinfo=timezone.utc),
        updated_at=datetime(2026, 5, 30, tzinfo=timezone.utc),
    )


def _fake_renderer(*, audio_bytes, cover_image_bytes):
    return b"mp4-bytes"


def _build_runner(tmp_path: Path) -> tuple[ScheduledBroadcastRunner, InMemoryBroadcastRepository, _FakeXClient]:
    cover = tmp_path / "cover.png"
    cover.write_bytes(b"cover")
    storage = InMemoryAudioStorage()
    repo = InMemoryBroadcastRepository()
    settings = BroadcastSettings(
        app_base_url="https://example.test",
        primary_voice_id="v1",
        secondary_voice_id="v2",
        primary_host_name="Vinnie",
        secondary_host_name="Demi",
        cover_image_path=cover,
    )
    service = BroadcastService(
        settings=settings,
        storage=storage,
        podcast_client=_FakePodcastClient(),
        renderer=_fake_renderer,
        episode_id_factory=lambda: "deadbeefdeadbeef",
    )
    x = _FakeXClient()
    publisher = BroadcastPublisher(storage=storage, x_client=x)
    picker = BroadcastTopicPicker(proposer=_FakeProposer(), repository=repo)
    runner = ScheduledBroadcastRunner(
        repository=repo,
        topic_picker=picker,
        broadcast_service=service,
        publisher=publisher,
        run_date_factory=lambda loop: date(2026, 5, 30),
    )
    return runner, repo, x


def test_run_persists_episode_with_tweet_ids(tmp_path):
    runner, repo, x = _build_runner(tmp_path)
    repo.save_loop(_loop())

    result = runner.run("us-morning")

    assert result.episode_id == "deadbeefdeadbeef"
    assert result.topic == "Proposed topic"
    assert result.episode_tweet_id == "100"
    assert result.feedback_prompt_tweet_id == "101"

    persisted = repo.get_episode("deadbeefdeadbeef")
    assert persisted is not None
    assert persisted.loop_id == "us-morning"
    assert persisted.topic_used == "Proposed topic"
    assert persisted.episode_tweet_id == "100"
    assert persisted.feedback_prompt_tweet_id == "101"
    assert persisted.run_date == date(2026, 5, 30)


def test_run_uses_default_tweet_text_when_no_override(tmp_path):
    runner, repo, x = _build_runner(tmp_path)
    repo.save_loop(_loop())

    runner.run("us-morning")

    assert "Proposed topic" in x.video_calls[0]["text"]
    assert x.video_calls[0]["text"].startswith("New episode: ")


def test_run_uses_tweet_text_override(tmp_path):
    runner, repo, x = _build_runner(tmp_path)
    repo.save_loop(_loop())

    runner.run("us-morning", tweet_text_override="custom!")

    assert x.video_calls[0]["text"] == "custom!"


def test_run_raises_loopnotfound_for_missing_loop(tmp_path):
    runner, _, _ = _build_runner(tmp_path)
    with pytest.raises(LoopNotFound):
        runner.run("missing")


def test_run_raises_loopinactive_for_paused_loop(tmp_path):
    runner, repo, _ = _build_runner(tmp_path)
    repo.save_loop(_loop(active=False))
    with pytest.raises(LoopInactive):
        runner.run("us-morning")


def test_run_threads_feedback_prompt_to_episode_tweet(tmp_path):
    runner, repo, x = _build_runner(tmp_path)
    repo.save_loop(_loop())

    runner.run("us-morning")

    assert len(x.reply_calls) == 1
    assert x.reply_calls[0]["in_reply_to_tweet_id"] == "100"
