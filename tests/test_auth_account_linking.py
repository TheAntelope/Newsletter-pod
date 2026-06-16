"""Login-time cross-provider account linking by verified email (R1b).

When a sign-in has no account for its own identity but a verified email matches
exactly one existing account that lacks an identity for that provider, we attach
the new identity to that account instead of creating a duplicate. Linking is
non-destructive (no data moved, no delete) and conservative (verified email only,
skip Apple relay addresses, skip ambiguous/conflicting matches).
"""
from __future__ import annotations

from fastapi.testclient import TestClient

from newsletter_pod.main import _build_container, create_app
from newsletter_pod.user_models import AppleIdentity, FirebaseIdentity


class _FakeAppleVerifier:
    def __init__(self, subject: str, email=None, email_verified: bool = True) -> None:
        self._identity = AppleIdentity(subject=subject, email=email, email_verified=email_verified)

    def verify(self, identity_token: str) -> AppleIdentity:
        return self._identity


class _FakeFirebaseVerifier:
    def __init__(self, subject: str, email=None, email_verified: bool = True) -> None:
        self._identity = FirebaseIdentity(subject=subject, email=email, email_verified=email_verified)

    def verify(self, id_token: str) -> FirebaseIdentity:
        return self._identity


def _build_app():
    from newsletter_pod.config import Settings

    settings = Settings.from_env()
    settings.use_inmemory_adapters = True
    settings.apple_client_id = "com.example.newsletterpod"
    settings.firebase_project_id = "theclawcast-9a045"
    settings.session_signing_secret = "test-session-secret-32-bytes-long"
    settings.podcast_api_enabled = False
    settings.job_trigger_token = None
    settings.alert_email_enabled = False
    settings.publish_summary_email_enabled = False
    settings.feedback_digest_email_enabled = False
    container = _build_container(settings)
    return container, TestClient(create_app(container=container))


def _apple(client: TestClient, subject: str, *, email=None, email_verified: bool = True):
    client.app.state.container.control_plane.apple_identity_verifier = _FakeAppleVerifier(
        subject, email, email_verified
    )
    return client.post("/v1/auth/apple", json={"identity_token": "tok"})


def _firebase(client: TestClient, subject: str, *, email=None, email_verified: bool = True):
    client.app.state.container.control_plane.firebase_identity_verifier = _FakeFirebaseVerifier(
        subject, email, email_verified
    )
    return client.post("/v1/auth/firebase", json={"id_token": "tok"})


def _user_count(container) -> int:
    return len(container.control_repository._users)


# ---------- linking happy paths ----------


def test_apple_then_google_same_email_links_to_one_account():
    container, client = _build_app()
    a = _apple(client, "apple-sub-1", email="user@gmail.com")
    assert a.status_code == 200 and a.json()["is_new_user"] is True
    g = _firebase(client, "fb-sub-1", email="user@gmail.com")
    assert g.status_code == 200
    # Linked onto the existing Apple account, not a new user.
    assert g.json()["is_new_user"] is False
    assert _user_count(container) == 1
    # Both identities now resolve, and both sessions work.
    assert client.get("/v1/me", headers={"Authorization": f"Bearer {a.json()['session_token']}"}).status_code == 200
    assert client.get("/v1/me", headers={"Authorization": f"Bearer {g.json()['session_token']}"}).status_code == 200


def test_google_then_apple_same_email_links_to_one_account():
    container, client = _build_app()
    g = _firebase(client, "fb-sub-2", email="dual@gmail.com")
    assert g.status_code == 200 and g.json()["is_new_user"] is True
    a = _apple(client, "apple-sub-2", email="dual@gmail.com")
    assert a.status_code == 200
    assert a.json()["is_new_user"] is False
    assert _user_count(container) == 1


def test_link_is_case_insensitive_on_email():
    container, client = _build_app()
    _apple(client, "apple-sub-3", email="Mixed.Case@Gmail.com")
    g = _firebase(client, "fb-sub-3", email="mixed.case@gmail.com")
    assert g.json()["is_new_user"] is False
    assert _user_count(container) == 1


# ---------- conservative guards (must NOT link) ----------


def test_unverified_email_does_not_link():
    container, client = _build_app()
    _apple(client, "apple-sub-4", email="x@gmail.com", email_verified=True)
    g = _firebase(client, "fb-sub-4", email="x@gmail.com", email_verified=False)
    assert g.json()["is_new_user"] is True  # created, not linked
    assert _user_count(container) == 2


def test_apple_private_relay_email_does_not_link():
    container, client = _build_app()
    # An account already carries the relay address (contrived), then an Apple
    # sign-in presents the same relay email — the relay guard must skip linking.
    _firebase(client, "fb-sub-5", email="abc123@privaterelay.appleid.com")
    a = _apple(client, "apple-sub-5", email="abc123@privaterelay.appleid.com")
    assert a.json()["is_new_user"] is True
    assert _user_count(container) == 2


def test_second_google_cannot_hijack_an_already_linked_account():
    container, client = _build_app()
    _apple(client, "apple-sub-6", email="shared@gmail.com")
    g1 = _firebase(client, "fb-sub-6a", email="shared@gmail.com")
    assert g1.json()["is_new_user"] is False  # linked onto the Apple account
    assert _user_count(container) == 1
    # A different Google identity with the same email must NOT steal the account.
    g2 = _firebase(client, "fb-sub-6b", email="shared@gmail.com")
    assert g2.json()["is_new_user"] is True
    assert _user_count(container) == 2


def test_ambiguous_email_match_does_not_link():
    container, client = _build_app()
    # Two accounts end up sharing an email (Apple acct + an unlinkable Google acct).
    _apple(client, "apple-sub-7", email="amb@gmail.com")
    _firebase(client, "fb-sub-7a", email="amb@gmail.com")  # links → still 1
    _firebase(client, "fb-sub-7b", email="amb@gmail.com")  # can't hijack → 2 accts share the email
    assert _user_count(container) == 2
    # A fresh Apple identity with that email now sees an ambiguous (2) match → no link.
    a = _apple(client, "apple-sub-7c", email="amb@gmail.com")
    assert a.json()["is_new_user"] is True
    assert _user_count(container) == 3


def test_no_email_does_not_link():
    container, client = _build_app()
    _apple(client, "apple-sub-8", email="noemail@gmail.com")
    g = _firebase(client, "fb-sub-8", email=None)  # Apple omits email after first auth
    assert g.json()["is_new_user"] is True
    assert _user_count(container) == 2


# ---------- regression: existing identity still resolves directly ----------


def test_linking_failure_falls_back_to_account_creation_not_500():
    # Linking is best-effort on the hot auth path: if the email lookup (or the
    # persist) blows up, sign-in must still succeed by creating an account —
    # never a 500.
    container, client = _build_app()
    _apple(client, "apple-sub-10", email="resilient@gmail.com")

    def boom(email):
        raise RuntimeError("firestore unavailable")

    container.control_repository.get_user_by_email = boom
    g = _firebase(client, "fb-sub-10", email="resilient@gmail.com")
    assert g.status_code == 200
    assert g.json()["is_new_user"] is True  # fell back to creation, no crash
    assert _user_count(container) == 2


def test_returning_apple_user_resolves_without_creating_a_duplicate():
    container, client = _build_app()
    first = _apple(client, "apple-sub-9", email="return@gmail.com")
    assert first.json()["is_new_user"] is True
    second = _apple(client, "apple-sub-9", email="return@gmail.com")
    assert second.json()["is_new_user"] is False
    assert _user_count(container) == 1
