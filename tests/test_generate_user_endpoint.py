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
