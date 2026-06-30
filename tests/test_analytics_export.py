from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from newsletter_pod.analytics_export import (
    ACQUISITION_TABLE,
    DEVICE_TOKENS_TABLE,
    SUBSCRIPTIONS_TABLE,
    build_acquisition_rows,
    build_device_token_rows,
    build_subscription_rows,
    run_export,
)
from newsletter_pod.config import Settings
from newsletter_pod.main import _build_container, create_app
from newsletter_pod.user_models import DeviceTokenRecord, SubscriptionRecord, UserRecord
from newsletter_pod.user_repository import InMemoryControlPlaneRepository

NOW = datetime(2026, 6, 14, 12, 0, tzinfo=timezone.utc)
EARLIER = datetime(2026, 6, 10, 8, 0, tzinfo=timezone.utc)


def _repo_with_data() -> InMemoryControlPlaneRepository:
    repo = InMemoryControlPlaneRepository()
    repo.save_subscription(
        SubscriptionRecord(
            user_id="u1", tier="pro", status="active",
            product_id="com.newsletterpod.pro.monthly", updated_at=NOW,
        )
    )
    repo.save_subscription(
        SubscriptionRecord(user_id="u2", tier="free", status="active", updated_at=NOW)
    )
    # u1: two tokens, android newer than ios -> newest is android.
    repo.save_device_token(
        DeviceTokenRecord(
            id="u1::ios", user_id="u1", token="t-ios", platform="ios",
            bundle_id="b", created_at=EARLIER, last_seen_at=EARLIER,
        )
    )
    repo.save_device_token(
        DeviceTokenRecord(
            id="u1::android", user_id="u1", token="t-and", platform="android",
            bundle_id="b", created_at=NOW, last_seen_at=NOW,
        )
    )
    repo.save_device_token(
        DeviceTokenRecord(
            id="u2::ios", user_id="u2", token="t2", platform="ios",
            bundle_id="b", created_at=NOW, last_seen_at=NOW,
        )
    )
    # Invalidated token must be excluded everywhere.
    repo.save_device_token(
        DeviceTokenRecord(
            id="u3::old", user_id="u3", token="t3", platform="ios",
            bundle_id="b", created_at=NOW, last_seen_at=NOW, invalidated_at=NOW,
        )
    )
    return repo


def test_build_subscription_rows():
    rows = build_subscription_rows(_repo_with_data())
    by_user = {r["user_id"]: r for r in rows}
    assert set(by_user) == {"u1", "u2"}
    assert by_user["u1"]["tier"] == "pro"
    assert by_user["u1"]["product_id"] == "com.newsletterpod.pro.monthly"
    # datetimes serialize to RFC3339 strings for the TIMESTAMP column.
    assert by_user["u1"]["updated_at"] == "2026-06-14T12:00:00+00:00"
    # Absent optional fields stay None (not missing), so the JSON load is clean.
    assert by_user["u2"]["product_id"] is None
    assert by_user["u2"]["started_at"] is None


def test_build_device_token_rows_excludes_invalidated():
    rows = build_device_token_rows(_repo_with_data())
    # u3's only token is invalidated -> dropped. u1 has two active tokens.
    assert len(rows) == 3
    assert "u3" not in {r["user_id"] for r in rows}
    u1 = [r for r in rows if r["user_id"] == "u1"]
    assert {r["platform"] for r in u1} == {"ios", "android"}


def test_list_all_active_device_tokens_excludes_invalidated():
    toks = _repo_with_data().list_all_active_device_tokens()
    assert {t.user_id for t in toks} == {"u1", "u2"}


def test_build_acquisition_rows():
    repo = InMemoryControlPlaneRepository()
    repo.save_user(
        UserRecord(
            id="u1", created_at=EARLIER, updated_at=NOW,
            acquisition_source="reddit", acquisition_recorded_at=NOW,
        )
    )
    # Unanswered user: source stays NULL so the breakdown can report response rate.
    repo.save_user(UserRecord(id="u2", created_at=NOW, updated_at=NOW))
    rows = build_acquisition_rows(repo)
    by_user = {r["user_id"]: r for r in rows}
    assert set(by_user) == {"u1", "u2"}
    assert by_user["u1"]["acquisition_source"] == "reddit"
    assert by_user["u1"]["acquisition_recorded_at"] == "2026-06-14T12:00:00+00:00"
    assert by_user["u1"]["created_at"] == "2026-06-10T08:00:00+00:00"
    assert by_user["u2"]["acquisition_source"] is None
    assert by_user["u2"]["acquisition_recorded_at"] is None


def test_run_export_calls_writer_per_table_and_counts():
    repo = _repo_with_data()
    captured: dict[str, tuple] = {}

    class FakeWriter:
        def replace_table(self, table, schema, rows):
            captured[table] = (schema, rows)

    counts = run_export(repo, FakeWriter())
    # _repo_with_data seeds subscriptions/tokens but no user records, so the
    # acquisition snapshot is present-but-empty.
    assert counts == {
        SUBSCRIPTIONS_TABLE: 2,
        DEVICE_TOKENS_TABLE: 3,
        ACQUISITION_TABLE: 0,
    }
    assert set(captured) == {
        SUBSCRIPTIONS_TABLE,
        DEVICE_TOKENS_TABLE,
        ACQUISITION_TABLE,
    }
    # Schema is threaded through so an empty snapshot still types the table.
    assert ("user_id", "STRING") in captured[SUBSCRIPTIONS_TABLE][0]
    assert ("last_seen_at", "TIMESTAMP") in captured[DEVICE_TOKENS_TABLE][0]
    assert ("acquisition_source", "STRING") in captured[ACQUISITION_TABLE][0]


def test_run_export_empty_repo_still_writes_all_tables():
    captured = []

    class FakeWriter:
        def replace_table(self, table, schema, rows):
            captured.append((table, rows))

    counts = run_export(InMemoryControlPlaneRepository(), FakeWriter())
    assert counts == {
        SUBSCRIPTIONS_TABLE: 0,
        DEVICE_TOKENS_TABLE: 0,
        ACQUISITION_TABLE: 0,
    }
    # Every table is replaced (emptied), not skipped.
    assert {t for t, _ in captured} == {
        SUBSCRIPTIONS_TABLE,
        DEVICE_TOKENS_TABLE,
        ACQUISITION_TABLE,
    }
    assert all(rows == [] for _, rows in captured)


def _build_app(*, export_enabled: bool) -> TestClient:
    settings = Settings.from_env()
    settings.use_inmemory_adapters = True
    settings.job_trigger_token = None
    # Keep _build_container happy regardless of the local .env (mailer wiring
    # asserts SMTP config when any email path is on).
    settings.alert_email_enabled = False
    settings.publish_summary_email_enabled = False
    settings.feedback_digest_email_enabled = False
    settings.analytics_export_enabled = export_enabled
    return TestClient(create_app(container=_build_container(settings)))


def test_export_endpoint_skips_when_disabled():
    """Default-off: the endpoint is wired and safe to schedule before BigQuery
    config exists — it must not touch BigQuery."""
    client = _build_app(export_enabled=False)
    resp = client.post("/jobs/export-analytics-snapshot")
    assert resp.status_code == 200
    assert resp.json() == {"skipped": "analytics_export_disabled"}
