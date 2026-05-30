from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pytest
import tweepy

from newsletter_pod.broadcast.x_client import (
    TWEET_TEXT_MAX_CHARS,
    XClient,
    XClientUnavailable,
    XPostFailed,
)


@dataclass
class _FakeMedia:
    media_id_string: str


class _FakeUploader:
    def __init__(self, media_id: str = "media-123", raise_on_upload: bool = False) -> None:
        self.media_id = media_id
        self.raise_on_upload = raise_on_upload
        self.calls: list[dict] = []

    def media_upload(self, filename: str, *, media_category: str, chunked: bool):
        self.calls.append(
            {"filename": filename, "media_category": media_category, "chunked": chunked}
        )
        if self.raise_on_upload:
            raise tweepy.TweepyException("upload boom")
        return _FakeMedia(media_id_string=self.media_id)


@dataclass
class _FakeTweetResponse:
    data: dict


class _FakePoster:
    def __init__(
        self,
        tweet_id: str = "1700000000000000000",
        raise_on_create: bool = False,
    ) -> None:
        self.tweet_id = tweet_id
        self.raise_on_create = raise_on_create
        self.calls: list[dict] = []

    def create_tweet(
        self,
        *,
        text: str,
        media_ids: Optional[list[str]] = None,
        in_reply_to_tweet_id: Optional[str] = None,
    ):
        self.calls.append(
            {
                "text": text,
                "media_ids": media_ids,
                "in_reply_to_tweet_id": in_reply_to_tweet_id,
            }
        )
        if self.raise_on_create:
            raise tweepy.TweepyException("tweet boom")
        return _FakeTweetResponse(data={"id": self.tweet_id})


def _client(uploader=None, poster=None, configured: bool = True, username: str = "theclawcast") -> XClient:
    if configured:
        creds = {"api_key": "k", "api_secret": "s", "access_token": "t", "access_token_secret": "ts"}
    else:
        creds = {"api_key": None, "api_secret": None, "access_token": None, "access_token_secret": None}
    return XClient(
        username=username,
        media_uploader=uploader,
        tweet_poster=poster,
        **creds,
    )


def test_is_configured_false_when_any_credential_missing():
    client = XClient(api_key="k", api_secret=None, access_token="t", access_token_secret="ts")
    assert client.is_configured is False

    client = XClient(api_key="k", api_secret="s", access_token="t", access_token_secret="ts")
    assert client.is_configured is True


def test_post_video_tweet_requires_full_credentials():
    client = _client(configured=False)
    with pytest.raises(XClientUnavailable):
        client.post_video_tweet(video_bytes=b"mp4", text="hi")


def test_post_video_tweet_uploads_then_posts_with_media_id():
    uploader = _FakeUploader(media_id="m1")
    poster = _FakePoster(tweet_id="42")
    client = _client(uploader=uploader, poster=poster)

    result = client.post_video_tweet(video_bytes=b"mp4-bytes", text="Hello X")

    assert result.tweet_id == "42"
    assert result.media_id == "m1"
    assert result.tweet_url == "https://x.com/theclawcast/status/42"
    assert len(uploader.calls) == 1
    assert uploader.calls[0]["chunked"] is True
    assert uploader.calls[0]["media_category"] == "tweet_video"
    assert len(poster.calls) == 1
    assert poster.calls[0]["text"] == "Hello X"
    assert poster.calls[0]["media_ids"] == ["m1"]
    assert poster.calls[0]["in_reply_to_tweet_id"] is None


def test_post_video_tweet_truncates_long_text():
    uploader = _FakeUploader()
    poster = _FakePoster()
    client = _client(uploader=uploader, poster=poster)
    long_text = "a" * (TWEET_TEXT_MAX_CHARS + 50)

    client.post_video_tweet(video_bytes=b"mp4", text=long_text)

    posted_text = poster.calls[0]["text"]
    assert len(posted_text) <= TWEET_TEXT_MAX_CHARS
    assert posted_text.endswith("…")


def test_post_video_tweet_wraps_upload_failure_as_xpostfailed():
    uploader = _FakeUploader(raise_on_upload=True)
    poster = _FakePoster()
    client = _client(uploader=uploader, poster=poster)

    with pytest.raises(XPostFailed) as excinfo:
        client.post_video_tweet(video_bytes=b"mp4", text="t")
    assert "upload" in str(excinfo.value).lower()
    # Poster should NOT have been called since the upload failed first.
    assert poster.calls == []


def test_post_video_tweet_wraps_create_failure_as_xpostfailed():
    uploader = _FakeUploader()
    poster = _FakePoster(raise_on_create=True)
    client = _client(uploader=uploader, poster=poster)

    with pytest.raises(XPostFailed):
        client.post_video_tweet(video_bytes=b"mp4", text="t")


def test_post_reply_posts_text_only_threaded_to_parent():
    poster = _FakePoster(tweet_id="99")
    client = _client(uploader=_FakeUploader(), poster=poster)

    result = client.post_reply(text="What should we cover?", in_reply_to_tweet_id="42")

    assert result.tweet_id == "99"
    assert result.media_id is None
    assert result.tweet_url == "https://x.com/theclawcast/status/99"
    assert poster.calls[-1]["in_reply_to_tweet_id"] == "42"
    assert poster.calls[-1]["media_ids"] is None


def test_post_reply_truncates_long_text():
    poster = _FakePoster()
    client = _client(uploader=_FakeUploader(), poster=poster)
    client.post_reply(text="x" * 400, in_reply_to_tweet_id="42")

    posted_text = poster.calls[-1]["text"]
    assert len(posted_text) <= TWEET_TEXT_MAX_CHARS
    assert posted_text.endswith("…")


def test_tweet_url_falls_back_to_anonymous_handle_when_username_unset():
    poster = _FakePoster(tweet_id="7")
    client = XClient(
        api_key="k", api_secret="s", access_token="t", access_token_secret="ts",
        tweet_poster=poster, media_uploader=_FakeUploader(),
    )

    result = client.post_reply(text="hi", in_reply_to_tweet_id="1")
    # tweepy convention: x.com/i/status/<id> works without a handle
    assert result.tweet_url == "https://x.com/i/status/7"
