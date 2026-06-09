from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from newsletter_pod.config import Settings
from newsletter_pod.main import _build_container, create_app
from newsletter_pod.user_models import UserRecord


class _FakeVerifier:
    """Stand-in for Apple/Firebase verifiers: verify() ignores the token and
    returns a fixed identity (mirrors FakeAppleVerifier in test_control_plane_api)."""

    def __init__(
        self,
        subject: str,
        email: str | None = None,
        email_verified: bool = False,
    ) -> None:
        self.subject = subject
        self.email = email
        self.email_verified = email_verified

    def verify(self, _token: str):
        return type(
            "Identity",
            (),
            {
                "subject": self.subject,
                "email": self.email,
                "email_verified": self.email_verified,
            },
        )()


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


def test_list_users_by_email_normalizes_and_isolates():
    container, _client = _build_app()
    repo = container.control_plane.repository
    repo.save_user(UserRecord(id="u-a", email="Person@Example.com", created_at=_now(), updated_at=_now()))
    repo.save_user(UserRecord(id="u-b", email="other@example.com", created_at=_now(), updated_at=_now()))

    # Case-insensitive / trimmed match.
    assert {u.id for u in repo.list_users_by_email("  person@example.com ")} == {"u-a"}
    assert repo.list_users_by_email("missing@example.com") == []
    # Empty / None email never matches.
    assert repo.list_users_by_email("") == []


# --- Cross-provider account linking ------------------------------------------


def _apple_sign_in(client, container, subject, email=None, verified=False):
    container.control_plane.apple_identity_verifier = _FakeVerifier(subject, email, verified)
    return client.post("/v1/auth/apple", json={"identity_token": "t"}).json()


def _firebase_sign_in(client, container, subject, email=None, verified=False):
    container.control_plane.firebase_identity_verifier = _FakeVerifier(subject, email, verified)
    return client.post("/v1/auth/firebase", json={"id_token": "t"}).json()


def test_firebase_links_to_apple_account_via_verified_email():
    """The core fix: an Apple (iOS) user signing in with Google (Firebase) under
    the same verified email resolves to the SAME account, not a duplicate."""
    container, client = _build_app()
    apple = _apple_sign_in(client, container, "apple-sub", "vince@example.com", verified=True)

    fb = _firebase_sign_in(client, container, "fb-sub", "vince@example.com", verified=True)

    assert fb["is_new_user"] is False
    assert fb["user"]["id"] == apple["user"]["id"]  # same account
    # Both identities now resolve to the one account.
    repo = container.control_plane.repository
    assert repo.get_user_by_identity("apple", "apple-sub").id == apple["user"]["id"]
    assert repo.get_user_by_identity("firebase", "fb-sub").id == apple["user"]["id"]
    # The Apple account kept its legacy slots; Firebase identity was appended.
    user = repo.get_user(apple["user"]["id"])
    assert user.identity_provider == "apple" and user.apple_subject == "apple-sub"
    providers = {ident.provider for ident in user.identities}
    assert providers == {"apple", "firebase"}


def test_apple_links_to_firebase_account_via_verified_email():
    """Reverse direction: a Firebase (Android) user adding Apple sign-in links,
    and the previously-empty apple_subject slot is backfilled."""
    container, client = _build_app()
    fb = _firebase_sign_in(client, container, "fb-sub", "vince@example.com", verified=True)

    apple = _apple_sign_in(client, container, "apple-sub", "vince@example.com", verified=True)

    assert apple["is_new_user"] is False
    assert apple["user"]["id"] == fb["user"]["id"]
    user = container.control_plane.repository.get_user(fb["user"]["id"])
    # Firebase stayed the primary; apple_subject backfilled into the free slot.
    assert user.identity_provider == "firebase"
    assert user.apple_subject == "apple-sub"
    assert {i.provider for i in user.identities} == {"firebase", "apple"}


def test_no_link_when_email_unverified():
    """Account-takeover guard: an unverified email never links."""
    container, client = _build_app()
    apple = _apple_sign_in(client, container, "apple-sub", "vince@example.com", verified=True)

    fb = _firebase_sign_in(client, container, "fb-sub", "vince@example.com", verified=False)

    assert fb["is_new_user"] is True
    assert fb["user"]["id"] != apple["user"]["id"]  # separate account


def test_no_link_when_email_absent():
    container, client = _build_app()
    apple = _apple_sign_in(client, container, "apple-sub", "vince@example.com", verified=True)

    fb = _firebase_sign_in(client, container, "fb-sub", email=None, verified=True)

    assert fb["is_new_user"] is True
    assert fb["user"]["id"] != apple["user"]["id"]


def test_no_link_when_multiple_accounts_share_email():
    """Ambiguous (pre-existing duplicate) emails are not auto-merged at sign-in —
    that is the merge backfill's job. A third sign-in must not silently pick one."""
    container, client = _build_app()
    repo = container.control_plane.repository
    for i in (1, 2):
        repo.save_user(UserRecord(
            id=f"dup-{i}", email="dup@example.com",
            identity_provider="firebase", provider_subject=f"old-fb-{i}",
            created_at=_now(), updated_at=_now(),
        ))

    apple = _apple_sign_in(client, container, "apple-sub", "dup@example.com", verified=True)

    assert apple["is_new_user"] is True
    assert apple["user"]["id"] not in {"dup-1", "dup-2"}


def test_link_is_idempotent():
    """After linking, the linked identity resolves directly (step 1) and does not
    append a duplicate identity entry."""
    container, client = _build_app()
    _apple_sign_in(client, container, "apple-sub", "vince@example.com", verified=True)
    first = _firebase_sign_in(client, container, "fb-sub", "vince@example.com", verified=True)
    second = _firebase_sign_in(client, container, "fb-sub", "vince@example.com", verified=True)

    assert first["user"]["id"] == second["user"]["id"]
    assert second["is_new_user"] is False
    user = container.control_plane.repository.get_user(first["user"]["id"])
    fb_identities = [i for i in user.identities if i.provider == "firebase"]
    assert len(fb_identities) == 1


def test_link_matches_email_case_insensitively():
    container, client = _build_app()
    apple = _apple_sign_in(client, container, "apple-sub", "Vince@Example.com", verified=True)

    fb = _firebase_sign_in(client, container, "fb-sub", "vince@example.com", verified=True)

    assert fb["is_new_user"] is False
    assert fb["user"]["id"] == apple["user"]["id"]


def test_new_user_records_identity_and_normalized_email():
    container, client = _build_app()
    body = _firebase_sign_in(client, container, "fb-sub", "MixedCase@Example.com", verified=True)
    user = container.control_plane.repository.get_user(body["user"]["id"])
    assert user.email == "mixedcase@example.com"
    assert len(user.identities) == 1
    ident = user.identities[0]
    assert ident.provider == "firebase" and ident.subject == "fb-sub"
    assert ident.email_verified is True
