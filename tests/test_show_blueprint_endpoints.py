from __future__ import annotations

from fastapi.testclient import TestClient

from newsletter_pod.blueprint import default_blueprint
from newsletter_pod.config import Settings
from newsletter_pod.main import _build_container, create_app


def _build_client(job_token: str | None = None) -> tuple[TestClient, object]:
    settings = Settings.from_env()
    settings.use_inmemory_adapters = True
    settings.session_signing_secret = "test-session-secret-32-bytes-long"
    settings.podcast_api_key = None
    settings.podcast_api_enabled = False
    settings.job_trigger_token = job_token
    settings.publish_summary_email_enabled = False
    settings.alert_email_enabled = False
    settings.feedback_digest_email_enabled = False
    container = _build_container(settings)
    client = TestClient(create_app(container=container))
    return client, container


def _valid_blueprint_payload() -> dict:
    bp = default_blueprint()
    # Disable the weather section (single source of truth for presence).
    for section in bp.sections:
        if section.kind == "weather":
            section.enabled = False
    bp.closing.announcements_text = "New voices shipped this week."
    bp.style.banned_phrases = ["let's dive in"]
    return bp.model_dump(mode="json")


def _weather_enabled(blueprint: dict) -> bool:
    return any(
        s["kind"] == "weather" and s["enabled"] for s in blueprint["sections"]
    )


def test_get_returns_seed_default_before_any_save():
    client, _ = _build_client()
    resp = client.get("/jobs/config")
    assert resp.status_code == 200
    body = resp.json()
    assert body["version"] == 0
    assert body["is_default"] is True
    assert body["blueprint"]["sections"][-1]["kind"] == "closing"


def test_put_saves_new_version_and_get_reflects_it():
    client, container = _build_client()

    resp = client.put(
        "/jobs/config",
        json={"blueprint": _valid_blueprint_payload(), "note": "drop weather"},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["version"] == 1

    got = client.get("/jobs/config").json()
    assert got["version"] == 1
    assert got["is_default"] is False
    assert _weather_enabled(got["blueprint"]) is False
    assert got["note"] == "drop weather"
    # The provider the control plane reads is the same instance the PUT
    # invalidated, so generation would see the new blueprint immediately.
    assert container.blueprint_provider.get().is_enabled("weather") is False


def test_put_rejects_invalid_blueprint_with_400():
    client, _ = _build_client()
    bad = default_blueprint().model_dump(mode="json")
    # Make the last enabled section not `closing` -> model validator fails.
    bad["sections"] = [{"kind": "story_block", "enabled": True}]
    resp = client.put("/jobs/config", json={"blueprint": bad})
    assert resp.status_code == 400
    assert "closing" in resp.text


def test_history_and_restore_create_new_version():
    client, _ = _build_client()
    # v1 (weather off), v2 (default with weather on)
    client.put("/jobs/config", json={"blueprint": _valid_blueprint_payload()})
    client.put("/jobs/config", json={"blueprint": default_blueprint().model_dump(mode="json")})

    hist = client.get("/jobs/config/history").json()["versions"]
    assert [v["version"] for v in hist] == [2, 1]

    restored = client.post("/jobs/config/restore", json={"version": 1})
    assert restored.status_code == 200
    assert restored.json()["version"] == 3
    assert restored.json()["note"] == "restore of v1"
    # Active now reflects v1's content (weather section disabled).
    assert _weather_enabled(client.get("/jobs/config").json()["blueprint"]) is False


def test_restore_unknown_version_404s():
    client, _ = _build_client()
    resp = client.post("/jobs/config/restore", json={"version": 42})
    assert resp.status_code == 404


def test_endpoints_require_job_token_when_configured():
    client, _ = _build_client(job_token="s3cret")
    assert client.get("/jobs/config").status_code == 401
    assert client.put("/jobs/config", json={"blueprint": _valid_blueprint_payload()}).status_code == 401

    headers = {"X-Job-Trigger-Token": "s3cret"}
    assert client.get("/jobs/config", headers=headers).status_code == 200
