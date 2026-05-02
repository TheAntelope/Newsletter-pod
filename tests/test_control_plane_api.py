from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from newsletter_pod.ingestion import IngestionResult, RSSIngestionService
from newsletter_pod.main import _build_container, create_app
from newsletter_pod.models import AudioSegment, GeneratedEpisode, SourceItem
from newsletter_pod.user_models import UserEpisodeRecord


class FakeAppleVerifier:
    def __init__(self, subject: str, email: str) -> None:
        self.subject = subject
        self.email = email

    def verify(self, identity_token: str):
        return type(
            "Identity",
            (),
            {"subject": self.subject, "email": self.email},
        )()


class FakePodcastClient:
    def generate(
        self,
        prompt: str,
        title: str,
        voice_id: str | None = None,
        secondary_voice_id: str | None = None,
        primary_speaker_name: str | None = None,
    ) -> GeneratedEpisode:
        return GeneratedEpisode(
            episode_title="Weekly AI Briefing",
            audio_bytes=b"mp3-bytes",
            mime_type="audio/mpeg",
            show_notes="Generated notes",
            audio_segments=[
                AudioSegment(speaker="Elena", text="Welcome."),
                AudioSegment(speaker="Marcus", text="Here is the update."),
            ],
            transcript="Elena: Welcome.\nMarcus: Here is the update.",
            duration_seconds=120,
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
    settings.free_max_delivery_days = 1
    settings.paid_max_delivery_days = 3
    container = _build_container(settings)
    return container, TestClient(create_app(container=container))


def _auth_headers(client: TestClient, verifier: FakeAppleVerifier) -> tuple[str, dict[str, str]]:
    app = client.app
    app.state.container.control_plane.apple_identity_verifier = verifier
    response = client.post("/v1/auth/apple", json={"identity_token": "apple-token"})
    assert response.status_code == 200
    token = response.json()["session_token"]
    return token, {"Authorization": f"Bearer {token}"}


def test_schedule_patch_accepts_local_time():
    container, client = _build_app()
    _, headers = _auth_headers(client, FakeAppleVerifier("schedule-time-user", "tz@example.com"))

    # Default schedule was seeded by signup; patch local_time to a custom value.
    # Free tier is capped at free_max_delivery_days (=1 in tests), so use one weekday.
    resp = client.patch(
        "/v1/me/schedule",
        json={"timezone": "America/Chicago", "weekdays": ["monday"], "local_time": "06:30"},
        headers=headers,
    )
    assert resp.status_code == 200
    schedule = resp.json()["schedule"]
    assert schedule["local_time"] == "06:30"
    assert schedule["weekdays"] == ["monday"]

    # Non-numeric or out-of-range values should fail validation.
    bad = client.patch("/v1/me/schedule", json={"local_time": "25:00"}, headers=headers)
    assert bad.status_code == 400
    bad2 = client.patch("/v1/me/schedule", json={"local_time": "garbage"}, headers=headers)
    assert bad2.status_code == 400


def test_voice_catalog_returns_only_enabled_voices():
    container, client = _build_app()
    catalog = client.get("/v1/voices/catalog")
    assert catalog.status_code == 200
    voices = catalog.json()["voices"]
    # voices.yml ships with 2 enabled (Vinnie + Demi) and 8 disabled placeholders.
    # Loader filters the disabled ones out, so the catalog should never expose them.
    assert len(voices) >= 2
    ids = {v["id"] for v in voices}
    assert "suMMgpGbVcnihP1CcgFS" in ids  # Vinnie
    assert "RKCbSROXui75bk1SVpy8" in ids  # Demi
    for placeholder in ("TODO_VOICE_M1", "TODO_VOICE_F1"):
        assert placeholder not in ids
    for voice in voices:
        assert {"id", "name", "gender", "description"} <= set(voice.keys())


def test_welcome_episode_seeded_for_new_user_when_configured():
    from newsletter_pod.config import Settings
    from newsletter_pod.control_plane import (
        WELCOME_EPISODE_DESCRIPTION,
        WELCOME_EPISODE_TITLE,
    )

    settings = Settings.from_env()
    settings.use_inmemory_adapters = True
    settings.apple_client_id = "com.example.newsletterpod"
    settings.session_signing_secret = "test-session-secret-32-bytes-long"
    settings.podcast_api_enabled = False
    settings.job_trigger_token = None
    settings.app_base_url = "http://testserver"
    settings.publish_summary_email_enabled = False
    settings.welcome_episode_object_name = "static/welcome-v1.mp3"
    settings.welcome_episode_size_bytes = 12345
    settings.welcome_episode_duration_seconds = 150
    settings.welcome_episode_version = "v1"
    container = _build_container(settings)
    client = TestClient(create_app(container=container))

    container.control_plane.apple_identity_verifier = FakeAppleVerifier("welcome-user", "welcome@example.com")
    auth = client.post("/v1/auth/apple", json={"identity_token": "apple-token"})
    assert auth.status_code == 200
    user_id = auth.json()["user"]["id"]

    episodes = container.control_repository.list_recent_user_episodes(user_id, limit=10)
    assert len(episodes) == 1
    welcome = episodes[0]
    assert welcome.title == WELCOME_EPISODE_TITLE
    assert welcome.description == WELCOME_EPISODE_DESCRIPTION
    assert welcome.audio_object_name == "static/welcome-v1.mp3"
    assert welcome.audio_size_bytes == 12345
    assert welcome.duration_seconds == 150
    assert welcome.id.endswith("-welcome-v1")

    token_record = container.control_repository.get_feed_token(user_id)
    assert token_record
    feed = client.get(f"/feeds/{token_record.token}.xml")
    assert feed.status_code == 200
    assert WELCOME_EPISODE_TITLE in feed.text


def test_welcome_episode_not_seeded_when_object_name_unset():
    container, client = _build_app()
    assert container.settings.welcome_episode_object_name in (None, "")

    container.control_plane.apple_identity_verifier = FakeAppleVerifier("no-welcome-user", "no-welcome@example.com")
    auth = client.post("/v1/auth/apple", json={"identity_token": "apple-token"})
    assert auth.status_code == 200
    user_id = auth.json()["user"]["id"]

    episodes = container.control_repository.list_recent_user_episodes(user_id, limit=10)
    assert episodes == []


def test_control_plane_auth_profile_sources_and_schedule_limits():
    container, client = _build_app()
    _, headers = _auth_headers(client, FakeAppleVerifier("apple-user-1", "first@example.com"))

    me = client.patch("/v1/me", json={"display_name": "Vince", "timezone": "America/Chicago"}, headers=headers)
    assert me.status_code == 200
    assert me.json()["user"]["display_name"] == "Vince"
    assert me.json()["user"]["timezone"] == "America/Chicago"

    catalog = client.get("/v1/sources/catalog")
    assert catalog.status_code == 200
    sources = catalog.json()["sources"]
    assert len(sources) >= 2

    put_sources = client.put(
        "/v1/me/sources",
        json={"sources": [{"source_id": sources[0]["source_id"]}, {"source_id": sources[1]["source_id"]}]},
        headers=headers,
    )
    assert put_sources.status_code == 200
    assert len(put_sources.json()["sources"]) == 2

    patch_profile = client.patch(
        "/v1/me/podcast-config",
        json={
            "format_preset": "rotating_guest",
            "host_primary_name": "Vince",
            "guest_names": ["Alex", "Sam"],
            "desired_duration_minutes": 5,
        },
        headers=headers,
    )
    assert patch_profile.status_code == 200
    assert patch_profile.json()["profile"]["format_preset"] == "rotating_guest"

    over_cap_duration = client.patch(
        "/v1/me/podcast-config",
        json={"desired_duration_minutes": 8},
        headers=headers,
    )
    assert over_cap_duration.status_code == 400

    too_many_days = client.patch(
        "/v1/me/schedule",
        json={"weekdays": ["monday", "wednesday"]},
        headers=headers,
    )
    assert too_many_days.status_code == 400

    good_schedule = client.patch(
        "/v1/me/schedule",
        json={"weekdays": ["wednesday"], "timezone": "America/Chicago"},
        headers=headers,
    )
    assert good_schedule.status_code == 200
    assert good_schedule.json()["schedule"]["weekdays"] == ["wednesday"]


def test_paid_feed_isolation_and_billing_unlock():
    container, client = _build_app()
    _, headers_one = _auth_headers(client, FakeAppleVerifier("apple-user-1", "first@example.com"))
    _, headers_two = _auth_headers(client, FakeAppleVerifier("apple-user-2", "second@example.com"))

    user_one = client.get("/v1/me", headers=headers_one).json()["user"]
    user_two = client.get("/v1/me", headers=headers_two).json()["user"]

    billing = client.post(
        "/v1/billing/app-store/notifications",
        json={
            "user_id": user_one["id"],
            "notification_type": "DID_RENEW",
            "product_id": container.settings.app_store_monthly_product_id,
        },
    )
    assert billing.status_code == 200

    paid_schedule = client.patch(
        "/v1/me/schedule",
        json={"weekdays": ["monday", "wednesday", "friday"]},
        headers=headers_one,
    )
    assert paid_schedule.status_code == 200

    repo = container.control_repository
    storage = container.storage
    token_one = repo.get_feed_token(user_one["id"])
    token_two = repo.get_feed_token(user_two["id"])
    assert token_one and token_two

    object_name_one, size_one = storage.upload_audio("ep-one", b"one-audio", "audio/mpeg")
    object_name_two, size_two = storage.upload_audio("ep-two", b"two-audio", "audio/mpeg")
    repo.save_user_episode(
        UserEpisodeRecord(
            id="ep-one",
            user_id=user_one["id"],
            title="Episode One",
            description="Notes one",
            published_at=datetime(2026, 4, 15, 10, 0, tzinfo=timezone.utc),
            audio_object_name=object_name_one,
            audio_size_bytes=size_one,
        )
    )
    repo.save_user_episode(
        UserEpisodeRecord(
            id="ep-two",
            user_id=user_two["id"],
            title="Episode Two",
            description="Notes two",
            published_at=datetime(2026, 4, 15, 11, 0, tzinfo=timezone.utc),
            audio_object_name=object_name_two,
            audio_size_bytes=size_two,
        )
    )

    feed_one = client.get(f"/feeds/{token_one.token}.xml")
    assert feed_one.status_code == 200
    assert "Episode One" in feed_one.text
    assert "Episode Two" not in feed_one.text

    good_media = client.get(f"/media/{token_one.token}/ep-one.mp3")
    assert good_media.status_code == 200
    assert good_media.content == b"one-audio"

    wrong_media = client.get(f"/media/{token_one.token}/ep-two.mp3")
    assert wrong_media.status_code == 404


def test_generate_endpoint_starts_async_run_and_run_status_is_queryable(monkeypatch):
    container, client = _build_app()
    container.control_plane.apple_identity_verifier = FakeAppleVerifier("apple-user-async", "async@example.com")
    auth = client.post("/v1/auth/apple", json={"identity_token": "apple-token"})
    session_token = auth.json()["session_token"]
    headers = {"Authorization": f"Bearer {session_token}"}

    catalog = client.get("/v1/sources/catalog").json()["sources"]
    client.put(
        "/v1/me/sources",
        json={"sources": [{"source_id": catalog[0]["source_id"]}]},
        headers=headers,
    )

    container.control_plane.podcast_client = FakePodcastClient()

    def fake_fetch(self, sources):
        return IngestionResult(
            items=[
                SourceItem(
                    source_id="source-a",
                    source_name="Source A",
                    guid="1",
                    link="https://example.com/1",
                    title="Story",
                    summary="Body",
                    published_at=datetime(2026, 4, 28, 8, 0, tzinfo=timezone.utc),
                    dedupe_key="1",
                )
            ],
            cursor_updates={"source-a": datetime(2026, 4, 28, 8, 0, tzinfo=timezone.utc)},
        )

    monkeypatch.setattr(RSSIngestionService, "fetch_new_items", fake_fetch)

    start = client.post("/v1/me/generate", headers=headers)
    assert start.status_code == 202
    payload = start.json()
    assert payload["started"] is True
    run_id = payload["run"]["id"]
    assert run_id

    status = client.get(f"/v1/me/runs/{run_id}", headers=headers)
    assert status.status_code == 200
    body = status.json()
    assert body["run"]["id"] == run_id
    assert body["run"]["status"] in {"in_progress", "published", "no_content"}

    missing = client.get("/v1/me/runs/does-not-exist", headers=headers)
    assert missing.status_code == 404


def test_process_user_generation_records_visible_cap(monkeypatch):
    container, client = _build_app()
    container.control_plane.apple_identity_verifier = FakeAppleVerifier("apple-user-3", "third@example.com")
    auth = client.post("/v1/auth/apple", json={"identity_token": "apple-token"})
    user_id = auth.json()["user"]["id"]

    catalog = client.get("/v1/sources/catalog").json()["sources"]
    session_token = auth.json()["session_token"]
    headers = {"Authorization": f"Bearer {session_token}"}
    client.put(
        "/v1/me/sources",
        json={"sources": [{"source_id": catalog[0]["source_id"]}]},
        headers=headers,
    )

    container.settings.free_max_items_per_episode = 1
    container.control_plane.podcast_client = FakePodcastClient()

    def fake_fetch(self, sources):
        return IngestionResult(
            items=[
                SourceItem(
                    source_id="source-a",
                    source_name="Source A",
                    guid="1",
                    link="https://example.com/1",
                    title="Story One",
                    summary="Summary one",
                    published_at=datetime(2026, 4, 15, 8, 0, tzinfo=timezone.utc),
                    dedupe_key="1",
                ),
                SourceItem(
                    source_id="source-a",
                    source_name="Source A",
                    guid="2",
                    link="https://example.com/2",
                    title="Story Two",
                    summary="Summary two",
                    published_at=datetime(2026, 4, 15, 9, 0, tzinfo=timezone.utc),
                    dedupe_key="2",
                ),
            ],
            cursor_updates={"source-a": datetime(2026, 4, 15, 9, 0, tzinfo=timezone.utc)},
        )

    monkeypatch.setattr(RSSIngestionService, "fetch_new_items", fake_fetch)

    result = client.post("/jobs/process-user-podcast", json={"user_id": user_id, "force": True})
    assert result.status_code == 200
    payload = result.json()
    assert payload["run"]["cap_hit"] is True
    assert payload["run"]["dropped_item_count"] == 1
    description = payload["episode"]["description"]
    assert "item cap" in description
    assert "**Sources**" in description
    assert "- **Source A** — [Story Two](https://example.com/2)" in description
    assert "https://example.com/1" not in description
