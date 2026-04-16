from __future__ import annotations

from datetime import date, datetime
from enum import Enum
from typing import Optional

from pydantic import BaseModel, Field


class PublishStatus(str, Enum):
    PUBLISHED = "published"
    NO_CONTENT = "no_content"
    PRE_ACCESS = "pre_access"
    FAILED = "failed"
    SKIPPED = "skipped"


class SourceDefinition(BaseModel):
    id: str
    name: str
    rss_url: str
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


class DigestCandidateSet(BaseModel):
    run_date: date
    items: list[SourceItem]


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
    host_primary_name: str = "Elena"
    host_secondary_name: str = "Marcus"
    format: str = "anchor_guest"
    tone: str = "calm_analyst"
    target_minutes: int = 6
    max_minutes: int = 8
    thin_day_minutes: int = 2


class EpisodeRecord(BaseModel):
    id: str
    title: str
    description: str
    published_at: datetime
    audio_object_name: str
    audio_mime_type: str = "audio/mpeg"
    audio_size_bytes: int = 0
    source_item_refs: list[SourceItemRef] = Field(default_factory=list)
    duration_seconds: Optional[int] = None


class RunRecord(BaseModel):
    id: str
    run_date: date
    started_at: datetime
    completed_at: datetime
    status: PublishStatus
    message: str
    candidate_count: int = 0
    published_episode_id: Optional[str] = None
    alert_sent: bool = False


class DayState(BaseModel):
    run_date: date
    has_published_episode: bool = False
    has_completed_run: bool = False
    has_alert_sent: bool = False
    last_attempt_at: Optional[datetime] = None


class GeneratedEpisode(BaseModel):
    episode_title: str = "Daily Newsletter Digest"
    audio_bytes: bytes
    mime_type: str = "audio/mpeg"
    show_notes: str
    audio_segments: list[AudioSegment] = Field(default_factory=list)
    transcript: Optional[str] = None
    duration_seconds: Optional[int] = None


class RunResult(BaseModel):
    run_id: str
    status: PublishStatus
    message: str
    episode_id: Optional[str] = None
    candidate_count: int = 0
