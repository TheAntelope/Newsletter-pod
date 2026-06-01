from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pytest
import tweepy

from datetime import datetime, timezone

from newsletter_pod.broadcast.x_client import (
    TWEET_TEXT_MAX_CHARS,
    ReplyItem,
    XClient,
    XClientUnavailable,
    XPostFailed,
    XReadFailed,
)


@dataclass
class _FakeMedia:
    media_id_string: str


class _FakeUploader:
    def __init__(self, media_id: str = "media-123", raise_on_upload: bool = False) -> None:
        self.media_id = media_id
        self.raise_on_upload = raise_on_upload
        self.calls: list[dict] = []

    def chunked_upload(self, filename: str, *, media_category: str, max_wait_seconds: int):
        self.calls.append(
            {
                "filename": filename,
                "media_category": media_category,
                "max_wait_seconds": max_wait_seconds,
            }
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


def _client(
    uploader=None,
    poster=None,
    searcher=None,
    configured: bool = True,
    username: Optional[str] = "theclawcast",
) -> XClient:
    if configured:
        creds = {"api_key": "k", "api_secret": "s", "access_token": "t", "access_token_secret": "ts"}
    else:
        creds = {"api_key": None, "api_secret": None, "access_token": None, "access_token_secret": None}
    return XClient(
        username=username,
        media_uploader=uploader,
        tweet_poster=poster,
        tweet_searcher=searcher,
        **creds,
    )


@dataclass
class _FakeUser:
    id: str
    username: str


@dataclass
class _FakeTweet:
    id: str
    text: str
    author_id: str
    created_at: Optional[datetime] = None


@dataclass
class _FakeSearchResponse:
    data: list
    includes: dict


class _FakeSearcher:
    def __init__(
        self,
        *,
        data: Optional[list] = None,
        users: Optional[list] = None,
        raise_on_search: bool = False,
    ) -> None:
        self.data = data or []
        self.users = users or []
        self.raise_on_search = raise_on_search
        self.calls: list[dict] = []

    def search_recent_tweets(
        self,
        query: str,
        *,
        max_results: int,
        tweet_fields: list,
        expansions: list,
        user_fields: list,
        user_auth: bool,
    ):
        self.calls.append(
            {
                "query": query,
                "max_results": max_results,
                "tweet_fields": tweet_fields,
                "expansions": expansions,
                "user_fields": user_fields,
                "user_auth": user_auth,
            }
        )
        if self.raise_on_search:
            raise tweepy.TweepyException("search boom")
        return _FakeSearchResponse(data=self.data, includes={"users": self.users})


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
    assert uploader.calls[0]["max_wait_seconds"] > 0
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


def test_fetch_conversation_replies_requires_full_credentials():
    client = _client(configured=False, searcher=_FakeSearcher())
    with pytest.raises(XClientUnavailable):
        client.fetch_conversation_replies(conversation_id="12345")


def test_fetch_conversation_replies_rejects_empty_conversation_id():
    client = _client(searcher=_FakeSearcher())
    with pytest.raises(ValueError):
        client.fetch_conversation_replies(conversation_id=" ")


def test_fetch_conversation_replies_excludes_our_own_handle_when_configured():
    # When username is set, the query must filter our own posts out so the
    # auto-posted feedback-prompt reply doesn't pollute audience signal.
    searcher = _FakeSearcher()
    client = _client(searcher=searcher, username="theclawcast_")

    client.fetch_conversation_replies(conversation_id="42")

    assert searcher.calls[-1]["query"] == "conversation_id:42 -from:theclawcast_"
    assert searcher.calls[-1]["user_auth"] is True


def test_fetch_conversation_replies_omits_from_filter_when_username_unset():
    searcher = _FakeSearcher()
    client = _client(searcher=searcher, username=None)

    client.fetch_conversation_replies(conversation_id="42")

    assert searcher.calls[-1]["query"] == "conversation_id:42"


def test_fetch_conversation_replies_caps_max_results():
    # X requires 10..100; we floor/ceil so a caller passing 5 or 250
    # doesn't hit a TweepyException on validation.
    searcher = _FakeSearcher()
    client = _client(searcher=searcher)

    client.fetch_conversation_replies(conversation_id="42", max_results=5)
    assert searcher.calls[-1]["max_results"] == 10

    client.fetch_conversation_replies(conversation_id="42", max_results=250)
    assert searcher.calls[-1]["max_results"] == 100


def test_fetch_conversation_replies_returns_chronological_replyitems():
    # Recent-search returns newest first; we reverse to chronological so
    # the summarizer reads the conversation as it actually happened.
    t1 = datetime(2026, 6, 1, 13, 45, tzinfo=timezone.utc)
    t2 = datetime(2026, 6, 1, 19, 32, tzinfo=timezone.utc)
    t3 = datetime(2026, 6, 1, 19, 33, tzinfo=timezone.utc)
    searcher = _FakeSearcher(
        data=[
            _FakeTweet(id="3", text="@theclawcast_ Opus 4.8", author_id="u1", created_at=t3),
            _FakeTweet(id="2", text="@theclawcast_ Claude and Opus 4.8", author_id="u1", created_at=t2),
            _FakeTweet(id="1", text="@theclawcast_ Salami betting link", author_id="u2", created_at=t1),
        ],
        users=[
            _FakeUser(id="u1", username="VincentMar97260"),
            _FakeUser(id="u2", username="Salamipace"),
        ],
    )
    client = _client(searcher=searcher)

    replies = client.fetch_conversation_replies(conversation_id="42")

    assert [r.tweet_id for r in replies] == ["1", "2", "3"]
    assert [r.author_username for r in replies] == ["Salamipace", "VincentMar97260", "VincentMar97260"]
    assert replies[-1].text.endswith("Opus 4.8")
    assert replies[-1].created_at == t3
    assert all(isinstance(r, ReplyItem) for r in replies)


def test_fetch_conversation_replies_drops_empty_text_rows():
    searcher = _FakeSearcher(
        data=[
            _FakeTweet(id="1", text="", author_id="u1"),
            _FakeTweet(id="2", text="something real", author_id="u1"),
        ],
        users=[_FakeUser(id="u1", username="someone")],
    )
    client = _client(searcher=searcher)

    replies = client.fetch_conversation_replies(conversation_id="42")

    assert [r.tweet_id for r in replies] == ["2"]


def test_fetch_conversation_replies_falls_back_to_author_id_when_user_not_in_includes():
    searcher = _FakeSearcher(
        data=[_FakeTweet(id="1", text="hi", author_id="u-unknown")],
        users=[],  # includes.users missing — happens when X omits the expansion
    )
    client = _client(searcher=searcher)

    replies = client.fetch_conversation_replies(conversation_id="42")

    assert replies[0].author_username == "u-unknown"


def test_fetch_conversation_replies_wraps_tweepy_error_as_xreadfailed():
    searcher = _FakeSearcher(raise_on_search=True)
    client = _client(searcher=searcher)

    with pytest.raises(XReadFailed) as excinfo:
        client.fetch_conversation_replies(conversation_id="42")
    assert "search" in str(excinfo.value).lower()


def test_fetch_conversation_replies_handles_dict_shapes():
    # Real tweepy returns objects with attributes; tests sometimes pass
    # plain dicts. Both shapes should parse — same belt-and-suspenders
    # pattern _extract_tweet_id uses on the write path.
    response = _FakeSearchResponse(
        data=[{"id": "9", "text": "yo", "author_id": "u1"}],
        includes={"users": [{"id": "u1", "username": "alice"}]},
    )

    class _DictReturningSearcher:
        def search_recent_tweets(self, query, *, max_results, tweet_fields,
                                 expansions, user_fields, user_auth):
            return response

    client = _client(searcher=_DictReturningSearcher())
    replies = client.fetch_conversation_replies(conversation_id="42")

    assert replies == [ReplyItem(tweet_id="9", author_username="alice", text="yo", created_at=None)]
