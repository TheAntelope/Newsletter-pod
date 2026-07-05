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


# --- preview AS a real account (uses their sources + profile) ----------------

def test_preview_uses_account_when_email_resolves(monkeypatch):
    from newsletter_pod.models import PodcastUxConfig

    client, container = _client(monkeypatch)
    cp = container.control_plane
    sample = cp._preview_sample_items()
    seen = {}

    def fake_resolve(user_id, email):
        seen["email"] = email
        return "u1" if email == "vince@example.com" else None

    def fake_inputs(uid, bp):
        seen["uid"] = uid
        return sample, PodcastUxConfig(blueprint=bp), "vince@example.com"

    cp._resolve_preview_user = fake_resolve
    cp._preview_inputs_for_user = fake_inputs

    resp = client.post(
        "/jobs/config/preview",
        json={
            "blueprint": default_blueprint().model_dump(mode="json"),
            "email": "vince@example.com",
        },
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["previewed_as"] == "vince@example.com"
    assert body["source_item_count"] == len(sample)
    assert seen["uid"] == "u1"


def test_resolve_preview_user(monkeypatch):
    from types import SimpleNamespace

    client, container = _client(monkeypatch)
    cp = container.control_plane
    cp.repository.get_user = lambda uid: SimpleNamespace(id=uid) if uid == "u9" else None
    cp.repository.list_users_by_email = (
        lambda e: [SimpleNamespace(id="u2")] if e == "me@x.com" else []
    )
    assert cp._resolve_preview_user("u9", None) == "u9"
    assert cp._resolve_preview_user("missing", None) is None
    assert cp._resolve_preview_user(None, "ME@X.com") == "u2"
    assert cp._resolve_preview_user(None, "nobody@x.com") is None
    assert cp._resolve_preview_user(None, None) is None


def test_record_to_source_item(monkeypatch):
    from datetime import datetime, timezone

    from newsletter_pod.models import SourceItemRecord

    client, container = _client(monkeypatch)
    cp = container.control_plane
    now = datetime(2026, 7, 5, tzinfo=timezone.utc)
    rec = SourceItemRecord(
        dedupe_key="k",
        source_id="s",
        source_name="Src",
        link="http://x/a",
        title="A story",
        summary="what happened",
        published_at=now,
        first_seen_at=now,
        last_seen_at=now,
    )
    item = cp._record_to_source_item(rec)
    assert item.dedupe_key == "k"
    assert item.source_id == "s"
    assert item.title == "A story"
    assert item.summary == "what happened"
