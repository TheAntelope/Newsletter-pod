from __future__ import annotations

from datetime import datetime, timezone

from fastapi.testclient import TestClient

from newsletter_pod.broadcast.models import BroadcastEpisodeRecord
from newsletter_pod.broadcast.repository import InMemoryBroadcastRepository
from newsletter_pod.config import Settings
from newsletter_pod.main import _build_container, create_app


def _build_client() -> tuple[TestClient, InMemoryBroadcastRepository]:
    settings = Settings.from_env()
    settings.use_inmemory_adapters = True
    settings.session_signing_secret = "test-session-secret-32-bytes-long"
    # Clear the LLM key so the broadcast tests are hermetic — the feedback
    # summarizer/topic proposer gate on podcast_api_key (a general OpenAI key),
    # which Settings.from_env() would otherwise pick up from a local .env and
    # silently flip the "no summarizer" path into a live call.
    settings.podcast_api_key = None
    settings.podcast_api_enabled = False
    settings.job_trigger_token = None  # auth disabled for tests
    settings.app_base_url = "http://testserver"
    settings.publish_summary_email_enabled = False
    container = _build_container(settings)
    client = TestClient(create_app(container=container))
    assert isinstance(container.broadcast_repository, InMemoryBroadcastRepository)
    return client, container.broadcast_repository


_VALID_LOOP_PAYLOAD = {
    "loop_id": "us-morning",
    "region": "US",
    "timezone": "America/Los_Angeles",
    "audience_persona": "indie founders",
    "post_local_time": "08:00",
    "seed_topics": ["topic-a", "topic-b"],
    "active": True,
}


def test_upsert_creates_loop_and_returns_payload():
    client, repo = _build_client()

    resp = client.post("/jobs/broadcast/loops", json=_VALID_LOOP_PAYLOAD)

    assert resp.status_code == 200
    body = resp.json()
    assert body["loop_id"] == "us-morning"
    assert body["region"] == "US"
    assert body["seed_topics"] == ["topic-a", "topic-b"]
    assert repo.get_loop("us-morning") is not None


def test_upsert_overwrites_existing_loop():
    client, repo = _build_client()
    client.post("/jobs/broadcast/loops", json=_VALID_LOOP_PAYLOAD)

    resp = client.post("/jobs/broadcast/loops", json={**_VALID_LOOP_PAYLOAD, "region": "Updated"})

    assert resp.status_code == 200
    assert resp.json()["region"] == "Updated"
    assert repo.get_loop("us-morning").region == "Updated"


def test_upsert_rejects_invalid_loop_id():
    client, _ = _build_client()
    bad = {**_VALID_LOOP_PAYLOAD, "loop_id": "has spaces"}

    resp = client.post("/jobs/broadcast/loops", json=bad)

    assert resp.status_code == 400


def test_list_loops_filters_active_only():
    client, _ = _build_client()
    client.post("/jobs/broadcast/loops", json=_VALID_LOOP_PAYLOAD)
    client.post(
        "/jobs/broadcast/loops",
        json={**_VALID_LOOP_PAYLOAD, "loop_id": "eu-morning", "active": False},
    )

    all_loops = client.get("/jobs/broadcast/loops").json()["loops"]
    active = client.get("/jobs/broadcast/loops?active_only=true").json()["loops"]

    assert {l["loop_id"] for l in all_loops} == {"us-morning", "eu-morning"}
    assert {l["loop_id"] for l in active} == {"us-morning"}


def test_get_loop_returns_404_for_missing():
    client, _ = _build_client()
    resp = client.get("/jobs/broadcast/loops/never-created")
    assert resp.status_code == 404


def test_delete_loop_is_idempotent():
    client, _ = _build_client()
    client.post("/jobs/broadcast/loops", json=_VALID_LOOP_PAYLOAD)

    first = client.delete("/jobs/broadcast/loops/us-morning")
    second = client.delete("/jobs/broadcast/loops/us-morning")

    assert first.status_code == 200
    assert first.json() == {"loop_id": "us-morning", "deleted": True}
    assert second.json() == {"loop_id": "us-morning", "deleted": False}


def test_paste_feedback_stores_raw_text_when_no_summarizer():
    # No podcast_api_key set → summarizer is None, only raw text is stored.
    client, repo = _build_client()
    client.post("/jobs/broadcast/loops", json=_VALID_LOOP_PAYLOAD)
    repo.save_episode(BroadcastEpisodeRecord(
        episode_id="deadbeefdeadbeef",
        loop_id="us-morning",
        run_date=datetime(2026, 5, 30).date(),
        topic_used="topic",
        title="t",
        show_notes="n",
        audio_object_name="broadcast/deadbeefdeadbeef.mp3",
        video_object_name="broadcast/deadbeefdeadbeef.mp4",
        created_at=datetime(2026, 5, 30, tzinfo=timezone.utc),
    ))

    resp = client.post(
        "/jobs/broadcast/episodes/deadbeefdeadbeef/feedback",
        json={"feedback_text": "Reply 1\nReply 2\nReply 3"},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["feedback_summary"] is None
    assert body["feedback_summary_status"] == "summarizer_unavailable"
    updated = repo.get_episode("deadbeefdeadbeef")
    assert updated.feedback_raw == "Reply 1\nReply 2\nReply 3"
    assert updated.feedback_pasted_at is not None


def test_paste_feedback_404_for_unknown_episode():
    client, _ = _build_client()
    resp = client.post(
        "/jobs/broadcast/episodes/deadbeefdeadbeef/feedback",
        json={"feedback_text": "x"},
    )
    assert resp.status_code == 404


def test_paste_feedback_rejects_malformed_episode_id():
    client, _ = _build_client()
    resp = client.post(
        "/jobs/broadcast/episodes/not-hex/feedback",
        json={"feedback_text": "x"},
    )
    assert resp.status_code == 400


def test_loop_episodes_endpoint_lists_in_descending_run_date():
    client, repo = _build_client()
    client.post("/jobs/broadcast/loops", json=_VALID_LOOP_PAYLOAD)
    for i, run_day in enumerate([29, 30, 31]):
        repo.save_episode(BroadcastEpisodeRecord(
            episode_id=f"{i:016x}",
            loop_id="us-morning",
            run_date=datetime(2026, 5, run_day).date(),
            topic_used=f"t{i}",
            title=f"title-{i}",
            show_notes="n",
            audio_object_name=f"broadcast/{i:016x}.mp3",
            video_object_name=f"broadcast/{i:016x}.mp4",
            created_at=datetime(2026, 5, run_day, tzinfo=timezone.utc),
        ))

    resp = client.get("/jobs/broadcast/loops/us-morning/episodes")

    assert resp.status_code == 200
    episodes = resp.json()["episodes"]
    assert [e["run_date"] for e in episodes] == ["2026-05-31", "2026-05-30", "2026-05-29"]
