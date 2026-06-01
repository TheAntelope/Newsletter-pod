from __future__ import annotations

from newsletter_pod.broadcast.framing import (
    APP_CTA,
    FEEDBACK,
    GREETING,
    OUTRO,
    build_framing,
)


def test_build_framing_default_feedback_and_topic_announcement():
    framing = build_framing(topic="The state of agent evals")

    assert framing.lead[0] == GREETING
    intro = framing.lead[1]
    assert "Welcome to The Claw Cast" in intro
    assert intro.endswith("Today's topic: The state of agent evals.")
    # App-Store CTA spoken right after the intro, before the body kicks
    # in — keeps the install pitch from getting buried at the end.
    assert framing.lead[2] == APP_CTA
    assert framing.tail == [FEEDBACK, OUTRO]


def test_app_cta_mentions_personalization_and_app_store():
    # Specific phrases the tweet copy and the show copy both lean on;
    # keeping them asserted here protects against silent rewording that
    # would break the audio/tweet alignment.
    assert "made just for you" in APP_CTA
    assert "App Store" in APP_CTA
    # The brand is "The Claw Cast" — the "The" matters and we want it
    # spoken naturally rather than dropping to just "Claw Cast".
    assert "The Claw Cast" in APP_CTA


def test_build_framing_prefers_loop_feedback_text():
    framing = build_framing(
        topic="x",
        feedback_text="Drop your hot take below.",
    )

    assert framing.tail == ["Drop your hot take below.", OUTRO]


def test_build_framing_blank_feedback_falls_back_to_default():
    framing = build_framing(topic="x", feedback_text="   ")

    assert framing.tail == [FEEDBACK, OUTRO]


def test_build_framing_blank_topic_omits_announcement():
    framing = build_framing(topic="   ")

    assert "Today's topic" not in framing.lead[1]
    # APP_CTA still plays even when the topic is blank — the install
    # pitch is not coupled to the topic announcement.
    assert framing.lead[2] == APP_CTA
