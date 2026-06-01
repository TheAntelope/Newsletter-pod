from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

# Standard show framing spoken around every broadcast (X) episode. Edit the
# spoken copy here — these are the single source of truth for the wrap, so the
# greeting/intro/feedback/outro never get inlined at the call site.
GREETING = "Hello, Clawcast listeners!"
INTRO = (
    "Welcome to The Claw Cast — your daily briefing, made from the writers "
    "and newsletters you actually follow, read to you by AI voices in about "
    "five minutes."
)
# Spoken App-Store CTA. Slots between the intro and the topic body so the
# pitch lands before listeners get absorbed in the deep dive. Mirrors the
# tweet CTA in runner._default_tweet_text — a listener landing in the
# audio gets the same message as one landing in the X feed.
APP_CTA = (
    "If you want your very own podcast made just for you — covering the "
    "writers, newsletters, and topics you actually follow — download "
    "Claw Cast on the App Store."
)
FEEDBACK = (
    "Enjoying the show? We'd love to hear from you — leave a comment to tell "
    "us what you think and what you'd like us to cover next."
)
OUTRO = "That's all for today. Thanks for listening — see you tomorrow."


@dataclass(frozen=True)
class EpisodeFraming:
    """Spoken framing wrapped around the generated episode body.

    `lead` plays before the body (greeting, then intro+topic) and `tail`
    plays after it (feedback, then outro). Each entry is its own spoken
    section so there is a natural pause between them.
    """

    lead: list[str]
    tail: list[str]


def build_framing(*, topic: str, feedback_text: Optional[str] = None) -> EpisodeFraming:
    """Assemble the standard show framing for one episode.

    `topic` is announced in the intro (the same value stored as
    `topic_used`). `feedback_text` lets the spoken feedback line stay in
    sync with the feedback tweet copy: when the loop carries an explicit
    feedback prompt we speak that verbatim, otherwise we fall back to the
    standard FEEDBACK line so every episode still invites a comment.
    """
    topic_clean = topic.strip()
    intro = f"{INTRO} Today's topic: {topic_clean}." if topic_clean else INTRO

    feedback_line = FEEDBACK
    if feedback_text and feedback_text.strip():
        feedback_line = feedback_text.strip()

    return EpisodeFraming(
        lead=[GREETING, intro, APP_CTA],
        tail=[feedback_line, OUTRO],
    )
