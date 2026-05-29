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
    fetch_latest_post,
    is_substack_sender,
    is_substack_verification_code,
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


def test_is_substack_verification_code_extracts_code_from_subject():
    assert is_substack_verification_code("812807 is your Substack verification code") == "812807"
    assert is_substack_verification_code("210395 is your substack verification code") == "210395"
    # Tolerate trailing punctuation / extra trailing text.
    assert (
        is_substack_verification_code("606763 is your Substack verification code (action required)")
        == "606763"
    )
    # Leading whitespace is OK.
    assert is_substack_verification_code("  448869 is your Substack verification code") == "448869"


def test_is_substack_verification_code_rejects_non_matching_subjects():
    assert is_substack_verification_code("Today's Stratechery: Apple Earnings") is None
    assert is_substack_verification_code("Please confirm your subscription") is None
    # Don't grab arbitrary 6-digit numbers from unrelated subjects.
    assert is_substack_verification_code("Issue 812807 of our newsletter") is None
    assert is_substack_verification_code("") is None
    assert is_substack_verification_code(None) is None  # type: ignore[arg-type]


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


# ---------- fetch_latest_post ----------


_SAMPLE_FEED_XML = """<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel>
  <title>Letters from an American</title>
  <link>https://heathercoxrichardson.substack.com</link>
  <item>
    <title>May 11, 2026</title>
    <link>https://heathercoxrichardson.substack.com/p/may-11-2026</link>
    <description>&lt;p&gt;Today's letter &amp;mdash; news and analysis.&lt;/p&gt;</description>
    <pubDate>Sun, 11 May 2026 23:00:00 +0000</pubDate>
  </item>
  <item>
    <title>May 10, 2026</title>
    <link>https://heathercoxrichardson.substack.com/p/may-10-2026</link>
    <description>Older post body.</description>
    <pubDate>Sat, 10 May 2026 23:00:00 +0000</pubDate>
  </item>
</channel></rss>
"""


def test_fetch_latest_post_returns_first_entry_with_cleaned_summary():
    fake = _FakeSession(_FakeResponse(_SAMPLE_FEED_XML))
    post = fetch_latest_post(
        "https://heathercoxrichardson.substack.com/feed", session=fake
    )
    assert post is not None
    assert post.title == "May 11, 2026"
    assert post.link == "https://heathercoxrichardson.substack.com/p/may-11-2026"
    # HTML tags and entities stripped from the summary.
    assert post.summary == "Today's letter — news and analysis."
    assert post.published_at.year == 2026 and post.published_at.month == 5
    assert post.published_at.day == 11


def test_fetch_latest_post_returns_none_on_empty_feed():
    empty = '<?xml version="1.0"?><rss version="2.0"><channel></channel></rss>'
    fake = _FakeSession(_FakeResponse(empty))
    assert fetch_latest_post("https://x.substack.com/feed", session=fake) is None


def test_fetch_latest_post_returns_none_on_http_error():
    fake = _FakeSession(_FakeResponse("oops", status_code=502))
    assert fetch_latest_post("https://x.substack.com/feed", session=fake) is None


def test_fetch_latest_post_returns_none_on_request_exception():
    import requests as _requests

    class _Boom:
        def get(self, url, **kwargs):
            raise _requests.ConnectionError("nope")

    assert fetch_latest_post("https://x.substack.com/feed", session=_Boom()) is None


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


def _install_fake_probe_with_feed(
    monkeypatch,
    *,
    homepage_html: str,
    feed_xml: str,
    feed_status: int = 200,
) -> list[str]:
    """Fake stub that returns homepage_html for non-/feed URLs and feed_xml
    (with optional status code) for /feed URLs. Lets integration tests
    exercise both the probe path and the RSS prefetch path in one request.
    """
    calls: list[str] = []

    class _M:
        @staticmethod
        def get(url, **kwargs):
            calls.append(url)
            if url.rstrip("/").endswith("/feed"):
                return _FakeResponse(feed_xml, status_code=feed_status)
            return _FakeResponse(homepage_html)

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


def test_create_intent_prefetches_latest_post_into_inbound_items(monkeypatch):
    container, user, client, headers = _build_app_with_authenticated_user(monkeypatch)
    calls = _install_fake_probe_with_feed(
        monkeypatch,
        homepage_html='<meta property="og:title" content="Letters" />',
        feed_xml=_SAMPLE_FEED_XML,
    )
    response = client.post(
        "/v1/me/substack/intents",
        json={"pub_url": "heathercoxrichardson.substack.com"},
        headers=headers,
    )
    assert response.status_code == 201
    # Both the homepage probe and the /feed prefetch were attempted.
    assert any(url.endswith("/feed") for url in calls), calls

    items = container.control_repository.list_recent_inbound_items(user.id, limit=10)
    assert len(items) == 1
    item = items[0]
    assert item.subject == "May 11, 2026"
    assert item.article_url == "https://heathercoxrichardson.substack.com/p/may-11-2026"
    assert item.sender_domain == "heathercoxrichardson.substack.com"
    # No real email Message-Id for RSS-prefetched items.
    assert item.message_id is None
    # Body summary was cleaned (HTML stripped, entities unescaped).
    assert "Today's letter — news and analysis." in item.body_text


def test_create_intent_prefetch_is_idempotent_on_re_subscribe(monkeypatch):
    container, user, client, headers = _build_app_with_authenticated_user(monkeypatch)
    _install_fake_probe_with_feed(
        monkeypatch,
        homepage_html="<title>Pub</title>",
        feed_xml=_SAMPLE_FEED_XML,
    )
    payload = {"pub_url": "heathercoxrichardson.substack.com"}
    client.post("/v1/me/substack/intents", json=payload, headers=headers)
    client.post("/v1/me/substack/intents", json=payload, headers=headers)
    items = container.control_repository.list_recent_inbound_items(user.id, limit=10)
    # Second call hits the existing-intent short-circuit; first call's
    # URL-keyed inbound item is the only one we should see.
    assert len(items) == 1


def test_create_intent_survives_feed_fetch_failure(monkeypatch):
    container, user, client, headers = _build_app_with_authenticated_user(monkeypatch)
    _install_fake_probe_with_feed(
        monkeypatch,
        homepage_html="<title>Pub</title>",
        feed_xml="ignored",
        feed_status=503,
    )
    response = client.post(
        "/v1/me/substack/intents",
        json={"pub_url": "lenny.substack.com"},
        headers=headers,
    )
    # Intent creation still succeeds even though the prefetch HTTP 503'd.
    assert response.status_code == 201
    items = container.control_repository.list_recent_inbound_items(user.id, limit=10)
    assert items == []
