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
    inbound_alias: Optional[str] = None
    last_weekly_update_iso_week: Optional[str] = None
    created_at: datetime
    updated_at: datetime


class PodcastProfileRecord(BaseModel):
    user_id: str
    title: str = "ClawCast"
    format_preset: str = "two_hosts"
    host_primary_name: str = "Vinnie"
    host_secondary_name: Optional[str] = "Demi"
    guest_names: list[str] = Field(default_factory=list)
    desired_duration_minutes: int = 3
    voice_id: Optional[str] = None
    secondary_voice_id: Optional[str] = None
    tone: str = "calm_analyst"
    key_findings_count: int = 3
    humor_style: str = "none"
    personalized_greeting: bool = True
    include_top_takeaways: bool = True
    include_weather: bool = False
    weather_location: Optional[str] = None
    custom_guidance: Optional[str] = None
    custom_guidance_preset_id: Optional[str] = None
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
    transcript_text: Optional[str] = None


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


class InboundEmailItem(BaseModel):
    """A single newsletter email captured via the Mailgun inbound webhook."""

    id: str  # deterministic: hash(message_id || user_id)
    user_id: str
    message_id: Optional[str] = None  # RFC 822 Message-Id, for dedupe
    from_email: str  # canonical sender address
    from_name: Optional[str] = None
    sender_domain: str  # parsed from from_email, e.g. "stratechery.com"
    subject: str
    body_text: str  # cleaned plaintext body
    article_url: Optional[str] = None  # extracted "read on web" link if found
    received_at: datetime
    consumed_at: Optional[datetime] = None  # set when included in an episode


class UserSubstackIntent(BaseModel):
    """A user's intent to subscribe to a Substack publication via their alias.

    Lifecycle:
      1. Created when user taps "Subscribe" on a publication in our app.
      2. `auto_confirmed_at` set when the inbound handler matches a Substack
         double-opt-in email to this intent and clicks the confirm link
         server-side.
      3. `confirmed_at` set when the first non-confirmation Substack email
         from this publication arrives at the alias. UI flips Pending ->
         Confirmed at this point (see decision: low-volume pubs may stay
         Pending for days, with copy that sets that expectation).
    """

    id: str  # sha256(user_id + ":" + pub_host)[:32] -- idempotent per (user, pub)
    user_id: str
    pub_url: str  # canonical: scheme + host, no path or trailing slash
    pub_host: str  # lowercased host, used to match incoming emails to intents
    pub_title: Optional[str] = None
    pub_author: Optional[str] = None
    pub_icon_url: Optional[str] = None
    has_paid_tier: bool = False
    alias_email: str  # snapshot of the alias at intent-creation time
    created_at: datetime
    auto_confirmed_at: Optional[datetime] = None
    confirmed_at: Optional[datetime] = None


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


class FeedbackRecord(BaseModel):
    id: str
    user_id: str
    raw_text: str
    english_text: Optional[str] = None
    locale_hint: Optional[str] = None
    source: str = "text"
    created_at: datetime


class SwipeRecord(BaseModel):
    """A single user reaction to a candidate item — the raw signal that drives
    interest-vector learning. Embedding is snapshotted from the source item at
    swipe time so the vector survives even if the source item is later
    re-embedded with a different model or rolls off the corpus.
    """

    id: str
    user_id: str
    source_item_dedupe_key: str
    direction: int  # +1 = right (more like this), -1 = left (less like this)
    title: str
    link: str
    source_id: str
    source_name: str
    embedding: list[float]
    embedding_model: str
    swiped_at: datetime


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
