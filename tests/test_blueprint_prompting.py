from __future__ import annotations

from datetime import date

from newsletter_pod.blueprint import SectionDef, ShowBlueprint, default_blueprint
from newsletter_pod.models import PodcastUxConfig, SourceItem
from newsletter_pod.podcast_api import PodcastApiClient
from newsletter_pod.prompting import build_closing_prompt, build_digest_prompt


def _items() -> list[SourceItem]:
    return [
        SourceItem(
            source_id="s1",
            source_name="Source A",
            link="https://example.com/a",
            title="A big story",
            summary="Something happened.",
            published_at=date(2026, 7, 1).isoformat(),
            dedupe_key="k1",
        )
    ]


def _ux(blueprint: ShowBlueprint | None, weather: str | None = None) -> PodcastUxConfig:
    return PodcastUxConfig(blueprint=blueprint, weather_summary=weather)


def test_legacy_prompt_has_no_segment_plan_when_blueprint_absent():
    prompt = build_digest_prompt(_items(), run_date=date(2026, 7, 1), ux=_ux(None))
    assert "Segment plan" not in prompt
    assert "Group related items into 2-4 top story blocks" in prompt


def test_blueprint_prompt_emits_ordered_segment_plan():
    bp = default_blueprint()
    prompt = build_digest_prompt(
        _items(),
        run_date=date(2026, 7, 1),
        ux=_ux(bp, weather="Oslo — 12°C and overcast."),
        skip_closing=True,
    )
    assert "Segment plan" in prompt
    assert "Do NOT add, drop, reorder, or merge sections" in prompt
    # cold_open appears before story_block in the plan text.
    assert prompt.index("section=cold_open") < prompt.index("section=story_block")
    # weather is voiced because the per-user summary is present.
    assert "section=weather" in prompt
    assert "12°C and overcast" in prompt
    # closing is owned by stage-2 on the live path -> not in the body plan.
    assert "section=closing" not in prompt


def test_weather_section_needs_both_section_and_user_gate():
    bp = default_blueprint()  # weather section enabled
    # No weather_summary (user gate off) -> weather omitted from the plan.
    prompt = build_digest_prompt(
        _items(), run_date=date(2026, 7, 1), ux=_ux(bp, weather=None), skip_closing=True
    )
    assert "section=weather" not in prompt


def test_blueprint_weather_section_does_not_duplicate_open_the_show_line():
    bp = default_blueprint()  # weather section enabled
    prompt = build_digest_prompt(
        _items(),
        run_date=date(2026, 7, 1),
        ux=_ux(bp, weather="Oslo — 12°C and overcast."),
        skip_closing=True,
    )
    # The dedicated weather section owns weather on the blueprint path...
    assert "section=weather" in prompt
    # ...so the legacy listener-preference open-the-show line must NOT also fire,
    # or the model reads weather twice.
    assert "Open the show with a brief mention of today's weather" not in prompt
    # And the summary itself is only injected once (by the weather section).
    assert prompt.count("12°C and overcast") == 1


def test_legacy_path_still_gets_open_the_show_weather_line():
    # No blueprint -> no weather section, so the open-the-show line is the only
    # thing that voices weather and must still be present.
    prompt = build_digest_prompt(
        _items(),
        run_date=date(2026, 7, 1),
        ux=_ux(None, weather="Oslo — 12°C and overcast."),
    )
    assert "Open the show with a brief mention of today's weather" in prompt
    assert prompt.count("12°C and overcast") == 1


def test_blueprint_with_weather_disabled_uses_open_the_show_line():
    bp = default_blueprint()
    for s in bp.sections:
        if s.kind == "weather":
            s.enabled = False
    prompt = build_digest_prompt(
        _items(),
        run_date=date(2026, 7, 1),
        ux=_ux(bp, weather="Oslo — 12°C and overcast."),
        skip_closing=True,
    )
    assert "section=weather" not in prompt
    # Weather is still wanted, so the fallback open-the-show line carries it once.
    assert "Open the show with a brief mention of today's weather" in prompt
    assert prompt.count("12°C and overcast") == 1


def test_announcements_only_when_text_present():
    bp = default_blueprint()
    for s in bp.sections:
        if s.kind == "announcements":
            s.enabled = True
    # enabled but empty text -> still omitted
    prompt = build_digest_prompt(
        _items(), run_date=date(2026, 7, 1), ux=_ux(bp), skip_closing=True
    )
    assert "section=announcements" not in prompt

    bp.closing.announcements_text = "Two new voices shipped this week."
    prompt2 = build_digest_prompt(
        _items(), run_date=date(2026, 7, 1), ux=_ux(bp), skip_closing=True
    )
    assert "section=announcements" in prompt2
    assert "Two new voices shipped this week." in prompt2


def test_custom_section_instructions_and_signoff_thread_through():
    bp = ShowBlueprint(
        sections=[
            SectionDef(kind="cold_open", instructions="Start with a provocative question."),
            SectionDef(kind="story_block", max_blocks=2),
            SectionDef(kind="closing"),
        ],
        closing={"signoff_override": "Stay curious — that's ClawCast."},
    )
    prompt = build_digest_prompt(
        _items(), run_date=date(2026, 7, 1), ux=_ux(bp), skip_closing=True
    )
    assert "Start with a provocative question." in prompt

    closing_prompt = build_closing_prompt("body transcript", _ux(bp))
    assert "Stay curious — that's ClawCast." in closing_prompt


def test_style_rules_present_even_without_blueprint():
    # The anti-slop base rules are always on, including the legacy no-blueprint
    # path — only the producer extension needs a blueprint.
    prompt = build_digest_prompt(_items(), run_date=date(2026, 7, 1), ux=_ux(None))
    assert "Voice and style rules" in prompt
    assert '"experts agree"' in prompt
    assert "Producer style guidance" not in prompt


def test_positive_guidance_threads_into_both_prompts():
    bp = default_blueprint()
    bp.style.positive_guidance = "  Keep sentences under 20 words.  "
    ux = _ux(bp)

    prompt = build_digest_prompt(
        _items(), run_date=date(2026, 7, 1), ux=ux, skip_closing=True
    )
    assert "Producer style guidance: Keep sentences under 20 words." in prompt

    closing = build_closing_prompt("body transcript", ux)
    assert "Producer style guidance: Keep sentences under 20 words." in closing
    assert "no fake-profound final" in closing


def test_blank_positive_guidance_adds_no_line():
    bp = default_blueprint()
    bp.style.positive_guidance = "   "
    prompt = build_digest_prompt(
        _items(), run_date=date(2026, 7, 1), ux=_ux(bp), skip_closing=True
    )
    assert "Producer style guidance" not in prompt


def _client() -> PodcastApiClient:
    return PodcastApiClient(
        enabled=True,
        provider="openai",
        base_url="https://api.openai.com",
        api_key="test-key",
        timeout_seconds=60,
        poll_seconds=5,
        text_model="gpt-5.4-mini",
        tts_model="gpt-4o-mini-tts",
        tts_voice="alloy",
    )


def test_parse_audio_segments_passes_valid_section_and_drops_unknown():
    client = _client()
    parsed = client._parse_audio_segments(
        [
            {"role": "primary", "section": "cold_open", "text": "Hi."},
            {"role": "primary", "section": "not_a_section", "text": "Body."},
            {"role": "primary", "text": "No section field."},
        ],
        primary_speaker_name="Vinnie",
    )
    assert [s.section for s in parsed] == ["cold_open", None, None]
