"""Tests for the "gift" trial-reset feature (first-100-users thank-you).

Covers the entitlements flag, the ack endpoint, the push payload/dispatch, and
the admin notify endpoint (selection + stamping + admin gating). Reuses the
test_push.py fakes for the push-shape assertions.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from fastapi.testclient import TestClient

from newsletter_pod.main import _build_container, create_app
from newsletter_pod.push import build_trial_gift_payload, send_trial_gift_push
from newsletter_pod.user_models import DeviceTokenRecord
from newsletter_pod.user_repository import InMemoryControlPlaneRepository
from newsletter_pod.utils import utc_now

from tests.test_control_plane_api import FakeAppleVerifier, _auth_headers
from tests.test_push import (
    _StubClient,
    _StubResponse,
    _make_android_device_token,
    _make_device_token,
    _make_fcm_sender,
    _make_sender,
)


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


# ---------- entitlements: trial_gift_pending ----------


def test_trial_gift_pending_true_when_granted_and_not_acked():
    container, client = _build_app()
    _, headers = _auth_headers(client, FakeAppleVerifier("gift-1", "g1@example.com"))
    user_id = client.get("/v1/me", headers=headers).json()["user"]["id"]

    repo = container.control_repository
    user = repo.get_user(user_id)
    user.trial_gift_granted_at = utc_now()
    repo.save_user(user)

    ent = client.get("/v1/me", headers=headers).json()["entitlements"]
    assert ent["trial_gift_pending"] is True


def test_trial_gift_pending_false_when_acked():
    container, client = _build_app()
    _, headers = _auth_headers(client, FakeAppleVerifier("gift-2", "g2@example.com"))
    user_id = client.get("/v1/me", headers=headers).json()["user"]["id"]

    repo = container.control_repository
    user = repo.get_user(user_id)
    user.trial_gift_granted_at = utc_now()
    user.trial_gift_acknowledged_at = utc_now()
    repo.save_user(user)

    ent = client.get("/v1/me", headers=headers).json()["entitlements"]
    assert ent["trial_gift_pending"] is False


def test_trial_gift_pending_false_when_never_granted():
    container, client = _build_app()
    _, headers = _auth_headers(client, FakeAppleVerifier("gift-3", "g3@example.com"))
    ent = client.get("/v1/me", headers=headers).json()["entitlements"]
    assert ent["trial_gift_pending"] is False


# ---------- ack endpoint ----------


def test_trial_gift_ack_flips_pending_and_is_idempotent():
    container, client = _build_app()
    _, headers = _auth_headers(client, FakeAppleVerifier("gift-4", "g4@example.com"))
    user_id = client.get("/v1/me", headers=headers).json()["user"]["id"]

    repo = container.control_repository
    user = repo.get_user(user_id)
    user.trial_gift_granted_at = utc_now()
    repo.save_user(user)

    # Pending before ack.
    assert client.get("/v1/me", headers=headers).json()["entitlements"][
        "trial_gift_pending"
    ] is True

    resp = client.post("/v1/me/trial-gift/ack", headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"ok": True}

    user = repo.get_user(user_id)
    first_ack = user.trial_gift_acknowledged_at
    assert first_ack is not None

    # Pending flips False.
    assert client.get("/v1/me", headers=headers).json()["entitlements"][
        "trial_gift_pending"
    ] is False

    # Idempotent: a second ack is a no-op and doesn't move the timestamp.
    resp2 = client.post("/v1/me/trial-gift/ack", headers=headers)
    assert resp2.status_code == 200, resp2.text
    assert repo.get_user(user_id).trial_gift_acknowledged_at == first_ack


def test_trial_gift_ack_requires_auth():
    _, client = _build_app()
    assert client.post("/v1/me/trial-gift/ack").status_code == 401


# ---------- push payload / dispatch ----------


def test_build_trial_gift_payload_has_expected_aps_shape():
    payload = build_trial_gift_payload()
    aps = payload["aps"]
    assert aps["alert"]["title"] == "A gift from ClawCast 🎁"
    assert (
        aps["alert"]["body"]
        == "We've reset your 7-day free trial. Full access is back. Tap to open."
    )
    assert aps["category"] == "TRIAL_GIFT"
    assert payload["type"] == "trial_gift"


def test_send_trial_gift_push_noops_when_both_senders_none():
    repo = InMemoryControlPlaneRepository()
    repo.save_device_token(_make_device_token("u1", "a" * 64))
    result = send_trial_gift_push(
        sender=None,
        fcm_sender=None,
        repository=repo,
        user_id="u1",
    )
    assert result == {"attempted": 0, "delivered": 0, "deregistered": 0}


def test_send_trial_gift_push_routes_android_to_fcm_and_ios_to_apns():
    repo = InMemoryControlPlaneRepository()
    repo.save_device_token(_make_device_token("u1", "a" * 64))  # ios → APNs
    repo.save_device_token(
        _make_android_device_token("u1", "AndroidToken" + "z" * 40)
    )  # android → FCM

    apns_client = _StubClient([_StubResponse(200)])
    fcm_client = _StubClient([_StubResponse(200, {"name": "ok"})])
    result = send_trial_gift_push(
        sender=_make_sender(apns_client),
        fcm_sender=_make_fcm_sender(fcm_client),
        repository=repo,
        user_id="u1",
    )
    assert result == {"attempted": 2, "delivered": 2, "deregistered": 0}
    assert len(apns_client.calls) == 1
    assert len(fcm_client.calls) == 1
    # iOS gets the aps alert; Android gets the notification + data.
    assert apns_client.calls[0]["json"]["aps"]["category"] == "TRIAL_GIFT"
    fcm_message = fcm_client.calls[0]["json"]["message"]
    assert fcm_message["notification"]["title"] == "A gift from ClawCast 🎁"
    assert fcm_message["data"]["type"] == "trial_gift"
    # Collapse id is user-keyed so a retry replaces rather than stacks.
    assert apns_client.calls[0]["headers"]["apns-collapse-id"] == "trial-gift-u1"


# ---------- admin notify endpoint ----------


def test_admin_trial_gift_notify_pushes_only_granted_not_pushed_and_stamps():
    container, client = _build_app()
    # Make this caller an admin.
    _, headers = _auth_headers(client, FakeAppleVerifier("admin-1", "admin@example.com"))
    admin_id = client.get("/v1/me", headers=headers).json()["user"]["id"]
    container.settings.admin_user_ids = admin_id

    repo = container.control_repository

    # Wire a stub APNs sender so the push actually "delivers" and we can count.
    apns_client = _StubClient([_StubResponse(200), _StubResponse(200)])
    container.push_sender = _make_sender(apns_client)

    now = utc_now()

    def _seed_user(uid: str, granted, pushed) -> None:
        from newsletter_pod.user_models import UserRecord

        repo.save_user(
            UserRecord(
                id=uid,
                created_at=now,
                updated_at=now,
                trial_gift_granted_at=granted,
                trial_gift_pushed_at=pushed,
            )
        )
        repo.save_device_token(_make_device_token(uid, (uid[:1] * 64)[:64]))

    # candidate: granted, not yet pushed
    _seed_user("cand-1", now, None)
    # already pushed → skipped
    _seed_user("done-1", now, now)
    # never granted → skipped
    _seed_user("never-1", None, None)

    resp = client.post("/admin/trial-gift/notify", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["candidates"] == 1
    assert body["pushed"] == 1

    # The candidate is now stamped; a re-run finds no candidates.
    assert repo.get_user("cand-1").trial_gift_pushed_at is not None
    apns_client._responses = [_StubResponse(200)]  # reset queue (none used)
    resp2 = client.post("/admin/trial-gift/notify", headers=headers)
    assert resp2.json()["candidates"] == 0
    assert resp2.json()["pushed"] == 0


def test_admin_trial_gift_notify_is_admin_gated():
    container, client = _build_app()
    _, headers = _auth_headers(client, FakeAppleVerifier("nonadmin-1", "n@example.com"))
    # ADMIN_USER_IDS empty by default → non-admin.
    container.settings.admin_user_ids = "someone-else"
    resp = client.post("/admin/trial-gift/notify", headers=headers)
    assert resp.status_code == 403
