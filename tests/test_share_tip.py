"""Tests for the share-sheet awareness push (2026-07-01).

Covers the push payload/dispatch and the admin broadcast endpoint (selection,
one-time stamping, no-token retry semantics, dry-run, and admin gating). Reuses
the test_push.py fakes for the push-shape assertions and mirrors the
test_trial_gift.py structure.
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from newsletter_pod.main import _build_container, create_app
from newsletter_pod.push import build_share_tip_payload, send_share_tip_push
from newsletter_pod.user_models import UserRecord
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


def _make_admin(container, client):
    """Authenticate an admin caller and stamp them out of the share-tip
    audience (they'd otherwise be a candidate like every other user), so tests
    can reason about only the users they seed. Returns the auth headers."""
    _, headers = _auth_headers(client, FakeAppleVerifier("admin-1", "admin@example.com"))
    admin_id = client.get("/v1/me", headers=headers).json()["user"]["id"]
    container.settings.admin_user_ids = admin_id
    admin = container.control_repository.get_user(admin_id)
    admin.share_tip_pushed_at = utc_now()
    container.control_repository.save_user(admin)
    return headers


def _seed_user(repo, uid: str, *, pushed, with_token: bool) -> None:
    now = utc_now()
    repo.save_user(
        UserRecord(
            id=uid,
            created_at=now,
            updated_at=now,
            share_tip_pushed_at=pushed,
        )
    )
    if with_token:
        repo.save_device_token(_make_device_token(uid, (uid[:1] * 64)[:64]))


# ---------- push payload / dispatch ----------


def test_build_share_tip_payload_has_expected_aps_shape():
    payload = build_share_tip_payload()
    aps = payload["aps"]
    assert aps["alert"]["title"] == "Turn any article into audio 🎧"
    assert aps["alert"]["body"] == (
        "From your browser, Mail, or Substack — share a story to ClawCast and "
        "hear it in your next briefing."
    )
    assert aps["category"] == "SHARE_TIP"
    assert payload["type"] == "share_tip"


def test_send_share_tip_push_noops_when_both_senders_none():
    repo = InMemoryControlPlaneRepository()
    repo.save_device_token(_make_device_token("u1", "a" * 64))
    result = send_share_tip_push(
        sender=None,
        fcm_sender=None,
        repository=repo,
        user_id="u1",
    )
    assert result == {"attempted": 0, "delivered": 0, "deregistered": 0}


def test_send_share_tip_push_routes_android_to_fcm_and_ios_to_apns():
    repo = InMemoryControlPlaneRepository()
    repo.save_device_token(_make_device_token("u1", "a" * 64))  # ios → APNs
    repo.save_device_token(
        _make_android_device_token("u1", "AndroidToken" + "z" * 40)
    )  # android → FCM

    apns_client = _StubClient([_StubResponse(200)])
    fcm_client = _StubClient([_StubResponse(200, {"name": "ok"})])
    result = send_share_tip_push(
        sender=_make_sender(apns_client),
        fcm_sender=_make_fcm_sender(fcm_client),
        repository=repo,
        user_id="u1",
    )
    assert result == {"attempted": 2, "delivered": 2, "deregistered": 0}
    assert apns_client.calls[0]["json"]["aps"]["category"] == "SHARE_TIP"
    fcm_message = fcm_client.calls[0]["json"]["message"]
    assert fcm_message["notification"]["title"] == "Turn any article into audio 🎧"
    assert fcm_message["data"]["type"] == "share_tip"
    # Collapse id is user-keyed so a retry replaces rather than stacks.
    assert apns_client.calls[0]["headers"]["apns-collapse-id"] == "share-tip-u1"


# ---------- admin notify endpoint ----------


def test_admin_share_tip_notify_pushes_unpushed_stamps_and_retries_no_token():
    container, client = _build_app()
    headers = _make_admin(container, client)
    repo = container.control_repository

    apns_client = _StubClient([_StubResponse(200)])
    container.push_sender = _make_sender(apns_client)

    _seed_user(repo, "cand-ios", pushed=None, with_token=True)   # reachable → pushed
    _seed_user(repo, "notoken-1", pushed=None, with_token=False)  # no token → skipped
    _seed_user(repo, "done-1", pushed=utc_now(), with_token=True)  # already pushed

    resp = client.post("/admin/share-tip/notify", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["dry_run"] is False
    assert body["candidates"] == 2  # cand-ios + notoken-1 (done-1 excluded)
    assert body["pushed"] == 1
    assert body["skipped_no_token"] == 1

    # Pushed user is stamped; the token-less user is left UNSTAMPED for a retry.
    assert repo.get_user("cand-ios").share_tip_pushed_at is not None
    assert repo.get_user("notoken-1").share_tip_pushed_at is None

    # A re-run finds only the still-unreachable user; nothing new is pushed.
    resp2 = client.post("/admin/share-tip/notify", headers=headers)
    body2 = resp2.json()
    assert body2["candidates"] == 1
    assert body2["pushed"] == 0
    assert body2["skipped_no_token"] == 1


def test_admin_share_tip_notify_stamps_dead_token_user_and_counts_deregistered():
    """A user whose only token is dead (410/Unregistered) was still REACHED, so
    they must be stamped (pushed), not left in skipped_no_token to retry forever
    — the stamp decision keys off attempted>0, not delivered>0. The dead token
    is also deregistered and counted in the response."""
    container, client = _build_app()
    headers = _make_admin(container, client)
    repo = container.control_repository

    container.push_sender = _make_sender(
        _StubClient([_StubResponse(410, {"reason": "Unregistered"})])
    )

    _seed_user(repo, "dead-1", pushed=None, with_token=True)

    resp = client.post("/admin/share-tip/notify", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["candidates"] == 1
    assert body["pushed"] == 1  # reached (attempted), even though delivery failed
    assert body["skipped_no_token"] == 0
    assert body["deregistered"] == 1

    # Reached-but-dead still stamps (so we don't retry a dead token forever),
    # and the dead token is deregistered.
    assert repo.get_user("dead-1").share_tip_pushed_at is not None
    assert repo.list_active_device_tokens("dead-1") == []


def test_admin_share_tip_notify_dry_run_reports_counts_without_sending():
    container, client = _build_app()
    headers = _make_admin(container, client)
    repo = container.control_repository

    # A stub with no queued responses would raise if the dry run tried to send.
    container.push_sender = _make_sender(_StubClient([]))

    _seed_user(repo, "cand-ios", pushed=None, with_token=True)
    _seed_user(repo, "notoken-1", pushed=None, with_token=False)
    _seed_user(repo, "done-1", pushed=utc_now(), with_token=True)

    resp = client.post("/admin/share-tip/notify?dry_run=true", headers=headers)
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["dry_run"] is True
    assert body["candidates"] == 2
    assert body["reachable"] == 1  # only cand-ios has an active token
    # Dry run must not stamp anyone.
    assert repo.get_user("cand-ios").share_tip_pushed_at is None


def test_admin_share_tip_notify_is_admin_gated():
    container, client = _build_app()
    _, headers = _auth_headers(client, FakeAppleVerifier("nonadmin-1", "n@example.com"))
    container.settings.admin_user_ids = "someone-else"
    resp = client.post("/admin/share-tip/notify", headers=headers)
    assert resp.status_code == 403
