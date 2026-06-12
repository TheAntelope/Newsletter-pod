from __future__ import annotations

from datetime import datetime, timezone
from xml.etree import ElementTree as ET

from fastapi.testclient import TestClient

from newsletter_pod.broadcast.models import BroadcastEpisodeRecord
from newsletter_pod.broadcast.repository import InMemoryBroadcastRepository
from newsletter_pod.config import Settings
from newsletter_pod.main import _build_container, create_app

ITUNES_NS = "http://www.itunes.com/dtds/podcast-1.0.dtd"


def _build_client() -> tuple[TestClient, InMemoryBroadcastRepository, object]:
    settings = Settings.from_env()
    settings.use_inmemory_adapters = True
    settings.session_signing_secret = "test-session-secret-32-bytes-long"
    settings.podcast_api_key = None
    settings.podcast_api_enabled = False
    settings.job_trigger_token = None  # auth disabled for tests
    settings.app_base_url = "http://testserver"
    settings.publish_summary_email_enabled = False
    container = _build_container(settings)
    client = TestClient(create_app(container=container))
    assert isinstance(container.broadcast_repository, InMemoryBroadcastRepository)
    return client, container.broadcast_repository, container.storage


_LOOP_PAYLOAD = {
    "loop_id": "us-morning",
    "region": "US",
    "timezone": "America/Los_Angeles",
    "audience_persona": "indie founders",
    "post_local_time": "08:00",
    "seed_topics": ["topic-a"],
    "active": True,
}


def _save_episode(repo, storage, *, episode_id: str, run_date: datetime, with_audio: bool = True):
    audio_object_name = f"broadcast/{episode_id}.mp3"
    if with_audio:
        storage.upload_object(audio_object_name, b"x" * 16000, "audio/mpeg")
    repo.save_episode(
        BroadcastEpisodeRecord(
            episode_id=episode_id,
            loop_id="us-morning",
            run_date=run_date.date(),
            topic_used="topic",
            title=f"Episode {episode_id[:4]}",
            show_notes="Show notes here.",
            audio_object_name=audio_object_name,
            video_object_name=f"broadcast/{episode_id}.mp4",
            episode_tweet_url="https://x.com/theclawcast_/status/1",
            created_at=run_date.replace(tzinfo=timezone.utc),
        )
    )


def test_feed_lists_episodes_newest_first_with_enclosures():
    client, repo, storage = _build_client()
    client.post("/jobs/broadcast/loops", json=_LOOP_PAYLOAD)
    _save_episode(repo, storage, episode_id="aaaaaaaaaaaaaaaa", run_date=datetime(2026, 6, 1))
    _save_episode(repo, storage, episode_id="bbbbbbbbbbbbbbbb", run_date=datetime(2026, 6, 3))

    resp = client.get("/broadcast/us-morning/feed.xml")

    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("application/rss+xml")
    root = ET.fromstring(resp.content)
    items = root.findall("./channel/item")
    # Newest first (run_date desc).
    guids = [item.find("guid").text for item in items]
    assert guids == ["bbbbbbbbbbbbbbbb", "aaaaaaaaaaaaaaaa"]
    enclosure = items[0].find("enclosure")
    assert enclosure.attrib["url"] == "http://testserver/broadcast/bbbbbbbbbbbbbbbb.mp3"
    assert enclosure.attrib["type"] == "audio/mpeg"
    assert int(enclosure.attrib["length"]) == 16000
    # Duration is derived from byte size at 128 kbps: 16000*8/128000 = 1s.
    assert items[0].find(f"{{{ITUNES_NS}}}duration").text == "1"


def test_feed_skips_episodes_whose_audio_is_missing():
    client, repo, storage = _build_client()
    client.post("/jobs/broadcast/loops", json=_LOOP_PAYLOAD)
    _save_episode(repo, storage, episode_id="cccccccccccccccc", run_date=datetime(2026, 6, 1))
    # Row exists but no audio object was uploaded (failed run).
    _save_episode(
        repo, storage, episode_id="dddddddddddddddd", run_date=datetime(2026, 6, 2), with_audio=False
    )

    resp = client.get("/broadcast/us-morning/feed.xml")

    assert resp.status_code == 200
    root = ET.fromstring(resp.content)
    guids = [item.find("guid").text for item in root.findall("./channel/item")]
    assert guids == ["cccccccccccccccc"]


def test_feed_for_unknown_loop_is_empty_not_error():
    client, _, _ = _build_client()
    client.post("/jobs/broadcast/loops", json=_LOOP_PAYLOAD)

    resp = client.get("/broadcast/never-created/feed.xml")

    # A real-but-empty loop id renders a valid feed with no items, rather than
    # leaking existence via status codes.
    assert resp.status_code == 200
    root = ET.fromstring(resp.content)
    assert root.findall("./channel/item") == []


def test_feed_rejects_malformed_loop_id_as_404():
    client, _, _ = _build_client()

    resp = client.get("/broadcast/has spaces/feed.xml")

    assert resp.status_code == 404


def test_feed_is_public_no_auth_required():
    # The job-trigger token is set, but the feed must remain reachable without
    # it — podcast players can't send the header.
    settings = Settings.from_env()
    settings.use_inmemory_adapters = True
    settings.session_signing_secret = "test-session-secret-32-bytes-long"
    settings.podcast_api_key = None
    settings.podcast_api_enabled = False
    settings.job_trigger_token = "secret-token"
    settings.app_base_url = "http://testserver"
    settings.publish_summary_email_enabled = False
    container = _build_container(settings)
    client = TestClient(create_app(container=container))

    # No loop created and no auth header sent — still a valid (empty) feed.
    resp = client.get("/broadcast/us-morning/feed.xml")
    assert resp.status_code == 200
