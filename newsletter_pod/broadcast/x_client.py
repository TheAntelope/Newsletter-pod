from __future__ import annotations

import logging
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional, Protocol

import tweepy

logger = logging.getLogger(__name__)


# X's standard tweet video category supports up to 140 seconds and 512MB
# on consumer accounts; Premium accounts get hours. We don't enforce these
# client-side — let X reject so the error surfaces naturally.
TWEET_TEXT_MAX_CHARS = 280

# Cap per-request HTTP timeout on the v1.1 media-upload session. Without
# this, tweepy.API defaults to no timeout and a network hiccup will hang
# Cloud Run for the full 600s request timeout.
TWEEPY_HTTP_TIMEOUT_SECONDS = 60

# Cap the chunked-upload FINALIZE polling loop. X transcodes the video
# server-side after FINALIZE and tweepy polls STATUS until it succeeds
# or the cap is hit. Default tweepy cap is 900s (15 min) which exceeds
# Cloud Run's request timeout, so we set our own ceiling.
TWEEPY_FINALIZE_MAX_WAIT_SECONDS = 180


class XClientUnavailable(RuntimeError):
    """Raised when the X client is constructed but one or more credentials
    are missing. Surfaced as a 503 by the endpoint so an operator sees
    "configure the four X_* env vars" rather than a generic 500."""


class XPostFailed(RuntimeError):
    """Raised when tweepy returns an error from the X API. The original
    tweepy exception is chained via __cause__."""


class XReadFailed(RuntimeError):
    """Raised when a read endpoint (conversation_id search etc.) errors.
    Kept separate from XPostFailed so the caller can distinguish a write
    failure (the daily run can't post) from a read failure (we couldn't
    pull replies — fall back to manual paste)."""


@dataclass(frozen=True)
class XPostResult:
    tweet_id: str
    tweet_url: str
    media_id: Optional[str] = None


# Max replies pulled in a single conversation_id search. X recent-search
# returns up to 100 per page; we'd need pagination beyond that. A single
# broadcast post realistically attracts ~dozens — 100 is a comfortable
# ceiling without paging logic.
_REPLY_PAGE_LIMIT = 100


@dataclass(frozen=True)
class ReplyItem:
    tweet_id: str
    author_username: str
    text: str
    created_at: Optional[datetime] = None


class _MediaUploader(Protocol):
    def chunked_upload(
        self, filename: str, *, media_category: str, max_wait_seconds: int
    ) -> object: ...


class _TweetPoster(Protocol):
    def create_tweet(
        self,
        *,
        text: str,
        media_ids: Optional[list[str]] = None,
        in_reply_to_tweet_id: Optional[str] = None,
    ) -> object: ...


class _TweetSearcher(Protocol):
    def search_recent_tweets(
        self,
        query: str,
        *,
        max_results: int,
        tweet_fields: list[str],
        expansions: list[str],
        user_fields: list[str],
        user_auth: bool,
    ) -> object: ...


class XClient:
    """Thin wrapper around tweepy that exposes only what the broadcast
    loop needs. Constructed lazily — pass `None` for any credential to
    get a client that raises XClientUnavailable on use, so wiring code
    doesn't have to branch on "do we have keys?"
    """

    def __init__(
        self,
        *,
        api_key: Optional[str],
        api_secret: Optional[str],
        access_token: Optional[str],
        access_token_secret: Optional[str],
        username: Optional[str] = None,
        # Injection seams for tests; default to real tweepy on prod.
        media_uploader: Optional[_MediaUploader] = None,
        tweet_poster: Optional[_TweetPoster] = None,
        tweet_searcher: Optional[_TweetSearcher] = None,
    ) -> None:
        self._api_key = api_key
        self._api_secret = api_secret
        self._access_token = access_token
        self._access_token_secret = access_token_secret
        self._username = (username or "").strip().lstrip("@") or None
        self._media_uploader_override = media_uploader
        self._tweet_poster_override = tweet_poster
        self._tweet_searcher_override = tweet_searcher
        self._media_uploader_cached: Optional[_MediaUploader] = None
        self._tweet_poster_cached: Optional[_TweetPoster] = None
        self._tweet_searcher_cached: Optional[_TweetSearcher] = None

    @property
    def is_configured(self) -> bool:
        return all(
            (self._api_key, self._api_secret, self._access_token, self._access_token_secret)
        )

    def _media_uploader(self) -> _MediaUploader:
        if self._media_uploader_override is not None:
            return self._media_uploader_override
        if self._media_uploader_cached is None:
            self._require_configured()
            auth = tweepy.OAuth1UserHandler(
                self._api_key,
                self._api_secret,
                self._access_token,
                self._access_token_secret,
            )
            self._media_uploader_cached = tweepy.API(auth, timeout=TWEEPY_HTTP_TIMEOUT_SECONDS)
        return self._media_uploader_cached

    def _tweet_poster(self) -> _TweetPoster:
        if self._tweet_poster_override is not None:
            return self._tweet_poster_override
        if self._tweet_poster_cached is None:
            self._require_configured()
            self._tweet_poster_cached = tweepy.Client(
                consumer_key=self._api_key,
                consumer_secret=self._api_secret,
                access_token=self._access_token,
                access_token_secret=self._access_token_secret,
            )
        return self._tweet_poster_cached

    def _tweet_searcher(self) -> _TweetSearcher:
        # Same underlying tweepy.Client as the poster in prod — the v2
        # endpoint set covers both. Kept as a separate injection seam so
        # tests can fake reads without faking writes (and vice versa).
        if self._tweet_searcher_override is not None:
            return self._tweet_searcher_override
        if self._tweet_searcher_cached is None:
            self._tweet_searcher_cached = self._tweet_poster()  # type: ignore[assignment]
        return self._tweet_searcher_cached

    def _require_configured(self) -> None:
        if not self.is_configured:
            raise XClientUnavailable(
                "X credentials are not fully configured. All four of "
                "X_API_KEY, X_API_SECRET, X_ACCESS_TOKEN, X_ACCESS_TOKEN_SECRET "
                "must be set."
            )

    def post_video_tweet(
        self,
        *,
        video_bytes: bytes,
        text: str,
        in_reply_to_tweet_id: Optional[str] = None,
    ) -> XPostResult:
        """Upload an MP4 to X and post it as a tweet. Text is truncated to
        X's hard 280-char limit; callers should shape text upstream rather
        than rely on truncation.

        Tweepy's chunked v1.1 media upload writes to a temp file because
        the underlying multipart APIs are file-path oriented; we clean
        up immediately after the upload returns the media_id.
        """
        self._require_configured()
        text = (text or "").strip()
        if len(text) > TWEET_TEXT_MAX_CHARS:
            text = text[: TWEET_TEXT_MAX_CHARS - 1].rstrip() + "…"

        with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as fp:
            tmp_path = Path(fp.name)
            fp.write(video_bytes)
        logger.info(
            "X media upload starting: bytes=%d path=%s", len(video_bytes), tmp_path
        )
        try:
            try:
                media = self._media_uploader().chunked_upload(
                    filename=str(tmp_path),
                    media_category="tweet_video",
                    max_wait_seconds=TWEEPY_FINALIZE_MAX_WAIT_SECONDS,
                )
            except tweepy.TweepyException as exc:
                raise XPostFailed(f"X media upload failed: {exc}") from exc
        finally:
            try:
                tmp_path.unlink()
            except OSError:
                logger.warning("Failed to delete temp file %s", tmp_path, exc_info=True)

        media_id = str(getattr(media, "media_id_string", None) or getattr(media, "media_id"))
        logger.info("X media upload finished: media_id=%s", media_id)

        logger.info("X create_tweet starting: media_id=%s text_len=%d", media_id, len(text))
        try:
            response = self._tweet_poster().create_tweet(
                text=text,
                media_ids=[media_id],
                in_reply_to_tweet_id=in_reply_to_tweet_id,
            )
        except tweepy.TweepyException as exc:
            raise XPostFailed(f"X tweet create failed: {exc}") from exc

        tweet_id = self._extract_tweet_id(response)
        logger.info("X create_tweet finished: tweet_id=%s", tweet_id)
        return XPostResult(
            tweet_id=tweet_id,
            tweet_url=self._tweet_url(tweet_id),
            media_id=media_id,
        )

    def post_reply(
        self,
        *,
        text: str,
        in_reply_to_tweet_id: str,
    ) -> XPostResult:
        """Post a text-only reply to an existing tweet. Used by the
        broadcast loop to attach the "what should we cover tomorrow?"
        prompt as a reply to the freshly-posted episode tweet."""
        self._require_configured()
        text = (text or "").strip()
        if len(text) > TWEET_TEXT_MAX_CHARS:
            text = text[: TWEET_TEXT_MAX_CHARS - 1].rstrip() + "…"

        try:
            response = self._tweet_poster().create_tweet(
                text=text,
                in_reply_to_tweet_id=in_reply_to_tweet_id,
            )
        except tweepy.TweepyException as exc:
            raise XPostFailed(f"X reply create failed: {exc}") from exc

        tweet_id = self._extract_tweet_id(response)
        return XPostResult(tweet_id=tweet_id, tweet_url=self._tweet_url(tweet_id))

    def fetch_conversation_replies(
        self,
        *,
        conversation_id: str,
        max_results: int = _REPLY_PAGE_LIMIT,
    ) -> list[ReplyItem]:
        """Pull replies to the tweet rooted at conversation_id (typically
        the broadcast episode tweet itself). Excludes posts by our own
        handle when configured, so the auto-posted feedback-prompt reply
        doesn't show up as audience signal.

        Returns oldest-first to match the order a human would read the
        thread; that ordering is also what the summarizer prompt expects.
        Raises XReadFailed on transport / API errors so the caller can
        distinguish "couldn't read" from "no replies yet"."""
        self._require_configured()
        if not conversation_id or not conversation_id.strip():
            raise ValueError("conversation_id is required")
        query = f"conversation_id:{conversation_id.strip()}"
        if self._username:
            query += f" -from:{self._username}"
        # X requires max_results between 10 and 100 on recent-search.
        capped = max(10, min(max_results, _REPLY_PAGE_LIMIT))
        logger.info(
            "X reply search starting: conversation_id=%s max_results=%d",
            conversation_id,
            capped,
        )
        try:
            response = self._tweet_searcher().search_recent_tweets(
                query,
                max_results=capped,
                tweet_fields=["author_id", "created_at"],
                expansions=["author_id"],
                user_fields=["username"],
                user_auth=True,
            )
        except tweepy.TweepyException as exc:
            raise XReadFailed(f"X reply search failed: {exc}") from exc

        data = getattr(response, "data", None) or []
        includes = getattr(response, "includes", None) or {}
        users_by_id = {
            str(getattr(u, "id", None) or (u.get("id") if isinstance(u, dict) else None)):
                (getattr(u, "username", None) or (u.get("username") if isinstance(u, dict) else None) or "")
            for u in includes.get("users", []) or []
        }

        replies: list[ReplyItem] = []
        for tweet in data:
            tweet_id = str(getattr(tweet, "id", None) or (tweet.get("id") if isinstance(tweet, dict) else "") or "")
            text = str(getattr(tweet, "text", None) or (tweet.get("text") if isinstance(tweet, dict) else "") or "")
            author_id = str(getattr(tweet, "author_id", None) or (tweet.get("author_id") if isinstance(tweet, dict) else "") or "")
            created_at = getattr(tweet, "created_at", None) or (tweet.get("created_at") if isinstance(tweet, dict) else None)
            author_username = users_by_id.get(author_id) or author_id
            if not tweet_id or not text:
                continue
            replies.append(
                ReplyItem(
                    tweet_id=tweet_id,
                    author_username=author_username,
                    text=text,
                    created_at=created_at if isinstance(created_at, datetime) else None,
                )
            )
        # X recent-search returns newest first; reverse for chronological
        # order so the summarizer sees the conversation as it happened.
        replies.reverse()
        logger.info(
            "X reply search finished: conversation_id=%s replies=%d",
            conversation_id,
            len(replies),
        )
        return replies

    def _tweet_url(self, tweet_id: str) -> str:
        handle = (self._username or "i").strip().lstrip("@") or "i"
        return f"https://x.com/{handle}/status/{tweet_id}"

    @staticmethod
    def _extract_tweet_id(response: object) -> str:
        # tweepy.Client.create_tweet returns a Response-like object whose
        # `.data` is a dict with `id`. Real tweepy uses a tweepy.client.Response
        # namedtuple; tests may pass a plain dict. Support both.
        data = getattr(response, "data", None)
        if data is None and isinstance(response, dict):
            data = response.get("data", response)
        if isinstance(data, dict):
            tweet_id = data.get("id")
        else:
            tweet_id = getattr(data, "id", None)
        if not tweet_id:
            raise XPostFailed("X response missing tweet id")
        return str(tweet_id)
