from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from newsletter_pod.config import Settings
from newsletter_pod.main import _build_container, create_app
from newsletter_pod.user_models import UserRecord


class _FakeVerifier:
    """Stand-in for Apple/Firebase verifiers: verify() ignores the token and
    returns a fixed identity (mirrors FakeAppleVerifier in test_control_plane_api)."""

    def __init__(self, subject: str, email: str | None = None) -> None:
        self.subject = subject
        self.email = email

    def verify(self, _token: str):
        return type("Identity", (), {"subject": self.subject, "email": self.email})()


def _build_app():
    settings = Settings.from_env()
    settings.use_inmemory_adapters = True
    settings.apple_client_id = "com.example.newsletterpod"
    settings.session_signing_secret = "test-session-secret-32-bytes-long"
    settings.podcast_api_enabled = False
    settings.job_trigger_token = None
    settings.app_base_url = "http://testserver"
    settings.publish_summary_email_enabled = False
    # firebase_project_id intentionally left unset (None) so the unconfigured
    # path is exercised unless a test swaps in a fake verifier.
    container = _build_container(settings)
    return container, TestClient(create_app(container=container))


def _now() -> datetime:
    return datetime.now(timezone.utc)


# --- Firebase sign-in --------------------------------------------------------


def test_firebase_sign_in_creates_neutral_user():
    container, client = _build_app()
    container.control_plane.firebase_identity_verifier = _FakeVerifier(
        "firebase-uid-1", "fb1@example.com"
    )

    resp = client.post("/v1/auth/firebase", json={"id_token": "fb-token"})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["is_new_user"] is True
    assert body["session_token"]
    user = body["user"]
    assert user["identity_provider"] == "firebase"
    assert user["provider_subject"] == "firebase-uid-1"
    # Firebase users have no Apple subject.
    assert user["apple_subject"] is None

    # Downstream is identity-agnostic: the neutral session works on /v1/me.
    headers = {"Authorization": f"Bearer {body['session_token']}"}
    me = client.get("/v1/me", headers=headers)
    assert me.status_code == 200, me.text
    assert me.json()["user"]["id"] == user["id"]


def test_firebase_sign_in_is_idempotent():
    container, client = _build_app()
    container.control_plane.firebase_identity_verifier = _FakeVerifier("firebase-uid-2")

    first = client.post("/v1/auth/firebase", json={"id_token": "t"}).json()
    second = client.post("/v1/auth/firebase", json={"id_token": "t"}).json()

    assert first["is_new_user"] is True
    assert second["is_new_user"] is False
    assert first["user"]["id"] == second["user"]["id"]


def test_firebase_auth_unconfigured_returns_400():
    # No project id configured and no fake verifier swapped in -> verify() raises
    # "FIREBASE_PROJECT_ID is not configured" before any network call.
    _container, client = _build_app()
    resp = client.post("/v1/auth/firebase", json={"id_token": "anything"})
    assert resp.status_code == 400
    assert "FIREBASE_PROJECT_ID" in resp.json()["detail"]


# --- Apple path stays intact + now dual-writes the neutral pair --------------


def test_apple_sign_in_dual_writes_identity():
    container, client = _build_app()
    container.control_plane.apple_identity_verifier = _FakeVerifier(
        "apple-sub-1", "a1@example.com"
    )

    body = client.post("/v1/auth/apple", json={"identity_token": "apple-token"}).json()
    user = body["user"]
    # apple_subject preserved (rollback-safe) AND neutral pair written.
    assert user["apple_subject"] == "apple-sub-1"
    assert user["identity_provider"] == "apple"
    assert user["provider_subject"] == "apple-sub-1"

    # The new neutral lookup resolves the same user.
    found = container.control_plane.repository.get_user_by_identity("apple", "apple-sub-1")
    assert found is not None and found.id == user["id"]


def test_apple_sign_in_backfills_legacy_user():
    container, client = _build_app()
    repo = container.control_plane.repository
    # Simulate a pre-migration row: apple_subject set, neutral pair absent.
    legacy = UserRecord(
        id="legacy-user-1",
        apple_subject="legacy-sub",
        created_at=_now(),
        updated_at=_now(),
    )
    repo.save_user(legacy)
    # Neutral index does not know it yet, but the Apple fallback still resolves it.
    assert repo.get_user_by_identity("apple", "legacy-sub").id == "legacy-user-1"

    container.control_plane.apple_identity_verifier = _FakeVerifier("legacy-sub")
    body = client.post("/v1/auth/apple", json={"identity_token": "x"}).json()
    assert body["is_new_user"] is False
    assert body["user"]["id"] == "legacy-user-1"

    # After sign-in the neutral pair is backfilled and persisted.
    healed = repo.get_user("legacy-user-1")
    assert healed.identity_provider == "apple"
    assert healed.provider_subject == "legacy-sub"


# --- Repository lookup semantics ---------------------------------------------


def test_get_user_by_identity_lookup_and_isolation():
    container, _client = _build_app()
    repo = container.control_plane.repository
    user = UserRecord(
        id="fb-user-x",
        identity_provider="firebase",
        provider_subject="fb-x",
        created_at=_now(),
        updated_at=_now(),
    )
    repo.save_user(user)

    assert repo.get_user_by_identity("firebase", "fb-x").id == "fb-user-x"
    # Wrong subject and non-apple provider without a match do not resolve, and
    # there is no cross-provider leakage to the Apple fallback.
    assert repo.get_user_by_identity("firebase", "nope") is None
    assert repo.get_user_by_identity("apple", "fb-x") is None
