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
from newsletter_pod.broadcast.x_client import ReplyItem, XPostResult, XReadFailed
from newsletter_pod.models import AudioSegment, GeneratedEpisode, SourceItem
from newsletter_pod.storage import InMemoryAudioStorage


def _src_item(source_id="src-a", title="t", summary="s"):
    return SourceItem(
        source_id=source_id,
        source_name=f"name-{source_id}",
        guid=title,
        link=f"https://x.test/{title}",
        title=title,
        summary=summary,
        published_at=datetime(2026, 5, 30, tzinfo=timezone.utc),
        dedupe_key=title,
    )


# Captures the prompt that generate() was called with — so the source-items
# test can assert the brief actually reached the LLM call.
class _CapturingPodcastClient:
    def __init__(self) -> None:
        self.prompts: list[str] = []

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
        lead_in_texts=None,
        tail_texts=None,
    ):
        self.prompts.append(prompt)
        return GeneratedEpisode(
            episode_title=title,
            audio_bytes=b"mp3",
            mime_type="audio/mpeg",
            show_notes="notes",
            audio_segments=[AudioSegment(role="primary", speaker="V", text="hi")],
            transcript="V: hi",
            duration_seconds=10,
        )


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
        lead_in_texts=None,
        tail_texts=None,
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
    def __init__(self, *, replies=None, raise_on_fetch=None) -> None:
        self.video_calls: list[dict] = []
        self.reply_calls: list[dict] = []
        self.fetch_calls: list[dict] = []
        self._replies = replies or []
        self._raise_on_fetch = raise_on_fetch

    def post_video_tweet(self, *, video_bytes, text, in_reply_to_tweet_id=None):
        self.video_calls.append({"text": text, "in_reply_to_tweet_id": in_reply_to_tweet_id})
        return XPostResult(tweet_id="100", tweet_url="https://x.com/i/status/100", media_id="m1")

    def post_reply(self, *, text, in_reply_to_tweet_id):
        self.reply_calls.append({"text": text, "in_reply_to_tweet_id": in_reply_to_tweet_id})
        return XPostResult(tweet_id="101", tweet_url="https://x.com/i/status/101")

    def fetch_conversation_replies(self, *, conversation_id, max_results=100):
        self.fetch_calls.append({"conversation_id": conversation_id, "max_results": max_results})
        if self._raise_on_fetch is not None:
            raise self._raise_on_fetch
        return list(self._replies)


class _FakeSummarizer:
    """Deterministic stand-in for OpenAIFeedbackSummarizer. summary_for can
    map a topic to a canned output (or None) so tests can simulate the
    summarizer returning nothing useful. raise_on_call lets us assert
    runner-level graceful handling."""

    def __init__(self, *, summary="audience wants more on X", raise_on_call=None) -> None:
        self.calls: list[dict] = []
        self._summary = summary
        self._raise = raise_on_call

    def summarize(self, *, replies_text, topic):
        self.calls.append({"replies_text": replies_text, "topic": topic})
        if self._raise is not None:
            raise self._raise
        return self._summary


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


def _build_runner(
    tmp_path: Path,
    *,
    source_item_provider=None,
    podcast_client=None,
    x_client: Optional[_FakeXClient] = None,
    feedback_summarizer=None,
    proposer=None,
) -> tuple[ScheduledBroadcastRunner, InMemoryBroadcastRepository, _FakeXClient]:
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
        podcast_client=podcast_client or _FakePodcastClient(),
        renderer=_fake_renderer,
        episode_id_factory=lambda: "deadbeefdeadbeef",
    )
    x = x_client or _FakeXClient()
    publisher = BroadcastPublisher(storage=storage, x_client=x)
    picker = BroadcastTopicPicker(
        proposer=proposer or _FakeProposer(), repository=repo,
    )
    runner = ScheduledBroadcastRunner(
        repository=repo,
        topic_picker=picker,
        broadcast_service=service,
        publisher=publisher,
        source_item_provider=source_item_provider,
        run_date_factory=lambda loop: date(2026, 5, 30),
        x_client=x if feedback_summarizer is not None else None,
        feedback_summarizer=feedback_summarizer,
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

    text = x.video_calls[0]["text"]
    assert "Proposed topic" in text
    assert text.startswith("New episode: ")
    # App-Store CTA: must be in the default tweet so every scheduled post
    # promotes the app and matches the spoken APP_CTA inside framing.py.
    # Total tweet length must stay under the 280-char cap.
    assert "https://www.theclawcast.com/" in text
    assert "App Store" in text
    # Brand is "The Claw Cast" — "The" intentional.
    assert "The Claw Cast" in text
    assert len(text) <= 280


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


def test_run_calls_source_item_provider_and_includes_items_in_prompt(tmp_path):
    captured: dict[str, list[str]] = {}

    def provider(source_ids: list[str]):
        captured["source_ids"] = list(source_ids)
        return [_src_item(source_id="src-a", title="Hot take from A")]

    client = _CapturingPodcastClient()
    runner, repo, _ = _build_runner(
        tmp_path, source_item_provider=provider, podcast_client=client
    )
    loop = _loop()
    loop = loop.model_copy(update={"source_ids": ["src-a", "src-b"]})
    repo.save_loop(loop)

    runner.run("us-morning")

    assert captured["source_ids"] == ["src-a", "src-b"]
    assert client.prompts, "podcast client never called"
    assert "Hot take from A" in client.prompts[0]
    assert "Recent source items" in client.prompts[0]


def test_run_falls_back_to_ungrounded_when_provider_raises(tmp_path):
    def provider(source_ids: list[str]):
        raise RuntimeError("upstream went down")

    client = _CapturingPodcastClient()
    runner, repo, _ = _build_runner(
        tmp_path, source_item_provider=provider, podcast_client=client
    )
    loop = _loop().model_copy(update={"source_ids": ["src-a"]})
    repo.save_loop(loop)

    runner.run("us-morning")

    # Run completes and the prompt does not get the source block.
    assert client.prompts
    assert "Recent source items" not in client.prompts[0]


def test_run_skips_provider_when_loop_has_no_source_ids(tmp_path):
    calls: list[list[str]] = []

    def provider(source_ids: list[str]):
        calls.append(list(source_ids))
        return [_src_item()]

    runner, repo, _ = _build_runner(tmp_path, source_item_provider=provider)
    repo.save_loop(_loop())  # default source_ids=[]

    runner.run("us-morning")

    assert calls == []


# ---- auto-poll of yesterday's replies before topic pick -------------------


def _prior_episode(
    *,
    episode_id="aaaaaaaaaaaaaaaa",
    loop_id="us-morning",
    tweet_id="900",
    feedback_pasted_at=None,
    topic="yesterday's topic",
) -> "BroadcastEpisodeRecord":
    from newsletter_pod.broadcast.models import BroadcastEpisodeRecord
    return BroadcastEpisodeRecord(
        episode_id=episode_id,
        loop_id=loop_id,
        run_date=date(2026, 5, 29),
        topic_used=topic,
        title="t",
        show_notes="n",
        audio_object_name=f"broadcast/{episode_id}.mp3",
        video_object_name=f"broadcast/{episode_id}.mp4",
        episode_tweet_id=tweet_id,
        episode_tweet_url=f"https://x.com/i/status/{tweet_id}" if tweet_id else None,
        feedback_pasted_at=feedback_pasted_at,
        created_at=datetime(2026, 5, 29, tzinfo=timezone.utc),
    )


class _CapturingProposer:
    """Mirrors _FakeProposer but exposes the audience signal the picker
    passed it — so we can assert the auto-poll wrote feedback BEFORE the
    pick read it."""

    def __init__(self, topic="Proposed topic") -> None:
        self.calls: list[dict] = []
        self._topic = topic

    def propose(self, *, audience_persona, prior_feedback_summary, seed_topics):
        self.calls.append({
            "audience_persona": audience_persona,
            "prior_feedback_summary": prior_feedback_summary,
            "seed_topics": list(seed_topics),
        })
        return self._topic


def test_auto_poll_persists_summary_before_topic_picker_reads_it(tmp_path):
    # Happy path: X returns replies, summarizer condenses them, the prior
    # episode is updated with feedback_summary, and the topic-picker's
    # next propose() call sees that summary as prior_feedback_summary.
    xclient = _FakeXClient(replies=[
        ReplyItem(tweet_id="r1", author_username="Reader", text="more on Opus 4.8 please"),
    ])
    summarizer = _FakeSummarizer(summary="audience wants Opus 4.8 deep dive")
    proposer = _CapturingProposer(topic="Opus 4.8 deep dive")
    runner, repo, _ = _build_runner(
        tmp_path,
        x_client=xclient,
        feedback_summarizer=summarizer,
        proposer=proposer,
    )
    repo.save_loop(_loop())
    repo.save_episode(_prior_episode())

    runner.run("us-morning")

    # Auto-poll hit the right conversation_id...
    assert xclient.fetch_calls[-1]["conversation_id"] == "900"
    # ...and summarizer got the formatted reply text + prior topic.
    assert summarizer.calls[-1]["topic"] == "yesterday's topic"
    assert "@Reader: more on Opus 4.8 please" in summarizer.calls[-1]["replies_text"]
    # Prior episode now carries the summary.
    refreshed_prior = repo.get_episode("aaaaaaaaaaaaaaaa")
    assert refreshed_prior.feedback_summary == "audience wants Opus 4.8 deep dive"
    assert refreshed_prior.feedback_pasted_at is not None
    # And the topic-picker saw it.
    assert proposer.calls[-1]["prior_feedback_summary"] == "audience wants Opus 4.8 deep dive"


def test_auto_poll_skipped_when_no_prior_episode(tmp_path):
    # First-run case for a loop: no episodes yet, auto-poll is a no-op.
    xclient = _FakeXClient(replies=[ReplyItem(tweet_id="r", author_username="x", text="hi")])
    summarizer = _FakeSummarizer()
    runner, repo, _ = _build_runner(
        tmp_path, x_client=xclient, feedback_summarizer=summarizer,
    )
    repo.save_loop(_loop())

    runner.run("us-morning")

    assert xclient.fetch_calls == []
    assert summarizer.calls == []


def test_auto_poll_skipped_when_prior_has_no_tweet_id(tmp_path):
    # Prior episode publish failed (no tweet_id) — nothing to poll against.
    xclient = _FakeXClient(replies=[ReplyItem(tweet_id="r", author_username="x", text="hi")])
    summarizer = _FakeSummarizer()
    runner, repo, _ = _build_runner(
        tmp_path, x_client=xclient, feedback_summarizer=summarizer,
    )
    repo.save_loop(_loop())
    repo.save_episode(_prior_episode(tweet_id=None))

    runner.run("us-morning")

    assert xclient.fetch_calls == []


def test_auto_poll_skipped_when_prior_already_has_feedback(tmp_path):
    # Operator-pasted (or a previous run already auto-polled). Don't
    # overwrite — feedback_pasted_at is the idempotency marker.
    xclient = _FakeXClient(replies=[ReplyItem(tweet_id="r", author_username="x", text="hi")])
    summarizer = _FakeSummarizer()
    runner, repo, _ = _build_runner(
        tmp_path, x_client=xclient, feedback_summarizer=summarizer,
    )
    repo.save_loop(_loop())
    repo.save_episode(_prior_episode(feedback_pasted_at=datetime(2026, 5, 29, 23, tzinfo=timezone.utc)))

    runner.run("us-morning")

    assert xclient.fetch_calls == []


def test_auto_poll_handles_x_read_failure_without_failing_run(tmp_path):
    # Rate limit / network blip on the read MUST not stop the run.
    xclient = _FakeXClient(raise_on_fetch=XReadFailed("rate limited"))
    summarizer = _FakeSummarizer()
    runner, repo, _ = _build_runner(
        tmp_path, x_client=xclient, feedback_summarizer=summarizer,
    )
    repo.save_loop(_loop())
    repo.save_episode(_prior_episode())

    result = runner.run("us-morning")  # must not raise

    assert result.episode_id == "deadbeefdeadbeef"
    # Prior record untouched — no write attempted after the read failed.
    assert repo.get_episode("aaaaaaaaaaaaaaaa").feedback_summary is None
    assert summarizer.calls == []


def test_auto_poll_skipped_when_no_replies(tmp_path):
    # X returned an empty result set — no write so we don't clobber an
    # existing summary on a follow-up run.
    xclient = _FakeXClient(replies=[])
    summarizer = _FakeSummarizer()
    runner, repo, _ = _build_runner(
        tmp_path, x_client=xclient, feedback_summarizer=summarizer,
    )
    repo.save_loop(_loop())
    repo.save_episode(_prior_episode())

    runner.run("us-morning")

    assert xclient.fetch_calls[-1]["conversation_id"] == "900"
    assert summarizer.calls == []
    assert repo.get_episode("aaaaaaaaaaaaaaaa").feedback_summary is None
    assert repo.get_episode("aaaaaaaaaaaaaaaa").feedback_pasted_at is None


def test_auto_poll_persists_raw_even_when_summarizer_raises(tmp_path):
    # Summarizer exception is non-fatal: persist raw text + None summary so
    # the operator can still see what came in, and tomorrow's picker falls
    # back to round-robin seeds.
    xclient = _FakeXClient(replies=[
        ReplyItem(tweet_id="r1", author_username="Reader", text="meaningful reply"),
    ])
    summarizer = _FakeSummarizer(raise_on_call=RuntimeError("LLM outage"))
    runner, repo, _ = _build_runner(
        tmp_path, x_client=xclient, feedback_summarizer=summarizer,
    )
    repo.save_loop(_loop())
    repo.save_episode(_prior_episode())

    runner.run("us-morning")  # must not raise

    refreshed = repo.get_episode("aaaaaaaaaaaaaaaa")
    assert refreshed.feedback_summary is None
    assert "@Reader: meaningful reply" in refreshed.feedback_raw
    assert refreshed.feedback_pasted_at is not None


def test_auto_poll_skipped_when_deps_not_wired(tmp_path):
    # Backward-compat path: original test setups that don't pass auto-poll
    # deps must not silently start hitting X.
    xclient = _FakeXClient(replies=[ReplyItem(tweet_id="r", author_username="x", text="hi")])
    runner, repo, _ = _build_runner(tmp_path, x_client=xclient)  # no summarizer
    repo.save_loop(_loop())
    repo.save_episode(_prior_episode())

    runner.run("us-morning")

    assert xclient.fetch_calls == []


def test_run_picks_source_led_topic_and_grounds_on_chosen_story(tmp_path):
    from newsletter_pod.broadcast.topic_picker import BroadcastTopicPicker, TopicProposal

    # Two stories available; the proposer commits to the second one.
    def provider(source_ids: list[str]):
        return [_src_item(title="Story A"), _src_item(title="Story B", source_id="src-b")]

    class _SourceProposer:
        def propose(self, *, audience_persona, prior_feedback_summary, seed_topics):
            return "should-not-be-used"

        def propose_from_sources(self, *, audience_persona, source_items):
            return TopicProposal(topic="Story B, in depth", source_dedupe_key="Story B")

    client = _CapturingPodcastClient()
    runner, repo, _ = _build_runner(
        tmp_path, source_item_provider=provider, podcast_client=client
    )
    # Swap in the source-aware proposer (no prior feedback exists for this loop).
    runner._topic_picker = BroadcastTopicPicker(proposer=_SourceProposer(), repository=repo)
    repo.save_loop(_loop().model_copy(update={"source_ids": ["src-a", "src-b"]}))

    result = runner.run("us-morning")

    assert result.topic == "Story B, in depth"
    assert repo.get_episode("deadbeefdeadbeef").topic_used == "Story B, in depth"
    prompt = client.prompts[0]
    # The episode is grounded on the chosen story only — Story A is dropped.
    assert "Story B" in prompt
    assert "Story A" not in prompt
