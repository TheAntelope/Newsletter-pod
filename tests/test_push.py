"""Tests for newsletter_pod.push — APNs sender + Substack verification push."""
from __future__ import annotations

import time
from datetime import datetime, timezone
from typing import Optional

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from newsletter_pod.push import (
    FcmSender,
    PushSender,
    build_fcm_sender_from_settings,
    build_pod_ready_payload,
    build_push_sender_from_settings,
    build_substack_verification_payload,
    send_pod_ready_push,
    send_substack_verification_push,
)
from newsletter_pod.user_models import DeviceTokenRecord
from newsletter_pod.user_repository import InMemoryControlPlaneRepository


# ---------- helpers ----------


def _generate_es256_pem() -> str:
    """Mint a throwaway ES256 key in PEM form for JWT signing tests.

    Apple's APNs keys are ES256 in the same PEM shape; the wire format we
    sign is identical, just with our own random key.
    """
    private_key = ec.generate_private_key(ec.SECP256R1())
    pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return pem.decode("utf-8")


class _StubResponse:
    def __init__(self, status_code: int, body: Optional[dict] = None) -> None:
        self.status_code = status_code
        self._body = body or {}

    def json(self) -> dict:
        return self._body


class _StubClient:
    def __init__(self, responses: list[_StubResponse]) -> None:
        self._responses = list(responses)
        self.calls: list[dict] = []

    def post(self, url: str, *, json: dict, headers: dict) -> _StubResponse:
        self.calls.append({"url": url, "json": json, "headers": headers})
        return self._responses.pop(0)


def _make_sender(client: _StubClient) -> PushSender:
    sender = PushSender(
        team_id="TEAM1234XY",
        key_id="KEYAB12345",
        auth_key_pem=_generate_es256_pem(),
        bundle_id="com.newsletterpod.app",
        environment="production",
    )
    sender._http_client = client  # type: ignore[assignment]
    return sender


def _make_device_token(user_id: str, token: str) -> DeviceTokenRecord:
    now = datetime(2026, 5, 29, 12, 0, tzinfo=timezone.utc)
    return DeviceTokenRecord(
        id=f"id-{token[:8]}",
        user_id=user_id,
        token=token,
        platform="ios",
        environment="production",
        bundle_id="com.newsletterpod.app",
        created_at=now,
        last_seen_at=now,
    )


# ---------- payload ----------


def test_build_substack_verification_payload_has_expected_aps_shape():
    payload = build_substack_verification_payload(code="812807", pub_title="Noahpinion")
    aps = payload["aps"]
    assert aps["alert"]["title"] == "Substack verification code"
    assert "812807" in aps["alert"]["body"]
    assert "Noahpinion" in aps["alert"]["body"]
    assert aps["category"] == "SUBSTACK_VERIFICATION"
    # Top-level fields the iOS handler reads to act on the tap.
    assert payload["type"] == "substack_verification"
    assert payload["code"] == "812807"
    assert payload["pub_title"] == "Noahpinion"


# ---------- JWT cache ----------


def test_push_sender_jwt_round_trips_and_caches():
    client = _StubClient([_StubResponse(200)])
    sender = _make_sender(client)

    token1 = sender._current_jwt()
    token2 = sender._current_jwt()
    # Second call returns cached JWT without re-signing.
    assert token1 == token2

    # Headers carry team_id (iss) and key_id (kid).
    decoded_headers = jwt.get_unverified_header(token1)
    assert decoded_headers["alg"] == "ES256"
    assert decoded_headers["kid"] == "KEYAB12345"
    decoded_payload = jwt.decode(token1, options={"verify_signature": False})
    assert decoded_payload["iss"] == "TEAM1234XY"


# ---------- send ----------


def test_push_sender_send_targets_correct_host_and_headers():
    client = _StubClient([_StubResponse(200)])
    sender = _make_sender(client)
    result = sender.send(
        device_token="abc123" * 11,  # 66 chars
        payload={"aps": {"alert": "hi"}},
    )
    assert result.status_code == 200
    assert result.token_invalid is False

    call = client.calls[0]
    assert call["url"] == "https://api.push.apple.com/3/device/" + "abc123" * 11
    assert call["headers"]["apns-topic"] == "com.newsletterpod.app"
    assert call["headers"]["apns-push-type"] == "alert"
    assert call["headers"]["apns-priority"] == "10"
    assert call["headers"]["authorization"].startswith("bearer ")


def test_push_sender_send_410_marks_token_invalid():
    client = _StubClient([_StubResponse(410, {"reason": "Unregistered"})])
    sender = _make_sender(client)
    result = sender.send(device_token="x" * 64, payload={})
    assert result.status_code == 410
    assert result.token_invalid is True
    assert result.reason == "Unregistered"


def test_push_sender_send_bad_device_token_400_marks_invalid():
    client = _StubClient([_StubResponse(400, {"reason": "BadDeviceToken"})])
    sender = _make_sender(client)
    result = sender.send(device_token="x" * 64, payload={})
    assert result.token_invalid is True


def test_push_sender_send_other_4xx_does_not_mark_invalid():
    client = _StubClient([_StubResponse(403, {"reason": "MissingTopic"})])
    sender = _make_sender(client)
    result = sender.send(device_token="x" * 64, payload={})
    assert result.status_code == 403
    assert result.token_invalid is False


# ---------- send_substack_verification_push ----------


def test_send_substack_verification_push_noops_when_sender_is_none():
    repo = InMemoryControlPlaneRepository()
    result = send_substack_verification_push(
        sender=None,
        repository=repo,
        user_id="u1",
        code="123456",
        pub_title="Noahpinion",
    )
    assert result == {"attempted": 0, "delivered": 0, "deregistered": 0}


def test_send_substack_verification_push_skips_when_no_device_tokens():
    repo = InMemoryControlPlaneRepository()
    client = _StubClient([])  # no calls expected
    sender = _make_sender(client)
    result = send_substack_verification_push(
        sender=sender,
        repository=repo,
        user_id="u1",
        code="123456",
        pub_title="Noahpinion",
    )
    assert result == {"attempted": 0, "delivered": 0, "deregistered": 0}
    assert client.calls == []


def test_send_substack_verification_push_delivers_to_all_active_tokens():
    repo = InMemoryControlPlaneRepository()
    repo.save_device_token(_make_device_token("u1", "a" * 64))
    repo.save_device_token(_make_device_token("u1", "b" * 64))

    client = _StubClient([_StubResponse(200), _StubResponse(200)])
    sender = _make_sender(client)
    result = send_substack_verification_push(
        sender=sender,
        repository=repo,
        user_id="u1",
        code="812807",
        pub_title="Noahpinion",
        pub_url="https://noahpinion.substack.com",
    )
    assert result == {"attempted": 2, "delivered": 2, "deregistered": 0}
    assert len(client.calls) == 2
    # Same collapse-id on every attempt so retries replace older codes
    # rather than stacking notifications.
    collapse_ids = {call["headers"]["apns-collapse-id"] for call in client.calls}
    assert len(collapse_ids) == 1
    # Payload carries the pub URL when provided.
    assert client.calls[0]["json"]["pub_url"] == "https://noahpinion.substack.com"


def test_send_substack_verification_push_deregisters_410_tokens():
    repo = InMemoryControlPlaneRepository()
    repo.save_device_token(_make_device_token("u1", "a" * 64))
    repo.save_device_token(_make_device_token("u1", "b" * 64))

    # First token 410, second token 200.
    client = _StubClient(
        [
            _StubResponse(410, {"reason": "Unregistered"}),
            _StubResponse(200),
        ]
    )
    sender = _make_sender(client)
    result = send_substack_verification_push(
        sender=sender,
        repository=repo,
        user_id="u1",
        code="812807",
        pub_title="Noahpinion",
    )
    assert result["deregistered"] == 1
    assert result["delivered"] == 1
    # The 410 token is now marked invalidated_at.
    active = repo.list_active_device_tokens("u1")
    assert len(active) == 1


# ---------- factory ----------


def test_build_push_sender_disabled_when_flag_off():
    sender = build_push_sender_from_settings(
        enabled=False,
        team_id="T",
        key_id="K",
        auth_key_pem=_generate_es256_pem(),
        bundle_id="com.example",
        environment="production",
    )
    assert sender is None


def test_build_push_sender_disabled_when_auth_key_missing():
    sender = build_push_sender_from_settings(
        enabled=True,
        team_id="T",
        key_id="K",
        auth_key_pem=None,
        bundle_id="com.example",
        environment="production",
    )
    assert sender is None


def test_build_push_sender_enabled_when_fully_configured():
    sender = build_push_sender_from_settings(
        enabled=True,
        team_id="T",
        key_id="K",
        auth_key_pem=_generate_es256_pem(),
        bundle_id="com.example",
        environment="sandbox",
    )
    assert sender is not None
    assert sender.host == "https://api.sandbox.push.apple.com"


# ========================= FCM (Android) =========================


def _make_fcm_sender(client: _StubClient, token: str = "ya29.test-access-token") -> FcmSender:
    sender = FcmSender(
        project_id="theclawcast-9a045",
        service_account_info={"type": "service_account"},
        # Bypass google-auth in tests — no real credentials needed.
        access_token_provider=lambda: token,
    )
    sender._http_client = client  # type: ignore[assignment]
    return sender


def _make_android_device_token(user_id: str, token: str) -> DeviceTokenRecord:
    now = datetime(2026, 5, 29, 12, 0, tzinfo=timezone.utc)
    return DeviceTokenRecord(
        id=f"id-{token[:8]}",
        user_id=user_id,
        token=token,
        platform="android",
        environment="production",
        bundle_id="com.newsletterpod.app",
        created_at=now,
        last_seen_at=now,
    )


# ---------- FcmSender.send ----------


def test_fcm_sender_send_200_targets_v1_endpoint_with_bearer():
    client = _StubClient([_StubResponse(200, {"name": "projects/x/messages/1"})])
    sender = _make_fcm_sender(client, token="ya29.abc")
    result = sender.send(
        device_token="d" * 64,
        notification={"title": "t", "body": "b"},
        data={"code": "812807"},
        collapse_key="substack-verify-abcdef12",
    )
    assert result.status_code == 200
    assert result.token_invalid is False

    call = client.calls[0]
    assert call["url"] == (
        "https://fcm.googleapis.com/v1/projects/theclawcast-9a045/messages:send"
    )
    assert call["headers"]["Authorization"] == "Bearer ya29.abc"
    message = call["json"]["message"]
    assert message["token"] == "d" * 64
    assert message["notification"] == {"title": "t", "body": "b"}
    assert message["data"]["code"] == "812807"  # values stringified
    assert message["android"]["priority"] == "high"
    assert message["android"]["collapse_key"] == "substack-verify-abcdef12"
    # iOS (FCM→APNs) gets explicit headers so an offline iPhone receives it on
    # reconnect; the collapse id rides the APNs leg too.
    apns_headers = message["apns"]["headers"]
    assert apns_headers["apns-push-type"] == "alert"
    assert apns_headers["apns-priority"] == "10"
    assert apns_headers["apns-collapse-id"] == "substack-verify-abcdef12"
    # No expiration requested → APNs uses its default (header absent).
    assert "apns-expiration" not in apns_headers


def test_fcm_sender_send_sets_apns_expiration_window():
    client = _StubClient([_StubResponse(200, {"name": "projects/x/messages/1"})])
    sender = _make_fcm_sender(client)
    before = int(time.time())
    sender.send(
        device_token="d" * 64,
        notification={"title": "t", "body": "b"},
        apns_expiration_seconds=24 * 60 * 60,
    )
    after = int(time.time())
    expiration = int(client.calls[0]["json"]["message"]["apns"]["headers"]["apns-expiration"])
    # Absolute UNIX expiry ≈ now + 24h, bounded by the wall-clock either side.
    assert before + 24 * 60 * 60 <= expiration <= after + 24 * 60 * 60


def test_fcm_sender_send_404_unregistered_marks_invalid():
    client = _StubClient(
        [_StubResponse(404, {"error": {"status": "NOT_FOUND", "details": [{"errorCode": "UNREGISTERED"}]}})]
    )
    sender = _make_fcm_sender(client)
    result = sender.send(device_token="x" * 64, notification={"title": "t", "body": "b"})
    assert result.status_code == 404
    assert result.token_invalid is True


def test_fcm_sender_send_invalid_argument_not_marked_invalid():
    # INVALID_ARGUMENT can mean a malformed message (our bug), not a dead token,
    # so we must NOT deregister on it.
    client = _StubClient(
        [_StubResponse(400, {"error": {"status": "INVALID_ARGUMENT", "details": [{"errorCode": "INVALID_ARGUMENT"}]}})]
    )
    sender = _make_fcm_sender(client)
    result = sender.send(device_token="x" * 64, notification={"title": "t", "body": "b"})
    assert result.status_code == 400
    assert result.token_invalid is False


# ---------- factory ----------


def test_build_fcm_sender_disabled_when_flag_off():
    assert build_fcm_sender_from_settings(
        enabled=False, service_account_json='{"type":"service_account"}', project_id="p"
    ) is None


def test_build_fcm_sender_disabled_when_json_missing():
    assert build_fcm_sender_from_settings(
        enabled=True, service_account_json=None, project_id="p"
    ) is None


def test_build_fcm_sender_disabled_when_json_invalid():
    assert build_fcm_sender_from_settings(
        enabled=True, service_account_json="definitely not json", project_id="p"
    ) is None


def test_build_fcm_sender_enabled_when_configured():
    sender = build_fcm_sender_from_settings(
        enabled=True,
        service_account_json='{"type":"service_account","project_id":"p"}',
        project_id="theclawcast-9a045",
    )
    assert sender is not None
    assert sender.project_id == "theclawcast-9a045"


# ---------- routing in send_substack_verification_push ----------


def test_send_substack_push_routes_android_to_fcm_and_ios_to_apns():
    repo = InMemoryControlPlaneRepository()
    repo.save_device_token(_make_device_token("u1", "a" * 64))  # ios → APNs
    repo.save_device_token(
        _make_android_device_token("u1", "AndroidToken" + "z" * 40)
    )  # android → FCM

    apns_client = _StubClient([_StubResponse(200)])
    fcm_client = _StubClient([_StubResponse(200, {"name": "ok"})])
    result = send_substack_verification_push(
        sender=_make_sender(apns_client),
        fcm_sender=_make_fcm_sender(fcm_client),
        repository=repo,
        user_id="u1",
        code="812807",
        pub_title="Noahpinion",
        pub_url="https://noahpinion.substack.com",
    )
    assert result == {"attempted": 2, "delivered": 2, "deregistered": 0}
    # Each sender got exactly one call → routed by platform (a misroute would
    # pop an empty stub queue and raise).
    assert len(apns_client.calls) == 1
    assert len(fcm_client.calls) == 1
    fcm_message = fcm_client.calls[0]["json"]["message"]
    assert fcm_message["data"]["code"] == "812807"
    assert fcm_message["data"]["pub_url"] == "https://noahpinion.substack.com"


def test_send_substack_push_noops_when_both_senders_none():
    repo = InMemoryControlPlaneRepository()
    repo.save_device_token(_make_android_device_token("u1", "AndroidToken" + "z" * 40))
    result = send_substack_verification_push(
        sender=None,
        fcm_sender=None,
        repository=repo,
        user_id="u1",
        code="123456",
        pub_title="Noahpinion",
    )
    assert result == {"attempted": 0, "delivered": 0, "deregistered": 0}


# ========================= pod-ready push =========================


def test_build_pod_ready_payload_has_expected_aps_shape():
    payload = build_pod_ready_payload(
        episode_title="Tuesday briefing: 4 stories",
        feed_url="https://api.example.com/feeds/abc.xml",
        episode_id="abc-2026-06-04-deadbeef",
    )
    aps = payload["aps"]
    assert aps["alert"]["title"] == "Your briefing is ready"
    assert aps["alert"]["body"] == "Tuesday briefing: 4 stories"
    assert aps["category"] == "POD_READY"
    assert payload["type"] == "pod_ready"
    # Deep-link fields ride along at top level for the iOS tap handler.
    assert payload["episode_id"] == "abc-2026-06-04-deadbeef"
    assert payload["feed_url"] == "https://api.example.com/feeds/abc.xml"


def test_build_pod_ready_payload_omits_optional_fields_when_absent():
    payload = build_pod_ready_payload(episode_title="Your latest briefing is ready.")
    assert "episode_id" not in payload
    assert "feed_url" not in payload


def test_send_pod_ready_push_noops_when_both_senders_none():
    repo = InMemoryControlPlaneRepository()
    repo.save_device_token(_make_device_token("u1", "a" * 64))
    result = send_pod_ready_push(
        sender=None,
        fcm_sender=None,
        repository=repo,
        user_id="u1",
        episode_title="Tuesday briefing",
    )
    assert result == {"attempted": 0, "delivered": 0, "deregistered": 0}


def test_send_pod_ready_push_routes_android_to_fcm_and_ios_to_apns():
    repo = InMemoryControlPlaneRepository()
    repo.save_device_token(_make_device_token("u1", "a" * 64))  # ios → APNs
    repo.save_device_token(
        _make_android_device_token("u1", "AndroidToken" + "z" * 40)
    )  # android → FCM

    apns_client = _StubClient([_StubResponse(200)])
    fcm_client = _StubClient([_StubResponse(200, {"name": "ok"})])
    result = send_pod_ready_push(
        sender=_make_sender(apns_client),
        fcm_sender=_make_fcm_sender(fcm_client),
        repository=repo,
        user_id="u1",
        episode_title="Tuesday briefing: 4 stories",
        episode_id="abc-2026-06-04-deadbeef",
        feed_url="https://api.example.com/feeds/abc.xml",
    )
    assert result == {"attempted": 2, "delivered": 2, "deregistered": 0}
    assert len(apns_client.calls) == 1
    assert len(fcm_client.calls) == 1
    # iOS gets the aps alert; Android gets the notification + data deep-link.
    assert apns_client.calls[0]["json"]["aps"]["category"] == "POD_READY"
    fcm_message = fcm_client.calls[0]["json"]["message"]
    assert fcm_message["notification"]["title"] == "Your briefing is ready"
    assert fcm_message["data"]["type"] == "pod_ready"
    assert fcm_message["data"]["episode_id"] == "abc-2026-06-04-deadbeef"
    # Collapse id is user-keyed so a newer episode replaces a stale alert.
    assert apns_client.calls[0]["headers"]["apns-collapse-id"] == "pod-ready-u1"
    # The FCM→APNs leg carries a 24h store-and-retry window so an iPhone that
    # was offline when the pod published still gets the briefing on reconnect.
    fcm_apns = fcm_message["apns"]["headers"]
    assert fcm_apns["apns-collapse-id"] == "pod-ready-u1"
    assert int(fcm_apns["apns-expiration"]) >= int(time.time()) + 24 * 60 * 60 - 5


def test_pod_ready_ios_fcm_token_routes_to_fcm_not_apns():
    # An iOS device registered via the Flutter app carries transport="fcm",
    # so it must go through FCM even though platform is "ios".
    repo = InMemoryControlPlaneRepository()
    now = datetime(2026, 6, 4, 12, 0, tzinfo=timezone.utc)
    repo.save_device_token(
        DeviceTokenRecord(
            id="id-iosfcm",
            user_id="u1",
            token="iOS-FCM-Token" + "Z" * 40,
            platform="ios",
            transport="fcm",
            environment="production",
            bundle_id="com.newsletterpod.app",
            created_at=now,
            last_seen_at=now,
        )
    )
    apns_client = _StubClient([])  # must NOT be called
    fcm_client = _StubClient([_StubResponse(200, {"name": "ok"})])
    result = send_pod_ready_push(
        sender=_make_sender(apns_client),
        fcm_sender=_make_fcm_sender(fcm_client),
        repository=repo,
        user_id="u1",
        episode_title="Tuesday briefing",
    )
    assert result["delivered"] == 1
    assert apns_client.calls == []  # routed to FCM, not APNs
    assert len(fcm_client.calls) == 1


def test_pod_ready_legacy_ios_token_falls_back_to_apns():
    # A token with transport=None (registered before the field existed) routes
    # by platform: ios → APNs.
    repo = InMemoryControlPlaneRepository()
    repo.save_device_token(_make_device_token("u1", "a" * 64))  # transport unset
    apns_client = _StubClient([_StubResponse(200)])
    fcm_client = _StubClient([])  # must NOT be called
    result = send_pod_ready_push(
        sender=_make_sender(apns_client),
        fcm_sender=_make_fcm_sender(fcm_client),
        repository=repo,
        user_id="u1",
        episode_title="Tuesday briefing",
    )
    assert result["delivered"] == 1
    assert len(apns_client.calls) == 1
    assert fcm_client.calls == []


def test_send_pod_ready_push_deregisters_dead_tokens():
    repo = InMemoryControlPlaneRepository()
    repo.save_device_token(_make_device_token("u1", "a" * 64))
    repo.save_device_token(_make_device_token("u1", "b" * 64))

    client = _StubClient(
        [_StubResponse(410, {"reason": "Unregistered"}), _StubResponse(200)]
    )
    result = send_pod_ready_push(
        sender=_make_sender(client),
        repository=repo,
        user_id="u1",
        episode_title="Tuesday briefing",
    )
    assert result["deregistered"] == 1
    assert result["delivered"] == 1
    assert len(repo.list_active_device_tokens("u1")) == 1


def test_send_substack_push_skips_android_when_fcm_sender_none():
    repo = InMemoryControlPlaneRepository()
    repo.save_device_token(_make_device_token("u1", "a" * 64))  # ios
    repo.save_device_token(
        _make_android_device_token("u1", "AndroidToken" + "z" * 40)
    )  # android, no FCM sender → skipped

    apns_client = _StubClient([_StubResponse(200)])
    result = send_substack_verification_push(
        sender=_make_sender(apns_client),
        fcm_sender=None,
        repository=repo,
        user_id="u1",
        code="812807",
        pub_title="Noahpinion",
    )
    assert result == {"attempted": 1, "delivered": 1, "deregistered": 0}
    assert len(apns_client.calls) == 1
