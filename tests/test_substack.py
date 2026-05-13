"""Tests for newsletter_pod.substack helpers + Substack intent endpoints."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest
from fastapi.testclient import TestClient

from newsletter_pod import substack as substack_module
from newsletter_pod.main import _build_container, create_app
from newsletter_pod.substack import (
    build_intent_id,
    canonicalize_pub_url,
    extract_confirm_url,
    is_substack_sender,
    match_intent_host,
    probe_publication,
)
from newsletter_pod.user_models import UserRecord


# ---------- canonicalization ----------


@pytest.mark.parametrize(
    "raw, expected_url, expected_host",
    [
        (
            "heathercoxrichardson.substack.com",
            "https://heathercoxrichardson.substack.com",
            "heathercoxrichardson.substack.com",
        ),
        (
            "https://heathercoxrichardson.substack.com",
            "https://heathercoxrichardson.substack.com",
            "heathercoxrichardson.substack.com",
        ),
        (
            "https://heathercoxrichardson.substack.com/p/some-post",
            "https://heathercoxrichardson.substack.com",
            "heathercoxrichardson.substack.com",
        ),
        (
            "  HTTPS://HEATHERCOXRICHARDSON.SUBSTACK.COM/  ",
            "https://heathercoxrichardson.substack.com",
            "heathercoxrichardson.substack.com",
        ),
        (
            "@lenny",
            "https://lenny.substack.com",
            "lenny.substack.com",
        ),
        (
            "custom-domain.example.com",
            "https://custom-domain.example.com",
            "custom-domain.example.com",
        ),
    ],
)
def test_canonicalize_pub_url_accepts_various_inputs(raw, expected_url, expected_host):
    pub_url, host = canonicalize_pub_url(raw)
    assert pub_url == expected_url
    assert host == expected_host


@pytest.mark.parametrize("bad", ["", "   ", "@", "@ bad handle", "not-a-host"])
def test_canonicalize_pub_url_rejects_garbage(bad):
    with pytest.raises(ValueError):
        canonicalize_pub_url(bad)


def test_build_intent_id_is_deterministic_per_user_pub():
    a = build_intent_id("user-1", "heathercoxrichardson.substack.com")
    b = build_intent_id("user-1", "heathercoxrichardson.substack.com")
    c = build_intent_id("user-2", "heathercoxrichardson.substack.com")
    d = build_intent_id("user-1", "lenny.substack.com")
    assert a == b
    assert a != c
    assert a != d
    # Case-insensitive on host.
    assert a == build_intent_id("user-1", "HeatherCoxRichardson.Substack.com")


# ---------- sender / link matching ----------


def test_is_substack_sender_matches_substack_addresses():
    assert is_substack_sender("no-reply@substack.com")
    assert is_substack_sender("hello@mg.substack.com")
    assert is_substack_sender("ALERT@SUBSTACK.COM")
    assert not is_substack_sender("ben@stratechery.com")
    assert not is_substack_sender("")
    assert not is_substack_sender("no-at-sign")


def test_extract_confirm_url_finds_redeem_link_in_html():
    html = (
        '<html><body><a href="https://substack.com/redeem/abc123def456?token=xyz">'
        "Confirm subscription</a></body></html>"
    )
    assert extract_confirm_url("", html) == "https://substack.com/redeem/abc123def456?token=xyz"


def test_extract_confirm_url_finds_subdomain_confirm_link():
    body = (
        "Click to confirm your subscription: "
        "https://heathercoxrichardson.substack.com/subscribe/confirm?email=foo "
        "thanks"
    )
    assert (
        extract_confirm_url(body, "")
        == "https://heathercoxrichardson.substack.com/subscribe/confirm?email=foo"
    )


def test_extract_confirm_url_returns_none_when_no_substack_link():
    assert extract_confirm_url("Just text", "<p>nothing relevant</p>") is None
    assert extract_confirm_url("", "") is None


def test_match_intent_host_direct_sender_match():
    intents = ["lenny.substack.com", "heathercoxrichardson.substack.com"]
    matched = match_intent_host(intents, "heathercoxrichardson.substack.com")
    assert matched == "heathercoxrichardson.substack.com"


def test_match_intent_host_finds_pub_host_in_body_when_sender_is_generic():
    intents = ["heathercoxrichardson.substack.com"]
    body = (
        "Confirm your subscription to Letters from an American: "
        "https://heathercoxrichardson.substack.com/subscribe/confirm/..."
    )
    matched = match_intent_host(intents, "no-reply@substack.com", body_text=body)
    # sender_domain here is just the bare domain; helper splits in handler.
    assert matched is None or matched == "heathercoxrichardson.substack.com"

    # Now with a proper sender_domain string the caller would compute:
    matched = match_intent_host(intents, "substack.com", body_text=body)
    assert matched == "heathercoxrichardson.substack.com"


def test_match_intent_host_no_match_when_nothing_lines_up():
    intents = ["lenny.substack.com"]
    matched = match_intent_host(intents, "newsletter@example.com", body_text="hi")
    assert matched is None


# ---------- probe_publication ----------


class _FakeResponse:
    def __init__(self, text: str, status_code: int = 200):
        self.text = text
        self.status_code = status_code
        self.ok = 200 <= status_code < 400

    def raise_for_status(self) -> None:
        if not self.ok:
            import requests

            raise requests.HTTPError(f"HTTP {self.status_code}")


class _FakeSession:
    def __init__(self, response: _FakeResponse):
        self.response = response
        self.calls: list[tuple[str, dict]] = []

    def get(self, url, **kwargs):
        self.calls.append((url, kwargs))
        return self.response


def test_probe_publication_extracts_title_author_icon_and_paid_signal():
    html = """
    <!DOCTYPE html><html><head>
      <title>Some Publication</title>
      <meta property="og:title" content="Letters from an American" />
      <meta name="author" content="Heather Cox Richardson" />
      <meta property="og:image" content="https://substackcdn.com/icon.png" />
      <script>{"hasPaidPlans":true,"name":"Letters"}</script>
    </head><body>Welcome.</body></html>
    """
    fake = _FakeSession(_FakeResponse(html))
    result = probe_publication("https://heathercoxrichardson.substack.com", session=fake)
    assert result.pub_url == "https://heathercoxrichardson.substack.com"
    assert result.pub_host == "heathercoxrichardson.substack.com"
    assert result.title == "Letters from an American"
    assert result.author == "Heather Cox Richardson"
    assert result.icon_url == "https://substackcdn.com/icon.png"
    assert result.has_paid_tier is True
    assert result.feed_url == "https://heathercoxrichardson.substack.com/feed"
    # The call used our canonical https URL.
    assert fake.calls[0][0] == "https://heathercoxrichardson.substack.com"


def test_probe_publication_returns_none_fields_when_metadata_missing():
    html = "<html><body>Just text. No metadata at all.</body></html>"
    fake = _FakeSession(_FakeResponse(html))
    result = probe_publication("lenny.substack.com", session=fake)
    assert result.title is None
    assert result.author is None
    assert result.icon_url is None
    assert result.has_paid_tier is False


def test_probe_publication_raises_on_http_error():
    import requests

    fake = _FakeSession(_FakeResponse("nope", status_code=502))
    with pytest.raises(requests.HTTPError):
        probe_publication("https://broken.substack.com", session=fake)


# ---------- endpoint integration ----------

SIGNING_KEY = "test-signing-key"


def _build_app_with_authenticated_user(monkeypatch):
    from newsletter_pod.config import Settings

    settings = Settings.from_env()
    settings.use_inmemory_adapters = True
    settings.apple_client_id = "com.example"
    settings.session_signing_secret = "test-session-secret-32-bytes-long"
    settings.podcast_api_enabled = False
    settings.job_trigger_token = None
    settings.app_base_url = "http://testserver"
    settings.publish_summary_email_enabled = False
    settings.inbound_email_domain = "theclawcast.com"
    settings.mailgun_webhook_signing_key = SIGNING_KEY
    container = _build_container(settings)

    now = datetime(2026, 5, 12, tzinfo=timezone.utc)
    user = UserRecord(
        id="u1",
        apple_subject="apple-1",
        email="vince@example.com",
        display_name="Vince",
        timezone="UTC",
        inbound_alias="sdke2jm",
        created_at=now,
        updated_at=now,
    )
    container.control_repository.save_user(user)

    class _FakeVerifier:
        def verify(self, identity_token: str):
            return type("Identity", (), {"subject": user.apple_subject, "email": user.email})()

    container.control_plane.apple_identity_verifier = _FakeVerifier()
    client = TestClient(create_app(container=container))
    auth = client.post("/v1/auth/apple", json={"identity_token": "tok"}).json()
    headers = {"Authorization": f"Bearer {auth['session_token']}"}
    return container, user, client, headers


def _install_fake_probe(monkeypatch, html: str = "<title>Pub</title>") -> list[str]:
    """Replace substack_module.requests with a fake that always returns html.

    Returns the call log so tests can assert on it.
    """
    calls: list[str] = []

    class _M:
        @staticmethod
        def get(url, **kwargs):
            calls.append(url)
            return _FakeResponse(html)

    monkeypatch.setattr(substack_module, "requests", _M)
    return calls


def test_probe_endpoint_returns_metadata(monkeypatch):
    _, _, client, _ = _build_app_with_authenticated_user(monkeypatch)
    _install_fake_probe(
        monkeypatch,
        html='<meta property="og:title" content="Heather Cox Richardson" />'
        '<meta name="author" content="HCR" />',
    )
    response = client.get(
        "/v1/substack/probe",
        params={"url": "heathercoxrichardson.substack.com"},
    )
    assert response.status_code == 200
    body = response.json()
    assert body["pub_host"] == "heathercoxrichardson.substack.com"
    assert body["title"] == "Heather Cox Richardson"
    assert body["author"] == "HCR"
    assert body["feed_url"] == "https://heathercoxrichardson.substack.com/feed"


def test_probe_endpoint_400s_on_unreachable_pub(monkeypatch):
    _, _, client, _ = _build_app_with_authenticated_user(monkeypatch)
    import requests

    class _M:
        @staticmethod
        def get(url, **kwargs):
            raise requests.ConnectionError("nope")

    monkeypatch.setattr(substack_module, "requests", _M)
    response = client.get(
        "/v1/substack/probe",
        params={"url": "https://broken.substack.com"},
    )
    assert response.status_code == 400


def test_create_intent_is_idempotent_per_pub(monkeypatch):
    _, user, client, headers = _build_app_with_authenticated_user(monkeypatch)
    _install_fake_probe(
        monkeypatch,
        html='<meta property="og:title" content="HCR" />',
    )
    payload = {"pub_url": "https://heathercoxrichardson.substack.com"}
    first = client.post("/v1/me/substack/intents", json=payload, headers=headers)
    assert first.status_code == 201
    intent_id = first.json()["intent"]["id"]
    second = client.post("/v1/me/substack/intents", json=payload, headers=headers)
    # Same id, no duplicate row.
    assert second.status_code == 201
    assert second.json()["intent"]["id"] == intent_id


def test_create_intent_records_alias_snapshot(monkeypatch):
    _, user, client, headers = _build_app_with_authenticated_user(monkeypatch)
    _install_fake_probe(monkeypatch, html="<title>Pub</title>")
    payload = {"pub_url": "lenny.substack.com"}
    response = client.post("/v1/me/substack/intents", json=payload, headers=headers)
    assert response.status_code == 201
    intent = response.json()["intent"]
    assert intent["alias_email"] == "sdke2jm@theclawcast.com"
    assert intent["status"] == "pending"


def test_list_intents_returns_user_subscriptions(monkeypatch):
    _, _, client, headers = _build_app_with_authenticated_user(monkeypatch)
    _install_fake_probe(monkeypatch, html="<title>Pub</title>")
    client.post(
        "/v1/me/substack/intents",
        json={"pub_url": "lenny.substack.com"},
        headers=headers,
    )
    client.post(
        "/v1/me/substack/intents",
        json={"pub_url": "heathercoxrichardson.substack.com"},
        headers=headers,
    )
    response = client.get("/v1/me/substack/intents", headers=headers)
    assert response.status_code == 200
    body = response.json()
    hosts = sorted(intent["pub_host"] for intent in body["intents"])
    assert hosts == ["heathercoxrichardson.substack.com", "lenny.substack.com"]
    assert body["inbound_address"] == "sdke2jm@theclawcast.com"


def test_delete_intent_removes_it(monkeypatch):
    _, _, client, headers = _build_app_with_authenticated_user(monkeypatch)
    _install_fake_probe(monkeypatch, html="<title>Pub</title>")
    created = client.post(
        "/v1/me/substack/intents",
        json={"pub_url": "lenny.substack.com"},
        headers=headers,
    ).json()
    intent_id = created["intent"]["id"]
    deleted = client.delete(
        f"/v1/me/substack/intents/{intent_id}",
        headers=headers,
    )
    assert deleted.status_code == 200
    assert deleted.json()["deleted"] is True
    # Subsequent list should be empty.
    listed = client.get("/v1/me/substack/intents", headers=headers).json()
    assert listed["intents"] == []


def test_delete_intent_404s_for_unknown_id(monkeypatch):
    _, _, client, headers = _build_app_with_authenticated_user(monkeypatch)
    response = client.delete(
        "/v1/me/substack/intents/does-not-exist",
        headers=headers,
    )
    assert response.status_code == 404
