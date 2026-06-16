"""Tests for the RevenueCat webhook (Android / Play Billing subscription events)."""
from __future__ import annotations

from fastapi.testclient import TestClient

from newsletter_pod.main import _build_container, create_app

SECRET = "rc-webhook-secret-xyz"


class _FakeAppleVerifier:
    def __init__(self, subject: str, email: str) -> None:
        self.subject = subject
        self.email = email

    def verify(self, identity_token: str):
        return type(
            "Identity", (), {"subject": self.subject, "email": self.email}
        )()


def _build_app(*, secret: str | None = SECRET):
    from newsletter_pod.config import Settings

    settings = Settings.from_env()
    settings.use_inmemory_adapters = True
    settings.apple_client_id = "com.example.newsletterpod"
    settings.session_signing_secret = "test-session-secret-32-bytes-long"
    settings.podcast_api_enabled = False
    settings.job_trigger_token = None
    # .env enables PUBLISH_SUMMARY_EMAIL_ENABLED; disable all email so the
    # container doesn't require SMTP config (mirrors test_control_plane_api).
    settings.alert_email_enabled = False
    settings.publish_summary_email_enabled = False
    settings.feedback_digest_email_enabled = False
    settings.revenuecat_webhook_auth_secret = secret
    settings.revenuecat_pro_monthly_product_id = "pro_monthly"
    settings.revenuecat_pro_annual_product_id = "pro_annual"
    settings.revenuecat_max_monthly_product_id = "max_monthly"
    settings.revenuecat_max_annual_product_id = "max_annual"
    container = _build_container(settings)
    return container, TestClient(create_app(container=container))


def _auth(client: TestClient) -> tuple[str, dict[str, str]]:
    """Create a user via Apple sign-in; return (user_id, auth_headers)."""
    app = client.app
    app.state.container.control_plane.apple_identity_verifier = _FakeAppleVerifier(
        "rc-user", "rc@example.com"
    )
    resp = client.post("/v1/auth/apple", json={"identity_token": "apple-token"})
    assert resp.status_code == 200
    token = resp.json()["session_token"]
    users = list(app.state.container.control_repository._users.values())
    return users[0].id, {"Authorization": f"Bearer {token}"}


def _event(**fields) -> dict:
    return {"event": {**fields}}


def _tier(client: TestClient, headers: dict[str, str]) -> str:
    return client.get("/v1/me", headers=headers).json()["subscription"]["tier"]


# ---------- auth ----------


def test_revenuecat_webhook_rejects_missing_or_wrong_auth():
    _, client = _build_app()
    assert client.post("/webhooks/revenuecat", json=_event(type="INITIAL_PURCHASE")).status_code == 401
    assert (
        client.post(
            "/webhooks/revenuecat",
            headers={"Authorization": "wrong"},
            json=_event(type="INITIAL_PURCHASE"),
        ).status_code
        == 401
    )


def test_revenuecat_webhook_503_when_unconfigured():
    _, client = _build_app(secret=None)
    resp = client.post(
        "/webhooks/revenuecat",
        headers={"Authorization": "anything"},
        json=_event(type="INITIAL_PURCHASE"),
    )
    assert resp.status_code == 503


# ---------- tier mutation ----------


def test_revenuecat_initial_purchase_flips_to_pro():
    container, client = _build_app()
    uid, headers = _auth(client)
    resp = client.post(
        "/webhooks/revenuecat",
        headers={"Authorization": SECRET},
        json=_event(
            type="INITIAL_PURCHASE",
            app_user_id=uid,
            product_id="pro_monthly",
            entitlement_ids=["pro"],
            expiration_at_ms=1893456000000,
        ),
    )
    assert resp.status_code == 200
    assert resp.json()["accepted"] is True
    sub = client.get("/v1/me", headers=headers).json()["subscription"]
    assert sub["tier"] == "pro"
    assert sub["status"] == "active"
    assert sub["product_id"] == "pro_monthly"


def test_revenuecat_max_resolved_via_entitlement_fallback():
    _, client = _build_app()
    uid, headers = _auth(client)
    # Unmapped product id → fall back to the entitlement ids.
    resp = client.post(
        "/webhooks/revenuecat",
        headers={"Authorization": SECRET},
        json=_event(
            type="INITIAL_PURCHASE",
            app_user_id=uid,
            product_id="some_unmapped_sku",
            entitlement_ids=["max"],
        ),
    )
    assert resp.status_code == 200
    assert _tier(client, headers) == "max"


def test_revenuecat_ios_app_store_product_id_resolves_to_pro():
    # iOS funnels through the SAME RevenueCat webhook (single source of truth for
    # the Flutter cut-over). Its product_id is an App Store SKU, not a Play one;
    # _revenuecat_tier must still resolve it (defense-in-depth, no entitlement_ids).
    _, client = _build_app()
    uid, headers = _auth(client)
    resp = client.post(
        "/webhooks/revenuecat",
        headers={"Authorization": SECRET},
        json=_event(
            type="INITIAL_PURCHASE",
            app_user_id=uid,
            product_id="com.newsletterpod.pro.monthly",
        ),
    )
    assert resp.status_code == 200
    sub = client.get("/v1/me", headers=headers).json()["subscription"]
    assert sub["tier"] == "pro"
    assert sub["status"] == "active"
    assert sub["product_id"] == "com.newsletterpod.pro.monthly"


def test_revenuecat_ios_event_resolves_via_entitlement_when_product_absent():
    # The store-agnostic primary path: an iOS event carrying only entitlement_ids
    # (App Store annual SKU we still recognise) resolves to max.
    _, client = _build_app()
    uid, headers = _auth(client)
    resp = client.post(
        "/webhooks/revenuecat",
        headers={"Authorization": SECRET},
        json=_event(
            type="INITIAL_PURCHASE",
            app_user_id=uid,
            product_id="com.newsletterpod.max.annual",
            entitlement_ids=["max"],
        ),
    )
    assert resp.status_code == 200
    assert _tier(client, headers) == "max"


def test_revenuecat_expiration_revokes_to_free():
    _, client = _build_app()
    uid, headers = _auth(client)
    client.post(
        "/webhooks/revenuecat",
        headers={"Authorization": SECRET},
        json=_event(type="INITIAL_PURCHASE", app_user_id=uid, product_id="pro_monthly", entitlement_ids=["pro"]),
    )
    assert _tier(client, headers) == "pro"
    resp = client.post(
        "/webhooks/revenuecat",
        headers={"Authorization": SECRET},
        json=_event(type="EXPIRATION", app_user_id=uid, product_id="pro_monthly"),
    )
    assert resp.status_code == 200
    sub = client.get("/v1/me", headers=headers).json()["subscription"]
    assert sub["tier"] == "free"
    assert sub["status"] == "expired"


def test_revenuecat_cancellation_keeps_entitlement():
    _, client = _build_app()
    uid, headers = _auth(client)
    client.post(
        "/webhooks/revenuecat",
        headers={"Authorization": SECRET},
        json=_event(type="INITIAL_PURCHASE", app_user_id=uid, product_id="max_monthly", entitlement_ids=["max"]),
    )
    # CANCELLATION = auto-renew off; the user keeps access until EXPIRATION.
    resp = client.post(
        "/webhooks/revenuecat",
        headers={"Authorization": SECRET},
        json=_event(type="CANCELLATION", app_user_id=uid, product_id="max_monthly"),
    )
    assert resp.status_code == 200
    assert _tier(client, headers) == "max"


def test_revenuecat_unknown_user_recorded_not_applied():
    _, client = _build_app()
    resp = client.post(
        "/webhooks/revenuecat",
        headers={"Authorization": SECRET},
        json=_event(type="INITIAL_PURCHASE", app_user_id="ghost-user", product_id="pro_monthly"),
    )
    assert resp.status_code == 200
    assert resp.json().get("warning") == "user not found"


def test_revenuecat_accepts_bearer_prefixed_authorization():
    # RevenueCat conventionally sends "Bearer <token>"; the bare secret is stored.
    _, client = _build_app()
    uid, headers = _auth(client)
    resp = client.post(
        "/webhooks/revenuecat",
        headers={"Authorization": f"Bearer {SECRET}"},
        json=_event(type="INITIAL_PURCHASE", app_user_id=uid, product_id="pro_monthly", entitlement_ids=["pro"]),
    )
    assert resp.status_code == 200
    assert _tier(client, headers) == "pro"


def test_revenuecat_product_change_upgrades_pro_to_max():
    _, client = _build_app()
    uid, headers = _auth(client)
    client.post(
        "/webhooks/revenuecat",
        headers={"Authorization": SECRET},
        json=_event(type="INITIAL_PURCHASE", app_user_id=uid, product_id="pro_monthly", entitlement_ids=["pro"]),
    )
    assert _tier(client, headers) == "pro"
    resp = client.post(
        "/webhooks/revenuecat",
        headers={"Authorization": SECRET},
        json=_event(type="PRODUCT_CHANGE", app_user_id=uid, product_id="max_monthly", entitlement_ids=["max"]),
    )
    assert resp.status_code == 200
    assert _tier(client, headers) == "max"


def test_revenuecat_ignores_stale_out_of_order_expiration():
    _, client = _build_app()
    uid, headers = _auth(client)
    future_ms = 2_000_000_000_000  # ~2033
    client.post(
        "/webhooks/revenuecat",
        headers={"Authorization": SECRET},
        json=_event(
            type="INITIAL_PURCHASE",
            app_user_id=uid,
            product_id="pro_monthly",
            entitlement_ids=["pro"],
            expiration_at_ms=future_ms,
        ),
    )
    assert _tier(client, headers) == "pro"
    # An EXPIRATION for an earlier period (out-of-order) must not revoke.
    resp = client.post(
        "/webhooks/revenuecat",
        headers={"Authorization": SECRET},
        json=_event(type="EXPIRATION", app_user_id=uid, product_id="pro_monthly", expiration_at_ms=1_000_000_000_000),
    )
    assert resp.status_code == 200
    assert resp.json().get("stale") is True
    assert _tier(client, headers) == "pro"


def test_revenuecat_duplicate_event_id_collapses_to_one_record():
    container, client = _build_app()
    uid, _ = _auth(client)
    body = _event(
        id="rc-evt-123",
        type="INITIAL_PURCHASE",
        app_user_id=uid,
        product_id="pro_monthly",
        entitlement_ids=["pro"],
    )
    headers = {"Authorization": SECRET}
    client.post("/webhooks/revenuecat", headers=headers, json=body)
    client.post("/webhooks/revenuecat", headers=headers, json=body)
    # Sign-in creates no billing events, so the retried webhook must leave
    # exactly one record (keyed on the RevenueCat event id).
    assert list(container.control_repository._billing_events.keys()) == ["rc-evt-123"]
