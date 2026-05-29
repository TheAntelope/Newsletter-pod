from __future__ import annotations

import pytest

from newsletter_pod.broadcast.prompting import BroadcastBrief, build_broadcast_prompt


def test_prompt_includes_topic_and_runtime():
    prompt = build_broadcast_prompt(
        BroadcastBrief(topic="OpenAI's new pricing tier", desired_minutes=5)
    )
    assert "OpenAI's new pricing tier" in prompt
    assert "roughly 5 minutes" in prompt
    assert "BROADCAST EPISODE" in prompt


def test_audience_hint_block_renders_when_set():
    prompt = build_broadcast_prompt(
        BroadcastBrief(
            topic="GPU shortage",
            audience_hint="founders building inference infra on consumer hardware",
        )
    )
    assert "Audience hint:" in prompt
    assert "founders building inference infra on consumer hardware" in prompt


def test_audience_hint_block_absent_when_unset():
    prompt = build_broadcast_prompt(BroadcastBrief(topic="GPU shortage"))
    assert "Audience hint:" not in prompt


def test_prior_feedback_block_renders_when_set():
    prompt = build_broadcast_prompt(
        BroadcastBrief(
            topic="agent frameworks",
            prior_feedback_summary="Yesterday's listeners asked for more on tool use.",
        )
    )
    assert "Signal from yesterday's audience" in prompt
    assert "more on tool use" in prompt


def test_empty_topic_rejected():
    with pytest.raises(ValueError):
        build_broadcast_prompt(BroadcastBrief(topic="   "))


def test_structure_guidance_always_present():
    # The guidance block is what shapes the script into X-postable form; if it
    # falls off, the output silently regresses to digest-shaped narration.
    prompt = build_broadcast_prompt(BroadcastBrief(topic="anything"))
    assert "Open with the hook" in prompt
    assert "single forward-looking question" in prompt
