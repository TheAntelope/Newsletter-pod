from __future__ import annotations

import math
from datetime import datetime, timezone

from fastapi.testclient import TestClient

from newsletter_pod.ingestion import IngestionResult, RSSIngestionService
from newsletter_pod.main import _build_container, create_app
from newsletter_pod.models import AudioSegment, GeneratedEpisode, SourceItem
from newsletter_pod.user_models import (
    InboundEmailItem,
    SwipeRecord,
    UserEpisodeRecord,
    UserSubstackIntent,
)


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


class FakeAppStoreVerifier:
    """Stand-in for `AppStoreNotificationVerifier` during tests. Lets a test
    seed the decoded notification it wants `verify` to return for any given
    signed_payload string; an unknown string raises
    `AppStoreVerificationError` so the bad-signature path is also coverable."""

    def __init__(self) -> None:
        self.results: dict[str, object] = {}
        self.transactions: dict[str, object] = {}

    def stub(self, signed_payload: str, decoded) -> None:
        self.results[signed_payload] = decoded

    def stub_transaction(self, signed_transaction_info: str, decoded) -> None:
        self.transactions[signed_transaction_info] = decoded

    def verify(self, signed_payload: str):
        from newsletter_pod.app_store_verifier import AppStoreVerificationError

        if signed_payload not in self.results:
            raise AppStoreVerificationError("signature mismatch")
        return self.results[signed_payload]

    def verify_transaction(self, signed_transaction_info: str):
        from newsletter_pod.app_store_verifier import AppStoreVerificationError

        if signed_transaction_info not in self.transactions:
            raise AppStoreVerificationError("signature mismatch")
        return self.transactions[signed_transaction_info]


class FakePodcastClient:
    def generate(
        self,
        prompt: str,
        title: str,
        voice_id: str | None = None,
        secondary_voice_id: str | None = None,
        primary_speaker_name: str | None = None,
        secondary_speaker_name: str | None = None,
        ux=None,
        force_default_voice: bool = False,
    ) -> GeneratedEpisode:
        return GeneratedEpisode(
            episode_title="Weekly AI Briefing",
            audio_bytes=b"mp3-bytes",
            mime_type="audio/mpeg",
            show_notes="Generated notes",
            audio_segments=[
                AudioSegment(role="primary", speaker="Elena", text="Welcome."),
                AudioSegment(role="secondary", speaker="Marcus", text="Here is the update."),
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
    settings.pro_max_delivery_days = 3
    settings.max_max_delivery_days = 3
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


def test_feedback_endpoint_translates_and_persists(monkeypatch):
    from newsletter_pod import control_plane as cp_module

    container, client = _build_app()
    _, headers = _auth_headers(client, FakeAppleVerifier("feedback-user", "fb@example.com"))

    seen = {}

    def fake_translate(text, *, api_key, text_model, base_url, locale_hint):
        seen["text"] = text
        seen["locale_hint"] = locale_hint
        return f"[en] {text}"

    monkeypatch.setattr(cp_module, "translate_to_english", fake_translate)

    resp = client.post(
        "/v1/me/feedback",
        json={"text": "  ¡Me encanta!  ", "locale_hint": "es-ES", "source": "voice"},
        headers=headers,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["raw_text"] == "¡Me encanta!"
    assert body["english_text"] == "[en] ¡Me encanta!"
    assert body["locale_hint"] == "es-ES"
    assert body["source"] == "voice"
    assert seen == {"text": "¡Me encanta!", "locale_hint": "es-ES"}

    user_id = body["user_id"]
    stored = container.control_repository.list_recent_feedback(user_id, limit=5)
    assert len(stored) == 1
    assert stored[0].english_text == "[en] ¡Me encanta!"

    empty = client.post("/v1/me/feedback", json={"text": "   "}, headers=headers)
    assert empty.status_code == 400


def test_feedback_translation_failure_still_persists_raw(monkeypatch):
    from newsletter_pod import control_plane as cp_module
    from newsletter_pod.translation import TranslationError

    container, client = _build_app()
    _, headers = _auth_headers(client, FakeAppleVerifier("fb-fail-user", "fb-fail@example.com"))

    def boom(*args, **kwargs):
        raise TranslationError("upstream down")

    monkeypatch.setattr(cp_module, "translate_to_english", boom)

    resp = client.post("/v1/me/feedback", json={"text": "hola"}, headers=headers)
    assert resp.status_code == 201
    body = resp.json()
    assert body["raw_text"] == "hola"
    assert body["english_text"] is None
    user_id = body["user_id"]
    stored = container.control_repository.list_recent_feedback(user_id, limit=5)
    assert len(stored) == 1


class _RecordingMailer:
    def __init__(self) -> None:
        self.sent: list[tuple[str, str, list[str] | None]] = []

    def send(self, subject, body, *, recipients=None):
        self.sent.append((subject, body, recipients))


def _enable_feedback_digest(container, *, extras="extra@example.com,vincemartin1991@gmail.com"):
    container.settings.feedback_digest_email_enabled = True
    container.settings.alert_email_to = "alerts@example.com"
    container.settings.feedback_digest_extra_recipients = extras
    mailer = _RecordingMailer()
    container.control_plane.mailer = mailer
    return mailer


def test_feedback_digest_no_feedback_still_sends(monkeypatch):
    container, client = _build_app()
    mailer = _enable_feedback_digest(container)

    resp = client.post("/jobs/send-feedback-digest")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "sent"
    assert body["feedback_count"] == 0
    assert body["since"] is None
    assert body["summary_present"] is False
    assert body["recipients"] == [
        "alerts@example.com",
        "extra@example.com",
        "vincemartin1991@gmail.com",
    ]

    assert len(mailer.sent) == 1
    subject, email_body, recipients = mailer.sent[0]
    assert "no feedback" in subject.lower()
    assert "No feedback" in email_body
    assert recipients == [
        "alerts@example.com",
        "extra@example.com",
        "vincemartin1991@gmail.com",
    ]

    # Cursor should have advanced even though there was nothing to summarize.
    assert container.control_repository.get_job_state("feedback_weekly_digest") is not None


def test_feedback_digest_first_run_includes_all_to_date(monkeypatch):
    from newsletter_pod import control_plane as cp_module
    from newsletter_pod import feedback_digest as fd_module

    container, client = _build_app()
    mailer = _enable_feedback_digest(container)

    _, headers_a = _auth_headers(client, FakeAppleVerifier("user-a", "a@example.com"))
    resp_a = client.post(
        "/v1/me/feedback",
        json={"text": "Love the welcome pod"},
        headers=headers_a,
    )
    assert resp_a.status_code == 201
    _, headers_b = _auth_headers(client, FakeAppleVerifier("user-b", "b@example.com"))
    resp_b = client.post(
        "/v1/me/feedback",
        json={"text": "Audio cut off mid-sentence"},
        headers=headers_b,
    )
    assert resp_b.status_code == 201

    summary_calls = {"count": 0}

    def fake_summary(records, **kwargs):
        summary_calls["count"] += 1
        summary_calls["record_count"] = len(records)
        return "- Users like welcome pod\n- One report of audio cutoff"

    monkeypatch.setattr(cp_module, "summarize_feedback_with_llm", fake_summary)
    # Also monkeypatch the symbol in fd_module to keep imports consistent.
    monkeypatch.setattr(fd_module, "summarize_feedback_with_llm", fake_summary, raising=False)

    resp = client.post("/jobs/send-feedback-digest")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "sent"
    assert body["feedback_count"] == 2
    assert body["since"] is None  # first run
    assert body["summary_present"] is True

    assert summary_calls["count"] == 1
    assert summary_calls["record_count"] == 2

    assert len(mailer.sent) == 1
    subject, email_body, _recipients = mailer.sent[0]
    assert "2 items" in subject
    assert "all-time" in subject
    assert "Summary" in email_body
    assert "audio cutoff" in email_body
    assert "Love the welcome pod" in email_body
    assert "Audio cut off mid-sentence" in email_body


def test_feedback_digest_disabled_short_circuits():
    container, client = _build_app()
    # Do NOT enable the digest flag. Should be a no-op.
    container.settings.feedback_digest_email_enabled = False
    mailer = _RecordingMailer()
    container.control_plane.mailer = mailer

    resp = client.post("/jobs/send-feedback-digest")
    assert resp.status_code == 200
    assert resp.json() == {"status": "disabled"}
    assert mailer.sent == []


def test_feedback_digest_second_run_uses_cursor(monkeypatch):
    from newsletter_pod import control_plane as cp_module

    container, client = _build_app()
    mailer = _enable_feedback_digest(container)

    _, headers = _auth_headers(client, FakeAppleVerifier("user-c", "c@example.com"))
    client.post("/v1/me/feedback", json={"text": "first item"}, headers=headers)

    monkeypatch.setattr(cp_module, "summarize_feedback_with_llm", lambda records, **_: "ok")

    first = client.post("/jobs/send-feedback-digest")
    assert first.status_code == 200
    assert first.json()["feedback_count"] == 1
    assert first.json()["since"] is None

    # New feedback arrives AFTER the first digest fired.
    client.post("/v1/me/feedback", json={"text": "second item"}, headers=headers)

    second = client.post("/jobs/send-feedback-digest")
    assert second.status_code == 200
    second_body = second.json()
    assert second_body["feedback_count"] == 1
    assert second_body["since"] is not None
    # The second mailer call should only mention the new feedback.
    _, email_body, _r = mailer.sent[-1]
    assert "second item" in email_body
    assert "first item" not in email_body


def test_refresh_cold_start_deck_job_recomputes_when_corpus_available():
    from newsletter_pod.models import SourceItemRecord
    from newsletter_pod.swipe_deck import COLD_START_DECK_ID

    container, client = _build_app()
    now = datetime(2026, 5, 11, 12, 0, tzinfo=timezone.utc)
    records = [
        SourceItemRecord(
            dedupe_key=f"k{i}",
            source_id="src-1",
            source_name="Source 1",
            guid=f"k{i}",
            link=f"https://example.com/{i}",
            title=f"Title {i}",
            summary="summary",
            published_at=now,
            first_seen_at=now,
            last_seen_at=now,
            embedding=[float(i), 1.0],
            embedding_model="fake",
            embedded_at=now,
        )
        for i in range(6)
    ]
    container.control_repository.upsert_source_items(records)

    resp = client.post("/jobs/refresh-cold-start-deck")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "refreshed"
    assert body["corpus_size"] == 6
    assert body["deck_size"] > 0
    assert container.control_repository.get_swipe_deck(COLD_START_DECK_ID) is not None


def test_refresh_cold_start_deck_job_skips_when_corpus_empty():
    container, client = _build_app()
    resp = client.post("/jobs/refresh-cold-start-deck")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "skipped"
    assert body["reason"] == "empty_corpus"


def _seed_source_item(container, dedupe_key: str, *, embedding: list[float] | None = None) -> None:
    from newsletter_pod.models import SourceItemRecord

    now = datetime(2026, 5, 11, 12, 0, tzinfo=timezone.utc)
    record = SourceItemRecord(
        dedupe_key=dedupe_key,
        source_id="src-1",
        source_name="Source 1",
        guid=dedupe_key,
        link=f"https://example.com/{dedupe_key}",
        title=f"Title {dedupe_key}",
        summary="summary",
        published_at=now,
        first_seen_at=now,
        last_seen_at=now,
        embedding=embedding,
        embedding_model="fake" if embedding is not None else None,
        embedded_at=now if embedding is not None else None,
    )
    container.control_repository.upsert_source_items([record])


def test_swipe_endpoint_persists_swipe_with_snapshotted_embedding():
    container, client = _build_app()
    _, headers = _auth_headers(client, FakeAppleVerifier("swipe-user-1", "swipe1@example.com"))

    _seed_source_item(container, "k-right", embedding=[0.6, 0.8])

    resp = client.post(
        "/v1/me/swipes",
        json={"source_item_dedupe_key": "k-right", "direction": 1},
        headers=headers,
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["direction"] == 1
    assert body["source_item_dedupe_key"] == "k-right"
    assert body["embedding"] == [0.6, 0.8]
    assert body["embedding_model"] == "fake"

    user_id = body["user_id"]
    swipes = container.control_repository.list_user_swipes(user_id)
    assert len(swipes) == 1
    assert swipes[0].embedding == [0.6, 0.8]


def test_swipe_endpoint_rejects_unknown_source_item():
    _, client = _build_app()
    _, headers = _auth_headers(client, FakeAppleVerifier("swipe-user-2", "swipe2@example.com"))

    resp = client.post(
        "/v1/me/swipes",
        json={"source_item_dedupe_key": "does-not-exist", "direction": 1},
        headers=headers,
    )
    assert resp.status_code == 400


def test_swipe_endpoint_rejects_invalid_direction():
    container, client = _build_app()
    _, headers = _auth_headers(client, FakeAppleVerifier("swipe-user-3", "swipe3@example.com"))
    _seed_source_item(container, "k", embedding=[1.0, 0.0])

    resp = client.post(
        "/v1/me/swipes",
        json={"source_item_dedupe_key": "k", "direction": 2},
        headers=headers,
    )
    assert resp.status_code == 400


def test_swipe_endpoint_rejects_source_item_without_embedding():
    container, client = _build_app()
    _, headers = _auth_headers(client, FakeAppleVerifier("swipe-user-4", "swipe4@example.com"))
    _seed_source_item(container, "k-no-embed", embedding=None)

    resp = client.post(
        "/v1/me/swipes",
        json={"source_item_dedupe_key": "k-no-embed", "direction": -1},
        headers=headers,
    )
    assert resp.status_code == 400


def _seed_catalog_source(container, source_id: str) -> None:
    from newsletter_pod.models import SourceDefinition

    container.control_plane._catalog[source_id] = SourceDefinition(
        id=source_id,
        name=f"Catalog {source_id}",
        rss_url=f"https://example.com/rss/{source_id}",
        enabled=True,
        topic="News",
    )


def test_right_swipe_auto_attaches_catalog_source_at_threshold():
    container, client = _build_app()
    _, headers = _auth_headers(
        client, FakeAppleVerifier("auto-attach-user", "aa@example.com")
    )
    container.control_plane.settings.auto_attach_right_swipe_threshold = 3
    _seed_catalog_source(container, "news-fresh")

    # Three distinct items from a non-attached catalog source.
    for i in range(3):
        _seed_source_item_with_source(
            container, f"fresh-{i}", source_id="news-fresh", embedding=[1.0, 0.0]
        )

    user_id = list(container.control_repository._users.values())[0].id
    assert not any(
        s.source_id == "news-fresh"
        for s in container.control_repository.list_user_sources(user_id)
    )

    for i in range(3):
        resp = client.post(
            "/v1/me/swipes",
            json={"source_item_dedupe_key": f"fresh-{i}", "direction": 1},
            headers=headers,
        )
        assert resp.status_code == 201

    attached = container.control_repository.list_user_sources(user_id)
    assert any(s.source_id == "news-fresh" and s.enabled for s in attached)


def test_right_swipe_does_not_attach_below_threshold():
    container, client = _build_app()
    _, headers = _auth_headers(
        client, FakeAppleVerifier("below-thresh-user", "bt@example.com")
    )
    container.control_plane.settings.auto_attach_right_swipe_threshold = 3
    _seed_catalog_source(container, "news-fresh")
    _seed_source_item_with_source(
        container, "fresh-0", source_id="news-fresh", embedding=[1.0, 0.0]
    )

    user_id = list(container.control_repository._users.values())[0].id
    resp = client.post(
        "/v1/me/swipes",
        json={"source_item_dedupe_key": "fresh-0", "direction": 1},
        headers=headers,
    )
    assert resp.status_code == 201

    attached_ids = {s.source_id for s in container.control_repository.list_user_sources(user_id)}
    assert "news-fresh" not in attached_ids


def test_left_swipes_do_not_count_toward_auto_attach():
    container, client = _build_app()
    _, headers = _auth_headers(
        client, FakeAppleVerifier("left-swipe-user", "ls@example.com")
    )
    container.control_plane.settings.auto_attach_right_swipe_threshold = 2
    _seed_catalog_source(container, "news-fresh")
    for i in range(3):
        _seed_source_item_with_source(
            container, f"fresh-{i}", source_id="news-fresh", embedding=[1.0, 0.0]
        )

    user_id = list(container.control_repository._users.values())[0].id
    for i in range(3):
        client.post(
            "/v1/me/swipes",
            json={"source_item_dedupe_key": f"fresh-{i}", "direction": -1},
            headers=headers,
        )

    attached_ids = {s.source_id for s in container.control_repository.list_user_sources(user_id)}
    assert "news-fresh" not in attached_ids


def test_corpus_refresh_endpoint_ingests_and_embeds_attached_sources(monkeypatch):
    from datetime import datetime, timezone

    from newsletter_pod.ingestion import IngestionResult, RSSIngestionService
    from newsletter_pod.models import SourceItem
    from newsletter_pod.user_models import UserSourceRecord

    container, client = _build_app()
    _, headers = _auth_headers(
        client, FakeAppleVerifier("warm-user-1", "warm1@example.com")
    )
    user_id = list(container.control_repository._users.values())[0].id

    container.control_repository.replace_user_sources(
        user_id,
        [
            UserSourceRecord(
                id=f"{user_id}:warm-src",
                user_id=user_id,
                source_id="warm-src",
                name="Warm Source",
                rss_url="https://example.com/warm.rss",
                created_at=datetime(2026, 5, 12, tzinfo=timezone.utc),
                updated_at=datetime(2026, 5, 12, tzinfo=timezone.utc),
            )
        ],
    )

    captured: dict = {}

    def fake_fetch(self, source_defs):
        captured["source_ids"] = [s.id for s in source_defs]
        item = SourceItem(
            source_id="warm-src",
            source_name="Warm Source",
            guid="warm-1",
            link="https://example.com/warm-1",
            title="Warm Item 1",
            summary="warm summary",
            published_at=datetime(2026, 5, 12, 10, 0, tzinfo=timezone.utc),
            dedupe_key="warm-1",
        )
        return IngestionResult(items=[item], cursor_updates={"warm-src": item.published_at})

    monkeypatch.setattr(RSSIngestionService, "fetch_new_items", fake_fetch)

    resp = client.post("/v1/me/corpus/refresh", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["sources_processed"] == 1
    assert body["items_ingested"] == 1
    assert captured["source_ids"] == ["warm-src"]

    # The persisted item should now be in source_items.
    stored = container.control_repository.get_source_item("warm-1")
    assert stored is not None
    assert stored.source_id == "warm-src"


def test_recent_deck_lazy_warms_when_empty(monkeypatch):
    from datetime import datetime, timezone

    from newsletter_pod.embeddings import DeterministicFakeEmbeddingProvider
    from newsletter_pod.ingestion import IngestionResult, RSSIngestionService
    from newsletter_pod.models import SourceItem
    from newsletter_pod.source_persistence import SourceItemPersistenceService
    from newsletter_pod.user_models import UserSourceRecord

    container, client = _build_app()
    _, headers = _auth_headers(
        client, FakeAppleVerifier("lazy-warm-user", "lw@example.com")
    )
    user_id = list(container.control_repository._users.values())[0].id

    # Inject an embedding provider so warmed items are deck-eligible (the
    # recent-deck filter only surfaces items that carry an embedding).
    container.control_plane._source_item_persistence = SourceItemPersistenceService(
        repository=container.control_repository,
        embeddings=DeterministicFakeEmbeddingProvider(dimensions=8),
    )

    container.control_repository.replace_user_sources(
        user_id,
        [
            UserSourceRecord(
                id=f"{user_id}:lazy-src",
                user_id=user_id,
                source_id="lazy-src",
                name="Lazy Source",
                rss_url="https://example.com/lazy.rss",
                created_at=datetime(2026, 5, 12, tzinfo=timezone.utc),
                updated_at=datetime(2026, 5, 12, tzinfo=timezone.utc),
            )
        ],
    )

    call_count = {"n": 0}

    def fake_fetch(self, source_defs):
        call_count["n"] += 1
        item = SourceItem(
            source_id="lazy-src",
            source_name="Lazy Source",
            guid="lazy-1",
            link="https://example.com/lazy-1",
            title="Lazy Item 1",
            summary="lazy summary",
            published_at=datetime(2026, 5, 12, 10, 0, tzinfo=timezone.utc),
            dedupe_key="lazy-1",
        )
        return IngestionResult(items=[item], cursor_updates={"lazy-src": item.published_at})

    monkeypatch.setattr(RSSIngestionService, "fetch_new_items", fake_fetch)

    resp = client.get("/v1/me/swipe-deck/recent", headers=headers)
    assert resp.status_code == 200
    assert call_count["n"] >= 1, "empty deck should trigger an inline warm"
    body = resp.json()
    assert len(body["items"]) == 1
    assert body["items"][0]["source_item_dedupe_key"] == "lazy-1"


def test_right_swipe_does_not_auto_attach_non_catalog_sources():
    container, client = _build_app()
    _, headers = _auth_headers(
        client, FakeAppleVerifier("custom-source-user", "cu@example.com")
    )
    container.control_plane.settings.auto_attach_right_swipe_threshold = 2
    # NOT seeded into the catalog; auto-attach should refuse to add it.
    for i in range(2):
        _seed_source_item_with_source(
            container, f"custom-{i}", source_id="custom-unknown", embedding=[1.0, 0.0]
        )

    user_id = list(container.control_repository._users.values())[0].id
    for i in range(2):
        client.post(
            "/v1/me/swipes",
            json={"source_item_dedupe_key": f"custom-{i}", "direction": 1},
            headers=headers,
        )

    attached_ids = {s.source_id for s in container.control_repository.list_user_sources(user_id)}
    assert "custom-unknown" not in attached_ids


def test_apply_swipe_ranker_returns_none_when_flag_disabled():
    from newsletter_pod.models import SourceItem

    container, _ = _build_app()
    container.control_plane.settings.swipe_ranker_enabled = False
    items = [
        SourceItem(
            source_id="src",
            source_name="Source",
            guid="k1",
            link="https://example.com/k1",
            title="t",
            summary="s",
            published_at=datetime(2026, 5, 11, tzinfo=timezone.utc),
            dedupe_key="k1",
        )
    ]
    assert container.control_plane._apply_swipe_ranker("u-anon", items, top_n=5) is None


def test_apply_swipe_ranker_returns_none_when_too_few_swipes():
    from newsletter_pod.models import SourceItem

    container, client = _build_app()
    _, headers = _auth_headers(client, FakeAppleVerifier("ranker-thin-user", "rt@example.com"))
    _seed_source_item(container, "k1", embedding=[1.0, 0.0])
    client.post(
        "/v1/me/swipes",
        json={"source_item_dedupe_key": "k1", "direction": 1},
        headers=headers,
    )
    user_id = container.control_repository.list_user_swipes
    # Pull the actual user id from the only stored swipe.
    swipes = list(container.control_repository._swipes.values())
    assert len(swipes) == 1
    user_id = swipes[0].user_id

    container.control_plane.settings.swipe_ranker_enabled = True
    container.control_plane.settings.swipe_ranker_min_swipes = 3
    items = [
        SourceItem(
            source_id="src-1", source_name="Source 1", guid="k1",
            link="https://example.com/k1", title="t", summary="s",
            published_at=datetime(2026, 5, 11, tzinfo=timezone.utc),
            dedupe_key="k1",
        )
    ]
    assert container.control_plane._apply_swipe_ranker(user_id, items, top_n=5) is None


def test_apply_swipe_ranker_orders_items_by_user_vector_when_enabled():
    from newsletter_pod.models import SourceItem

    container, client = _build_app()
    _, headers = _auth_headers(client, FakeAppleVerifier("ranker-active-user", "ra@example.com"))

    # Seed three items with embeddings that point in three different directions
    # in 2D space, plus three swipes (right on east-pointing, left on the
    # north-pointing) so the user vector strongly favours east.
    _seed_source_item(container, "east", embedding=[1.0, 0.0])
    _seed_source_item(container, "north", embedding=[0.0, 1.0])
    _seed_source_item(container, "west", embedding=[-1.0, 0.0])
    for key, direction in [("east", 1), ("east", 1), ("north", -1)]:
        client.post(
            "/v1/me/swipes",
            json={"source_item_dedupe_key": key, "direction": direction},
            headers=headers,
        )
    user_id = list(container.control_repository._swipes.values())[0].user_id

    container.control_plane.settings.swipe_ranker_enabled = True
    container.control_plane.settings.swipe_ranker_min_swipes = 1
    candidate_items = [
        SourceItem(
            source_id="s", source_name="S", guid=key, link=f"https://example.com/{key}",
            title=key, summary="x",
            published_at=datetime(2026, 5, 11, 12, idx, tzinfo=timezone.utc),
            dedupe_key=key,
        )
        for idx, key in enumerate(["east", "north", "west"])
    ]
    ranked = container.control_plane._apply_swipe_ranker(user_id, candidate_items, top_n=2)
    assert ranked is not None
    # east scores highest (right-swiped), west lowest (opposite of east), north
    # is below east (it was left-swiped). Top 2 should be east + north,
    # restored to chronological order (east at index 0, north at index 1).
    assert [item.dedupe_key for item in ranked] == ["east", "north"]


def test_apply_swipe_ranker_boosts_inbound_dedupe_keys_above_weak_rss_match():
    from newsletter_pod.models import SourceItem

    container, client = _build_app()
    _, headers = _auth_headers(client, FakeAppleVerifier("ranker-boost-user", "rb@example.com"))

    # Seed swipes that build a user_vector pointing east, with an RSS item
    # whose embedding is only weakly east-aligned (cosine ≈ 0.3). The inbound
    # item has no embedding (neutral score 0.0). Without bias, the RSS item
    # wins the top_n=1 slot; with a 0.5 bias it loses to the inbound item.
    _seed_source_item(container, "rss-weak", embedding=[0.3, math.sqrt(1 - 0.09)])
    _seed_source_item(container, "rss-east", embedding=[1.0, 0.0])
    for direction in (1, 1, 1):
        client.post(
            "/v1/me/swipes",
            json={"source_item_dedupe_key": "rss-east", "direction": direction},
            headers=headers,
        )
    user_id = list(container.control_repository._swipes.values())[0].user_id

    container.control_plane.settings.swipe_ranker_enabled = True
    container.control_plane.settings.swipe_ranker_min_swipes = 1
    container.control_plane.settings.inbound_ranker_bias = 0.5

    items = [
        SourceItem(
            source_id="src", source_name="Source",
            guid="rss-weak", link="https://example.com/rss",
            title="rss", summary="x",
            published_at=datetime(2026, 5, 11, 12, 0, tzinfo=timezone.utc),
            dedupe_key="rss-weak",
        ),
        SourceItem(
            source_id="inbound:example.com", source_name="Inbound Pub",
            guid="inbound-key", link="https://example.com/inbound",
            title="inbound", summary="x",
            published_at=datetime(2026, 5, 11, 12, 1, tzinfo=timezone.utc),
            dedupe_key="inbound:high-intent",
        ),
    ]

    without_bias = container.control_plane._apply_swipe_ranker(
        user_id, items, top_n=1, boosted_dedupe_keys=set()
    )
    assert [item.dedupe_key for item in without_bias] == ["rss-weak"], (
        "control: without the inbound key in boosted set, RSS wins on cosine"
    )

    with_bias = container.control_plane._apply_swipe_ranker(
        user_id, items, top_n=1, boosted_dedupe_keys={"inbound:high-intent"}
    )
    assert [item.dedupe_key for item in with_bias] == ["inbound:high-intent"], (
        "bias of 0.5 should beat RSS cosine of 0.3"
    )


def test_cold_start_swipe_deck_endpoint_returns_centroid_items():
    container, client = _build_app()
    _, headers = _auth_headers(client, FakeAppleVerifier("deck-cold-user", "dc@example.com"))

    # Three obvious clusters in 2D space; deck size of 3 should land one per cluster.
    for cluster_index, base_x in enumerate((1.0, -1.0, 5.0)):
        for offset in range(3):
            _seed_source_item(
                container,
                f"cluster-{cluster_index}-{offset}",
                embedding=[base_x + 0.01 * offset, base_x],
            )

    container.control_plane.settings.cold_start_deck_size = 3
    resp = client.get("/v1/me/swipe-deck/cold-start", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert "items" in body
    assert len(body["items"]) == 3
    item = body["items"][0]
    assert {
        "source_item_dedupe_key",
        "title",
        "summary",
        "source_id",
        "source_name",
        "link",
        "published_at",
    } <= item.keys()


def test_cold_start_deck_drops_items_after_user_swipes_on_them():
    container, client = _build_app()
    _, headers = _auth_headers(client, FakeAppleVerifier("deck-skip-user", "ds@example.com"))

    for i in range(6):
        _seed_source_item(container, f"k{i}", embedding=[float(i), 0.0])
    container.control_plane.settings.cold_start_deck_size = 4

    first = client.get("/v1/me/swipe-deck/cold-start", headers=headers).json()["items"]
    swiped_key = first[0]["source_item_dedupe_key"]
    assert client.post(
        "/v1/me/swipes",
        json={"source_item_dedupe_key": swiped_key, "direction": 1},
        headers=headers,
    ).status_code == 201

    second = client.get("/v1/me/swipe-deck/cold-start", headers=headers).json()["items"]
    second_keys = {item["source_item_dedupe_key"] for item in second}
    assert swiped_key not in second_keys


def test_recent_deck_endpoint_returns_items_from_user_sources_when_exploration_off():
    from datetime import datetime, timezone

    from newsletter_pod.user_models import UserSourceRecord

    container, client = _build_app()
    _, headers = _auth_headers(client, FakeAppleVerifier("deck-recent-user", "dr@example.com"))

    # Exploration off for this scenario — assert the pure-attached behaviour.
    container.control_plane.settings.recent_deck_exploration_ratio = 0.0

    users = list(container.control_repository._users.values())
    assert users, "auth flow should have created the user"
    user_id = users[0].id

    container.control_repository.replace_user_sources(
        user_id,
        [
            UserSourceRecord(
                id=f"{user_id}:src-mine",
                user_id=user_id,
                source_id="src-mine",
                name="Mine",
                rss_url="https://example.com/rss-mine",
                created_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
                updated_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
            )
        ],
    )

    _seed_source_item_with_source(container, "mine-1", source_id="src-mine", embedding=[1.0, 0.0])
    _seed_source_item_with_source(container, "mine-2", source_id="src-mine", embedding=[1.0, 0.0])
    _seed_source_item_with_source(container, "other-1", source_id="src-other", embedding=[1.0, 0.0])

    resp = client.get("/v1/me/swipe-deck/recent", headers=headers)
    assert resp.status_code == 200
    keys = {item["source_item_dedupe_key"] for item in resp.json()["items"]}
    assert keys == {"mine-1", "mine-2"}


def _seed_source_item_with_source(container, dedupe_key: str, *, source_id: str, embedding) -> None:
    from datetime import datetime, timezone

    from newsletter_pod.models import SourceItemRecord

    now = datetime(2026, 5, 11, 12, 0, tzinfo=timezone.utc)
    record = SourceItemRecord(
        dedupe_key=dedupe_key,
        source_id=source_id,
        source_name=f"Name {source_id}",
        guid=dedupe_key,
        link=f"https://example.com/{dedupe_key}",
        title=f"Title {dedupe_key}",
        summary="summary",
        published_at=now,
        first_seen_at=now,
        last_seen_at=now,
        embedding=embedding,
        embedding_model="fake" if embedding is not None else None,
        embedded_at=now if embedding is not None else None,
    )
    container.control_repository.upsert_source_items([record])


def test_voice_catalog_returns_only_enabled_voices():
    container, client = _build_app()
    catalog = client.get("/v1/voices/catalog")
    assert catalog.status_code == 200
    voices = catalog.json()["voices"]
    # Loader filters out enabled: false entries; the catalog should only ever
    # expose voices we've explicitly turned on.
    assert len(voices) >= 2
    ids = {v["id"] for v in voices}
    assert "suMMgpGbVcnihP1CcgFS" in ids  # Vinnie
    assert "RKCbSROXui75bk1SVpy8" in ids  # Demi
    for voice in voices:
        assert {"id", "name", "gender", "description", "preview_url"} <= set(voice.keys())


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


def test_signed_app_store_notification_flips_tier_to_max():
    from newsletter_pod.app_store_verifier import DecodedNotification

    container, client = _build_app()
    _, headers = _auth_headers(
        client, FakeAppleVerifier("signed-flip-user", "flip@example.com")
    )
    me = client.get("/v1/me", headers=headers).json()
    user_id = me["user"]["id"]

    fake_verifier = FakeAppStoreVerifier()
    fake_verifier.stub(
        "fake-jws-token",
        DecodedNotification(
            notification_type="SUBSCRIBED",
            subtype=None,
            notification_uuid="11111111-2222-3333-4444-555555555555",
            bundle_id="com.newsletterpod.app",
            environment="Sandbox",
            transaction_id="200000000000001",
            product_id=container.settings.app_store_max_annual_product_id,
            # Apple delivers appAccountToken in hyphenated UUID form; the
            # handler normalizes back to our 32-char hex user_id.
            app_account_token=f"{user_id[:8]}-{user_id[8:12]}-{user_id[12:16]}-{user_id[16:20]}-{user_id[20:]}",
            expires_date_ms=2000000000000,
            revocation_date_ms=None,
        ),
    )
    container.control_plane.app_store_verifier = fake_verifier

    resp = client.post(
        "/v1/billing/app-store/notifications",
        json={"signedPayload": "fake-jws-token"},
    )
    assert resp.status_code == 200, resp.text

    subscription = container.control_repository.get_subscription(user_id)
    assert subscription is not None
    assert subscription.tier == "max"
    assert subscription.status == "active"
    assert subscription.product_id == container.settings.app_store_max_annual_product_id
    assert subscription.expires_at is not None


def test_signed_app_store_notification_rejects_bad_signature():
    container, client = _build_app()
    container.control_plane.app_store_verifier = FakeAppStoreVerifier()

    resp = client.post(
        "/v1/billing/app-store/notifications",
        json={"signedPayload": "this-was-not-signed-by-apple"},
    )
    assert resp.status_code == 400
    assert "signature" in resp.text.lower() or "verification" in resp.text.lower()


def test_unsigned_notification_rejected_when_require_signed_is_on():
    container, client = _build_app()
    container.settings.app_store_notifications_require_signed = True

    resp = client.post(
        "/v1/billing/app-store/notifications",
        json={
            "user_id": "deadbeefdeadbeefdeadbeefdeadbeef",
            "notification_type": "DID_RENEW",
            "product_id": container.settings.app_store_pro_monthly_product_id,
        },
    )
    assert resp.status_code == 400
    assert "signedPayload" in resp.text or "signed" in resp.text.lower()


def test_client_verified_transaction_flips_tier_to_max():
    """iOS posts a StoreKit2 transaction JWS to /v1/me/subscription/verify
    after a successful purchase, since sandbox ASN delivery is unreliable.
    The backend should verify, record a billing event, and flip the tier."""
    from newsletter_pod.app_store_verifier import DecodedTransaction

    container, client = _build_app()
    _, headers = _auth_headers(
        client, FakeAppleVerifier("client-verify-user", "verify@example.com")
    )
    user_id = client.get("/v1/me", headers=headers).json()["user"]["id"]

    fake_verifier = FakeAppStoreVerifier()
    fake_verifier.stub_transaction(
        "ios-jws-token",
        DecodedTransaction(
            transaction_id="200000000000123",
            product_id=container.settings.app_store_max_monthly_product_id,
            app_account_token=f"{user_id[:8]}-{user_id[8:12]}-{user_id[12:16]}-{user_id[16:20]}-{user_id[20:]}",
            expires_date_ms=2000000000000,
            revocation_date_ms=None,
            bundle_id="com.newsletterpod.app",
            environment="Sandbox",
        ),
    )
    container.control_plane.app_store_verifier = fake_verifier

    resp = client.post(
        "/v1/me/subscription/verify",
        json={"signed_transaction_info": "ios-jws-token"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["accepted"] is True
    assert body["subscription"]["tier"] == "max"
    assert body["subscription"]["status"] == "active"

    subscription = container.control_repository.get_subscription(user_id)
    assert subscription.tier == "max"
    assert subscription.product_id == container.settings.app_store_max_monthly_product_id


def test_client_verified_transaction_rejects_token_mismatch():
    """A JWS Apple signed for someone else's appAccountToken must not be
    accepted as evidence the *authenticated* user paid. Otherwise one user
    could attach another user's purchase to their account."""
    from newsletter_pod.app_store_verifier import DecodedTransaction

    container, client = _build_app()
    _, headers = _auth_headers(
        client, FakeAppleVerifier("mismatch-user", "mismatch@example.com")
    )

    fake_verifier = FakeAppStoreVerifier()
    fake_verifier.stub_transaction(
        "someone-elses-jws",
        DecodedTransaction(
            transaction_id="200000000000124",
            product_id=container.settings.app_store_max_monthly_product_id,
            # Different user_id encoded in the appAccountToken
            app_account_token="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            expires_date_ms=2000000000000,
            revocation_date_ms=None,
            bundle_id="com.newsletterpod.app",
            environment="Sandbox",
        ),
    )
    container.control_plane.app_store_verifier = fake_verifier

    resp = client.post(
        "/v1/me/subscription/verify",
        json={"signed_transaction_info": "someone-elses-jws"},
        headers=headers,
    )
    assert resp.status_code == 400
    assert "does not match" in resp.text.lower() or "mismatch" in resp.text.lower()


def test_client_verified_transaction_rejects_bad_signature():
    container, client = _build_app()
    _, headers = _auth_headers(
        client, FakeAppleVerifier("bad-sig-user", "badsig@example.com")
    )
    container.control_plane.app_store_verifier = FakeAppStoreVerifier()

    resp = client.post(
        "/v1/me/subscription/verify",
        json={"signed_transaction_info": "not-signed-by-apple"},
        headers=headers,
    )
    assert resp.status_code == 400


def test_signed_notification_handler_records_billing_event_for_unknown_user():
    """Verified payload for a user_id we've never seen should still record
    the BillingEvent (so we can audit drift) but not crash or 500."""
    from newsletter_pod.app_store_verifier import DecodedNotification

    container, client = _build_app()
    fake_verifier = FakeAppStoreVerifier()
    fake_verifier.stub(
        "verified-but-orphan",
        DecodedNotification(
            notification_type="SUBSCRIBED",
            subtype=None,
            notification_uuid=None,
            bundle_id="com.newsletterpod.app",
            environment="Sandbox",
            transaction_id="200000000000099",
            product_id=container.settings.app_store_pro_monthly_product_id,
            app_account_token="00000000-0000-0000-0000-000000000000",
            expires_date_ms=None,
            revocation_date_ms=None,
        ),
    )
    container.control_plane.app_store_verifier = fake_verifier

    resp = client.post(
        "/v1/billing/app-store/notifications",
        json={"signedPayload": "verified-but-orphan"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body.get("accepted") is True
    assert "warning" in body


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
            "product_id": container.settings.app_store_pro_monthly_product_id,
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


def test_left_swiped_items_are_excluded_from_episode(monkeypatch):
    """First-time user feedback (2026-05-26): a user swiped left on two items
    in the cold-start deck and they immediately resurfaced in the first
    briefing. The ranker only soft-downweights via cosine similarity, and
    below swipe_ranker_min_swipes it's bypassed entirely — so an explicit
    "no" from the deck must hard-exclude the item.
    """
    container, client = _build_app()
    container.control_plane.apple_identity_verifier = FakeAppleVerifier(
        "apple-leftswipe", "leftswipe@example.com"
    )
    auth = client.post("/v1/auth/apple", json={"identity_token": "apple-token"})
    user_id = auth.json()["user"]["id"]

    catalog = client.get("/v1/sources/catalog").json()["sources"]
    headers = {"Authorization": f"Bearer {auth.json()['session_token']}"}
    client.put(
        "/v1/me/sources",
        json={"sources": [{"source_id": catalog[0]["source_id"]}]},
        headers=headers,
    )
    container.control_plane.podcast_client = FakePodcastClient()

    now = datetime(2026, 5, 26, 12, 0, tzinfo=timezone.utc)
    container.control_repository.save_swipe(
        SwipeRecord(
            id="declined-1",
            user_id=user_id,
            source_item_dedupe_key="2",
            direction=-1,
            title="Story Two",
            link="https://example.com/2",
            source_id="source-a",
            source_name="Source A",
            embedding=[0.0, 1.0],
            embedding_model="test",
            swiped_at=now,
        )
    )

    def fake_fetch(self, sources):
        return IngestionResult(
            items=[
                SourceItem(
                    source_id="source-a", source_name="Source A", guid="1",
                    link="https://example.com/1", title="Story One",
                    summary="Summary one",
                    published_at=datetime(2026, 5, 26, 8, 0, tzinfo=timezone.utc),
                    dedupe_key="1",
                ),
                SourceItem(
                    source_id="source-a", source_name="Source A", guid="2",
                    link="https://example.com/2", title="Story Two",
                    summary="Summary two",
                    published_at=datetime(2026, 5, 26, 9, 0, tzinfo=timezone.utc),
                    dedupe_key="2",
                ),
            ],
            cursor_updates={"source-a": datetime(2026, 5, 26, 9, 0, tzinfo=timezone.utc)},
        )

    monkeypatch.setattr(RSSIngestionService, "fetch_new_items", fake_fetch)

    result = client.post(
        "/jobs/process-user-podcast",
        json={"user_id": user_id, "force": True},
    )
    assert result.status_code == 200, result.text
    payload = result.json()
    refs = payload["episode"]["source_item_refs"]
    assert [ref["link"] for ref in refs] == ["https://example.com/1"]


def _seed_user_for_inbound_run(client, container, monkeypatch, *, email, subject):
    """Common scaffolding for the inbound-merge tests: auth a user, attach a
    source so the no-sources short-circuit doesn't fire, swap in a stub
    podcast client, and stub RSS to return no items (so the only candidates
    are inbound). Returns (user_id, headers)."""
    container.control_plane.apple_identity_verifier = FakeAppleVerifier(subject, email)
    auth = client.post("/v1/auth/apple", json={"identity_token": "apple-token"})
    user_id = auth.json()["user"]["id"]
    headers = {"Authorization": f"Bearer {auth.json()['session_token']}"}
    catalog = client.get("/v1/sources/catalog").json()["sources"]
    client.put(
        "/v1/me/sources",
        json={"sources": [{"source_id": catalog[0]["source_id"]}]},
        headers=headers,
    )
    container.control_plane.podcast_client = FakePodcastClient()
    monkeypatch.setattr(
        RSSIngestionService,
        "fetch_new_items",
        lambda self, sources: IngestionResult(items=[], cursor_updates={}),
    )
    return user_id, headers


def test_process_user_generation_pulls_unconsumed_inbound_items_into_episode(monkeypatch):
    container, client = _build_app()
    user_id, _ = _seed_user_for_inbound_run(
        client, container, monkeypatch,
        email="inbound@example.com", subject="apple-inbound-1",
    )

    repo = container.control_plane.repository
    received_at = datetime(2026, 4, 15, 8, 0, tzinfo=timezone.utc)
    inbound_item = InboundEmailItem(
        id="inbound-item-1",
        user_id=user_id,
        message_id="<msg-1@stratechery.com>",
        from_email="ben@stratechery.com",
        from_name="Ben Thompson",
        sender_domain="stratechery.com",
        subject="The Aggregation Layer",
        body_text="Today we are talking about platform aggregation theory.",
        article_url="https://stratechery.com/aggregation",
        received_at=received_at,
    )
    repo.save_inbound_item(inbound_item)

    result = client.post(
        "/jobs/process-user-podcast",
        json={"user_id": user_id, "force": True},
    )
    assert result.status_code == 200, result.text
    payload = result.json()
    assert payload["run"]["candidate_count"] == 1
    refs = payload["episode"]["source_item_refs"]
    assert len(refs) == 1
    assert refs[0]["link"] == "https://stratechery.com/aggregation"
    assert refs[0]["source_name"] == "Ben Thompson"
    assert refs[0]["title"] == "The Aggregation Layer"

    stored = repo.get_inbound_item("inbound-item-1")
    assert stored is not None
    assert stored.consumed_at is not None, "consumed_at should be stamped on the included item"


def test_substack_intent_pub_title_overrides_inbound_source_name(monkeypatch):
    container, client = _build_app()
    user_id, _ = _seed_user_for_inbound_run(
        client, container, monkeypatch,
        email="intent@example.com", subject="apple-inbound-2",
    )

    repo = container.control_plane.repository
    repo.save_substack_intent(
        UserSubstackIntent(
            id="intent-1",
            user_id=user_id,
            pub_url="https://heathercoxrichardson.substack.com",
            pub_host="heathercoxrichardson.substack.com",
            pub_title="Letters from an American",
            pub_author="Heather Cox Richardson",
            alias_email="user@theclawcast.com",
            created_at=datetime(2026, 4, 1, tzinfo=timezone.utc),
            confirmed_at=datetime(2026, 4, 2, tzinfo=timezone.utc),
        )
    )
    repo.save_inbound_item(
        InboundEmailItem(
            id="inbound-item-2",
            user_id=user_id,
            message_id="<msg-2@substack.com>",
            from_email="noreply@heathercoxrichardson.substack.com",
            from_name="Heather Cox Richardson",
            sender_domain="heathercoxrichardson.substack.com",
            subject="May 22, 2026",
            body_text="Today in history...",
            article_url="https://heathercoxrichardson.substack.com/p/may-22",
            received_at=datetime(2026, 4, 15, 9, 0, tzinfo=timezone.utc),
        )
    )

    result = client.post(
        "/jobs/process-user-podcast",
        json={"user_id": user_id, "force": True},
    )
    assert result.status_code == 200, result.text
    refs = result.json()["episode"]["source_item_refs"]
    assert len(refs) == 1
    assert refs[0]["source_name"] == "Letters from an American"


def test_substack_confirmation_email_is_filtered_out_of_candidates(monkeypatch):
    container, client = _build_app()
    user_id, _ = _seed_user_for_inbound_run(
        client, container, monkeypatch,
        email="confirm@example.com", subject="apple-inbound-3",
    )

    repo = container.control_plane.repository
    repo.save_inbound_item(
        InboundEmailItem(
            id="confirm-item",
            user_id=user_id,
            message_id="<confirm-1@substack.com>",
            from_email="no-reply@substack.com",
            from_name="Substack",
            sender_domain="substack.com",
            subject="Confirm your subscription to Stratechery",
            body_text=(
                "Click the link below to confirm your subscription.\n"
                "https://substack.com/redeem/abcdef1234567890"
            ),
            article_url=None,
            received_at=datetime(2026, 4, 15, 7, 0, tzinfo=timezone.utc),
        )
    )

    result = client.post(
        "/jobs/process-user-podcast",
        json={"user_id": user_id, "force": True},
    )
    assert result.status_code == 200, result.text
    # No-content path returns the run record flat (no "run" / "episode" wrapper).
    payload = result.json()
    assert payload["status"] == "no_content"
    assert payload["candidate_count"] == 0
    stored = repo.get_inbound_item("confirm-item")
    assert stored is not None
    assert stored.consumed_at is None, (
        "Confirmation emails are filtered before the ranker, "
        "so consumed_at should never be set on them"
    )


def test_inbound_items_dropped_by_cap_stay_unconsumed(monkeypatch):
    container, client = _build_app()
    user_id, _ = _seed_user_for_inbound_run(
        client, container, monkeypatch,
        email="cap@example.com", subject="apple-inbound-4",
    )
    container.settings.free_max_items_per_episode = 1

    repo = container.control_plane.repository
    older = InboundEmailItem(
        id="inbound-older",
        user_id=user_id,
        message_id="<older@example.com>",
        from_email="news@example.com",
        from_name="Example Daily",
        sender_domain="example.com",
        subject="Older story",
        body_text="Older body.",
        article_url="https://example.com/older",
        received_at=datetime(2026, 4, 15, 8, 0, tzinfo=timezone.utc),
    )
    newer = InboundEmailItem(
        id="inbound-newer",
        user_id=user_id,
        message_id="<newer@example.com>",
        from_email="news@example.com",
        from_name="Example Daily",
        sender_domain="example.com",
        subject="Newer story",
        body_text="Newer body.",
        article_url="https://example.com/newer",
        received_at=datetime(2026, 4, 15, 10, 0, tzinfo=timezone.utc),
    )
    repo.save_inbound_item(older)
    repo.save_inbound_item(newer)

    result = client.post(
        "/jobs/process-user-podcast",
        json={"user_id": user_id, "force": True},
    )
    assert result.status_code == 200, result.text
    payload = result.json()
    assert payload["run"]["candidate_count"] == 2
    refs = payload["episode"]["source_item_refs"]
    assert len(refs) == 1
    kept_link = refs[0]["link"]
    assert kept_link == "https://example.com/newer"

    # Newer was included (consumed_at set), older was dropped (still unconsumed).
    stored_newer = repo.get_inbound_item("inbound-newer")
    stored_older = repo.get_inbound_item("inbound-older")
    assert stored_newer.consumed_at is not None
    assert stored_older.consumed_at is None


# ----------------------------------------------------------------------------
# Share-to-ClawCast endpoint + generation integration
# ----------------------------------------------------------------------------


def _signin_share_user(client, container, *, subject="share-user", email="share@example.com"):
    container.control_plane.apple_identity_verifier = FakeAppleVerifier(subject, email)
    auth = client.post("/v1/auth/apple", json={"identity_token": "apple-token"})
    assert auth.status_code == 200
    user_id = auth.json()["user"]["id"]
    headers = {"Authorization": f"Bearer {auth.json()['session_token']}"}
    return user_id, headers


def test_share_endpoint_url_creates_kind_share_item(monkeypatch):
    from newsletter_pod import control_plane as cp_module

    container, client = _build_app()
    user_id, headers = _signin_share_user(client, container, subject="share-url-user")

    def fake_extract_url(url):
        assert url == "https://example.com/article"
        return ("Article Headline", "Article body text.")

    monkeypatch.setattr(cp_module, "extract_from_url", fake_extract_url)

    resp = client.post(
        "/v1/items/shared",
        data={"kind": "url", "url": "https://example.com/article"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["share_kind"] == "url"
    assert body["title"] == "Article Headline"
    assert body["duplicate"] is False
    assert body["dedupe_key"].startswith("inbound:")

    stored = container.control_plane.repository.get_inbound_item(body["item_id"])
    assert stored is not None
    assert stored.kind == "share"
    assert stored.article_url == "https://example.com/article"
    assert stored.from_email == "share@theclawcast.com"


def test_share_endpoint_plain_text_creates_item():
    container, client = _build_app()
    user_id, headers = _signin_share_user(client, container, subject="share-text-user")

    resp = client.post(
        "/v1/items/shared",
        data={"kind": "text"},
        files={"file": ("note.txt", b"Headline line\n\nBody paragraph here.", "text/plain")},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["share_kind"] == "text"
    assert body["title"] == "Headline line"

    stored = container.control_plane.repository.get_inbound_item(body["item_id"])
    assert stored.kind == "share"
    assert "Body paragraph here" in stored.body_text


def test_share_endpoint_is_idempotent_for_identical_url(monkeypatch):
    from newsletter_pod import control_plane as cp_module

    container, client = _build_app()
    user_id, headers = _signin_share_user(client, container, subject="share-dup-user")

    monkeypatch.setattr(
        cp_module,
        "extract_from_url",
        lambda url: ("Same title", "Same body."),
    )

    first = client.post(
        "/v1/items/shared",
        data={"kind": "url", "url": "https://example.com/x"},
        headers=headers,
    )
    second = client.post(
        "/v1/items/shared",
        data={"kind": "url", "url": "https://example.com/x"},
        headers=headers,
    )
    assert first.status_code == 201
    assert second.status_code == 201
    assert first.json()["item_id"] == second.json()["item_id"]
    assert first.json()["duplicate"] is False
    assert second.json()["duplicate"] is True


def test_share_endpoint_rejects_unsupported_kind():
    container, client = _build_app()
    user_id, headers = _signin_share_user(client, container, subject="share-bad-kind")

    resp = client.post(
        "/v1/items/shared",
        data={"kind": "video"},
        headers=headers,
    )
    assert resp.status_code == 400
    assert "Unsupported kind" in resp.json()["detail"]


def test_share_endpoint_requires_url_for_url_kind():
    container, client = _build_app()
    user_id, headers = _signin_share_user(client, container, subject="share-missing-url")

    resp = client.post(
        "/v1/items/shared",
        data={"kind": "url"},
        headers=headers,
    )
    assert resp.status_code == 400
    assert "url is required" in resp.json()["detail"]


def test_share_endpoint_requires_file_for_file_kind():
    container, client = _build_app()
    user_id, headers = _signin_share_user(client, container, subject="share-missing-file")

    resp = client.post(
        "/v1/items/shared",
        data={"kind": "text"},
        headers=headers,
    )
    assert resp.status_code == 400


def test_share_endpoint_requires_auth():
    container, client = _build_app()
    resp = client.post(
        "/v1/items/shared",
        data={"kind": "url", "url": "https://example.com"},
    )
    assert resp.status_code == 401


def test_shared_items_force_included_bypass_per_tier_item_cap(monkeypatch):
    """Free tier with max_items_per_episode=1: one RSS item + two shares
    should produce a 3-item episode (1 RSS + 2 shares), proving shares
    are *additive* to the per-tier cap rather than competing with it."""
    from newsletter_pod import control_plane as cp_module

    container, client = _build_app()
    container.settings.free_max_items_per_episode = 1

    user_id, headers = _seed_user_for_inbound_run(
        client, container, monkeypatch,
        email="share-cap@example.com", subject="share-cap-user",
    )

    # One real inbound (email) item — should be subject to the per-tier cap.
    repo = container.control_plane.repository
    repo.save_inbound_item(
        InboundEmailItem(
            id="inbound-email-1",
            user_id=user_id,
            kind="email",
            message_id="<email-1@example.com>",
            from_email="news@example.com",
            from_name="Example Daily",
            sender_domain="example.com",
            subject="Email-delivered story",
            body_text="Email body.",
            article_url="https://example.com/email-story",
            received_at=datetime(2026, 4, 15, 8, 0, tzinfo=timezone.utc),
        )
    )

    # Two share items — should both be included, bypassing the cap.
    monkeypatch.setattr(
        cp_module,
        "extract_from_url",
        lambda url: (f"Shared title {url[-1]}", f"Shared body for {url}"),
    )
    for suffix in ("a", "b"):
        resp = client.post(
            "/v1/items/shared",
            data={"kind": "url", "url": f"https://example.com/shared-{suffix}"},
            headers=headers,
        )
        assert resp.status_code == 201

    result = client.post(
        "/jobs/process-user-podcast",
        json={"user_id": user_id, "force": True},
    )
    assert result.status_code == 200, result.text
    payload = result.json()

    refs = payload["episode"]["source_item_refs"]
    # 1 email-kind inbound (under the cap=1) + 2 shared items (cap-bypassing).
    assert len(refs) == 3, f"expected 3 refs (1 email + 2 shared), got {len(refs)}: {refs}"

    ref_links = {r["link"] for r in refs}
    assert "https://example.com/email-story" in ref_links
    assert "https://example.com/shared-a" in ref_links
    assert "https://example.com/shared-b" in ref_links

    # All inbound items (email + share) should be marked consumed.
    for item_id in ["inbound-email-1"]:
        assert repo.get_inbound_item(item_id).consumed_at is not None
    for shared_item in repo.list_recent_inbound_items(user_id, limit=10):
        if shared_item.kind == "share":
            assert shared_item.consumed_at is not None, (
                f"shared item {shared_item.id} should be consumed after episode publishes"
            )


def test_only_shared_items_can_publish_an_episode(monkeypatch):
    """A user with zero RSS items and zero email-kind inbound items but one
    shared item should still produce an episode — the no-content short-circuit
    must consider shared items."""
    from newsletter_pod import control_plane as cp_module

    container, client = _build_app()
    user_id, headers = _seed_user_for_inbound_run(
        client, container, monkeypatch,
        email="only-share@example.com", subject="only-share-user",
    )

    monkeypatch.setattr(
        cp_module,
        "extract_from_url",
        lambda url: ("Only thing", "Only body."),
    )
    resp = client.post(
        "/v1/items/shared",
        data={"kind": "url", "url": "https://example.com/only"},
        headers=headers,
    )
    assert resp.status_code == 201

    result = client.post(
        "/jobs/process-user-podcast",
        json={"user_id": user_id, "force": True},
    )
    assert result.status_code == 200, result.text
    payload = result.json()
    # The "no content" branch returns the run record bare; "has content"
    # wraps it in {"run": ..., "episode": ...}. We want the wrapped form.
    assert "episode" in payload, f"expected an episode, got {payload}"
    refs = payload["episode"]["source_item_refs"]
    assert len(refs) == 1
    assert refs[0]["link"] == "https://example.com/only"


def test_weekly_update_segment_stamps_user_once_per_iso_week(monkeypatch):
    from newsletter_pod import control_plane as cp_module

    container, client = _build_app()
    container.control_plane.apple_identity_verifier = FakeAppleVerifier(
        "weekly-user", "weekly@example.com"
    )
    auth = client.post("/v1/auth/apple", json={"identity_token": "apple-token"})
    user_id = auth.json()["user"]["id"]
    session_token = auth.json()["session_token"]
    headers = {"Authorization": f"Bearer {session_token}"}

    catalog = client.get("/v1/sources/catalog").json()["sources"]
    client.put(
        "/v1/me/sources",
        json={"sources": [{"source_id": catalog[0]["source_id"]}]},
        headers=headers,
    )
    container.control_plane.podcast_client = FakePodcastClient()

    captured_prompts: list[str] = []

    class CapturingPodcastClient(FakePodcastClient):
        def generate(self, prompt, title, voice_id=None, secondary_voice_id=None, primary_speaker_name=None, secondary_speaker_name=None, ux=None, force_default_voice=False):
            captured_prompts.append(prompt)
            return super().generate(
                prompt,
                title,
                voice_id=voice_id,
                secondary_voice_id=secondary_voice_id,
                primary_speaker_name=primary_speaker_name,
                secondary_speaker_name=secondary_speaker_name,
                ux=ux,
                force_default_voice=force_default_voice,
            )

    container.control_plane.podcast_client = CapturingPodcastClient()

    def fake_fetch(self, sources):
        return IngestionResult(
            items=[
                SourceItem(
                    source_id="source-a",
                    source_name="Source A",
                    guid="1",
                    link="https://example.com/1",
                    title="Story",
                    summary="Summary",
                    published_at=datetime(2026, 5, 4, 8, 0, tzinfo=timezone.utc),
                    dedupe_key="1",
                ),
            ],
            cursor_updates={"source-a": datetime(2026, 5, 4, 8, 0, tzinfo=timezone.utc)},
        )

    monkeypatch.setattr(RSSIngestionService, "fetch_new_items", fake_fetch)
    monkeypatch.setattr(
        cp_module,
        "load_recent_commits",
        lambda project_root: ["Add Last Week in Denmark to default News sources"],
    )

    first = client.post(
        "/jobs/process-user-podcast", json={"user_id": user_id, "force": True}
    )
    assert first.status_code == 200
    assert "This week at ClawCast" in captured_prompts[0]

    user_after_first = container.control_repository.get_user(user_id)
    assert user_after_first is not None
    stamped_week = user_after_first.last_weekly_update_iso_week
    assert stamped_week is not None
    assert stamped_week.startswith(str(datetime.now(timezone.utc).year))

    # Second run in the same ISO week should NOT include the segment.
    second = client.post(
        "/jobs/process-user-podcast", json={"user_id": user_id, "force": True}
    )
    assert second.status_code == 200
    assert len(captured_prompts) == 2
    assert "This week at ClawCast" not in captured_prompts[1]

    # Stamp is unchanged.
    user_after_second = container.control_repository.get_user(user_id)
    assert user_after_second.last_weekly_update_iso_week == stamped_week


def test_weekly_update_segment_skipped_when_no_commits(monkeypatch):
    from newsletter_pod import control_plane as cp_module

    container, client = _build_app()
    container.control_plane.apple_identity_verifier = FakeAppleVerifier(
        "weekly-empty-user", "weekly2@example.com"
    )
    auth = client.post("/v1/auth/apple", json={"identity_token": "apple-token"})
    user_id = auth.json()["user"]["id"]
    session_token = auth.json()["session_token"]
    headers = {"Authorization": f"Bearer {session_token}"}

    catalog = client.get("/v1/sources/catalog").json()["sources"]
    client.put(
        "/v1/me/sources",
        json={"sources": [{"source_id": catalog[0]["source_id"]}]},
        headers=headers,
    )

    captured_prompts: list[str] = []

    class CapturingPodcastClient(FakePodcastClient):
        def generate(self, prompt, title, voice_id=None, secondary_voice_id=None, primary_speaker_name=None, secondary_speaker_name=None, ux=None, force_default_voice=False):
            captured_prompts.append(prompt)
            return super().generate(
                prompt,
                title,
                voice_id=voice_id,
                secondary_voice_id=secondary_voice_id,
                primary_speaker_name=primary_speaker_name,
                secondary_speaker_name=secondary_speaker_name,
                ux=ux,
                force_default_voice=force_default_voice,
            )

    container.control_plane.podcast_client = CapturingPodcastClient()

    def fake_fetch(self, sources):
        return IngestionResult(
            items=[
                SourceItem(
                    source_id="source-a",
                    source_name="Source A",
                    guid="1",
                    link="https://example.com/1",
                    title="Story",
                    summary="Summary",
                    published_at=datetime(2026, 5, 4, 8, 0, tzinfo=timezone.utc),
                    dedupe_key="1",
                ),
            ],
            cursor_updates={"source-a": datetime(2026, 5, 4, 8, 0, tzinfo=timezone.utc)},
        )

    monkeypatch.setattr(RSSIngestionService, "fetch_new_items", fake_fetch)
    monkeypatch.setattr(cp_module, "load_recent_commits", lambda project_root: [])

    response = client.post(
        "/jobs/process-user-podcast", json={"user_id": user_id, "force": True}
    )
    assert response.status_code == 200
    assert "This week at ClawCast" not in captured_prompts[0]
    user_after = container.control_repository.get_user(user_id)
    assert user_after.last_weekly_update_iso_week is None


class _FakeIntakeExtractor:
    def __init__(self, payload) -> None:
        self._payload = payload
        self.calls: list[str] = []

    def extract(self, transcript: str):
        self.calls.append(transcript)
        return self._payload


def _wire_voice_intake(container, payload) -> _FakeIntakeExtractor:
    from newsletter_pod.embeddings import DeterministicFakeEmbeddingProvider
    from newsletter_pod.source_persistence import SourceItemPersistenceService

    extractor = _FakeIntakeExtractor(payload)
    container.control_plane.intake_extractor = extractor
    container.control_plane.embedding_provider = DeterministicFakeEmbeddingProvider()
    container.control_plane._source_item_persistence = SourceItemPersistenceService(
        repository=container.control_repository,
        embeddings=container.control_plane.embedding_provider,
    )
    return extractor


def test_voice_intake_seeds_synthetic_swipes_and_appends_guidance():
    from newsletter_pod.voice_intake import ExtractedIntake

    container, client = _build_app()
    _, headers = _auth_headers(client, FakeAppleVerifier("voice-user-1", "vu1@example.com"))
    _wire_voice_intake(
        container,
        ExtractedIntake(
            topics=["AI compute", "Premier League"],
            named_entities=["Anthropic"],
            anchor_phrases=["chasing the compute story"],
            vibe_notes="Casual and quick.",
        ),
    )
    response = client.post(
        "/v1/me/voice-intake",
        json={"transcript": "I've been chasing the Anthropic compute story and Premier League."},
        headers=headers,
    )
    assert response.status_code == 201
    body = response.json()
    assert body["seeded_count"] == 4  # 2 topics + 1 entity + 1 anchor
    assert body["vibe_notes"] == "Casual and quick."

    swipes = list(container.control_repository._swipes.values())
    assert len(swipes) == 4
    assert {swipe.seed_kind for swipe in swipes} == {"voice_intake"}
    assert all(swipe.direction == 1 for swipe in swipes)

    profile_response = client.get("/v1/me/podcast-config", headers=headers)
    assert profile_response.status_code == 200
    custom_guidance = profile_response.json()["profile"]["custom_guidance"]
    assert custom_guidance and "Casual and quick." in custom_guidance


def test_voice_intake_rejects_empty_transcript():
    from newsletter_pod.voice_intake import ExtractedIntake

    container, client = _build_app()
    _, headers = _auth_headers(client, FakeAppleVerifier("voice-user-2", "vu2@example.com"))
    _wire_voice_intake(container, ExtractedIntake())

    response = client.post(
        "/v1/me/voice-intake", json={"transcript": "   "}, headers=headers
    )
    assert response.status_code == 400


def test_voice_intake_returns_400_when_embeddings_not_configured():
    container, client = _build_app()
    _, headers = _auth_headers(client, FakeAppleVerifier("voice-user-3", "vu3@example.com"))
    container.control_plane.embedding_provider = None
    container.control_plane.intake_extractor = _FakeIntakeExtractor(None)

    response = client.post(
        "/v1/me/voice-intake",
        json={"transcript": "Some thoughts I have"},
        headers=headers,
    )
    assert response.status_code == 400
    assert "embeddings" in response.json()["detail"].lower()


def test_voice_intake_anchors_surface_in_listener_anchors():
    from newsletter_pod.voice_intake import ExtractedIntake

    container, client = _build_app()
    _, headers = _auth_headers(client, FakeAppleVerifier("anchor-user", "anchor@example.com"))
    _wire_voice_intake(
        container,
        ExtractedIntake(
            topics=["AI compute"],
            anchor_phrases=["chasing the compute story"],
        ),
    )
    client.post(
        "/v1/me/voice-intake",
        json={"transcript": "AI stuff"},
        headers=headers,
    )
    user_id = list(container.control_repository._users.values())[0].id
    anchors = container.control_plane._compute_listener_anchors(user_id)
    # Both topics and anchor phrases are written as voice-intake seeds; both
    # should surface as listener anchors.
    assert "AI compute" in anchors
    assert "chasing the compute story" in anchors


def test_substack_intent_creation_seeds_interest_vector(monkeypatch):
    container, client = _build_app()
    _, headers = _auth_headers(
        client, FakeAppleVerifier("substack-seed-user", "ss@example.com")
    )

    from newsletter_pod.embeddings import DeterministicFakeEmbeddingProvider
    container.control_plane.embedding_provider = DeterministicFakeEmbeddingProvider()

    from newsletter_pod import control_plane as cp_module
    from newsletter_pod.substack import SubstackProbeResult

    def _fake_probe(pub_url, session=None):
        return SubstackProbeResult(
            pub_url="https://stratechery.substack.com",
            pub_host="stratechery.substack.com",
            title="Stratechery",
            author="Ben Thompson",
            icon_url=None,
            has_paid_tier=True,
            feed_url="https://stratechery.substack.com/feed",
        )

    monkeypatch.setattr(cp_module, "probe_publication", _fake_probe)

    response = client.post(
        "/v1/me/substack/intents",
        json={"pub_url": "https://stratechery.substack.com"},
        headers=headers,
    )
    assert response.status_code == 201

    swipes = list(container.control_repository._swipes.values())
    paste_seeds = [swipe for swipe in swipes if swipe.seed_kind == "substack_paste"]
    assert len(paste_seeds) == 1
    assert paste_seeds[0].title == "Stratechery"
    assert paste_seeds[0].direction == 1


def test_forwarded_mail_creates_synthetic_swipe_when_sender_matches_user_email():
    from newsletter_pod.embeddings import DeterministicFakeEmbeddingProvider
    from newsletter_pod.inbound import InboundEmailHandler
    import hashlib
    import hmac

    container, _ = _build_app()
    repo = container.control_repository
    # Manually create a user + alias.
    from newsletter_pod.user_models import UserRecord
    user = UserRecord(
        id="fwd-user-1",
        apple_subject="fwd-subject-1",
        email="vince@example.com",
        display_name="Vince",
        timezone="UTC",
        inbound_alias="abcd1234",
        created_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
        updated_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
    )
    repo.save_user(user)

    handler = InboundEmailHandler(
        repository=repo,
        inbound_email_domain="theclawcast.com",
        mailgun_signing_key="testkey",
        embeddings=DeterministicFakeEmbeddingProvider(),
    )

    timestamp = "1700000000"
    token = "fwd-token"
    signature = hmac.new(
        key=b"testkey", msg=f"{timestamp}{token}".encode(), digestmod=hashlib.sha256
    ).hexdigest()
    payload = {
        "recipient": "abcd1234@theclawcast.com",
        "from": "Vince <vince@example.com>",
        "subject": "Fwd: Anthropic and the future of compute",
        "stripped-text": "Worth reading. Original article by Ben Thompson...",
        "Date": "Wed, 30 Apr 2026 12:00:00 +0000",
        "Message-Id": "<fwd-msg-1@example.com>",
        "timestamp": timestamp,
        "token": token,
        "signature": signature,
    }

    result = handler.handle(payload)
    assert result["status"] == "stored"

    swipes = list(repo._swipes.values())
    forwarded_seeds = [swipe for swipe in swipes if swipe.seed_kind == "forwarded_mail"]
    assert len(forwarded_seeds) == 1
    assert "Anthropic" in forwarded_seeds[0].title


def test_discover_substacks_endpoint_returns_validated_candidates(monkeypatch):
    container, client = _build_app()
    _, headers = _auth_headers(
        client, FakeAppleVerifier("discover-user", "discover@example.com")
    )

    from newsletter_pod.substack import SubstackProbeResult
    from newsletter_pod.substack_discovery import (
        DiscoveredPublication,
        SubstackDiscoveryService,
    )

    class _Stub:
        def discover(self, query):
            return [
                DiscoveredPublication(
                    probe=SubstackProbeResult(
                        pub_url="https://stratechery.substack.com",
                        pub_host="stratechery.substack.com",
                        title="Stratechery",
                        author="Ben Thompson",
                        icon_url=None,
                        has_paid_tier=True,
                        feed_url="https://stratechery.substack.com/feed",
                    ),
                    why="AI strategy and platform economics.",
                ),
            ]

    container.control_plane.substack_discovery = _Stub()
    response = client.post(
        "/v1/substack/discover",
        json={"query": "AI strategy"},
        headers=headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert len(body["candidates"]) == 1
    candidate = body["candidates"][0]
    assert candidate["pub_host"] == "stratechery.substack.com"
    assert candidate["title"] == "Stratechery"
    assert candidate["why"] == "AI strategy and platform economics."


def test_discover_substacks_returns_400_when_discovery_unavailable():
    container, client = _build_app()
    _, headers = _auth_headers(
        client, FakeAppleVerifier("discover-no-llm", "noll@example.com")
    )
    container.control_plane.substack_discovery = None

    response = client.post(
        "/v1/substack/discover",
        json={"query": "anything"},
        headers=headers,
    )
    assert response.status_code == 400


def test_discover_substacks_rejects_empty_query():
    container, client = _build_app()
    _, headers = _auth_headers(
        client, FakeAppleVerifier("discover-empty", "empty@example.com")
    )

    class _StubAlwaysEmpty:
        def discover(self, query):
            return []

    container.control_plane.substack_discovery = _StubAlwaysEmpty()
    response = client.post(
        "/v1/substack/discover", json={"query": "   "}, headers=headers
    )
    assert response.status_code == 400


def test_cold_start_deck_runs_card_summaries():
    """Cold-start deck items get card_summary populated by the configured
    summarizer service before being serialized."""
    container, client = _build_app()
    _, headers = _auth_headers(
        client, FakeAppleVerifier("card-summary-user", "cs@example.com")
    )

    # Seed an embedded item so the k-means deck has something to pick.
    _seed_source_item(container, "cs-key-1", embedding=[1.0, 0.0])

    class _StubSummarizer:
        model = "stub"

        def summarize(self, items):
            return [f"brief: {title}" for title, _body in items]

    from newsletter_pod.card_summary import CardSummaryService
    container.control_plane.card_summarizer = _StubSummarizer()
    container.control_plane._card_summary_service = CardSummaryService(
        repository=container.control_repository,
        summarizer=_StubSummarizer(),
    )

    response = client.get("/v1/me/swipe-deck/cold-start", headers=headers)
    assert response.status_code == 200
    items = response.json()["items"]
    assert items, "deck should not be empty"
    assert items[0]["card_summary"].startswith("brief: ")


def test_forwarded_mail_does_not_seed_when_sender_does_not_match_user_email():
    from newsletter_pod.embeddings import DeterministicFakeEmbeddingProvider
    from newsletter_pod.inbound import InboundEmailHandler
    import hashlib
    import hmac

    container, _ = _build_app()
    repo = container.control_repository
    from newsletter_pod.user_models import UserRecord
    user = UserRecord(
        id="fwd-user-2",
        apple_subject="fwd-subject-2",
        email="vince@example.com",
        display_name="Vince",
        timezone="UTC",
        inbound_alias="efgh5678",
        created_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
        updated_at=datetime(2026, 5, 1, tzinfo=timezone.utc),
    )
    repo.save_user(user)

    handler = InboundEmailHandler(
        repository=repo,
        inbound_email_domain="theclawcast.com",
        mailgun_signing_key="testkey",
        embeddings=DeterministicFakeEmbeddingProvider(),
    )
    timestamp = "1700000000"
    token = "fwd-token-2"
    signature = hmac.new(
        key=b"testkey", msg=f"{timestamp}{token}".encode(), digestmod=hashlib.sha256
    ).hexdigest()
    payload = {
        "recipient": "efgh5678@theclawcast.com",
        "from": "Ben Thompson <ben@stratechery.com>",
        "subject": "The compute story",
        "stripped-text": "This week...",
        "Date": "Wed, 30 Apr 2026 12:00:00 +0000",
        "Message-Id": "<reg-msg-1@example.com>",
        "timestamp": timestamp,
        "token": token,
        "signature": signature,
    }
    handler.handle(payload)

    swipes = list(repo._swipes.values())
    forwarded_seeds = [swipe for swipe in swipes if swipe.seed_kind == "forwarded_mail"]
    assert forwarded_seeds == []


def test_delete_me_wipes_account_and_audio():
    container, client = _build_app()
    verifier = FakeAppleVerifier("delete-user", "delete@example.com")
    token, headers = _auth_headers(client, verifier)
    repo = container.control_repository
    storage = container.storage

    # Stash a fake episode + audio blob so we can verify both get wiped.
    object_name, _ = storage.upload_audio("ep-1", b"audio-bytes", "audio/mpeg")
    user_id = container.control_plane.get_authenticated_user(token).id
    repo.save_user_episode(
        UserEpisodeRecord(
            id="ep-1",
            user_id=user_id,
            title="Test episode",
            description="",
            published_at=datetime(2026, 5, 16, tzinfo=timezone.utc),
            audio_object_name=object_name,
            audio_size_bytes=len(b"audio-bytes"),
        )
    )

    # Submit a piece of feedback so we have a per-user record outside the
    # default-seeded ones to confirm wiping.
    fb_resp = client.post("/v1/me/feedback", json={"text": "hi"}, headers=headers)
    assert fb_resp.status_code == 201
    assert len(repo.list_recent_feedback(user_id, limit=5)) == 1
    assert repo.get_user(user_id) is not None

    # Act: delete the account.
    resp = client.delete("/v1/me", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["already_deleted"] is False
    assert body["audio_objects_deleted"] == 1
    records = body["records"]
    assert records["users"] == 1
    assert records["podcast_profiles"] == 1
    assert records["feedback"] >= 1
    assert records["user_episodes"] == 1

    # User and per-user records gone.
    assert repo.get_user(user_id) is None
    assert repo.get_profile(user_id) is None
    assert repo.get_schedule(user_id) is None
    assert repo.list_recent_feedback(user_id, limit=5) == []
    assert repo.list_recent_user_episodes(user_id, limit=5) == []

    # Audio blob gone from storage.
    import pytest

    with pytest.raises(FileNotFoundError):
        storage.download_audio(object_name)

    # Session token no longer authenticates anything.
    after = client.get("/v1/me", headers=headers)
    assert after.status_code in (401, 404)


def test_delete_me_is_idempotent():
    container, client = _build_app()
    verifier = FakeAppleVerifier("delete-twice-user", "twice@example.com")
    _, headers = _auth_headers(client, verifier)

    first = client.delete("/v1/me", headers=headers)
    assert first.status_code == 200
    assert first.json()["already_deleted"] is False

    # Second call uses the same now-invalid session and should fail auth
    # rather than 500.
    second = client.delete("/v1/me", headers=headers)
    assert second.status_code in (401, 404)


def test_reset_me_wipes_onboarding_state_but_keeps_account():
    from newsletter_pod.substack import build_intent_id
    from newsletter_pod.user_models import (
        DeliveryScheduleRecord,
        PodcastProfileRecord,
        SwipeRecord,
        UserSourceRecord,
        UserSubstackIntent,
    )

    container, client = _build_app()
    verifier = FakeAppleVerifier("reset-user", "reset@example.com")
    token, headers = _auth_headers(client, verifier)
    repo = container.control_repository
    user_id = container.control_plane.get_authenticated_user(token).id

    now = datetime(2026, 5, 16, tzinfo=timezone.utc)
    repo.replace_user_sources(
        user_id,
        [
            UserSourceRecord(
                id=f"{user_id}:src-a",
                user_id=user_id,
                source_id="src-a",
                name="Source A",
                rss_url="https://example.com/a.rss",
                created_at=now,
                updated_at=now,
            )
        ],
    )
    repo.save_profile(
        PodcastProfileRecord(user_id=user_id, created_at=now, updated_at=now)
    )
    repo.save_schedule(
        DeliveryScheduleRecord(user_id=user_id, created_at=now, updated_at=now)
    )
    repo.save_swipe(
        SwipeRecord(
            id="swipe-1",
            user_id=user_id,
            source_item_dedupe_key="dk-1",
            direction=1,
            title="An item",
            link="https://example.com/1",
            source_id="src-a",
            source_name="Source A",
            embedding=[0.1, 0.2],
            embedding_model="test",
            swiped_at=now,
        )
    )
    repo.save_substack_intent(
        UserSubstackIntent(
            id=build_intent_id(user_id, "example.substack.com"),
            user_id=user_id,
            pub_url="https://example.substack.com",
            pub_host="example.substack.com",
            pub_title="Test Pub",
            alias_email="aaa@theclawcast.com",
            created_at=now,
        )
    )
    repo.update_user_source_cursors(user_id, {"src-a": now})
    user = repo.get_user(user_id)
    user.last_weekly_update_iso_week = "2026-W20"
    repo.save_user(user)

    # Also stash an episode so we can prove reset KEEPS episode history.
    repo.save_user_episode(
        UserEpisodeRecord(
            id="ep-1",
            user_id=user_id,
            title="Past episode",
            description="",
            published_at=now,
            audio_object_name="audio/ep-1.mp3",
            audio_size_bytes=10,
        )
    )

    resp = client.post("/v1/me/reset", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert body["user_id"] == user_id
    records = body["records"]
    assert records["user_sources"] == 1
    assert records["podcast_profiles"] == 1
    assert records["delivery_schedules"] == 1
    assert records["swipes"] == 1
    assert records["user_substack_intents"] == 1
    assert records["user_cursors"] == 1

    assert repo.list_user_sources(user_id) == []
    assert repo.get_profile(user_id) is None
    assert repo.get_schedule(user_id) is None
    assert repo.list_user_swipes(user_id) == []
    assert repo.list_user_substack_intents(user_id) == []
    assert repo.get_user_source_cursor(user_id, "src-a") is None
    assert repo.get_user(user_id).last_weekly_update_iso_week is None

    # Account, session, and episode history survive.
    assert repo.get_user(user_id) is not None
    assert repo.list_recent_user_episodes(user_id, limit=5)[0].id == "ep-1"
    me_after = client.get("/v1/me", headers=headers)
    assert me_after.status_code == 200


def test_reset_me_is_idempotent():
    container, client = _build_app()
    verifier = FakeAppleVerifier("reset-twice-user", "reset2@example.com")
    _, headers = _auth_headers(client, verifier)

    first = client.post("/v1/me/reset", headers=headers)
    assert first.status_code == 200
    second = client.post("/v1/me/reset", headers=headers)
    assert second.status_code == 200
    assert all(count == 0 for count in second.json()["records"].values())


def test_delete_me_anonymizes_billing_events():
    from newsletter_pod.user_models import BillingEventRecord

    container, client = _build_app()
    verifier = FakeAppleVerifier("billing-user", "bill@example.com")
    token, headers = _auth_headers(client, verifier)
    repo = container.control_repository
    user_id = container.control_plane.get_authenticated_user(token).id

    repo.save_billing_event(
        BillingEventRecord(
            id="evt-1",
            user_id=user_id,
            notification_type="SUBSCRIBED",
            product_id="pro-monthly",
            raw_payload={"signedPayload": "..."},
            created_at=datetime(2026, 5, 16, tzinfo=timezone.utc),
        )
    )

    resp = client.delete("/v1/me", headers=headers)
    assert resp.status_code == 200
    assert resp.json()["records"]["billing_events_anonymized"] == 1

    # The billing row survives but is no longer linked to the user.
    assert repo._billing_events["evt-1"].user_id is None
    assert repo._billing_events["evt-1"].notification_type == "SUBSCRIBED"
