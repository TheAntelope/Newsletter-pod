from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from newsletter_pod import events as events_module
from newsletter_pod.churn_risk import ChurnRiskScoringService
from newsletter_pod.config import Settings
from newsletter_pod.main import _build_container, create_app
from newsletter_pod.user_models import (
    DeliveryScheduleRecord,
    FeedbackRecord,
    SubscriptionRecord,
    SwipeRecord,
    UserEpisodeRecord,
    UserRecord,
)


def _build():
    s = Settings.from_env()
    s.use_inmemory_adapters = True
    s.apple_client_id = "com.example.newsletterpod"
    s.session_signing_secret = "test-session-secret-32-bytes-long"
    s.podcast_api_enabled = False
    s.job_trigger_token = "test-trigger-token"
    s.app_base_url = "http://testserver"
    s.publish_summary_email_enabled = False
    s.feedback_digest_email_enabled = False
    s.alert_email_enabled = False
    s.free_max_delivery_days = 7
    s.pro_max_delivery_days = 7
    s.max_max_delivery_days = 7
    s.churn_risk_threshold = 0.6
    container = _build_container(s)
    return container, TestClient(create_app(container=container))


def _now() -> datetime:
    return datetime(2026, 5, 26, 12, 0, tzinfo=timezone.utc)


def _seed(
    container,
    user_id: str,
    *,
    tier: str = "pro",
    status: str = "active",
    created_days_ago: int = 60,
    last_episode_days_ago: int | None = None,
    swipes_14d: int = 0,
    schedule_weekdays: list[str] | None = None,
    negative_feedback_30d: int = 0,
    now: datetime | None = None,
) -> None:
    now = now or _now()
    container.control_repository.save_user(UserRecord(
        id=user_id, apple_subject=f"sub-{user_id}",
        display_name=user_id, timezone="UTC",
        created_at=now - timedelta(days=created_days_ago),
        updated_at=now - timedelta(days=created_days_ago),
    ))
    container.control_repository.save_subscription(SubscriptionRecord(
        user_id=user_id, tier=tier, status=status,
        product_id="com.newsletterpod.pro.monthly" if tier == "pro" else None,
        updated_at=now,
    ))
    if schedule_weekdays is None:
        schedule_weekdays = [
            "monday", "tuesday", "wednesday", "thursday",
            "friday", "saturday", "sunday",
        ]
    container.control_repository.save_schedule(DeliveryScheduleRecord(
        user_id=user_id, timezone="UTC",
        weekdays=schedule_weekdays, local_time="07:00",
        cutoff_time="11:00", enabled=True,
        created_at=now, updated_at=now,
    ))
    if last_episode_days_ago is not None:
        container.control_repository.save_user_episode(UserEpisodeRecord(
            id=f"ep-{user_id}", user_id=user_id, title="t",
            description="", published_at=now - timedelta(days=last_episode_days_ago),
            audio_object_name=f"obj/{user_id}", audio_size_bytes=1,
        ))
    for i in range(swipes_14d):
        container.control_repository.save_swipe(SwipeRecord(
            id=f"sw-{user_id}-{i}", user_id=user_id,
            source_item_dedupe_key=f"k-{i}", direction=1,
            title="t", link="https://example.com", source_id="s",
            source_name="S", embedding=[1.0], embedding_model="x",
            swiped_at=now - timedelta(days=1, hours=i),
        ))
    for i in range(negative_feedback_30d):
        container.control_repository.save_feedback(FeedbackRecord(
            id=f"fb-{user_id}-{i}", user_id=user_id,
            raw_text="this app is terrible and boring",
            english_text="this app is terrible and boring",
            source="text",
            created_at=now - timedelta(days=5 + i),
        ))


def test_score_recently_active_user_below_threshold():
    container, _ = _build()
    _seed(
        container, "happy",
        last_episode_days_ago=0,
        swipes_14d=14,
        schedule_weekdays=None,            # 7-day schedule (full)
        negative_feedback_30d=0,
    )
    svc = ChurnRiskScoringService(
        repository=container.control_repository, settings=container.settings,
    )
    result = svc.score_all_active_paid_users(now=_now())
    assert result["scored"] == 1
    assert result["at_risk"] == 0

    record = container.control_repository.get_churn_risk("happy")
    assert record is not None
    assert record.at_risk is False
    assert record.score < 0.3, f"expected low risk, got {record.score}"


def test_score_classic_at_risk_pattern_above_threshold():
    container, _ = _build()
    _seed(
        container, "atrisk",
        last_episode_days_ago=14,          # max recency risk
        swipes_14d=0,                       # max swipe risk
        schedule_weekdays=["monday"],      # 1 of 7 days = high schedule risk
        negative_feedback_30d=3,            # max feedback risk
    )
    svc = ChurnRiskScoringService(
        repository=container.control_repository, settings=container.settings,
    )
    result = svc.score_all_active_paid_users(now=_now())
    assert result["at_risk"] == 1

    record = container.control_repository.get_churn_risk("atrisk")
    assert record is not None
    assert record.at_risk is True
    assert record.score > 0.6, f"expected at-risk, got {record.score}"
    # Signal values must be persisted alongside the score so the admin
    # page / cohort report can render them without re-deriving.
    assert record.signals["days_since_last_episode"] >= 14
    assert record.signals["swipes_14d"] == 0
    assert record.signals["feedback_negative_30d"] == 3


def test_no_signal_user_scores_below_threshold():
    """Healthy paid user with no negative signals — exactly mid-range
    schedule, recent activity. Score should be safely below 0.6 even
    though we have data."""
    container, _ = _build()
    _seed(
        container, "ok",
        last_episode_days_ago=2,
        swipes_14d=5,
        schedule_weekdays=["monday", "wednesday", "friday", "sunday"],
        negative_feedback_30d=0,
    )
    svc = ChurnRiskScoringService(
        repository=container.control_repository, settings=container.settings,
    )
    svc.score_all_active_paid_users(now=_now())
    record = container.control_repository.get_churn_risk("ok")
    assert record is not None
    assert record.at_risk is False


def test_skip_users_within_new_user_grace_window():
    container, _ = _build()
    # Created 5 days ago — inside the 14-day grace window.
    _seed(
        container, "fresh",
        created_days_ago=5,
        last_episode_days_ago=None,   # never delivered
        swipes_14d=0,
    )
    svc = ChurnRiskScoringService(
        repository=container.control_repository, settings=container.settings,
    )
    result = svc.score_all_active_paid_users(now=_now())
    assert result["skipped_new_users"] == 1
    assert result["scored"] == 0
    assert container.control_repository.get_churn_risk("fresh") is None


def test_free_users_are_not_scored():
    container, _ = _build()
    _seed(container, "freeloader", tier="free", last_episode_days_ago=30)
    svc = ChurnRiskScoringService(
        repository=container.control_repository, settings=container.settings,
    )
    result = svc.score_all_active_paid_users(now=_now())
    assert result["scored"] == 0
    assert container.control_repository.get_churn_risk("freeloader") is None


def test_idempotency_re_run_overwrites_record():
    container, _ = _build()
    _seed(container, "atrisk", last_episode_days_ago=14, swipes_14d=0,
          schedule_weekdays=["monday"], negative_feedback_30d=3)
    svc = ChurnRiskScoringService(
        repository=container.control_repository, settings=container.settings,
    )
    first = svc.score_all_active_paid_users(now=_now())
    record_first = container.control_repository.get_churn_risk("atrisk")
    assert record_first is not None

    # Same inputs, second run.
    second = svc.score_all_active_paid_users(
        now=_now() + timedelta(hours=2),
    )
    record_second = container.control_repository.get_churn_risk("atrisk")
    assert record_second is not None

    assert first["scored"] == second["scored"]
    assert first["at_risk"] == second["at_risk"]
    # Score is deterministic from the underlying state.
    assert record_first.score == record_second.score
    # But scored_at advances — proves it's an overwrite, not a stale read.
    assert record_second.scored_at > record_first.scored_at
    # And there's still exactly one record per user (not two).
    assert len(container.control_repository.list_churn_risks()) == 1


def test_at_risk_user_emits_churn_event(caplog):
    container, _ = _build()
    _seed(container, "atrisk", last_episode_days_ago=14, swipes_14d=0,
          schedule_weekdays=["monday"], negative_feedback_30d=3)
    _seed(container, "happy", last_episode_days_ago=0, swipes_14d=14,
          schedule_weekdays=None)

    caplog.set_level(logging.INFO, logger=events_module.__name__)
    svc = ChurnRiskScoringService(
        repository=container.control_repository, settings=container.settings,
    )
    svc.score_all_active_paid_users(now=_now())

    import json
    events = []
    for record in caplog.records:
        if record.name != events_module.__name__:
            continue
        try:
            payload = json.loads(record.getMessage())
        except (ValueError, TypeError):
            continue
        if payload.get("event_name") == "churn_risk_scored":
            events.append(payload)
    assert len(events) == 1, "only at-risk users emit CHURN_RISK_SCORED"
    assert events[0]["user_id"] == "atrisk"
    assert events[0]["properties"]["score"] >= 0.6


def test_score_endpoint_requires_job_token():
    container, client = _build()
    resp = client.post("/jobs/score-churn-risk")
    assert resp.status_code == 401

    resp = client.post(
        "/jobs/score-churn-risk",
        headers={"X-Job-Trigger-Token": "wrong"},
    )
    assert resp.status_code == 401


def test_score_endpoint_returns_summary_with_job_token():
    container, client = _build()
    _seed(container, "atrisk", last_episode_days_ago=14, swipes_14d=0,
          schedule_weekdays=["monday"])
    resp = client.post(
        "/jobs/score-churn-risk",
        headers={"X-Job-Trigger-Token": container.settings.job_trigger_token},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert body["scored"] >= 1
    assert "at_risk" in body
    assert "threshold" in body
