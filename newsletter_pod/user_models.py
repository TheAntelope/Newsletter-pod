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

    # Trial + weekly quota tracking (launch tier model, 2026-05-16).
    # Trial: every new user starts with `trial_premium_pods_total` premium-voice
    # podcasts. Decremented each time a premium-voice episode is generated.
    # When it hits 0, `trial_exhausted_at` is set and `first_month_ends_at`
    # is set to trial_exhausted_at + FREE_FIRST_MONTH_GRACE_DAYS.
    trial_premium_pods_remaining: Optional[int] = None
    trial_exhausted_at: Optional[datetime] = None
    first_month_ends_at: Optional[datetime] = None
    # Weekly counters. `current_week_iso` is "YYYY-Www" (ISO 8601 week);
    # counters are zeroed when the stored week differs from the current week.
    current_week_iso: Optional[str] = None
    premium_pods_this_week: int = 0
    default_pods_this_week: int = 0


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
    """A single piece of user-originated content arriving outside the RSS path.

    Despite the name (kept for backwards compatibility with the inbound-email
    collection), this model carries three kinds of items, discriminated by
    `kind`:
      - "email": delivered to the user's Mailgun alias (forwarded newsletter,
        Substack delivery, or a prefetched latest-post stub).
      - "share": uploaded via the iOS Share extension or POST /v1/items/shared.
        Force-included in the next generation run, bypassing the per-tier
        item cap (see control_plane._select_candidates).
    """

    id: str  # deterministic: hash(message_id || user_id) for email; hash(content || user_id) for share
    user_id: str
    kind: str = "email"  # "email" | "share"
    message_id: Optional[str] = None  # RFC 822 Message-Id, for dedupe (email only)
    from_email: str  # canonical sender address; sentinel "share@theclawcast.com" for shares
    from_name: Optional[str] = None
    sender_domain: str  # parsed from from_email, e.g. "stratechery.com"; "share" for shares
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
    # Substack's newer signup flow delivers a one-time numeric code (e.g.
    # "812807") that the user has to paste back into the publication's
    # subscribe page. We can't auto-confirm those server-side, so the inbound
    # handler stamps the code here so the iOS Sources screen can surface it
    # before it expires (~15 min).
    pending_verification_code: Optional[str] = None
    pending_verification_expires_at: Optional[datetime] = None


class DeviceTokenRecord(BaseModel):
    """An APNs device token registered to a user, used for push notifications.

    `token` is the hex-encoded APNs device token (~64 chars). `id` is keyed
    on (user_id + token) so re-registering the same device is idempotent.
    `environment` distinguishes sandbox vs production builds; the push
    sender targets the matching APNs host. `last_seen_at` is bumped on every
    register call so we can age out stale tokens after long inactivity.
    """

    id: str
    user_id: str
    token: str
    platform: str = "ios"
    environment: str = "production"  # "production" | "sandbox"
    bundle_id: str
    created_at: datetime
    last_seen_at: datetime
    # When APNs returns 410 Gone for this token, we mark it inactive instead
    # of deleting outright so we keep a paper trail for debugging.
    invalidated_at: Optional[datetime] = None


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

    `seed_kind` is set on synthetic swipes (voice intake, forwarded-mail
    bootstrap, Substack paste). These swipes use a `seed:<kind>:<digest>`
    dedupe key so they never collide with real source items, but they share
    the same shape so `compute_user_vector` can blend them with real swipes
    without special-casing.
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
    seed_kind: Optional[str] = None  # None = real swipe; else "voice_intake" | "forwarded_mail" | "substack_paste"


class BillingEventRecord(BaseModel):
    id: str
    user_id: Optional[str] = None
    notification_type: str
    subtype: Optional[str] = None
    product_id: Optional[str] = None
    raw_payload: dict = Field(default_factory=dict)
    created_at: datetime


class UserEntitlements(BaseModel):
    """What this user is currently allowed to do, computed from tier + trial
    state + weekly counters. Tier is one of "free" | "pro" | "max".

    Premium pods use ElevenLabs voices (from the voice catalog). Default pods
    use OpenAI TTS with a single bundled voice. The per-week counters are
    capacity remaining for the current ISO week.
    """

    tier: str
    max_delivery_days: int
    min_duration_minutes: int
    max_duration_minutes: int
    max_items_per_episode: int

    # Per-week voice-tier budgets and remaining capacity for the current week.
    premium_pods_per_week: int = 0
    default_pods_per_week: int = 0
    premium_pods_remaining_this_week: int = 0
    default_pods_remaining_this_week: int = 0

    # Trial / first-month state. `is_in_trial` is True while
    # trial_premium_pods_remaining > 0. `is_in_first_month` is True for free
    # users between trial exhaustion and first_month_ends_at.
    is_in_trial: bool = False
    trial_premium_pods_remaining: int = 0
    is_in_first_month: bool = False
    first_month_ends_at: Optional[datetime] = None


class ChurnRiskRecord(BaseModel):
    """Latest churn-risk score for a single paid user. Phase 3 scoring is
    Firestore-derived; play data lives only in Cloud Logging until the
    BigQuery sink is wired up, so `signals['days_since_last_episode']`
    is the engagement-recency proxy (true `days_since_last_play` will
    land when the events_raw view becomes queryable).

    Re-running the score job overwrites the prior record (keyed by
    user_id), so this table is always "latest snapshot", not history.
    A future change can append rather than overwrite if we want a
    score-over-time view.
    """

    user_id: str
    score: float                    # 0.0 (no risk) to 1.0 (high risk)
    at_risk: bool                   # score >= settings.churn_risk_threshold
    signals: dict[str, float] = Field(default_factory=dict)
    scored_at: datetime


class AuthenticatedSession(BaseModel):
    user_id: str
    issued_at: datetime
    expires_at: datetime


class AppleIdentity(BaseModel):
    subject: str
    email: Optional[str] = None
