"""Tests for newsletter_pod.push — APNs sender + Substack verification push."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

from newsletter_pod.push import (
    PushSender,
    build_push_sender_from_settings,
    build_substack_verification_payload,
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
