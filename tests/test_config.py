from __future__ import annotations

from newsletter_pod.config import Settings


def test_default_tier_caps_align_with_paywall_copy(monkeypatch):
    # Drop any env that would mask the in-code defaults.
    for key in [
        "FREE_MAX_SOURCES",
        "PAID_MAX_SOURCES",
        "FREE_MAX_DELIVERY_DAYS",
        "PAID_MAX_DELIVERY_DAYS",
        "FREE_MIN_DURATION_MINUTES",
        "FREE_MAX_DURATION_MINUTES",
        "PAID_MIN_DURATION_MINUTES",
        "PAID_MAX_DURATION_MINUTES",
    ]:
        monkeypatch.delenv(key, raising=False)
    settings = Settings()
    assert settings.free_max_sources == 5
    assert settings.paid_max_sources == 15
    assert settings.free_max_delivery_days == 5
    assert settings.paid_max_delivery_days == 7
    assert settings.free_min_duration_minutes == 3
    assert settings.free_max_duration_minutes == 5
    assert settings.paid_min_duration_minutes == 5
    assert settings.paid_max_duration_minutes == 20


def test_from_env_strips_trailing_newlines_from_secret_backed_values(monkeypatch):
    monkeypatch.setenv("JOB_TRIGGER_TOKEN", "job-token\r\n")
    monkeypatch.setenv("PODCAST_API_KEY", "podcast-key\r\n")
    monkeypatch.setenv("SMTP_PASSWORD", "smtp-password\r\n")
    monkeypatch.setenv("ELEVENLABS_API_KEY", "el-key\r\n")

    settings = Settings.from_env()

    assert settings.job_trigger_token == "job-token"
    assert settings.podcast_api_key == "podcast-key"
    assert settings.smtp_password == "smtp-password"
    assert settings.elevenlabs_api_key == "el-key"
