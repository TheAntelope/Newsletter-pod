from __future__ import annotations

import pytest
from pydantic import ValidationError

from newsletter_pod.blueprint import (
    SectionDef,
    ShowBlueprint,
    _DETAIL_WORDS,
    default_blueprint,
)


def _sections(*kinds: str) -> list[SectionDef]:
    return [SectionDef(kind=k) for k in kinds]


def test_default_blueprint_ends_with_closing_and_covers_core_sections():
    bp = default_blueprint()
    kinds = [s.kind for s in bp.enabled_sections()]
    assert kinds[-1] == "closing"
    # The seed mirrors today's behaviour: a cold open, headlines, weather, and
    # story blocks, then the closing. Announcements/market/music ship disabled.
    assert "cold_open" in kinds
    assert "story_block" in kinds
    assert bp.section("announcements") is not None
    assert bp.is_enabled("announcements") is False
    assert bp.predictions.enabled is False
    assert bp.opening.intro_music_enabled is False


def test_last_enabled_section_must_be_closing():
    with pytest.raises(ValidationError):
        ShowBlueprint(sections=_sections("cold_open", "story_block"))


def test_disabled_trailing_sections_do_not_count_as_last():
    # closing is enabled and is the last ENABLED section; a disabled section
    # after it is fine.
    bp = ShowBlueprint(
        sections=[
            SectionDef(kind="story_block"),
            SectionDef(kind="closing"),
            SectionDef(kind="announcements", enabled=False),
        ]
    )
    assert bp.enabled_sections()[-1].kind == "closing"


def test_at_least_one_section_must_be_enabled():
    with pytest.raises(ValidationError):
        ShowBlueprint(sections=[SectionDef(kind="closing", enabled=False)])


def test_effective_words_uses_detail_map_then_override():
    deep = SectionDef(kind="story_block", detail_level="deep")
    assert deep.effective_words() == _DETAIL_WORDS["deep"]
    override = SectionDef(kind="story_block", detail_level="deep", target_words=222)
    assert override.effective_words() == 222


def test_blueprint_round_trips_through_json():
    bp = default_blueprint()
    restored = ShowBlueprint.model_validate(bp.model_dump(mode="json"))
    assert restored == bp
