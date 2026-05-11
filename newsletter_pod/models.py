from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


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


class VoiceDefinition(BaseModel):
    id: str
    name: str
    gender: str = "neutral"
    description: str = ""
    preview_url: str = ""
    enabled: bool = True


class SourceItem(BaseModel):
    source_id: str
    source_name: str
    guid: Optional[str] = None
    link: str
    title: str
    summary: str
    published_at: datetime
    dedupe_key: str


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
    embedding: Optional[list[float]] = None
    embedding_model: Optional[str] = None
    embedded_at: Optional[datetime] = None


class SourceItemRef(BaseModel):
    source_id: str
    source_name: str
    title: str
    link: str
    guid: Optional[str] = None


class AudioSegment(BaseModel):
    role: str = "primary"
    speaker: str
    text: str


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


class GeneratedEpisode(BaseModel):
    episode_title: str = "Daily Newsletter Digest"
    audio_bytes: bytes
    mime_type: str = "audio/mpeg"
    show_notes: str
    audio_segments: list[AudioSegment] = Field(default_factory=list)
    transcript: Optional[str] = None
    duration_seconds: Optional[int] = None
