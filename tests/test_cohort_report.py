from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

from fastapi.testclient import TestClient

from newsletter_pod.churn_risk import ChurnRiskScoringService
from newsletter_pod.cohort_report import (
    CohortReportService,
    JOB_STATE_NAME,
    _last_iso_week_bounds,
)
from newsletter_pod.config import Settings
from newsletter_pod.main import _build_container, create_app
from newsletter_pod.user_models import (
    DeliveryScheduleRecord,
    SubscriptionRecord,
    UserEpisodeRecord,
    UserRecord,
)


class _RecordingMailer:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str, list[str] | None]] = []

    def send(self, subject, body, *, recipients=None) -> None:
        self.sent.append((subject, body, recipients))


def _build():
    s = Settings.from_env()
    s.use_inmemory_adapters = True
    s.apple_client_id = "com.example.newsletterpod"
    s.session_signing_secret = "test-session-secret-32-bytes-long"
    s.podcast_api_enabled = False
    s.job_trigger_token = "test-trigger-token"
    s.app_base_url = "http://testserver"
    s.publish_summary_email_enabled = False
    s.alert_email_enabled = False
    s.feedback_digest_email_enabled = False
    s.alert_email_to = "alerts@example.com"
    s.feedback_digest_extra_recipients = "extra@example.com"
    s.cohort_report_email_enabled = True
    container = _build_container(s)
    return container, TestClient(create_app(container=container))


def _seed_user(
    container, user_id: str,
    *,
    created_at: datetime,
    tier: str = "free",
    status: str = "active",
    has_episode: bool = False,
) -> None:
    container.control_repository.save_user(UserRecord(
        id=user_id, apple_subject=f"sub-{user_id}",
        display_name=user_id, timezone="UTC",
        created_at=created_at, updated_at=created_at,
    ))
    container.control_repository.save_subscription(SubscriptionRecord(
        user_id=user_id, tier=tier, status=status,
        updated_at=created_at,
    ))
    container.control_repository.save_schedule(DeliveryScheduleRecord(
        user_id=user_id, timezone="UTC",
        weekdays=["monday"], local_time="07:00", cutoff_time="11:00",
        enabled=True, created_at=created_at, updated_at=created_at,
    ))
    if has_episode:
        container.control_repository.save_user_episode(UserEpisodeRecord(
            id=f"ep-{user_id}", user_id=user_id, title="t",
            description="", published_at=created_at + timedelta(days=1),
            audio_object_name=f"obj/{user_id}", audio_size_bytes=1,
        ))


# -------- ISO week helper --------


def test_last_iso_week_bounds_from_monday():
    # Monday 2026-05-25 → just-ended week is Mon 2026-05-18..Sun 2026-05-24.
    monday = date(2026, 5, 25)
    start, end = _last_iso_week_bounds(monday)
    assert start == date(2026, 5, 18)
    assert end == date(2026, 5, 24)
    assert (end - start).days == 6


def test_last_iso_week_bounds_from_midweek():
    # Wednesday 2026-05-27 → just-ended week is still Mon 2026-05-18..Sun 2026-05-24.
    wednesday = date(2026, 5, 27)
    start, end = _last_iso_week_bounds(wednesday)
    assert start == date(2026, 5, 18)
    assert end == date(2026, 5, 24)


# -------- Service-level cohort math --------


def test_no_signups_last_week_still_sends_email():
    container, _ = _build()
    mailer = _RecordingMailer()
    now = datetime(2026, 5, 25, 7, 0, tzinfo=timezone.utc)  # Monday
    svc = CohortReportService(
        repository=container.control_repository,
        mailer=mailer, settings=container.settings,
    )
    result = svc.send_weekly_cohort_report(now=now)
    assert result["status"] == "sent"
    assert result["cohort_size"] == 0
    assert len(mailer.sent) == 1
    subject, body, _ = mailer.sent[0]
    assert "no signups" in subject.lower()
    assert "n/a (no signups)" in body


def test_cohort_with_signups_activation_and_paid_conversion():
    container, _ = _build()
    mailer = _RecordingMailer()
    now = datetime(2026, 5, 25, 7, 0, tzinfo=timezone.utc)
    last_monday = datetime(2026, 5, 18, 12, 0, tzinfo=timezone.utc)

    # Three signups inside last week's window.
    _seed_user(container, "a", created_at=last_monday, has_episode=True)
    _seed_user(container, "b", created_at=last_monday + timedelta(days=2),
               tier="pro", has_episode=True)
    _seed_user(container, "c", created_at=last_monday + timedelta(days=4),
               has_episode=False)
    # One outside the window (signed up two weeks ago).
    _seed_user(container, "old", created_at=last_monday - timedelta(days=10))

    svc = CohortReportService(
        repository=container.control_repository,
        mailer=mailer, settings=container.settings,
    )
    result = svc.send_weekly_cohort_report(now=now)
    assert result["cohort_size"] == 3
    assert result["activated"] == 2          # a + b
    assert result["paid_converted"] == 1     # b only
    assert result["status"] == "sent"

    subject, body, recipients = mailer.sent[0]
    assert "3 signups" in subject
    assert "67%" in body  # activation 2/3
    assert "33%" in body  # paid 1/3
    assert "alerts@example.com" in recipients
    assert "extra@example.com" in recipients


def test_includes_top_three_churn_risk_users_when_scored():
    container, _ = _build()
    mailer = _RecordingMailer()
    now = datetime(2026, 5, 25, 7, 0, tzinfo=timezone.utc)
    last_monday = datetime(2026, 5, 18, 12, 0, tzinfo=timezone.utc)

    # Five paid users created long enough ago to be scored.
    long_ago = now - timedelta(days=60)
    for letter in "abcde":
        _seed_user(container, f"paid-{letter}", created_at=long_ago,
                   tier="pro", status="active")
        # No episodes / swipes → all five will score above threshold.

    # Run churn scoring to populate ChurnRiskRecord.
    scorer = ChurnRiskScoringService(
        repository=container.control_repository, settings=container.settings,
    )
    scorer.score_all_active_paid_users(now=now)
    assert len(container.control_repository.list_churn_risks(at_risk_only=True)) == 5

    # One signup last week so the cohort isn't empty.
    _seed_user(container, "newbie", created_at=last_monday)

    svc = CohortReportService(
        repository=container.control_repository,
        mailer=mailer, settings=container.settings,
    )
    result = svc.send_weekly_cohort_report(now=now)
    assert len(result["churn_top3_user_ids"]) == 3, (
        "only top 3 risk users land in the email"
    )
    subject, body, _ = mailer.sent[0]
    for uid in result["churn_top3_user_ids"]:
        assert uid in body


def test_no_churn_records_renders_graceful_placeholder():
    container, _ = _build()
    mailer = _RecordingMailer()
    now = datetime(2026, 5, 25, 7, 0, tzinfo=timezone.utc)

    svc = CohortReportService(
        repository=container.control_repository,
        mailer=mailer, settings=container.settings,
    )
    result = svc.send_weekly_cohort_report(now=now)
    _, body, _ = mailer.sent[0]
    assert "no at-risk users" in body.lower()
    # Doesn't error and still sends.
    assert result["status"] == "sent"


def test_disabled_short_circuits():
    container, _ = _build()
    container.settings.cohort_report_email_enabled = False
    mailer = _RecordingMailer()
    svc = CohortReportService(
        repository=container.control_repository,
        mailer=mailer, settings=container.settings,
    )
    result = svc.send_weekly_cohort_report()
    assert result == {"status": "disabled"}
    assert mailer.sent == []


def test_no_recipients_returns_status_without_sending():
    container, _ = _build()
    container.settings.alert_email_to = None
    container.settings.feedback_digest_extra_recipients = ""
    mailer = _RecordingMailer()
    svc = CohortReportService(
        repository=container.control_repository,
        mailer=mailer, settings=container.settings,
    )
    result = svc.send_weekly_cohort_report()
    assert result["status"] == "no_recipients"
    assert mailer.sent == []


def test_idempotency_repeat_run_updates_job_state_cursor():
    container, _ = _build()
    mailer = _RecordingMailer()
    svc = CohortReportService(
        repository=container.control_repository,
        mailer=mailer, settings=container.settings,
    )
    first_now = datetime(2026, 5, 25, 7, 0, tzinfo=timezone.utc)
    svc.send_weekly_cohort_report(now=first_now)
    first_state = container.control_repository.get_job_state(JOB_STATE_NAME)
    assert first_state == first_now

    # Re-run a few hours later (simulating a retry); state must advance,
    # mailer should fire again (no per-day dedupe — Cloud Scheduler
    # retries are infrequent enough that we tolerate the duplicate).
    second_now = first_now + timedelta(hours=2)
    svc.send_weekly_cohort_report(now=second_now)
    second_state = container.control_repository.get_job_state(JOB_STATE_NAME)
    assert second_state == second_now
    assert len(mailer.sent) == 2


# -------- HTTP endpoint --------


def test_cohort_endpoint_requires_job_token():
    _, client = _build()
    resp = client.post("/jobs/weekly-cohort-report")
    assert resp.status_code == 401


def test_cohort_endpoint_returns_200_with_job_token():
    container, client = _build()
    resp = client.post(
        "/jobs/weekly-cohort-report",
        headers={"X-Job-Trigger-Token": container.settings.job_trigger_token},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] in {"sent", "no_recipients", "disabled"}
