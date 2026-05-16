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

    job_trigger_token: Optional[str] = Field(default=None, alias="JOB_TRIGGER_TOKEN")
    session_signing_secret: str = Field(default="dev-session-secret", alias="SESSION_SIGNING_SECRET")
    session_ttl_hours: int = Field(default=720, alias="SESSION_TTL_HOURS")
    apple_client_id: Optional[str] = Field(default=None, alias="APPLE_CLIENT_ID")

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
    free_max_delivery_days: int = Field(default=5, alias="FREE_MAX_DELIVERY_DAYS")
    paid_max_delivery_days: int = Field(default=7, alias="PAID_MAX_DELIVERY_DAYS")
    free_min_duration_minutes: int = Field(default=3, alias="FREE_MIN_DURATION_MINUTES")
    free_max_duration_minutes: int = Field(default=5, alias="FREE_MAX_DURATION_MINUTES")
    free_default_duration_minutes: int = Field(default=3, alias="FREE_DEFAULT_DURATION_MINUTES")
    paid_min_duration_minutes: int = Field(default=5, alias="PAID_MIN_DURATION_MINUTES")
    paid_max_duration_minutes: int = Field(default=20, alias="PAID_MAX_DURATION_MINUTES")
    free_max_items_per_episode: int = Field(default=25, alias="FREE_MAX_ITEMS_PER_EPISODE")
    paid_max_items_per_episode: int = Field(default=75, alias="PAID_MAX_ITEMS_PER_EPISODE")

    cloud_tasks_project_id: Optional[str] = Field(default=None, alias="CLOUD_TASKS_PROJECT_ID")
    cloud_tasks_location: Optional[str] = Field(default=None, alias="CLOUD_TASKS_LOCATION")
    cloud_tasks_queue: Optional[str] = Field(default=None, alias="CLOUD_TASKS_QUEUE")
    cloud_tasks_service_account: Optional[str] = Field(default=None, alias="CLOUD_TASKS_SERVICE_ACCOUNT")

    app_store_monthly_product_id: str = Field(default="com.newsletterpod.paid.monthly", alias="APP_STORE_MONTHLY_PRODUCT_ID")
    app_store_annual_product_id: str = Field(default="com.newsletterpod.paid.annual", alias="APP_STORE_ANNUAL_PRODUCT_ID")

    inbound_email_domain: str = Field(default="theclawcast.com", alias="INBOUND_EMAIL_DOMAIN")
    mailgun_webhook_signing_key: Optional[str] = Field(default=None, alias="MAILGUN_WEBHOOK_SIGNING_KEY")
    mailgun_api_key: Optional[str] = Field(default=None, alias="MAILGUN_API_KEY")

    # Welcome episode: pre-recorded MP3 seeded into every new user's feed at signup.
    # Set object_name + size + duration to enable; leave object_name empty to disable.
    welcome_episode_object_name: Optional[str] = Field(default=None, alias="WELCOME_EPISODE_OBJECT_NAME")
    welcome_episode_size_bytes: int = Field(default=0, alias="WELCOME_EPISODE_SIZE_BYTES")
    welcome_episode_duration_seconds: int = Field(default=0, alias="WELCOME_EPISODE_DURATION_SECONDS")
    welcome_episode_version: str = Field(default="v1", alias="WELCOME_EPISODE_VERSION")

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
        settings.session_signing_secret = _normalize_secret_value(
            _resolve_secret_reference(settings.session_signing_secret)
        ) or "dev-session-secret"
        settings.openai_embedding_api_key = _normalize_secret_value(
            _resolve_secret_reference(settings.openai_embedding_api_key)
        ) or settings.podcast_api_key
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
