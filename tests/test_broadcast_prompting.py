from __future__ import annotations

from datetime import datetime, timezone

import pytest

from newsletter_pod.broadcast.prompting import BroadcastBrief, build_broadcast_prompt
from newsletter_pod.models import SourceItem


def _item(*, source_id="src-a", source_name="Source A", title="A", summary="A summary", published_at=None, dedupe_key=None):
    return SourceItem(
        source_id=source_id,
        source_name=source_name,
        guid=dedupe_key or title,
        link=f"https://example.com/{title}",
        title=title,
        summary=summary,
        published_at=published_at or datetime(2026, 5, 30, tzinfo=timezone.utc),
        dedupe_key=dedupe_key or title,
    )


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


def test_source_items_block_renders_with_grounding_instruction():
    prompt = build_broadcast_prompt(
        BroadcastBrief(
            topic="agent frameworks",
            source_items=[
                _item(
                    source_id="src-stratechery",
                    source_name="Stratechery",
                    title="Aggregation and the AI agent",
                    summary="Ben argues the agent layer becomes the new aggregator.",
                ),
            ],
        )
    )
    assert "Recent source items" in prompt
    assert "Stratechery" in prompt
    assert "Aggregation and the AI agent" in prompt
    assert "Ground every concrete claim in one of the source items" in prompt


def test_source_items_block_absent_without_items():
    prompt = build_broadcast_prompt(BroadcastBrief(topic="anything"))
    assert "Recent source items" not in prompt
    assert "Ground every concrete claim" not in prompt


def test_source_items_caps_per_source_in_brief():
    items = [
        _item(
            source_id="src-a",
            source_name="Source A",
            title=f"Item {i}",
            published_at=datetime(2026, 5, 30 - i, tzinfo=timezone.utc),
            dedupe_key=f"item-{i}",
        )
        for i in range(10)
    ]
    prompt = build_broadcast_prompt(BroadcastBrief(topic="x", source_items=items))
    assert "Item 0" in prompt
    assert "Item 3" in prompt
    assert "Item 4" not in prompt
    assert "Item 9" not in prompt


def test_source_items_total_ceiling():
    items = []
    for s in range(5):
        for i in range(5):
            items.append(
                _item(
                    source_id=f"src-{s}",
                    source_name=f"Source {s}",
                    title=f"S{s}-I{i}",
                    published_at=datetime(2026, 5, 30 - i, tzinfo=timezone.utc),
                    dedupe_key=f"s{s}-i{i}",
                )
            )
    prompt = build_broadcast_prompt(BroadcastBrief(topic="x", source_items=items))
    rendered_bullets = sum(1 for line in prompt.splitlines() if line.startswith("- ["))
    assert rendered_bullets <= 18


def test_structure_guidance_always_present():
    # The guidance block is what shapes the script into X-postable form; if it
    # falls off, the output silently regresses to digest-shaped narration.
    prompt = build_broadcast_prompt(BroadcastBrief(topic="anything"))
    assert "Open with the hook" in prompt
    assert "single forward-looking question" in prompt
