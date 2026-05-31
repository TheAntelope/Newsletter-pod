from __future__ import annotations

from newsletter_pod.broadcast.framing import (
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
    assert framing.tail == [FEEDBACK, OUTRO]


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
