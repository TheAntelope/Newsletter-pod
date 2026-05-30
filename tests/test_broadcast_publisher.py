from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pytest

from newsletter_pod.broadcast.publisher import (
    DEFAULT_FEEDBACK_PROMPT,
    BroadcastPublisher,
)
from newsletter_pod.broadcast.x_client import XPostFailed, XPostResult
from newsletter_pod.storage import InMemoryAudioStorage


@dataclass
class _RecordedVideoTweet:
    video_bytes: bytes
    text: str
    in_reply_to_tweet_id: Optional[str]


@dataclass
class _RecordedReply:
    text: str
    in_reply_to_tweet_id: str


class _FakeXClient:
    def __init__(
        self,
        *,
        episode_tweet_id: str = "100",
        reply_tweet_id: str = "101",
        episode_post_raises: Optional[Exception] = None,
        reply_raises: Optional[Exception] = None,
        handle: str = "theclawcast",
    ) -> None:
        self.episode_tweet_id = episode_tweet_id
        self.reply_tweet_id = reply_tweet_id
        self.episode_post_raises = episode_post_raises
        self.reply_raises = reply_raises
        self.handle = handle
        self.video_calls: list[_RecordedVideoTweet] = []
        self.reply_calls: list[_RecordedReply] = []

    def post_video_tweet(self, *, video_bytes, text, in_reply_to_tweet_id=None):
        self.video_calls.append(_RecordedVideoTweet(video_bytes, text, in_reply_to_tweet_id))
        if self.episode_post_raises:
            raise self.episode_post_raises
        return XPostResult(
            tweet_id=self.episode_tweet_id,
            tweet_url=f"https://x.com/{self.handle}/status/{self.episode_tweet_id}",
            media_id="m1",
        )

    def post_reply(self, *, text, in_reply_to_tweet_id):
        self.reply_calls.append(_RecordedReply(text, in_reply_to_tweet_id))
        if self.reply_raises:
            raise self.reply_raises
        return XPostResult(
            tweet_id=self.reply_tweet_id,
            tweet_url=f"https://x.com/{self.handle}/status/{self.reply_tweet_id}",
        )


def _seed_video(storage: InMemoryAudioStorage, episode_id: str, video_bytes: bytes = b"mp4") -> None:
    storage.upload_object(f"broadcast/{episode_id}.mp4", video_bytes, "video/mp4")


def test_publish_posts_episode_then_default_feedback_reply():
    storage = InMemoryAudioStorage()
    _seed_video(storage, "0123456789abcdef", video_bytes=b"the-video")
    x = _FakeXClient(episode_tweet_id="555", reply_tweet_id="556")
    publisher = BroadcastPublisher(storage=storage, x_client=x)

    result = publisher.publish(
        episode_id="0123456789abcdef",
        tweet_text="ep!",
    )

    assert result.episode_tweet_id == "555"
    assert result.episode_tweet_url.endswith("/status/555")
    assert result.feedback_prompt_tweet_id == "556"
    assert result.feedback_prompt_tweet_url.endswith("/status/556")
    assert len(x.video_calls) == 1
    assert x.video_calls[0].video_bytes == b"the-video"
    assert x.video_calls[0].text == "ep!"
    # Reply threads under the episode tweet, with the default copy.
    assert len(x.reply_calls) == 1
    assert x.reply_calls[0].in_reply_to_tweet_id == "555"
    assert x.reply_calls[0].text == DEFAULT_FEEDBACK_PROMPT


def test_publish_with_explicit_feedback_text_overrides_default():
    storage = InMemoryAudioStorage()
    _seed_video(storage, "deadbeefdeadbeef")
    x = _FakeXClient()
    publisher = BroadcastPublisher(storage=storage, x_client=x)

    publisher.publish(
        episode_id="deadbeefdeadbeef",
        tweet_text="ep",
        feedback_prompt_text="custom prompt",
    )

    assert x.reply_calls[-1].text == "custom prompt"


def test_publish_with_none_feedback_text_suppresses_reply():
    storage = InMemoryAudioStorage()
    _seed_video(storage, "deadbeefdeadbeef")
    x = _FakeXClient()
    publisher = BroadcastPublisher(storage=storage, x_client=x)

    result = publisher.publish(
        episode_id="deadbeefdeadbeef",
        tweet_text="ep",
        feedback_prompt_text=None,
    )

    assert result.feedback_prompt_tweet_id is None
    assert result.feedback_prompt_tweet_url is None
    assert x.reply_calls == []


def test_publish_returns_success_even_when_feedback_reply_fails():
    # Episode is the load-bearing post; a failed reply is a degraded
    # success, not a publish failure. The caller learns about it via
    # the missing feedback_prompt_tweet_id, plus warning-level logs.
    storage = InMemoryAudioStorage()
    _seed_video(storage, "deadbeefdeadbeef")
    x = _FakeXClient(reply_raises=XPostFailed("reply boom"))
    publisher = BroadcastPublisher(storage=storage, x_client=x)

    result = publisher.publish(
        episode_id="deadbeefdeadbeef",
        tweet_text="ep",
    )

    assert result.episode_tweet_id == "100"
    assert result.feedback_prompt_tweet_id is None


def test_publish_propagates_episode_post_failure():
    storage = InMemoryAudioStorage()
    _seed_video(storage, "deadbeefdeadbeef")
    x = _FakeXClient(episode_post_raises=XPostFailed("episode boom"))
    publisher = BroadcastPublisher(storage=storage, x_client=x)

    with pytest.raises(XPostFailed):
        publisher.publish(episode_id="deadbeefdeadbeef", tweet_text="ep")
    # Reply should never have been attempted.
    assert x.reply_calls == []


def test_publish_raises_filenotfound_when_video_missing():
    publisher = BroadcastPublisher(storage=InMemoryAudioStorage(), x_client=_FakeXClient())

    with pytest.raises(FileNotFoundError):
        publisher.publish(episode_id="missingmissingxx", tweet_text="ep")
