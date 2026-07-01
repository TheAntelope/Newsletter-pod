"""Show blueprint — the admin-editable, versioned shape of the per-user daily
briefing.

Pure models + defaults + validation, no I/O. The blueprint is the global source
of truth for episode STRUCTURE (which named sections exist, in what order, how
deep each goes) and STYLE (de-AI guardrails, prediction-market and music
settings, closing/announcements). It is persisted + versioned by
``config_repository.py`` and read at generation time through a short-TTL cache.

Kept dependency-free (imports nothing from the rest of the package at runtime)
so ``models.py`` can import ``ShowBlueprint`` for ``PodcastUxConfig`` without a
cycle. ``default_blueprint`` accepts the ``Settings`` object but only for a
forward-compatible seed hook — it is typed under ``TYPE_CHECKING`` to keep the
no-runtime-dependency contract.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Literal, Optional

from pydantic import BaseModel, Field, field_validator

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .config import Settings


# Ordered on-air section kinds. `story_block` may repeat conceptually (the LLM
# emits up to `max_blocks` blocks under one section entry); everything else is a
# singleton. `closing` must be the last enabled section (validated below).
SectionKind = Literal[
    "cold_open",
    "headlines",
    "weather",
    "story_block",
    "market",
    "announcements",
    "closing",
]

DetailLevel = Literal["headline", "shallow", "standard", "deep"]

# Spoken-word budget per detail level. Anchors the LLM's per-section length on
# top of the episode-wide minute target (see prompting.WORDS_PER_MINUTE).
_DETAIL_WORDS: dict[str, int] = {
    "headline": 40,
    "shallow": 90,
    "standard": 160,
    "deep": 300,
}


class SectionDef(BaseModel):
    kind: SectionKind
    enabled: bool = True
    detail_level: DetailLevel = "standard"
    # Explicit word budget override. When None the detail_level map is used.
    target_words: Optional[int] = Field(default=None, ge=10, le=1200)
    # Free-text steer for this section, injected verbatim into the segment plan.
    instructions: Optional[str] = None
    # story_block only: soft cap on how many distinct story blocks to produce.
    max_blocks: Optional[int] = Field(default=None, ge=1, le=8)

    def effective_words(self) -> int:
        if self.target_words is not None:
            return self.target_words
        return _DETAIL_WORDS[self.detail_level]


class OpeningConfig(BaseModel):
    # Whether a music bed plays under the open. The `sections` list is the
    # single source of truth for WHICH sections exist and their order/detail
    # (including headlines and weather) — this config only carries the
    # audio-production concern, so there's no second place to toggle a section.
    intro_music_enabled: bool = False
    # GCS object name (under the music/ prefix) for the intro bed.
    intro_music_asset: Optional[str] = None


class StyleGuardrails(BaseModel):
    # Extends text_lint.DEFAULT_BANNED_PHRASES; substring or regex tics to avoid.
    banned_phrases: list[str] = Field(default_factory=list)
    positive_guidance: Optional[str] = None
    lint_enabled: bool = True
    # Hard cap on how many offending segments the post-gen rewrite pass touches.
    max_rewrite_segments: int = Field(default=3, ge=0, le=8)


class PredictionMarketConfig(BaseModel):
    enabled: bool = False
    max_mentions: int = Field(default=2, ge=0, le=6)
    # Cosine-similarity floor for matching a market to a story item.
    min_relevance: float = Field(default=0.35, ge=0.0, le=1.0)


class MusicConfig(BaseModel):
    outro_music_enabled: bool = False
    outro_music_asset: Optional[str] = None
    # ffmpeg mix parameters (see audio_mastering.splice_music).
    music_gain_db: float = Field(default=-18.0, ge=-40.0, le=0.0)
    intro_bed_seconds: float = Field(default=4.0, ge=0.0, le=20.0)
    fade_ms: int = Field(default=800, ge=0, le=5000)


class ClosingConfig(BaseModel):
    # Read verbatim in the announcements section / threaded into the closing.
    announcements_text: Optional[str] = None
    signoff_override: Optional[str] = None


class ShowBlueprint(BaseModel):
    sections: list[SectionDef]
    opening: OpeningConfig = Field(default_factory=OpeningConfig)
    style: StyleGuardrails = Field(default_factory=StyleGuardrails)
    predictions: PredictionMarketConfig = Field(default_factory=PredictionMarketConfig)
    music: MusicConfig = Field(default_factory=MusicConfig)
    closing: ClosingConfig = Field(default_factory=ClosingConfig)

    @field_validator("sections")
    @classmethod
    def _validate_sections(cls, sections: list[SectionDef]) -> list[SectionDef]:
        enabled = [s for s in sections if s.enabled]
        if not enabled:
            raise ValueError("at least one section must be enabled")
        if enabled[-1].kind != "closing":
            raise ValueError("the last enabled section must be `closing`")
        return sections

    def enabled_sections(self) -> list[SectionDef]:
        return [s for s in self.sections if s.enabled]

    def section(self, kind: SectionKind) -> Optional[SectionDef]:
        for s in self.sections:
            if s.kind == kind:
                return s
        return None

    def is_enabled(self, kind: SectionKind) -> bool:
        s = self.section(kind)
        return bool(s and s.enabled)


def default_blueprint(settings: Optional["Settings"] = None) -> ShowBlueprint:
    """The v1 seed blueprint, mirroring today's freeform behaviour: a cold open,
    a quick headlines pass, weather (subject to the per-user gate), 2-4 story
    blocks, then the closing. Announcements/market/music are present but off.

    `settings` is accepted for forward compatibility but not currently read —
    there is no env var that maps to section structure. Generation falls back to
    this when no admin version has been saved, so the product works before any
    edit.
    """

    return ShowBlueprint(
        sections=[
            SectionDef(kind="cold_open", detail_level="shallow"),
            SectionDef(kind="headlines", detail_level="headline"),
            SectionDef(kind="weather", detail_level="headline"),
            SectionDef(kind="story_block", detail_level="standard", max_blocks=4),
            SectionDef(kind="announcements", enabled=False, detail_level="headline"),
            SectionDef(kind="closing", detail_level="shallow"),
        ],
    )


class BlueprintVersionRecord(BaseModel):
    """One persisted, immutable version of the blueprint. `version` is a
    monotonically increasing counter; a restore writes a NEW version referencing
    the old one in `note` rather than rewinding the counter.
    """

    version: int = Field(ge=1)
    blueprint: ShowBlueprint
    updated_at: datetime
    updated_by: str = "admin"
    note: Optional[str] = None
