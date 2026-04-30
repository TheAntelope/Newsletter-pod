from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timezone

import pytest
from fastapi.testclient import TestClient

from newsletter_pod.inbound import (
    InboundEmailHandler,
    InboundSignatureError,
    ensure_user_inbound_alias,
    extract_alias_from_recipient,
    extract_article_url,
    looks_like_confirmation,
    parse_email_address,
    verify_mailgun_signature,
)
from newsletter_pod.main import _build_container, create_app
from newsletter_pod.user_models import UserRecord


SIGNING_KEY = "test-signing-key"


def _sign(timestamp: str, token: str) -> str:
    return hmac.new(
        key=SIGNING_KEY.encode(),
        msg=f"{timestamp}{token}".encode(),
        digestmod=hashlib.sha256,
    ).hexdigest()


def _payload(*, recipient: str, sender: str, subject: str, body: str, message_id: str | None = None) -> dict[str, str]:
    timestamp = "1700000000"
    token = "test-token"
    payload = {
        "recipient": recipient,
        "from": sender,
        "subject": subject,
        "stripped-text": body,
        "Date": "Wed, 30 Apr 2026 12:00:00 +0000",
        "timestamp": timestamp,
        "token": token,
        "signature": _sign(timestamp, token),
    }
    if message_id is not None:
        payload["Message-Id"] = message_id
    return payload


def test_verify_mailgun_signature_round_trip():
    sig = _sign("1700000000", "abc")
    assert verify_mailgun_signature(
        signing_key=SIGNING_KEY, timestamp="1700000000", token="abc", signature=sig
    )
    assert not verify_mailgun_signature(
        signing_key=SIGNING_KEY, timestamp="1700000000", token="abc", signature="wrong"
    )


def test_extract_alias_from_recipient_strips_plus_tags_and_normalizes_case():
    assert extract_alias_from_recipient("A7F2BK9Q@clawcast.app", "clawcast.app") == "a7f2bk9q"
    assert extract_alias_from_recipient("a7f2bk9q+marketing@clawcast.app", "clawcast.app") == "a7f2bk9q"
    assert extract_alias_from_recipient("a7f2bk9q@somewhere.else", "clawcast.app") is None
    assert extract_alias_from_recipient("malformed", "clawcast.app") is None


def test_parse_email_address_handles_display_names():
    assert parse_email_address('"Ben Thompson" <ben@stratechery.com>') == ("ben@stratechery.com", "Ben Thompson")
    assert parse_email_address("ben@stratechery.com") == ("ben@stratechery.com", None)


def test_looks_like_confirmation_requires_subject_and_body_signal():
    # Both subject + body hit -> flagged.
    assert looks_like_confirmation(
        "Confirm your subscription",
        "Click here to confirm your subscription to Stratechery.",
    )
    # Subject hits, body does not -> still flagged (subject is decisive).
    assert looks_like_confirmation("Please confirm your email", "")
    # Subject misses -> not flagged even with confirm-y body.
    assert not looks_like_confirmation(
        "Today's Stratechery: Apple Earnings",
        "Read on the web. Click here to confirm.",
    )


def test_extract_article_url_picks_first_article_path():
    body = "Hi! Read on the web: https://stratechery.com/2026/article-name/ thanks."
    assert extract_article_url(body) == "https://stratechery.com/2026/article-name/"
    assert extract_article_url("no urls here") is None


def _build_app_with_user():
    from newsletter_pod.config import Settings

    settings = Settings.from_env()
    settings.use_inmemory_adapters = True
    settings.apple_client_id = "com.example"
    settings.session_signing_secret = "test-session-secret-32-bytes-long"
    settings.podcast_api_enabled = False
    settings.job_trigger_token = None
    settings.app_base_url = "http://testserver"
    settings.publish_summary_email_enabled = False
    settings.inbound_email_domain = "clawcast.app"
    settings.mailgun_webhook_signing_key = SIGNING_KEY
    container = _build_container(settings)

    repo = container.control_repository
    now = datetime(2026, 4, 30, tzinfo=timezone.utc)
    user = UserRecord(
        id="u1",
        apple_subject="apple-1",
        email="vince@example.com",
        display_name="Vince",
        timezone="UTC",
        inbound_alias="a7f2bk9q",
        created_at=now,
        updated_at=now,
    )
    repo.save_user(user)
    client = TestClient(create_app(container=container))
    return container, repo, user, client


def test_inbound_handler_stores_email_for_known_alias():
    container, repo, user, client = _build_app_with_user()
    payload = _payload(
        recipient="a7f2bk9q@clawcast.app",
        sender='"Ben Thompson" <newsletter@stratechery.com>',
        subject="Today's Stratechery",
        body="Read on the web: https://stratechery.com/2026/some-article/",
        message_id="<abc@stratechery.com>",
    )
    response = client.post("/webhooks/mailgun/inbound", data=payload)
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "stored"
    item = repo.get_inbound_item(body["item_id"])
    assert item is not None
    assert item.user_id == user.id
    assert item.from_email == "newsletter@stratechery.com"
    assert item.from_name == "Ben Thompson"
    assert item.sender_domain == "stratechery.com"
    assert item.subject == "Today's Stratechery"
    assert item.article_url == "https://stratechery.com/2026/some-article/"


def test_inbound_handler_returns_unauthorized_on_bad_signature():
    _, _, _, client = _build_app_with_user()
    payload = _payload(
        recipient="a7f2bk9q@clawcast.app",
        sender="x@y.com",
        subject="hi",
        body="body",
    )
    payload["signature"] = "tampered"
    response = client.post("/webhooks/mailgun/inbound", data=payload)
    assert response.status_code == 401


def test_inbound_handler_ignores_unknown_alias():
    _, _, _, client = _build_app_with_user()
    payload = _payload(
        recipient="ghost1234@clawcast.app",
        sender="x@y.com",
        subject="hi",
        body="body",
    )
    response = client.post("/webhooks/mailgun/inbound", data=payload)
    assert response.status_code == 200
    assert response.json()["status"] == "ignored"
    assert response.json()["reason"] == "unknown_alias"


def test_inbound_handler_skips_confirmation_emails():
    _, repo, _, client = _build_app_with_user()
    payload = _payload(
        recipient="a7f2bk9q@clawcast.app",
        sender="newsletter@example.com",
        subject="Please confirm your subscription",
        body="Click here to confirm your subscription.",
        message_id="<conf@example.com>",
    )
    response = client.post("/webhooks/mailgun/inbound", data=payload)
    assert response.status_code == 200
    assert response.json()["status"] == "skipped"
    assert response.json()["reason"] == "confirmation"


def test_inbound_handler_dedupes_on_message_id():
    _, repo, _, client = _build_app_with_user()
    payload = _payload(
        recipient="a7f2bk9q@clawcast.app",
        sender="x@y.com",
        subject="A digest",
        body="content",
        message_id="<dup@y.com>",
    )
    first = client.post("/webhooks/mailgun/inbound", data=payload)
    second = client.post("/webhooks/mailgun/inbound", data=payload)
    assert first.json()["status"] == "stored"
    assert second.json()["status"] == "duplicate"


def test_ensure_user_inbound_alias_generates_unique_value():
    container, repo, user, _ = _build_app_with_user()
    user.inbound_alias = None
    repo.save_user(user)
    fresh = repo.get_user(user.id)
    assert fresh is not None and fresh.inbound_alias is None
    alias = ensure_user_inbound_alias(repo, fresh)
    assert len(alias) == 8
    assert all(c in "abcdefghjkmnpqrstuvwxyz23456789" for c in alias)
    again = ensure_user_inbound_alias(repo, repo.get_user(user.id))
    assert again == alias  # idempotent


def test_handler_rejects_when_signing_key_missing():
    container, repo, user, _ = _build_app_with_user()
    handler = InboundEmailHandler(
        repository=repo,
        inbound_email_domain="clawcast.app",
        mailgun_signing_key=None,
    )
    with pytest.raises(Exception):
        handler.handle({"recipient": "a7f2bk9q@clawcast.app"})
