from __future__ import annotations

import json as jsonlib

from fastapi.testclient import TestClient

import newsletter_pod.podcast_api as papi
from newsletter_pod.blueprint import default_blueprint
from newsletter_pod.config import Settings
from newsletter_pod.main import _build_container, create_app


class FakeResponse:
    def __init__(self, *, status_code=200, json_data=None):
        self.status_code = status_code
        self._json = json_data

    def json(self):
        return self._json

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def _wrap(obj):
    return {"output": [{"content": [{"type": "output_text", "text": jsonlib.dumps(obj)}]}]}


def _fake_post(url, json, headers, timeout):
    if url.endswith("/v1/responses"):
        name = json["text"]["format"]["name"]
        if name == "newsletter_digest":
            return FakeResponse(
                json_data=_wrap(
                    {
                        "episode_title": "Preview Episode",
                        "show_notes": "- notes",
                        "audio_segments": [
                            {"role": "primary", "section": "cold_open", "text": "Good morning."},
                            {"role": "primary", "section": "story_block", "text": "Rates may fall."},
                        ],
                    }
                )
            )
        if name == "closing_segment":
            return FakeResponse(json_data=_wrap({"text": "See you next time on ClawCast."}))
        raise AssertionError(name)
    raise AssertionError(f"unexpected TTS call in text_only preview: {url}")


def _client(monkeypatch):
    monkeypatch.setattr(papi.requests, "post", _fake_post)
    settings = Settings.from_env()
    settings.use_inmemory_adapters = True
    settings.podcast_api_enabled = True
    settings.podcast_api_key = "test-key"
    settings.podcast_provider = "openai"
    settings.job_trigger_token = None
    settings.alert_email_enabled = False
    settings.publish_summary_email_enabled = False
    settings.feedback_digest_email_enabled = False
    container = _build_container(settings)
    return TestClient(create_app(container=container)), container


def test_preview_returns_shaped_script_without_persisting(monkeypatch):
    client, container = _client(monkeypatch)
    resp = client.post(
        "/jobs/config/preview",
        json={"blueprint": default_blueprint().model_dump(mode="json")},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["text_only"] is True
    assert "Good morning." in body["transcript"]
    assert "cold_open" in body["section_order"]
    assert body["lint_hits"] == []
    # Nothing was persisted — no active version exists.
    assert container.blueprint_repository.get_active() is None


def test_preview_rejects_invalid_blueprint(monkeypatch):
    client, _ = _client(monkeypatch)
    bad = default_blueprint().model_dump(mode="json")
    bad["sections"] = [{"kind": "story_block", "enabled": True}]  # closing not last
    resp = client.post("/jobs/config/preview", json={"blueprint": bad})
    assert resp.status_code == 400
