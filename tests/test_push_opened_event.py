"""Tests for POST /v1/me/push-opened (notification-tap analytics).

Covers the happy path (a PUSH_OPENED app_event is emitted with the push type
and the caller's user id), normalization, input validation, and auth.
"""
from __future__ import annotations

import json

from fastapi.testclient import TestClient

from newsletter_pod.main import _build_container, create_app

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


def _signin(client, subject: str):
    _, headers = _auth_headers(client, FakeAppleVerifier(subject, f"{subject}@example.com"))
    user_id = client.get("/v1/me", headers=headers).json()["user"]["id"]
    return headers, user_id


def _app_events(caplog) -> list[dict]:
    events = []
    for record in caplog.records:
        try:
            payload = json.loads(record.getMessage())
        except (ValueError, TypeError):
            continue
        if isinstance(payload, dict) and payload.get("event") == "app_event":
            events.append(payload)
    return events


def test_push_opened_logs_event_with_type_and_user(caplog):
    _, client = _build_app()
    headers, user_id = _signin(client, "push-open-1")

    with caplog.at_level("INFO", logger="newsletter_pod.events"):
        resp = client.post(
            "/v1/me/push-opened", headers=headers, json={"push_type": "pod_ready"}
        )

    assert resp.status_code == 200, resp.text
    assert resp.json() == {"ok": True}

    events = [e for e in _app_events(caplog) if e["event_name"] == "push_opened"]
    assert len(events) == 1
    assert events[0]["user_id"] == user_id
    assert events[0]["properties"] == {"push_type": "pod_ready"}


def test_push_opened_normalizes_case_and_whitespace(caplog):
    _, client = _build_app()
    headers, _ = _signin(client, "push-open-2")

    with caplog.at_level("INFO", logger="newsletter_pod.events"):
        resp = client.post(
            "/v1/me/push-opened", headers=headers, json={"push_type": "  Trial_Gift "}
        )

    assert resp.status_code == 200, resp.text
    events = [e for e in _app_events(caplog) if e["event_name"] == "push_opened"]
    assert events[0]["properties"] == {"push_type": "trial_gift"}


def test_push_opened_rejects_malformed_types():
    _, client = _build_app()
    headers, _ = _signin(client, "push-open-3")

    for bad in ["", "has space", "über", "x" * 33, "semi;colon"]:
        resp = client.post(
            "/v1/me/push-opened", headers=headers, json={"push_type": bad}
        )
        assert resp.status_code == 400, f"push_type={bad!r}: {resp.text}"


def test_push_opened_requires_session():
    _, client = _build_app()
    resp = client.post("/v1/me/push-opened", json={"push_type": "pod_ready"})
    assert resp.status_code == 401
