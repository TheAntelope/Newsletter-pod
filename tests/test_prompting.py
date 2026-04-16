from __future__ import annotations

from datetime import datetime, timezone

from newsletter_pod.models import PodcastUxConfig, SourceItem
from newsletter_pod.prompting import build_digest_prompt


def test_prompt_enforces_calm_daily_briefing_with_named_hosts():
    items = [
        SourceItem(
            source_id="a",
            source_name="Source A",
            guid="1",
            link="https://example.com/a",
            title="Title A",
            summary="Summary A",
            published_at=datetime(2026, 3, 9, 5, 0, tzinfo=timezone.utc),
            dedupe_key="1",
        ),
        SourceItem(
            source_id="b",
            source_name="Source B",
            guid="2",
            link="https://example.com/b",
            title="Title B",
            summary="Summary B",
            published_at=datetime(2026, 3, 9, 5, 5, tzinfo=timezone.utc),
            dedupe_key="2",
        ),
        SourceItem(
            source_id="c",
            source_name="Source C",
            guid="3",
            link="https://example.com/c",
            title="Title C",
            summary="Summary C",
            published_at=datetime(2026, 3, 9, 5, 10, tzinfo=timezone.utc),
            dedupe_key="3",
        ),
    ]

    prompt = build_digest_prompt(
        items,
        run_date=datetime(2026, 3, 9, 5, 0, tzinfo=timezone.utc).date(),
        ux=PodcastUxConfig(),
    )

    assert "Episode date: 2026-03-09" in prompt
    assert "Primary host: Elena" in prompt
    assert "Secondary host: Marcus" in prompt
    assert "Open as a dated daily edition." in prompt
    assert "top 3 takeaways" in prompt
    assert "spoken attribution light and natural" in prompt
    assert "Select the most useful themes" in prompt
    assert "occasional interjections" in prompt
    assert "Source: Source A" in prompt
    assert "Source: Source B" in prompt
    assert "Source: Source C" in prompt


def test_prompt_switches_to_thin_day_runtime_guidance():
    items = [
        SourceItem(
            source_id="a",
            source_name="Source A",
            guid="1",
            link="https://example.com/a",
            title="Title A",
            summary="Summary A",
            published_at=datetime(2026, 3, 9, 5, 0, tzinfo=timezone.utc),
            dedupe_key="1",
        )
    ]

    prompt = build_digest_prompt(
        items,
        run_date=datetime(2026, 3, 9, 5, 0, tzinfo=timezone.utc).date(),
        ux=PodcastUxConfig(),
    )

    assert "2-4 minutes" in prompt
    assert "thin-news day" in prompt
