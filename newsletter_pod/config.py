from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import yaml
from google.cloud import secretmanager
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

from .models import PodcastUxConfig, SourceDefinition


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

    feed_token: str = Field(default="change-me", alias="FEED_TOKEN")
    sources_file: str = Field(default="sources.yml", alias="SOURCES_FILE")

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
    podcast_tts_model: str = Field(default="gpt-4o-mini-tts", alias="PODCAST_TTS_MODEL")
    podcast_tts_voice: str = Field(default="alloy", alias="PODCAST_TTS_VOICE")
    podcast_tts_instructions: Optional[str] = Field(default=None, alias="PODCAST_TTS_INSTRUCTIONS")
    podcast_host_primary_name: str = Field(default="Elena", alias="PODCAST_HOST_PRIMARY_NAME")
    podcast_host_secondary_name: str = Field(default="Marcus", alias="PODCAST_HOST_SECONDARY_NAME")
    podcast_format: str = Field(default="anchor_guest", alias="PODCAST_FORMAT")
    podcast_tone: str = Field(default="calm_analyst", alias="PODCAST_TONE")
    podcast_target_minutes: int = Field(default=6, alias="PODCAST_TARGET_MINUTES")
    podcast_max_minutes: int = Field(default=8, alias="PODCAST_MAX_MINUTES")
    podcast_thin_day_minutes: int = Field(default=2, alias="PODCAST_THIN_DAY_MINUTES")
    podcast_bootstrap_max_items_per_source: int = Field(default=3, alias="PODCAST_BOOTSTRAP_MAX_ITEMS_PER_SOURCE")

    gcs_bucket_name: Optional[str] = Field(default=None, alias="GCS_BUCKET_NAME")
    gcs_prefix: str = Field(default="episodes", alias="GCS_PREFIX")

    firestore_collection_prefix: str = Field(default="newsletter_pod", alias="FIRESTORE_COLLECTION_PREFIX")

    alert_email_enabled: bool = Field(default=False, alias="ALERT_EMAIL_ENABLED")
    alert_email_from: Optional[str] = Field(default=None, alias="ALERT_EMAIL_FROM")
    alert_email_to: Optional[str] = Field(default=None, alias="ALERT_EMAIL_TO")
    publish_summary_email_enabled: bool = Field(default=False, alias="PUBLISH_SUMMARY_EMAIL_ENABLED")
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

    free_max_sources: int = Field(default=5, alias="FREE_MAX_SOURCES")
    paid_max_sources: int = Field(default=15, alias="PAID_MAX_SOURCES")
    free_max_delivery_days: int = Field(default=7, alias="FREE_MAX_DELIVERY_DAYS")
    paid_max_delivery_days: int = Field(default=7, alias="PAID_MAX_DELIVERY_DAYS")
    free_min_duration_minutes: int = Field(default=3, alias="FREE_MIN_DURATION_MINUTES")
    free_max_duration_minutes: int = Field(default=8, alias="FREE_MAX_DURATION_MINUTES")
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

    @classmethod
    def from_env(cls) -> "Settings":
        settings = cls()
        settings.feed_token = _normalize_secret_value(_resolve_secret_reference(settings.feed_token))
        settings.podcast_api_key = _normalize_secret_value(_resolve_secret_reference(settings.podcast_api_key))
        settings.smtp_password = _normalize_secret_value(_resolve_secret_reference(settings.smtp_password))
        settings.job_trigger_token = _normalize_secret_value(_resolve_secret_reference(settings.job_trigger_token))
        settings.session_signing_secret = _normalize_secret_value(
            _resolve_secret_reference(settings.session_signing_secret)
        ) or "dev-session-secret"
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
