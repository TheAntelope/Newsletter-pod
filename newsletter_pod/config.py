from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import yaml
from google.cloud import secretmanager
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from .models import PodcastUxConfig, SourceDefinition, VoiceDefinition


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: str = Field(default="dev", alias="APP_ENV")
    app_base_url: str = Field(default="http://localhost:8000", alias="APP_BASE_URL")
    app_timezone: str = Field(default="Europe/Copenhagen", alias="APP_TIMEZONE")
    use_inmemory_adapters: bool = Field(default=False, alias="USE_INMEMORY_ADAPTERS")
    google_cloud_project: Optional[str] = Field(default=None, alias="GOOGLE_CLOUD_PROJECT")

    # Daily Firestore->BigQuery snapshot export (analytics_export.py). Off by
    # default so it's a no-op locally / in tests; set true on Cloud Run. The
    # dataset must already exist (created with the log sink) and live in
    # `bigquery_location`. Project falls back to the BigQuery client's inferred
    # project (the Cloud Run metadata server) when google_cloud_project is unset.
    analytics_export_enabled: bool = Field(default=False, alias="ANALYTICS_EXPORT_ENABLED")
    bigquery_dataset_id: str = Field(default="analytics", alias="BIGQUERY_DATASET_ID")
    bigquery_location: str = Field(default="europe-west1", alias="BIGQUERY_LOCATION")

    job_trigger_token: Optional[str] = Field(default=None, alias="JOB_TRIGGER_TOKEN")
    session_signing_secret: str = Field(default="dev-session-secret", alias="SESSION_SIGNING_SECRET")
    session_ttl_hours: int = Field(default=720, alias="SESSION_TTL_HOURS")
    apple_client_id: Optional[str] = Field(default=None, alias="APPLE_CLIENT_ID")
    firebase_project_id: Optional[str] = Field(default=None, alias="FIREBASE_PROJECT_ID")

    sources_file: str = Field(default="sources.yml", alias="SOURCES_FILE")
    voices_file: str = Field(default="voices.yml", alias="VOICES_FILE")

    podcast_title: str = Field(default="Daily Newsletter Digest", alias="PODCAST_TITLE")
    podcast_description: str = Field(
        default="A private daily digest generated from multiple newsletter sources.",
        alias="PODCAST_DESCRIPTION",
    )
    podcast_author: str = Field(default="Newsletter Pod", alias="PODCAST_AUTHOR")
    podcast_language: str = Field(default="en-us", alias="PODCAST_LANGUAGE")
    podcast_owner_email: str = Field(default="vincemartin1991@gmail.com", alias="PODCAST_OWNER_EMAIL")
    podcast_image_url: Optional[str] = Field(
        default="https://newsletter-pod-497154432194.europe-west1.run.app/static/cover.png",
        alias="PODCAST_IMAGE_URL",
    )
    podcast_category: str = Field(default="News", alias="PODCAST_CATEGORY")

    podcast_provider: str = Field(default="openai", alias="PODCAST_PROVIDER")
    podcast_api_enabled: bool = Field(default=False, alias="PODCAST_API_ENABLED")
    podcast_api_base_url: Optional[str] = Field(default="https://api.openai.com", alias="PODCAST_API_BASE_URL")
    podcast_api_key: Optional[str] = Field(default=None, alias="PODCAST_API_KEY")
    podcast_api_timeout_seconds: int = Field(default=600, alias="PODCAST_API_TIMEOUT_SECONDS")
    podcast_api_poll_seconds: int = Field(default=10, alias="PODCAST_API_POLL_SECONDS")
    podcast_text_model: str = Field(default="gpt-5.4-mini", alias="PODCAST_TEXT_MODEL")
    podcast_tts_provider: str = Field(default="elevenlabs", alias="PODCAST_TTS_PROVIDER")
    podcast_tts_model: str = Field(default="gpt-4o-mini-tts", alias="PODCAST_TTS_MODEL")
    podcast_tts_voice: str = Field(default="alloy", alias="PODCAST_TTS_VOICE")
    podcast_tts_instructions: Optional[str] = Field(default=None, alias="PODCAST_TTS_INSTRUCTIONS")
    elevenlabs_api_key: Optional[str] = Field(default=None, alias="ELEVENLABS_API_KEY")
    elevenlabs_model: str = Field(default="eleven_multilingual_v2", alias="ELEVENLABS_MODEL")
    elevenlabs_voice_primary_id: str = Field(
        default="suMMgpGbVcnihP1CcgFS", alias="ELEVENLABS_VOICE_PRIMARY_ID"
    )
    elevenlabs_voice_primary_name: str = Field(
        default="Vinnie Chase", alias="ELEVENLABS_VOICE_PRIMARY_NAME"
    )
    elevenlabs_voice_secondary_id: str = Field(
        default="RKCbSROXui75bk1SVpy8", alias="ELEVENLABS_VOICE_SECONDARY_ID"
    )
    elevenlabs_voice_secondary_name: str = Field(
        default="Demi Dreams", alias="ELEVENLABS_VOICE_SECONDARY_NAME"
    )
    podcast_host_primary_name: str = Field(default="Vinnie", alias="PODCAST_HOST_PRIMARY_NAME")
    podcast_host_secondary_name: str = Field(default="Demi", alias="PODCAST_HOST_SECONDARY_NAME")
    podcast_format: str = Field(default="anchor_guest", alias="PODCAST_FORMAT")
    podcast_tone: str = Field(default="calm_analyst", alias="PODCAST_TONE")
    podcast_target_minutes: int = Field(default=6, alias="PODCAST_TARGET_MINUTES")
    podcast_max_minutes: int = Field(default=8, alias="PODCAST_MAX_MINUTES")
    podcast_thin_day_minutes: int = Field(default=2, alias="PODCAST_THIN_DAY_MINUTES")
    podcast_bootstrap_max_items_per_source: int = Field(default=3, alias="PODCAST_BOOTSTRAP_MAX_ITEMS_PER_SOURCE")

    # Source-item embeddings (Phase 1 of the swipe-based interest learning workstream).
    # When enabled, every fetched item is upserted to the source_items collection and
    # embedded with the configured OpenAI model. The api_key falls back to podcast_api_key
    # so a single OpenAI key can drive both script generation and embeddings.
    source_item_embeddings_enabled: bool = Field(default=False, alias="SOURCE_ITEM_EMBEDDINGS_ENABLED")
    openai_embedding_api_key: Optional[str] = Field(default=None, alias="OPENAI_EMBEDDING_API_KEY")
    openai_embedding_model: str = Field(default="text-embedding-3-small", alias="OPENAI_EMBEDDING_MODEL")
    openai_embedding_endpoint: str = Field(
        default="https://api.openai.com/v1/embeddings", alias="OPENAI_EMBEDDING_ENDPOINT"
    )

    # Swipe-based ranker (Phase 2). When enabled, candidate items for a user's
    # episode are scored by cosine similarity to the user's interest vector
    # (mean of right-swipe embeddings minus mean of left-swipe embeddings)
    # before tier caps are applied. Falls back to chronological ordering when
    # the user has fewer than swipe_ranker_min_swipes recorded.
    #
    # ON by default as of the 2026-05 onboarding rework: voice-intake +
    # Substack-paste + swipe-deck steps all produce synthetic seeds, so a
    # user typically clears the min-swipe threshold during onboarding before
    # the first generation run.
    swipe_ranker_enabled: bool = Field(default=True, alias="SWIPE_RANKER_ENABLED")
    swipe_ranker_min_swipes: int = Field(default=3, alias="SWIPE_RANKER_MIN_SWIPES")

    # Score bonus added to inbound newsletter items (Substack subscriptions,
    # forwarded mail, prefetched-on-intent posts) when the swipe ranker is
    # active. The bonus is added to cosine_similarity(user_vector, item) in
    # [-1, +1] space, so +0.25 reliably places inbound items above the bulk
    # of RSS items but still lets a strongly-aligned RSS item rank above
    # them. Set to 0.0 to disable; raise toward 1.0 to make inbound content
    # nearly always survive the per-episode cap. Has no effect on users
    # below swipe_ranker_min_swipes (chronological fallback ignores it).
    inbound_ranker_bias: float = Field(default=0.25, alias="INBOUND_RANKER_BIAS")

    # Voice-intake LLM model. Light extraction task; default to a fast/cheap
    # model since the prompt is small and the output is structured JSON.
    voice_intake_model: str = Field(default="gpt-4o-mini", alias="VOICE_INTAKE_MODEL")

    # Card-summary LLM model. Produces 1-2 sentence rewrites of raw RSS
    # summaries for swipe-deck cards. Cached on the source_items doc so each
    # item is summarized at most once.
    card_summary_model: str = Field(default="gpt-4o-mini", alias="CARD_SUMMARY_MODEL")

    # Substack-discovery LLM model. Takes a free-text user description and
    # proposes candidate Substack publications, validated server-side via the
    # existing probe_publication helper.
    substack_discovery_model: str = Field(
        default="gpt-4o-mini", alias="SUBSTACK_DISCOVERY_MODEL"
    )

    # Cold-start swipe deck (Phase 3). The deck is global, recomputed lazily
    # on the first request after the TTL expires. Recent-items deck is per-user,
    # never cached, drawn from items the user's currently-attached sources
    # produced within the lookback window.
    cold_start_deck_size: int = Field(default=20, alias="COLD_START_DECK_SIZE")
    cold_start_deck_ttl_hours: int = Field(default=168, alias="COLD_START_DECK_TTL_HOURS")
    cold_start_corpus_limit: int = Field(default=5000, alias="COLD_START_CORPUS_LIMIT")
    recent_deck_size: int = Field(default=5, alias="RECENT_DECK_SIZE")
    recent_deck_lookback_days: int = Field(default=14, alias="RECENT_DECK_LOOKBACK_DAYS")
    # Fraction of the recent deck drawn from sources the user has NOT attached,
    # so the swipe loop can discover new interests instead of only refining
    # within already-subscribed sources. 0.0 = no exploration; 1.0 = pure
    # exploration. Items from non-attached sources are interleaved with
    # attached-source items, not visually distinguished.
    recent_deck_exploration_ratio: float = Field(
        default=0.3, alias="RECENT_DECK_EXPLORATION_RATIO"
    )
    # After this many right-swipes on items from a single non-attached source,
    # the source is silently attached to the user. Failures (e.g. source not
    # in the curated catalog) are swallowed — auto-attach never blocks a swipe.
    auto_attach_right_swipe_threshold: int = Field(
        default=3, alias="AUTO_ATTACH_RIGHT_SWIPE_THRESHOLD"
    )

    # "Next episode queue" spike — exposes a live view of what's likely to
    # land in the user's next pod, with pin / exclude levers.
    # - candidate_queue_enabled: flag-gates the hourly poll job, the queue
    #   endpoints, and the pin-honoring hook in generation. Default off so
    #   the feature ships dark.
    # - next_episode_max_pins: hard cap on how many pinned items can force-
    #   into a single episode, protecting per-tier item caps from being
    #   eaten entirely by pins.
    # - next_episode_candidates_lookback_days: how far back the candidates
    #   view scans `source_items`. Bounded so a user opening the queue for
    #   the first time doesn't see months of stale items.
    # - next_episode_candidates_limit: defensive cap on the response size.
    candidate_queue_enabled: bool = Field(
        default=False, alias="CANDIDATE_QUEUE_ENABLED"
    )
    next_episode_max_pins: int = Field(
        default=5, alias="NEXT_EPISODE_MAX_PINS"
    )
    next_episode_candidates_lookback_days: int = Field(
        default=14, alias="NEXT_EPISODE_CANDIDATES_LOOKBACK_DAYS"
    )
    next_episode_candidates_limit: int = Field(
        default=50, alias="NEXT_EPISODE_CANDIDATES_LIMIT"
    )

    gcs_bucket_name: Optional[str] = Field(default=None, alias="GCS_BUCKET_NAME")
    gcs_prefix: str = Field(default="episodes", alias="GCS_PREFIX")

    firestore_collection_prefix: str = Field(default="newsletter_pod", alias="FIRESTORE_COLLECTION_PREFIX")

    alert_email_enabled: bool = Field(default=False, alias="ALERT_EMAIL_ENABLED")
    alert_email_from: Optional[str] = Field(default=None, alias="ALERT_EMAIL_FROM")
    alert_email_to: Optional[str] = Field(default=None, alias="ALERT_EMAIL_TO")
    publish_summary_email_enabled: bool = Field(default=False, alias="PUBLISH_SUMMARY_EMAIL_ENABLED")
    feedback_digest_email_enabled: bool = Field(
        default=False, alias="FEEDBACK_DIGEST_EMAIL_ENABLED"
    )
    feedback_digest_extra_recipients: str = Field(
        default="vincemartin1991@gmail.com",
        alias="FEEDBACK_DIGEST_EXTRA_RECIPIENTS",
    )
    smtp_host: Optional[str] = Field(default=None, alias="SMTP_HOST")
    smtp_port: int = Field(default=587, alias="SMTP_PORT")
    smtp_username: Optional[str] = Field(default=None, alias="SMTP_USERNAME")
    smtp_password: Optional[str] = Field(default=None, alias="SMTP_PASSWORD")
    smtp_use_tls: bool = Field(default=True, alias="SMTP_USE_TLS")

    schedule_start_local: str = Field(default="06:30", alias="SCHEDULE_START_LOCAL")
    schedule_target_local: str = Field(default="07:00", alias="SCHEDULE_TARGET_LOCAL")
    schedule_cutoff_local: str = Field(default="23:00", alias="SCHEDULE_CUTOFF_LOCAL")
    rapid_retry_minutes: int = Field(default=5, alias="RAPID_RETRY_MINUTES")
    periodic_retry_minutes: int = Field(default=30, alias="PERIODIC_RETRY_MINUTES")

    max_feed_episodes: int = Field(default=30, alias="MAX_FEED_EPISODES")
    weekly_target_local: str = Field(default="07:00", alias="WEEKLY_TARGET_LOCAL")
    weekly_cutoff_local: str = Field(default="11:00", alias="WEEKLY_CUTOFF_LOCAL")
    dispatch_interval_minutes: int = Field(default=15, alias="DISPATCH_INTERVAL_MINUTES")

    # Defensive ceiling on user source count. Not a tier limit — the paywall
    # doesn't mention it. Sized to absorb pathological cases (OPML paste,
    # runaway add loop) without letting ingestion explode.
    max_sources_safety_cap: int = Field(default=100, alias="MAX_SOURCES_SAFETY_CAP")

    # Tier delivery-day caps. After the launch tier-model change (2026-05-16),
    # delivery days no longer differ across tiers — pro/max both deliver 7 days,
    # free is 7 days (with most days using OpenAI default voice after the
    # first-month grace window). Kept as separate settings so we can split
    # later without a schema change.
    free_max_delivery_days: int = Field(default=7, alias="FREE_MAX_DELIVERY_DAYS")
    pro_max_delivery_days: int = Field(default=7, alias="PRO_MAX_DELIVERY_DAYS")
    max_max_delivery_days: int = Field(default=7, alias="MAX_MAX_DELIVERY_DAYS")
    # Duration ranges. 5-min episode ceiling is firm across all tiers — see
    # billing_model_2026_05.md.
    free_min_duration_minutes: int = Field(default=3, alias="FREE_MIN_DURATION_MINUTES")
    free_max_duration_minutes: int = Field(default=5, alias="FREE_MAX_DURATION_MINUTES")
    free_default_duration_minutes: int = Field(default=3, alias="FREE_DEFAULT_DURATION_MINUTES")
    pro_min_duration_minutes: int = Field(default=3, alias="PRO_MIN_DURATION_MINUTES")
    pro_max_duration_minutes: int = Field(default=5, alias="PRO_MAX_DURATION_MINUTES")
    max_min_duration_minutes: int = Field(default=3, alias="MAX_MIN_DURATION_MINUTES")
    max_max_duration_minutes: int = Field(default=5, alias="MAX_MAX_DURATION_MINUTES")
    free_max_items_per_episode: int = Field(default=25, alias="FREE_MAX_ITEMS_PER_EPISODE")
    pro_max_items_per_episode: int = Field(default=75, alias="PRO_MAX_ITEMS_PER_EPISODE")
    max_max_items_per_episode: int = Field(default=75, alias="MAX_MAX_ITEMS_PER_EPISODE")

    # Per-week voice-tier quotas. Premium = ElevenLabs voices; default = OpenAI TTS.
    # Counters reset weekly (ISO week). Trial premium pods (below) are consumed
    # by every premium-voice episode until exhausted, regardless of tier.
    trial_premium_pods_total: int = Field(default=5, alias="TRIAL_PREMIUM_PODS_TOTAL")
    free_first_month_grace_days: int = Field(default=28, alias="FREE_FIRST_MONTH_GRACE_DAYS")
    free_first_month_premium_pods_per_week: int = Field(
        default=1, alias="FREE_FIRST_MONTH_PREMIUM_PODS_PER_WEEK"
    )
    free_post_month_default_pods_per_week: int = Field(
        default=1, alias="FREE_POST_MONTH_DEFAULT_PODS_PER_WEEK"
    )
    pro_premium_pods_per_week: int = Field(default=3, alias="PRO_PREMIUM_PODS_PER_WEEK")
    pro_default_pods_per_week: int = Field(default=4, alias="PRO_DEFAULT_PODS_PER_WEEK")
    max_premium_pods_per_week: int = Field(default=7, alias="MAX_PREMIUM_PODS_PER_WEEK")

    # 7-day full-access trial (2026-06-13). Every new user gets `trial_tier`
    # entitlements for `trial_window_days` days from signup; existing unpaid
    # users were granted the same window via scripts/grant_time_trial.py. While
    # the window is open a free user is treated as `trial_tier` for capability
    # purposes (their subscription tier stays "free", so the paywall still
    # shows). After it closes they fall back to the free model (1 default-voice
    # pod/week). This supersedes the legacy pod-count trial
    # (`trial_premium_pods_total`) for users created after the change.
    trial_window_days: int = Field(default=7, alias="TRIAL_WINDOW_DAYS")
    trial_tier: str = Field(default="max", alias="TRIAL_TIER")

    cloud_tasks_project_id: Optional[str] = Field(default=None, alias="CLOUD_TASKS_PROJECT_ID")
    cloud_tasks_location: Optional[str] = Field(default=None, alias="CLOUD_TASKS_LOCATION")
    cloud_tasks_queue: Optional[str] = Field(default=None, alias="CLOUD_TASKS_QUEUE")
    cloud_tasks_service_account: Optional[str] = Field(default=None, alias="CLOUD_TASKS_SERVICE_ACCOUNT")

    # StoreKit subscription product IDs. Four SKUs: pro/max × monthly/annual.
    # See billing_model_2026_05.md for the launch tier model.
    app_store_pro_monthly_product_id: str = Field(
        default="com.newsletterpod.pro.monthly", alias="APP_STORE_PRO_MONTHLY_PRODUCT_ID"
    )
    app_store_pro_annual_product_id: str = Field(
        default="com.newsletterpod.pro.annual", alias="APP_STORE_PRO_ANNUAL_PRODUCT_ID"
    )
    app_store_max_monthly_product_id: str = Field(
        default="com.newsletterpod.max.monthly", alias="APP_STORE_MAX_MONTHLY_PRODUCT_ID"
    )
    app_store_max_annual_product_id: str = Field(
        default="com.newsletterpod.max.annual", alias="APP_STORE_MAX_ANNUAL_PRODUCT_ID"
    )

    # RevenueCat (Android / Play Billing). The webhook auth secret is the BARE
    # token from the Authorization value configured in the RevenueCat dashboard
    # (store it WITHOUT any "Bearer " prefix — the webhook strips that prefix
    # off the incoming header before a constant-time compare). Product ids map
    # the RevenueCat/Play products → tier (mirrors the App Store ids above).
    # When the secret is unset the webhook 503s, so this ships safely ahead of setup.
    revenuecat_webhook_auth_secret: Optional[str] = Field(
        default=None, alias="REVENUECAT_WEBHOOK_AUTH_SECRET"
    )
    revenuecat_pro_monthly_product_id: str = Field(
        default="pro_monthly", alias="REVENUECAT_PRO_MONTHLY_PRODUCT_ID"
    )
    revenuecat_pro_annual_product_id: str = Field(
        default="pro_annual", alias="REVENUECAT_PRO_ANNUAL_PRODUCT_ID"
    )
    revenuecat_max_monthly_product_id: str = Field(
        default="max_monthly", alias="REVENUECAT_MAX_MONTHLY_PRODUCT_ID"
    )
    revenuecat_max_annual_product_id: str = Field(
        default="max_annual", alias="REVENUECAT_MAX_ANNUAL_PRODUCT_ID"
    )

    # App Store Server Notifications V2 signed-payload verification.
    # - bundle_id: must match what's registered in App Store Connect.
    # - environment: "sandbox" or "production" (Apple uses different cert
    #   chains and notification semantics in each).
    # - app_apple_id: the numeric App Store Connect id. Apple's library
    #   requires this for environment="production"; sandbox tolerates None.
    # - notifications_require_signed: when True, any POST to the
    #   /v1/billing/app-store/notifications endpoint that doesn't include
    #   `signedPayload` is rejected. Leave False during development so
    #   tests can keep posting flat JSON; flip to True before public
    #   launch so anonymous POSTs can't tamper with tier state.
    app_store_bundle_id: str = Field(
        default="com.newsletterpod.app", alias="APP_STORE_BUNDLE_ID"
    )
    app_store_environment: str = Field(default="sandbox", alias="APP_STORE_ENVIRONMENT")
    app_store_app_apple_id: Optional[int] = Field(
        default=None, alias="APP_STORE_APP_APPLE_ID"
    )
    app_store_notifications_require_signed: bool = Field(
        default=False, alias="APP_STORE_NOTIFICATIONS_REQUIRE_SIGNED"
    )

    # Comma-separated list of UserRecord.id values allowed to hit /admin/*.
    # Empty string = endpoint is effectively closed (everyone gets 403).
    admin_user_ids: str = Field(default="", alias="ADMIN_USER_IDS")

    # Phase 3 churn-risk scoring threshold (0.0 - 1.0). Scores at or above
    # this value flip the record's `at_risk` flag and emit a
    # CHURN_RISK_SCORED event. 0.6 was the brief's default; tune in
    # response to the first weeks of operator triage.
    churn_risk_threshold: float = Field(default=0.6, alias="CHURN_RISK_THRESHOLD")

    # Phase 3 weekly cohort report (Mondays). When False the job
    # endpoint short-circuits returning {"status": "disabled"}; matches
    # the feedback_digest_email_enabled pattern so an operator can flip
    # either job independently.
    cohort_report_email_enabled: bool = Field(
        default=True, alias="COHORT_REPORT_EMAIL_ENABLED"
    )

    inbound_email_domain: str = Field(default="theclawcast.com", alias="INBOUND_EMAIL_DOMAIN")
    mailgun_webhook_signing_key: Optional[str] = Field(default=None, alias="MAILGUN_WEBHOOK_SIGNING_KEY")
    mailgun_api_key: Optional[str] = Field(default=None, alias="MAILGUN_API_KEY")

    # APNs (Apple Push Notifications) — token-based authentication using a
    # .p8 ES256 key generated in Apple Developer Portal. When apns_enabled
    # is False (or auth_key is unset), the push sender no-ops with a single
    # info-log per call so verification-code emails still land but no push
    # is attempted. environment must match the build's aps-environment
    # entitlement: "production" for App Store / TestFlight builds,
    # "sandbox" for development builds running from Xcode.
    apns_enabled: bool = Field(default=False, alias="APNS_ENABLED")
    apns_team_id: Optional[str] = Field(default=None, alias="APNS_TEAM_ID")
    apns_key_id: Optional[str] = Field(default=None, alias="APNS_KEY_ID")
    apns_auth_key: Optional[str] = Field(default=None, alias="APNS_AUTH_KEY")
    apns_bundle_id: str = Field(default="com.newsletterpod.app", alias="APNS_BUNDLE_ID")
    apns_environment: str = Field(default="production", alias="APNS_ENVIRONMENT")

    # FCM (Firebase Cloud Messaging) — the Android counterpart to APNs. Sends
    # via the HTTP v1 API authenticated with a Firebase service-account JSON
    # (FCM_SERVICE_ACCOUNT_JSON, a Secret Manager secret). project_id is reused
    # from firebase_project_id. When fcm_enabled is False (or the JSON is
    # unset), the FCM sender no-ops with a single info-log per call.
    fcm_enabled: bool = Field(default=False, alias="FCM_ENABLED")
    fcm_service_account_json: Optional[str] = Field(
        default=None, alias="FCM_SERVICE_ACCOUNT_JSON"
    )

    # Welcome episode: pre-recorded MP3 seeded into every new user's feed at signup.
    # Set object_name + size + duration to enable; leave object_name empty to disable.
    welcome_episode_object_name: Optional[str] = Field(default=None, alias="WELCOME_EPISODE_OBJECT_NAME")
    welcome_episode_size_bytes: int = Field(default=0, alias="WELCOME_EPISODE_SIZE_BYTES")
    welcome_episode_duration_seconds: int = Field(default=0, alias="WELCOME_EPISODE_DURATION_SECONDS")
    welcome_episode_version: str = Field(default="v1", alias="WELCOME_EPISODE_VERSION")

    # X (Twitter) API — OAuth 1.0a user-context credentials for the
    # broadcast-loop poster. All four are required to publish; any one
    # missing disables the X client (publish endpoints return 503).
    x_api_key: Optional[str] = Field(default=None, alias="X_API_KEY")
    x_api_secret: Optional[str] = Field(default=None, alias="X_API_SECRET")
    x_access_token: Optional[str] = Field(default=None, alias="X_ACCESS_TOKEN")
    x_access_token_secret: Optional[str] = Field(default=None, alias="X_ACCESS_TOKEN_SECRET")
    # The X handle the broadcast loop posts as. Used by the reply reader
    # to exclude our own posts (the feedback-prompt reply we auto-post)
    # from conversation_id search results. Strip the leading "@" if
    # present in env. Leaving this unset disables self-filtering — the
    # raw search results still flow through, just including our own
    # feedback-prompt reply in the LLM-summarizer input.
    broadcast_x_username: Optional[str] = Field(default=None, alias="BROADCAST_X_USERNAME")

    # Phase 2 broadcast-loop LLM model. Used by both the topic picker
    # (proposes tomorrow's topic from yesterday's feedback summary +
    # seed topics) and the feedback summarizer (condenses pasted X
    # replies into a 1-3 sentence brief). One model serves both because
    # the tasks share shape — small chat completion with a JSON
    # response format. Falls back to round-robin / raw replies when no
    # OpenAI key is configured.
    broadcast_llm_model: str = Field(default="gpt-4o-mini", alias="BROADCAST_LLM_MODEL")

    @classmethod
    def from_env(cls) -> "Settings":
        settings = cls()
        settings.podcast_api_key = _normalize_secret_value(_resolve_secret_reference(settings.podcast_api_key))
        settings.elevenlabs_api_key = _normalize_secret_value(
            _resolve_secret_reference(settings.elevenlabs_api_key)
        )
        settings.smtp_password = _normalize_secret_value(_resolve_secret_reference(settings.smtp_password))
        settings.job_trigger_token = _normalize_secret_value(_resolve_secret_reference(settings.job_trigger_token))
        settings.mailgun_webhook_signing_key = _normalize_secret_value(
            _resolve_secret_reference(settings.mailgun_webhook_signing_key)
        )
        settings.mailgun_api_key = _normalize_secret_value(
            _resolve_secret_reference(settings.mailgun_api_key)
        )
        # APNs .p8 is multiline PEM; _normalize_secret_value strips outer
        # whitespace but preserves internal newlines, which is what PyJWT
        # needs when loading the ES256 key.
        settings.apns_auth_key = _normalize_secret_value(
            _resolve_secret_reference(settings.apns_auth_key)
        )
        settings.apns_key_id = _normalize_secret_value(
            _resolve_secret_reference(settings.apns_key_id)
        )
        # FCM service-account JSON is multiline; _normalize_secret_value keeps
        # internal newlines (json.loads is whitespace-tolerant either way).
        settings.fcm_service_account_json = _normalize_secret_value(
            _resolve_secret_reference(settings.fcm_service_account_json)
        )
        settings.revenuecat_webhook_auth_secret = _normalize_secret_value(
            _resolve_secret_reference(settings.revenuecat_webhook_auth_secret)
        )
        settings.session_signing_secret = _normalize_secret_value(
            _resolve_secret_reference(settings.session_signing_secret)
        ) or "dev-session-secret"
        settings.openai_embedding_api_key = _normalize_secret_value(
            _resolve_secret_reference(settings.openai_embedding_api_key)
        ) or settings.podcast_api_key
        settings.x_api_key = _normalize_secret_value(_resolve_secret_reference(settings.x_api_key))
        settings.x_api_secret = _normalize_secret_value(_resolve_secret_reference(settings.x_api_secret))
        settings.x_access_token = _normalize_secret_value(_resolve_secret_reference(settings.x_access_token))
        settings.x_access_token_secret = _normalize_secret_value(
            _resolve_secret_reference(settings.x_access_token_secret)
        )
        settings.google_cloud_project = settings.google_cloud_project or os.getenv("GCP_PROJECT")
        return settings

    def podcast_ux_config(self) -> PodcastUxConfig:
        return PodcastUxConfig(
            host_primary_name=self.podcast_host_primary_name,
            host_secondary_name=self.podcast_host_secondary_name,
            format=self.podcast_format,
            tone=self.podcast_tone,
            target_minutes=self.podcast_target_minutes,
            max_minutes=self.podcast_max_minutes,
            thin_day_minutes=self.podcast_thin_day_minutes,
        )


def load_sources(path: str) -> list[SourceDefinition]:
    source_path = Path(path)
    if not source_path.exists():
        return []

    data = yaml.safe_load(source_path.read_text(encoding="utf-8")) or {}
    raw_sources = data.get("sources", [])
    sources = [SourceDefinition.model_validate(item) for item in raw_sources]
    return [source for source in sources if source.enabled]


def load_voices(path: str) -> list[VoiceDefinition]:
    voices_path = Path(path)
    if not voices_path.exists():
        return []

    data = yaml.safe_load(voices_path.read_text(encoding="utf-8")) or {}
    raw_voices = data.get("voices", [])
    voices = [VoiceDefinition.model_validate(item) for item in raw_voices]
    return [voice for voice in voices if voice.enabled]


def _resolve_secret_reference(value: Optional[str]) -> Optional[str]:
    if not value:
        return value
    if not value.startswith("sm://"):
        return value

    secret_name = value.removeprefix("sm://")
    project_id = os.getenv("GOOGLE_CLOUD_PROJECT") or os.getenv("GCP_PROJECT")
    if not project_id:
        raise RuntimeError("GOOGLE_CLOUD_PROJECT must be set for sm:// secret references")

    client = secretmanager.SecretManagerServiceClient()
    secret_path = f"projects/{project_id}/secrets/{secret_name}/versions/latest"
    response = client.access_secret_version(request={"name": secret_path})
    return response.payload.data.decode("utf-8")


def _normalize_secret_value(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    return value.strip()
