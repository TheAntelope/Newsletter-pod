from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

from newsletter_pod.config import Settings
from newsletter_pod.main import _build_container, create_app


def _build(job_token: str | None = None):
    settings = Settings.from_env()
    settings.use_inmemory_adapters = True
    settings.podcast_api_key = None
    settings.podcast_api_enabled = False
    settings.job_trigger_token = job_token
    settings.alert_email_enabled = False
    settings.publish_summary_email_enabled = False
    settings.feedback_digest_email_enabled = False
    container = _build_container(settings)
    return TestClient(create_app(container=container)), container


def test_requires_user_id_or_email():
    client, _ = _build()
    resp = client.post("/jobs/generate-user", json={})
    assert resp.status_code == 400


def test_unknown_email_404s():
    client, _ = _build()
    resp = client.post("/jobs/generate-user", json={"email": "nobody@example.com"})
    assert resp.status_code == 404


def test_user_id_path_triggers_real_generation(monkeypatch):
    client, container = _build()
    calls = {}
    container.control_plane.process_user_generation_job = (
        lambda user_id, force=False: calls.update(user_id=user_id, force=force)
        or {"run": {"status": "published"}, "episode": {"id": "e1", "title": "T"}, "feed_url": "http://x/feeds/tok.xml"}
    )
    resp = client.post("/jobs/generate-user", json={"user_id": "u1"})
    assert resp.status_code == 200
    assert resp.json()["episode"]["id"] == "e1"
    assert calls == {"user_id": "u1", "force": True}


def test_email_resolves_to_user_id(monkeypatch):
    client, container = _build()
    container.control_plane.repository.list_users_by_email = (
        lambda email: [SimpleNamespace(id="u2")] if email == "me@example.com" else []
    )
    captured = {}
    container.control_plane.process_user_generation_job = (
        lambda user_id, force=False: captured.update(user_id=user_id) or {"run": {"status": "no_content"}}
    )
    resp = client.post("/jobs/generate-user", json={"email": "ME@Example.com"})
    assert resp.status_code == 200
    assert captured["user_id"] == "u2"


def test_requires_job_token_when_configured():
    client, _ = _build(job_token="s3cret")
    assert client.post("/jobs/generate-user", json={"user_id": "u1"}).status_code == 401


# --- async start/status (robust Studio UX) ----------------------------------

def test_start_returns_run_id_and_schedules_background():
    client, container = _build()
    cp = container.control_plane
    calls = {}
    cp.start_user_generation = lambda user_id, force=False: {
        "run": {"id": "r1", "status": "in_progress"},
        "started": True,
    }
    cp.run_user_generation_in_background = lambda **kw: calls.update(kw)

    resp = client.post("/jobs/generate-user/start", json={"user_id": "u1"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["user_id"] == "u1"
    assert body["started"] is True
    assert body["run"]["id"] == "r1"
    # TestClient runs background tasks after the response.
    assert calls.get("run_id") == "r1"
    assert calls.get("user_id") == "u1"
    assert calls.get("force") is True


def test_start_does_not_schedule_when_already_in_flight():
    client, container = _build()
    cp = container.control_plane
    calls = {}
    cp.start_user_generation = lambda user_id, force=False: {
        "run": {"id": "r2", "status": "in_progress"},
        "started": False,
    }
    cp.run_user_generation_in_background = lambda **kw: calls.update(kw)

    resp = client.post("/jobs/generate-user/start", json={"user_id": "u1"})
    assert resp.status_code == 200
    assert resp.json()["started"] is False
    assert calls == {}  # no second generation kicked off


def test_status_returns_run_episode_and_feed_url():
    client, container = _build()
    cp = container.control_plane
    cp.get_user_run_status = lambda user_id, run_id: {
        "run": {"status": "published", "published_episode_id": "e1"},
        "episode": {"id": "e1", "title": "T"},
    }
    cp.get_feed_details = lambda user_id: {"feed_url": "http://x/feeds/tok.xml"}

    resp = client.get(
        "/jobs/generate-user/status", params={"user_id": "u1", "run_id": "r1"}
    )
    assert resp.status_code == 200
    b = resp.json()
    assert b["run"]["status"] == "published"
    assert b["episode"]["id"] == "e1"
    assert b["feed_url"].endswith("tok.xml")


def test_status_surfaces_skip_message():
    client, container = _build()
    cp = container.control_plane
    cp.get_user_run_status = lambda user_id, run_id: {
        "run": {"status": "skipped", "message": "Weekly podcast quota reached for your plan"}
    }
    cp.get_feed_details = lambda user_id: {"feed_url": "http://x/feeds/tok.xml"}

    b = client.get(
        "/jobs/generate-user/status", params={"user_id": "u1", "run_id": "r1"}
    ).json()
    assert b["run"]["status"] == "skipped"
    assert "quota" in b["run"]["message"]


def test_status_404_when_run_missing():
    from newsletter_pod.control_plane import ControlPlaneError

    client, container = _build()

    def _raise(user_id, run_id):
        raise ControlPlaneError("Run not found")

    container.control_plane.get_user_run_status = _raise
    resp = client.get(
        "/jobs/generate-user/status", params={"user_id": "u1", "run_id": "nope"}
    )
    assert resp.status_code == 404


def test_async_endpoints_require_job_token():
    client, _ = _build(job_token="s3cret")
    assert client.post("/jobs/generate-user/start", json={"user_id": "u1"}).status_code == 401
    assert (
        client.get(
            "/jobs/generate-user/status", params={"user_id": "u1", "run_id": "r1"}
        ).status_code
        == 401
    )
