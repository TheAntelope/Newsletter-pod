from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from ..storage import AudioStorage
from .service import BROADCAST_PREFIX
from .x_client import XClient, XPostResult

logger = logging.getLogger(__name__)


# Default reply text posted as a thread under the episode tweet. Phasing
# this in via reply (rather than the main tweet) keeps the episode tweet
# clean for retweeting while still soliciting feedback.
DEFAULT_FEEDBACK_PROMPT = (
    "What should we cover tomorrow? Reply below — the most-loved suggestion "
    "becomes tomorrow's episode."
)


@dataclass(frozen=True)
class PublishResult:
    episode_tweet_id: str
    episode_tweet_url: str
    feedback_prompt_tweet_id: Optional[str]
    feedback_prompt_tweet_url: Optional[str]


class BroadcastPublisher:
    """Reads a generated broadcast episode's MP4 from storage and posts it
    to X, optionally followed by a feedback-prompt reply.

    Stateless and free of generation concerns — this exists so the
    publish step can be invoked independently of generation (re-post a
    previously generated episode) and so generate_and_publish in the
    endpoint stays a simple two-line orchestration.
    """

    def __init__(
        self,
        *,
        storage: AudioStorage,
        x_client: XClient,
    ) -> None:
        self._storage = storage
        self._x_client = x_client

    def publish(
        self,
        *,
        episode_id: str,
        tweet_text: str,
        feedback_prompt_text: Optional[str] = DEFAULT_FEEDBACK_PROMPT,
    ) -> PublishResult:
        video_object_name = f"{BROADCAST_PREFIX}/{episode_id}.mp4"
        video_bytes = self._storage.get_object(video_object_name)

        episode_post: XPostResult = self._x_client.post_video_tweet(
            video_bytes=video_bytes,
            text=tweet_text,
        )

        feedback_id: Optional[str] = None
        feedback_url: Optional[str] = None
        if feedback_prompt_text:
            try:
                feedback_post = self._x_client.post_reply(
                    text=feedback_prompt_text,
                    in_reply_to_tweet_id=episode_post.tweet_id,
                )
                feedback_id = feedback_post.tweet_id
                feedback_url = feedback_post.tweet_url
            except Exception:
                # The episode tweet already went out; a failed reply is a
                # follow-up problem, not a publish failure. Log and return
                # success so the operator doesn't think the post failed.
                logger.warning(
                    "Episode tweet %s posted but feedback reply failed",
                    episode_post.tweet_id,
                    exc_info=True,
                )

        return PublishResult(
            episode_tweet_id=episode_post.tweet_id,
            episode_tweet_url=episode_post.tweet_url,
            feedback_prompt_tweet_id=feedback_id,
            feedback_prompt_tweet_url=feedback_url,
        )
