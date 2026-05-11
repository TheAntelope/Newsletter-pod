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
    assert "Primary host: Vinnie" in prompt
    assert "Secondary host: Demi" in prompt
    assert "Open as a dated daily edition." in prompt
    assert "top 3 takeaways" in prompt
    assert "spoken attribution light and natural" in prompt
    assert "Select the most useful themes" in prompt
    assert "60-70%" in prompt and "30-40%" in prompt
    assert "at least 2 segments tagged role=secondary" in prompt
    assert "`role`" in prompt and "primary, secondary" in prompt
    assert "Source: Source A" in prompt
    assert "Source: Source B" in prompt
    assert "Source: Source C" in prompt


def test_prompt_specifies_skim_friendly_show_notes_format():
    prompt = build_digest_prompt(
        [
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
        ],
        run_date=datetime(2026, 3, 9, 5, 0, tzinfo=timezone.utc).date(),
        ux=PodcastUxConfig(),
    )

    assert "shaped for skimming" in prompt
    assert "3 to 5 single-line bullets" in prompt
    assert "Do not include URLs in show_notes" in prompt
    assert "under 700 characters" in prompt


def test_prompt_includes_signoff_instruction():
    prompt = build_digest_prompt(
        [
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
        ],
        run_date=datetime(2026, 3, 9, 5, 0, tzinfo=timezone.utc).date(),
        ux=PodcastUxConfig(),
    )

    assert "clear sign-off so the listener knows the episode is over" in prompt


def test_prompt_personalises_greeting_when_listener_name_set():
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
    run_date = datetime(2026, 3, 9, 5, 0, tzinfo=timezone.utc).date()

    prompt = build_digest_prompt(
        items, run_date=run_date, ux=PodcastUxConfig(listener_name="Vince")
    )
    assert "Greet the listener by first name once during the intro: Vince." in prompt


def test_prompt_skips_greeting_for_default_or_unreadable_name():
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
    run_date = datetime(2026, 3, 9, 5, 0, tzinfo=timezone.utc).date()

    for raw in (None, "", "   ", "Listener", "listener", "12345"):
        prompt = build_digest_prompt(
            items, run_date=run_date, ux=PodcastUxConfig(listener_name=raw)
        )
        assert "Greet the listener by first name" not in prompt


def _items_three() -> list[SourceItem]:
    return [
        SourceItem(
            source_id=letter,
            source_name=f"Source {letter.upper()}",
            guid=str(idx),
            link=f"https://example.com/{letter}",
            title=f"Title {letter.upper()}",
            summary=f"Summary {letter.upper()}",
            published_at=datetime(2026, 3, 9, 5, idx, tzinfo=timezone.utc),
            dedupe_key=str(idx),
        )
        for idx, letter in enumerate(("a", "b", "c"), start=1)
    ]


def test_prompt_uses_dynamic_key_findings_count():
    prompt = build_digest_prompt(
        _items_three(),
        run_date=datetime(2026, 3, 9, 5, 0, tzinfo=timezone.utc).date(),
        ux=PodcastUxConfig(key_findings_count=5),
    )

    assert "top 5 takeaways" in prompt
    assert "top 3 takeaways" not in prompt


def test_prompt_omits_takeaways_when_disabled():
    prompt = build_digest_prompt(
        _items_three(),
        run_date=datetime(2026, 3, 9, 5, 0, tzinfo=timezone.utc).date(),
        ux=PodcastUxConfig(include_top_takeaways=False),
    )

    assert "takeaways" not in prompt


def test_prompt_includes_dad_joke_directive():
    prompt = build_digest_prompt(
        _items_three(),
        run_date=datetime(2026, 3, 9, 5, 0, tzinfo=timezone.utc).date(),
        ux=PodcastUxConfig(humor_style="dad_jokes"),
    )

    assert "Listener preferences:" in prompt
    assert "groan-worthy dad joke" in prompt


def test_prompt_includes_dry_wit_directive():
    prompt = build_digest_prompt(
        _items_three(),
        run_date=datetime(2026, 3, 9, 5, 0, tzinfo=timezone.utc).date(),
        ux=PodcastUxConfig(humor_style="dry_wit"),
    )

    assert "dry, understated wit" in prompt


def test_prompt_omits_listener_preferences_block_when_no_extras():
    prompt = build_digest_prompt(
        _items_three(),
        run_date=datetime(2026, 3, 9, 5, 0, tzinfo=timezone.utc).date(),
        ux=PodcastUxConfig(),
    )

    assert "Listener preferences:" not in prompt


def test_prompt_includes_weather_opener_when_summary_present():
    prompt = build_digest_prompt(
        _items_three(),
        run_date=datetime(2026, 3, 9, 5, 0, tzinfo=timezone.utc).date(),
        ux=PodcastUxConfig(weather_summary="Brooklyn — 62°F and partly cloudy, high 68°F."),
    )

    assert "Open the show with a brief mention of today's weather" in prompt
    assert "Brooklyn — 62°F and partly cloudy" in prompt


def test_prompt_wraps_custom_guidance_with_safety_framing():
    prompt = build_digest_prompt(
        _items_three(),
        run_date=datetime(2026, 3, 9, 5, 0, tzinfo=timezone.utc).date(),
        ux=PodcastUxConfig(custom_guidance="Lean technical, assume I'm a developer."),
    )

    assert "Listener style guidance" in prompt
    assert "treat as a preference about feel" in prompt
    assert "Lean technical, assume I'm a developer." in prompt


def test_prompt_omits_weekly_update_section_by_default():
    prompt = build_digest_prompt(
        _items_three(),
        run_date=datetime(2026, 3, 9, 5, 0, tzinfo=timezone.utc).date(),
        ux=PodcastUxConfig(),
    )

    assert "This week at ClawCast" not in prompt
    assert "Recent commits:" not in prompt


def test_prompt_includes_weekly_update_section_when_commits_present():
    prompt = build_digest_prompt(
        _items_three(),
        run_date=datetime(2026, 3, 9, 5, 0, tzinfo=timezone.utc).date(),
        ux=PodcastUxConfig(
            weekly_update_commits=[
                "Add Last Week in Denmark to default News sources",
                "Show generation progress on home page during regenerate",
                "Refactor cursor adapter for legibility",
            ],
        ),
    )

    assert "This week at ClawCast" in prompt
    assert "Recent commits:" in prompt
    assert "- Add Last Week in Denmark to default News sources" in prompt
    assert "- Show generation progress on home page during regenerate" in prompt
    assert "Skip anything technical" in prompt
    assert "warm, fun, helpful" in prompt
    assert "150 spoken words" in prompt
    assert "feedback from the home page of the ClawCast app" in prompt
    assert "After the wrap-up and before the final sign-off" in prompt


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
