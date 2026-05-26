from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from newsletter_pod.admin_metrics import (
    AdminMetricsService,
    is_admin,
    parse_admin_user_ids,
)
from newsletter_pod.main import _build_container, create_app
from newsletter_pod.user_models import (
    SubscriptionRecord,
    SwipeRecord,
    UserEpisodeRecord,
    UserRecord,
    UserRunRecord,
)


class FakeAppleVerifier:
    def __init__(self, subject: str, email: str) -> None:
        self.subject = subject
        self.email = email

    def verify(self, identity_token: str):
        return type(
            "Identity",
            (),
            {"subject": self.subject, "email": self.email},
        )()


def _build_app(*, admin_ids: str = ""):
    from newsletter_pod.config import Settings

    settings = Settings.from_env()
    settings.use_inmemory_adapters = True
    settings.apple_client_id = "com.example.newsletterpod"
    settings.session_signing_secret = "test-session-secret-32-bytes-long"
    settings.podcast_api_enabled = False
    settings.job_trigger_token = None
    settings.app_base_url = "http://testserver"
    settings.publish_summary_email_enabled = False
    settings.free_max_delivery_days = 1
    settings.pro_max_delivery_days = 3
    settings.max_max_delivery_days = 3
    settings.admin_user_ids = admin_ids
    container = _build_container(settings)
    return container, TestClient(create_app(container=container))


def _auth(client: TestClient, verifier: FakeAppleVerifier) -> tuple[str, dict[str, str]]:
    client.app.state.container.control_plane.apple_identity_verifier = verifier
    resp = client.post("/v1/auth/apple", json={"identity_token": "apple-token"})
    assert resp.status_code == 200
    token = resp.json()["session_token"]
    return token, {"Authorization": f"Bearer {token}"}


def _user_id_of(container) -> str:
    return next(iter(container.control_repository._users.values())).id


# -------- parse_admin_user_ids / is_admin --------


def test_parse_admin_user_ids_handles_empty_and_whitespace():
    assert parse_admin_user_ids(None) == set()
    assert parse_admin_user_ids("") == set()
    assert parse_admin_user_ids("   ") == set()
    assert parse_admin_user_ids("a, b ,c") == {"a", "b", "c"}
    assert parse_admin_user_ids("solo") == {"solo"}


def test_is_admin_requires_membership():
    from newsletter_pod.config import Settings

    s = Settings.from_env()
    s.admin_user_ids = "user-1,user-2"
    assert is_admin("user-1", s) is True
    assert is_admin("user-2", s) is True
    assert is_admin("user-3", s) is False
    assert is_admin(None, s) is False
    assert is_admin("", s) is False

    s.admin_user_ids = ""
    assert is_admin("user-1", s) is False, "empty allowlist closes the endpoint"


# -------- HTTP gating --------


def test_admin_metrics_requires_session_token():
    _, client = _build_app(admin_ids="anything")
    resp = client.get("/admin/metrics")
    assert resp.status_code == 401


def test_admin_metrics_forbids_authenticated_non_admin():
    container, client = _build_app(admin_ids="someone-else")
    _, headers = _auth(client, FakeAppleVerifier("not-admin", "na@example.com"))
    resp = client.get("/admin/metrics", headers=headers)
    assert resp.status_code == 403
    assert "admin" in resp.text.lower()


def test_admin_metrics_renders_html_for_admin():
    container, client = _build_app(admin_ids="placeholder")
    _, headers = _auth(client, FakeAppleVerifier("the-admin", "admin@example.com"))
    admin_id = _user_id_of(container)
    # Allowlist the actual created user id.
    container.settings.admin_user_ids = admin_id

    resp = client.get("/admin/metrics", headers=headers)
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/html")
    body = resp.text
    assert "ClawCast admin metrics" in body
    assert "Total users" in body
    # BigQuery-pending tiles render as placeholders.
    assert "vw_dau_wau_mau" in body
    assert "Requires BigQuery sink" in body
    # The auth-flow sign-in created at least one user; total should be >= 1.
    assert ">1<" in body or ">2<" in body


def test_admin_metrics_user_param_returns_timeline_html():
    container, client = _build_app(admin_ids="placeholder")
    _, headers = _auth(client, FakeAppleVerifier("admin-user", "a@example.com"))
    admin_id = _user_id_of(container)
    container.settings.admin_user_ids = admin_id

    resp = client.get(f"/admin/metrics?user_id={admin_id}", headers=headers)
    assert resp.status_code == 200
    body = resp.text
    assert admin_id in body
    assert "Recent episodes" in body
    assert "Current interest vector" in body


def test_admin_metrics_user_param_404_for_unknown_user():
    container, client = _build_app(admin_ids="placeholder")
    _, headers = _auth(client, FakeAppleVerifier("admin-user-2", "b@example.com"))
    container.settings.admin_user_ids = _user_id_of(container)

    resp = client.get("/admin/metrics?user_id=does-not-exist", headers=headers)
    assert resp.status_code == 404
    assert "User not found" in resp.text


# -------- Service-level (no HTTP) --------


def _seed_user(container, *, user_id: str, created_at: datetime, tier: str = "free",
               status: str = "active", product_id=None) -> None:
    now = created_at
    container.control_repository.save_user(UserRecord(
        id=user_id, apple_subject=f"sub-{user_id}", email=None,
        display_name=f"User {user_id}", timezone="UTC",
        created_at=now, updated_at=now,
    ))
    container.control_repository.save_subscription(SubscriptionRecord(
        user_id=user_id, tier=tier, status=status,
        product_id=product_id, updated_at=now,
    ))


def test_summary_counts_users_episodes_swipes_in_correct_windows():
    container, _ = _build_app(admin_ids="x")
    now = datetime(2026, 5, 26, 12, 0, tzinfo=timezone.utc)

    # Three users: one fresh (5d ago), one mid (15d ago), one old (45d ago).
    _seed_user(container, user_id="fresh", created_at=now - timedelta(days=5),
               tier="pro", product_id="com.newsletterpod.pro.monthly")
    _seed_user(container, user_id="mid", created_at=now - timedelta(days=15),
               tier="max", product_id="com.newsletterpod.max.annual")
    _seed_user(container, user_id="old", created_at=now - timedelta(days=45),
               tier="free")

    # Episodes: two inside 7d, one inside 30d but outside 7d, one outside 30d.
    for episode_id, days_ago in [
        ("ep-7a", 1), ("ep-7b", 4), ("ep-30", 20), ("ep-old", 45),
    ]:
        container.control_repository.save_user_episode(UserEpisodeRecord(
            id=episode_id, user_id="fresh", title=f"T {episode_id}",
            description="", published_at=now - timedelta(days=days_ago),
            audio_object_name=f"obj/{episode_id}", audio_size_bytes=1,
        ))

    # Swipes: 3 inside 7d, 2 outside.
    for swipe_id, days_ago in [
        ("sw-a", 1), ("sw-b", 3), ("sw-c", 6), ("sw-d", 9), ("sw-e", 14),
    ]:
        container.control_repository.save_swipe(SwipeRecord(
            id=swipe_id, user_id="fresh",
            source_item_dedupe_key=swipe_id, direction=1,
            title="t", link="https://example.com", source_id="s",
            source_name="S", embedding=[1.0], embedding_model="x",
            swiped_at=now - timedelta(days=days_ago),
        ))

    service = AdminMetricsService(
        repository=container.control_repository, settings=container.settings
    )
    summary = service.get_summary(now=now)

    totals = summary["totals"]
    assert totals["users"] == 3
    assert totals["new_users_7d"] == 1   # 'fresh' only
    assert totals["new_users_30d"] == 2  # 'fresh' + 'mid'
    assert totals["episodes_7d"] == 2
    assert totals["episodes_30d"] == 3
    assert totals["swipes_7d"] == 3

    tier_map = {t["tier"]: t for t in summary["tier_breakdown"]}
    assert tier_map["pro"]["count"] == 1
    assert tier_map["max"]["count"] == 1
    assert tier_map["free"]["count"] == 1


def test_user_timeline_includes_swipe_trend_and_vector_preview():
    container, _ = _build_app(admin_ids="x")
    now = datetime(2026, 5, 26, 12, 0, tzinfo=timezone.utc)
    _seed_user(container, user_id="vec-user", created_at=now - timedelta(days=10))

    # Three swipes across two ISO weeks so the bucket has >1 entry.
    # Right- and left-swipe embeddings must differ for compute_user_vector
    # to produce a non-zero centroid (a zero vector normalizes to None).
    right_emb = [1.0, 0.0, 0.5, 0.25, 0.1, 0.9, 0.3, 0.7, 0.0]
    left_emb = [0.0, 1.0, 0.0, 0.5, 0.0, 0.1, 0.7, 0.3, 0.9]
    for swipe_id, days_ago, direction, embedding in [
        ("v-1", 1, 1, right_emb),
        ("v-2", 2, 1, right_emb),
        ("v-3", 9, -1, left_emb),
    ]:
        container.control_repository.save_swipe(SwipeRecord(
            id=swipe_id, user_id="vec-user",
            source_item_dedupe_key=swipe_id, direction=direction,
            title="t", link="https://example.com", source_id="s",
            source_name="S", embedding=embedding,
            embedding_model="x", swiped_at=now - timedelta(days=days_ago),
        ))

    container.control_repository.save_user_run(UserRunRecord(
        id="run-1", user_id="vec-user",
        local_run_date=(now - timedelta(days=1)).date(),
        started_at=now - timedelta(days=1),
        completed_at=now - timedelta(days=1),
        status="published",
        message="ok",
        candidate_count=10, processed_item_count=5, dropped_item_count=2,
        cap_hit=False,
    ))

    service = AdminMetricsService(
        repository=container.control_repository, settings=container.settings
    )
    timeline = service.get_user_timeline("vec-user")
    assert timeline is not None
    assert timeline["user"]["id"] == "vec-user"
    assert timeline["interest"]["total_swipes"] == 3
    assert timeline["interest"]["vector_dim"] == 9
    assert len(timeline["interest"]["vector_preview"]) == 8
    # Trend buckets each swipe into its ISO week. With `now = 2026-05-26`
    # (a Tuesday in W22), day-1 lands in W22, day-2 (Sunday) in W21, and
    # day-9 (Sunday) in W20 — three distinct weeks.
    weekly = timeline["interest"]["swipes_per_iso_week"]
    assert sum(row["swipes"] for row in weekly) == 3
    assert {row["iso_week"] for row in weekly} == {"2026-W20", "2026-W21", "2026-W22"}
    assert len(timeline["runs"]) == 1
    assert timeline["runs"][0]["status"] == "published"


def test_user_timeline_returns_none_for_unknown_user():
    container, _ = _build_app(admin_ids="x")
    service = AdminMetricsService(
        repository=container.control_repository, settings=container.settings
    )
    assert service.get_user_timeline("ghost-user") is None
