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


class SourceItem(BaseModel):
    source_id: str
    source_name: str
    guid: Optional[str] = None
    link: str
    title: str
    summary: str
    published_at: datetime
    dedupe_key: str


class SourceItemRef(BaseModel):
    source_id: str
    source_name: str
    title: str
    link: str
    guid: Optional[str] = None


class AudioSegment(BaseModel):
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


class GeneratedEpisode(BaseModel):
    episode_title: str = "Daily Newsletter Digest"
    audio_bytes: bytes
    mime_type: str = "audio/mpeg"
    show_notes: str
    audio_segments: list[AudioSegment] = Field(default_factory=list)
    transcript: Optional[str] = None
    duration_seconds: Optional[int] = None
