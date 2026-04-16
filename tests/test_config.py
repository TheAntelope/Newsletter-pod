from __future__ import annotations

from newsletter_pod.config import Settings


def test_from_env_strips_trailing_newlines_from_secret_backed_values(monkeypatch):
    monkeypatch.setenv("FEED_TOKEN", "feed-token\r\n")
    monkeypatch.setenv("JOB_TRIGGER_TOKEN", "job-token\r\n")
    monkeypatch.setenv("PODCAST_API_KEY", "podcast-key\r\n")
    monkeypatch.setenv("SMTP_PASSWORD", "smtp-password\r\n")

    settings = Settings.from_env()

    assert settings.feed_token == "feed-token"
    assert settings.job_trigger_token == "job-token"
    assert settings.podcast_api_key == "podcast-key"
    assert settings.smtp_password == "smtp-password"
