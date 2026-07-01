from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal, Optional

from pydantic import BaseModel, Field

from .blueprint import ShowBlueprint


class PublishStatus(str, Enum):
    PUBLISHED = "published"
    NO_CONTENT = "no_content"
    PRE_ACCESS = "pre_access"
    FAILED = "failed"
    SKIPPED = "skipped"
    IN_PROGRESS = "in_progress"


class SourceDefinition(BaseModel):
    id: str
    name: str
    rss_url: str
    enabled: bool = True
    topic: Optional[str] = None
    # Geographic relevance as an ISO 3166-1 alpha-2 country code (e.g. "US",
    # "DK", "GB") or the pseudo-region "EU" for pan-European publishers. None =
    # globally relevant (no regional bias). Used to nudge region-matching sources
    # up the onboarding swipe deck based on the user's timezone — see regions.py.
    region: Optional[str] = None
    # "full"   — feed carries the complete article/post text
    # "excerpt" — feed carries only a teaser; full content lives behind the link
    ingest_mode: Literal["full", "excerpt"] = "excerpt"
    # True for press publishers established in EU/EEA member states where
    # Article 15 DSM Directive (press-publisher neighbouring right) may apply.
    jurisdiction_sensitive: bool = False
    # Content medium. "article" (default) — a text newsletter/blog item.
    # "podcast" — an episode whose RSS item carries an audio <enclosure>.
    # Drives the mic icon in the Sources UI and podcast-flavoured on-air
    # attribution. Phase 1a still ingests the show notes as the item summary
    # exactly like an article; the captured audio_url/duration are groundwork
    # for later in-app playback and transcript enrichment (Phase 1b).
    kind: Literal["article", "podcast"] = "article"


class VoiceDefinition(BaseModel):
    id: str
    name: str
    gender: str = "neutral"
    description: str = ""
    preview_url: str = ""
    enabled: bool = True
    # ElevenLabs voice_settings.speed, in API range 0.7-1.2. None = let the
    # provider use its default. We bake the speed into the voice rather than
    # the user profile because it's a per-voice character trait — some
    # voices read naturally slow and want a nudge faster.
    speed: Optional[float] = None


class SourceItem(BaseModel):
    source_id: str
    source_name: str
    guid: Optional[str] = None
    link: str
    title: str
    summary: str
    published_at: datetime
    dedupe_key: str
    # "article" (default) or "podcast" — inherited from the SourceDefinition the
    # item was fetched from. Podcast items also carry the episode audio asset and
    # its length; both are captured unconditionally from the RSS <enclosure> /
    # <itunes:duration> so the data is there for any source, but only podcast
    # feeds populate them in practice.
    kind: str = "article"
    audio_url: Optional[str] = None
    audio_duration_seconds: Optional[int] = None


class SwipeDeckRecord(BaseModel):
    """Cached output of the cold-start k-means deck computation. Singleton per
    deck_id (currently only `cold_start`). Refreshed lazily when older than
    its TTL.
    """

    id: str
    dedupe_keys: list[str]
    corpus_size: int
    computed_at: datetime
    version: str = "v1"


class SourceItemRecord(BaseModel):
    """Persistent form of a SourceItem — first-class doc in the source_items collection.

    Document id is the dedupe_key. embedding/embedded_at are populated by the
    embedding pipeline; they are nullable so an item can be persisted before
    the embedding call (or when the embedding provider is disabled).

    `card_summary` is a short LLM-generated 1-2 sentence rewrite of the raw
    RSS summary, suitable for swipe cards. Populated lazily the first time
    an item appears in any swipe deck; written back to Firestore so all
    subsequent reads are free.
    """

    dedupe_key: str
    source_id: str
    source_name: str
    guid: Optional[str] = None
    link: str
    title: str
    summary: str
    published_at: datetime
    first_seen_at: datetime
    last_seen_at: datetime
    # Podcast metadata (see SourceItem). Nullable so existing rows and all
    # article items round-trip unchanged; kind defaults to "article".
    kind: str = "article"
    audio_url: Optional[str] = None
    audio_duration_seconds: Optional[int] = None
    embedding: Optional[list[float]] = None
    embedding_model: Optional[str] = None
    embedded_at: Optional[datetime] = None
    card_summary: Optional[str] = None
    card_summary_model: Optional[str] = None
    card_summarized_at: Optional[datetime] = None


class SourceItemRef(BaseModel):
    source_id: str
    source_name: str
    title: str
    link: str
    guid: Optional[str] = None


class SourcePollingStateRecord(BaseModel):
    """Per-source cursor for the global hourly poll job (candidate-queue spike).

    Unlike `user_cursors`, this state is keyed by source_id only — the poll
    walks each distinct source once per tick regardless of how many users
    are attached to it. Doc id = source_id.

    `cursor` tracks the latest `published_at` we've ingested for the source;
    subsequent polls only persist items newer than that. `last_polled_at` and
    `last_error` are diagnostic — surfaced in the job response so a flaky
    source shows up in Cloud Logging.
    """

    source_id: str
    last_polled_at: datetime
    cursor: Optional[datetime] = None
    last_item_count: int = 0
    last_error: Optional[str] = None


class NextEpisodeOverrideRecord(BaseModel):
    """A per-user, per-item override against the next episode's selection.

    `kind="pin"` forces the item into the next published episode (up to
    `next_episode_max_pins`). `kind="exclude"` drops the item from the
    candidate pool. The two states are mutually exclusive; flipping
    one to the other replaces the existing record.

    `consumed_at` is stamped when an episode publishes that honored the
    override — pins drop off the candidate list once consumed; excludes
    persist until a TTL sweep (out of scope for the spike).

    Doc id: `{user_id}:{dedupe_key_hash}` so two users can pin the same
    item independently.
    """

    user_id: str
    source_item_dedupe_key: str
    kind: Literal["pin", "exclude"]
    created_at: datetime
    consumed_at: Optional[datetime] = None


class AudioSegment(BaseModel):
    role: str = "primary"
    speaker: str
    text: str
    # Named section this segment belongs to (cold_open, headlines, weather,
    # story_block, market, announcements, closing) when a show blueprint drove
    # the script. None on the legacy freeform path and on code-built framing.
    section: Optional[str] = None


class PodcastUxConfig(BaseModel):
    host_primary_name: str = "Vinnie"
    host_secondary_name: str = "Demi"
    format: str = "anchor_guest"
    tone: str = "calm_analyst"
    target_minutes: int = 6
    max_minutes: int = 8
    thin_day_minutes: int = 2
    listener_name: Optional[str] = None
    key_findings_count: int = 3
    humor_style: str = "none"
    include_top_takeaways: bool = True
    custom_guidance: Optional[str] = None
    weather_summary: Optional[str] = None
    weekly_update_commits: Optional[list[str]] = None
    # Names, topics, publications, or phrases the listener volunteered at
    # onboarding (voice intake), subscribed to (Substack paste), or recently
    # forwarded. The script may acknowledge one once per episode when it
    # naturally connects to an item — never list them at the top of the show.
    listener_anchors: Optional[list[str]] = None
    # Global admin show blueprint (structure + style). None keeps the legacy
    # freeform prompt behaviour; when present it drives the segment plan and
    # style guardrails. See blueprint.py / config_repository.py.
    blueprint: Optional[ShowBlueprint] = None


class GeneratedEpisode(BaseModel):
    episode_title: str = "Daily Newsletter Digest"
    audio_bytes: bytes
    mime_type: str = "audio/mpeg"
    show_notes: str
    audio_segments: list[AudioSegment] = Field(default_factory=list)
    transcript: Optional[str] = None
    duration_seconds: Optional[int] = None
