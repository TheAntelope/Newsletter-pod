"""Tests for promo-code redemption (1-year-free style codes).

Covers the happy path (grant → Max via the trial lever), the cap, once-per-user
idempotency, expiry/inactive, the already-subscribed guard, the
never-shrink-an-existing-window rule, and auth.
"""
from __future__ import annotations

from datetime import timedelta

from fastapi.testclient import TestClient

from newsletter_pod.main import _build_container, create_app
from newsletter_pod.user_models import PromoCodeRecord, SubscriptionRecord
from newsletter_pod.utils import utc_now

from tests.test_control_plane_api import FakeAppleVerifier, _auth_headers


def _build_app():
    from newsletter_pod.config import Settings

    settings = Settings.from_env()
    settings.use_inmemory_adapters = True
    settings.apple_client_id = "com.example.newsletterpod"
    settings.session_signing_secret = "test-session-secret-32-bytes-long"
    settings.podcast_api_enabled = False
    settings.job_trigger_token = None
    settings.app_base_url = "http://testserver"
    settings.publish_summary_email_enabled = False
    container = _build_container(settings)
    return container, TestClient(create_app(container=container))


def _seed_code(container, **overrides) -> PromoCodeRecord:
    now = utc_now()
    fields = dict(
        code="CLAWCAST1YR",
        grant_days=365,
        max_redemptions=500,
        active=True,
        created_at=now,
        updated_at=now,
    )
    fields.update(overrides)
    record = PromoCodeRecord(**fields)
    container.control_repository.save_promo_code(record)
    return record


def _signin(client, subject: str):
    _, headers = _auth_headers(client, FakeAppleVerifier(subject, f"{subject}@example.com"))
    user_id = client.get("/v1/me", headers=headers).json()["user"]["id"]
    return headers, user_id


# ---------- happy path ----------


def test_redeem_valid_code_grants_max_for_a_year():
    container, client = _build_app()
    _seed_code(container)
    headers, user_id = _signin(client, "promo-1")

    resp = client.post("/v1/me/redeem", headers=headers, json={"code": "CLAWCAST1YR"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] is True
    assert body["granted_days"] == 365

    # The user is now computed as Max while the window is open: subscription
    # tier stays "free" (paywall still shows) but capacity == Max and the
    # countdown is surfaced.
    ent = client.get("/v1/me", headers=headers).json()["entitlements"]
    assert ent["tier"] == "free"
    assert ent["trial_ends_at"] is not None
    assert ent["premium_pods_per_week"] == container.settings.max_premium_pods_per_week

    # Counter incremented exactly once.
    assert container.control_repository.get_promo_code("CLAWCAST1YR").redemptions_used == 1
    assert container.control_repository.get_promo_redemption("CLAWCAST1YR", user_id) is not None


def test_redeem_is_case_and_whitespace_insensitive():
    container, client = _build_app()
    _seed_code(container)
    headers, _ = _signin(client, "promo-case")
    resp = client.post("/v1/me/redeem", headers=headers, json={"code": "  clawcast1yr "})
    assert resp.status_code == 200, resp.text


# ---------- failures ----------


def test_redeem_unknown_code_400():
    _, client = _build_app()
    headers, _ = _signin(client, "promo-2")
    resp = client.post("/v1/me/redeem", headers=headers, json={"code": "NOPE"})
    assert resp.status_code == 400
    assert "valid" in resp.json()["detail"].lower()


def test_redeem_same_code_twice_is_rejected():
    container, client = _build_app()
    _seed_code(container)
    headers, _ = _signin(client, "promo-3")
    assert client.post("/v1/me/redeem", headers=headers, json={"code": "CLAWCAST1YR"}).status_code == 200
    second = client.post("/v1/me/redeem", headers=headers, json={"code": "CLAWCAST1YR"})
    assert second.status_code == 400
    assert "already" in second.json()["detail"].lower()
    # No double increment.
    assert container.control_repository.get_promo_code("CLAWCAST1YR").redemptions_used == 1


def test_redeem_respects_total_cap():
    container, client = _build_app()
    _seed_code(container, max_redemptions=1)

    h1, _ = _signin(client, "promo-cap-1")
    h2, _ = _signin(client, "promo-cap-2")

    assert client.post("/v1/me/redeem", headers=h1, json={"code": "CLAWCAST1YR"}).status_code == 200
    second = client.post("/v1/me/redeem", headers=h2, json={"code": "CLAWCAST1YR"})
    assert second.status_code == 400
    assert "limit" in second.json()["detail"].lower()
    assert container.control_repository.get_promo_code("CLAWCAST1YR").redemptions_used == 1


def test_redeem_expired_code_400():
    container, client = _build_app()
    _seed_code(container, expires_at=utc_now() - timedelta(days=1))
    headers, _ = _signin(client, "promo-exp")
    resp = client.post("/v1/me/redeem", headers=headers, json={"code": "CLAWCAST1YR"})
    assert resp.status_code == 400
    assert "expired" in resp.json()["detail"].lower()


def test_redeem_inactive_code_400():
    container, client = _build_app()
    _seed_code(container, active=False)
    headers, _ = _signin(client, "promo-inact")
    resp = client.post("/v1/me/redeem", headers=headers, json={"code": "CLAWCAST1YR"})
    assert resp.status_code == 400


def test_redeem_rejected_for_paid_user():
    container, client = _build_app()
    _seed_code(container)
    headers, user_id = _signin(client, "promo-paid")
    container.control_repository.save_subscription(
        SubscriptionRecord(user_id=user_id, tier="pro", status="active", updated_at=utc_now())
    )
    resp = client.post("/v1/me/redeem", headers=headers, json={"code": "CLAWCAST1YR"})
    assert resp.status_code == 400
    assert "subscription" in resp.json()["detail"].lower()
    # The capped redemption was NOT spent.
    assert container.control_repository.get_promo_code("CLAWCAST1YR").redemptions_used == 0


def test_redeem_never_shrinks_a_longer_existing_window():
    container, client = _build_app()
    _seed_code(container, grant_days=1)  # short code
    headers, user_id = _signin(client, "promo-noshrink")

    repo = container.control_repository
    user = repo.get_user(user_id)
    far_future = utc_now() + timedelta(days=400)
    user.trial_ends_at = far_future
    repo.save_user(user)

    resp = client.post("/v1/me/redeem", headers=headers, json={"code": "CLAWCAST1YR"})
    assert resp.status_code == 200, resp.text
    # Existing 400-day window is longer than the 1-day code → kept.
    assert repo.get_user(user_id).trial_ends_at == far_future


def test_redeem_requires_auth():
    _, client = _build_app()
    assert client.post("/v1/me/redeem", json={"code": "CLAWCAST1YR"}).status_code == 401
