from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from newsletter_pod.config import Settings
from newsletter_pod.ingestion import RSSIngestionService
from newsletter_pod.main import ServiceContainer, create_app
from newsletter_pod.mailer import NoopMailer
from newsletter_pod.models import EpisodeRecord
from newsletter_pod.pipeline import DigestPipeline
from newsletter_pod.podcast_api import PodcastApiClient
from newsletter_pod.repository import InMemoryRepository
from newsletter_pod.retry_policy import RetryPolicy
from newsletter_pod.storage import InMemoryAudioStorage


def build_test_client(feed_token: str = "secret-token") -> tuple[TestClient, InMemoryRepository, InMemoryAudioStorage]:
    settings = Settings.from_env()
    settings.feed_token = feed_token
    settings.app_base_url = "http://testserver"
    settings.job_trigger_token = None
    settings.max_feed_episodes = 30

    repository = InMemoryRepository()
    storage = InMemoryAudioStorage()
    ingestion = RSSIngestionService(repository=repository)
    retry_policy = RetryPolicy(
        timezone_name="Europe/Copenhagen",
        start_local="06:30",
        target_local="07:00",
        cutoff_local="23:00",
        rapid_retry_minutes=5,
        periodic_retry_minutes=30,
    )

    pipeline = DigestPipeline(
        sources=[],
        repository=repository,
        ingestion_service=ingestion,
        podcast_client=PodcastApiClient(
            enabled=False,
            provider="generic",
            base_url=None,
            api_key=None,
            timeout_seconds=60,
            poll_seconds=5,
            text_model="gpt-5.4-mini",
            tts_model="gpt-4o-mini-tts",
            tts_voice="alloy",
        ),
        storage=storage,
        mailer=NoopMailer(),
        retry_policy=retry_policy,
    )

    container = ServiceContainer(
        settings=settings,
        repository=repository,
        storage=storage,
        pipeline=pipeline,
    )

    app = create_app(container=container)
    return TestClient(app), repository, storage


def test_run_digest_accepts_x_job_trigger_token_header():
    settings = Settings.from_env()
    settings.feed_token = "secret-token"
    settings.app_base_url = "http://testserver"
    settings.job_trigger_token = "job-token"
    settings.max_feed_episodes = 30

    repository = InMemoryRepository()
    storage = InMemoryAudioStorage()
    ingestion = RSSIngestionService(repository=repository)
    retry_policy = RetryPolicy(
        timezone_name="Europe/Copenhagen",
        start_local="06:30",
        target_local="07:00",
        cutoff_local="23:00",
        rapid_retry_minutes=5,
        periodic_retry_minutes=30,
    )

    pipeline = DigestPipeline(
        sources=[],
        repository=repository,
        ingestion_service=ingestion,
        podcast_client=PodcastApiClient(
            enabled=False,
            provider="generic",
            base_url=None,
            api_key=None,
            timeout_seconds=60,
            poll_seconds=5,
            text_model="gpt-5.4-mini",
            tts_model="gpt-4o-mini-tts",
            tts_voice="alloy",
        ),
        storage=storage,
        mailer=NoopMailer(),
        retry_policy=retry_policy,
    )

    container = ServiceContainer(
        settings=settings,
        repository=repository,
        storage=storage,
        pipeline=pipeline,
    )

    client = TestClient(create_app(container=container))
    response = client.post(
        "/jobs/run-digest",
        json={"force": True},
        headers={"X-Job-Trigger-Token": "job-token"},
    )

    assert response.status_code == 200


def test_feed_and_media_require_valid_token_and_return_content():
    client, repository, storage = build_test_client()
    assert client.get("/healthz").status_code == 200
    assert client.get("/health").status_code == 200

    object_name, size = storage.upload_audio("ep-1", b"audio", "audio/mpeg")

    episode = EpisodeRecord(
        id="ep-1",
        title="Episode 1",
        description="Show notes",
        published_at=datetime(2026, 3, 9, 6, 0, tzinfo=timezone.utc),
        audio_object_name=object_name,
        audio_mime_type="audio/mpeg",
        audio_size_bytes=size,
        source_item_refs=[],
    )
    repository.save_episode(episode)

    bad_feed = client.get("/feed/wrong.xml")
    assert bad_feed.status_code == 404

    good_feed = client.get("/feed/secret-token.xml")
    assert good_feed.status_code == 200
    assert "application/rss+xml" in good_feed.headers["content-type"]
    assert "itunes:author" in good_feed.text
    assert "enclosure" in good_feed.text
    assert "/media/secret-token/ep-1.mp3" in good_feed.text
    assert good_feed.headers["accept-ranges"] == "bytes"

    head_feed = client.head("/feed/secret-token.xml")
    assert head_feed.status_code == 200
    assert "application/rss+xml" in head_feed.headers["content-type"]
    assert head_feed.headers["accept-ranges"] == "bytes"

    bad_media = client.get("/media/wrong/ep-1.mp3")
    assert bad_media.status_code == 404

    good_media = client.get("/media/secret-token/ep-1.mp3")
    assert good_media.status_code == 200
    assert good_media.content == b"audio"
    assert good_media.headers["accept-ranges"] == "bytes"

    head_media = client.head("/media/secret-token/ep-1.mp3")
    assert head_media.status_code == 200
    assert head_media.headers["content-length"] == "5"
    assert head_media.headers["accept-ranges"] == "bytes"

    ranged_media = client.get("/media/secret-token/ep-1.mp3", headers={"Range": "bytes=0-1"})
    assert ranged_media.status_code == 206
    assert ranged_media.content == b"au"
    assert ranged_media.headers["content-range"] == "bytes 0-1/5"
    assert ranged_media.headers["content-length"] == "2"
