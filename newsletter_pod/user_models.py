from __future__ import annotations

from datetime import date, datetime
from typing import Optional

from pydantic import BaseModel, Field

from .models import SourceItemRef


class UserRecord(BaseModel):
    id: str
    apple_subject: str
    email: Optional[str] = None
    display_name: str = "Listener"
    timezone: str = "UTC"
    created_at: datetime
    updated_at: datetime


class PodcastProfileRecord(BaseModel):
    user_id: str
    title: str = "mycast"
    format_preset: str = "two_hosts"
    host_primary_name: str = "Demi"
    host_secondary_name: Optional[str] = "Vinnie"
    guest_names: list[str] = Field(default_factory=list)
    desired_duration_minutes: int = 3
    voice_id: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class UserSourceRecord(BaseModel):
    id: str
    user_id: str
    source_id: str
    name: str
    rss_url: str
    is_custom: bool = False
    enabled: bool = True
    validated_at: Optional[datetime] = None
    created_at: datetime
    updated_at: datetime


class FeedTokenRecord(BaseModel):
    token: str
    user_id: str
    created_at: datetime


class SubscriptionRecord(BaseModel):
    user_id: str
    tier: str = "free"
    status: str = "active"
    product_id: Optional[str] = None
    started_at: Optional[datetime] = None
    renewal_at: Optional[datetime] = None
    expires_at: Optional[datetime] = None
    updated_at: datetime


class DeliveryScheduleRecord(BaseModel):
    user_id: str
    timezone: str = "UTC"
    weekdays: list[str] = Field(
        default_factory=lambda: [
            "monday", "tuesday", "wednesday", "thursday",
            "friday", "saturday", "sunday",
        ]
    )
    local_time: str = "07:00"
    cutoff_time: str = "11:00"
    enabled: bool = True
    created_at: datetime
    updated_at: datetime


class UserEpisodeRecord(BaseModel):
    id: str
    user_id: str
    title: str
    description: str
    published_at: datetime
    audio_object_name: str
    audio_mime_type: str = "audio/mpeg"
    audio_size_bytes: int = 0
    source_item_refs: list[SourceItemRef] = Field(default_factory=list)
    duration_seconds: Optional[int] = None
    processed_item_count: int = 0
    dropped_item_count: int = 0
    cap_hit: bool = False
    guest_name: Optional[str] = None


class UserRunRecord(BaseModel):
    id: str
    user_id: str
    local_run_date: date
    started_at: datetime
    completed_at: datetime
    status: str
    message: str
    candidate_count: int = 0
    processed_item_count: int = 0
    dropped_item_count: int = 0
    cap_hit: bool = False
    published_episode_id: Optional[str] = None


class CostRecord(BaseModel):
    run_id: str
    user_id: str
    text_input_tokens_estimate: int = 0
    text_output_tokens_estimate: int = 0
    tts_input_tokens_estimate: int = 0
    tts_output_minutes_estimate: float = 0.0
    openai_cost_usd: float = 0.0
    infra_reserve_cost_usd: float = 0.0
    total_cost_usd: float = 0.0
    recorded_at: datetime


class BillingEventRecord(BaseModel):
    id: str
    user_id: Optional[str] = None
    notification_type: str
    subtype: Optional[str] = None
    product_id: Optional[str] = None
    raw_payload: dict = Field(default_factory=dict)
    created_at: datetime


class UserEntitlements(BaseModel):
    tier: str
    max_sources: int
    max_delivery_days: int
    min_duration_minutes: int
    max_duration_minutes: int
    max_items_per_episode: int


class AuthenticatedSession(BaseModel):
    user_id: str
    issued_at: datetime
    expires_at: datetime


class AppleIdentity(BaseModel):
    subject: str
    email: Optional[str] = None
