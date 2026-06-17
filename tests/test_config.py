from __future__ import annotations

from newsletter_pod.config import Settings


def test_default_tier_caps_align_with_paywall_copy(monkeypatch):
    # Drop any env that would mask the in-code defaults.
    for key in [
        "MAX_SOURCES_SAFETY_CAP",
        "FREE_MAX_DELIVERY_DAYS",
        "PRO_MAX_DELIVERY_DAYS",
        "MAX_MAX_DELIVERY_DAYS",
        "FREE_MIN_DURATION_MINUTES",
        "FREE_MAX_DURATION_MINUTES",
        "PRO_MIN_DURATION_MINUTES",
        "PRO_MAX_DURATION_MINUTES",
        "MAX_MIN_DURATION_MINUTES",
        "MAX_MAX_DURATION_MINUTES",
        "TRIAL_PREMIUM_PODS_TOTAL",
        "PRO_PREMIUM_PODS_PER_WEEK",
        "PRO_DEFAULT_PODS_PER_WEEK",
        "MAX_PREMIUM_PODS_PER_WEEK",
        "FREE_FIRST_MONTH_PREMIUM_PODS_PER_WEEK",
        "FREE_POST_MONTH_DEFAULT_PODS_PER_WEEK",
    ]:
        monkeypatch.delenv(key, raising=False)
    settings = Settings()
    assert settings.max_sources_safety_cap == 100
    # Launch tier model (2026-05-16): all tiers deliver 7 days; episode length
    # is uniform 3-7 min across tiers (default 5) — differentiation is voice
    # tier, not duration or cadence. (Max raised 5->7, default 3->5 on 2026-06-17.)
    assert settings.free_max_delivery_days == 7
    assert settings.pro_max_delivery_days == 7
    assert settings.max_max_delivery_days == 7
    assert settings.free_min_duration_minutes == 3
    assert settings.free_max_duration_minutes == 7
    assert settings.free_default_duration_minutes == 5
    assert settings.pro_min_duration_minutes == 3
    assert settings.pro_max_duration_minutes == 7
    assert settings.max_min_duration_minutes == 3
    assert settings.max_max_duration_minutes == 7
    # Per-week premium/default voice budgets per tier.
    assert settings.trial_premium_pods_total == 5
    assert settings.pro_premium_pods_per_week == 3
    assert settings.pro_default_pods_per_week == 4
    assert settings.max_premium_pods_per_week == 7
    assert settings.free_first_month_premium_pods_per_week == 1
    assert settings.free_post_month_default_pods_per_week == 1


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
