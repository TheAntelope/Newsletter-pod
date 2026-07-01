from __future__ import annotations

import json as jsonlib
from typing import Callable

from newsletter_pod.blueprint import SectionDef, ShowBlueprint
from newsletter_pod.models import PodcastUxConfig
from newsletter_pod.podcast_api import PodcastApiClient


class FakeResponse:
    def __init__(self, *, status_code: int = 200, json_data=None, content: bytes = b"") -> None:
        self.status_code = status_code
        self._json_data = json_data
        self.content = content

    def json(self):
        return self._json_data

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def _wrap(obj: dict) -> dict:
    return {"output": [{"content": [{"type": "output_text", "text": jsonlib.dumps(obj)}]}]}


def _make_fake_post(
    script_segments: list[dict],
    rewrite: Callable[[str], str],
    closing_text: str = "That's the briefing — see you next time on ClawCast.",
):
    tts_texts: list[str] = []
    rewrite_inputs: list[str] = []

    def fake_post(url, json, headers, timeout):
        if url.endswith("/v1/responses"):
            name = json["text"]["format"]["name"]
            if name == "newsletter_digest":
                return FakeResponse(
                    json_data=_wrap(
                        {
                            "episode_title": "T",
                            "show_notes": "notes",
                            "audio_segments": script_segments,
                        }
                    )
                )
            if name == "closing_segment":
                return FakeResponse(json_data=_wrap({"text": closing_text}))
            if name == "delinted_segment":
                user_text = json["input"][1]["content"][0]["text"]
                rewrite_inputs.append(user_text)
                return FakeResponse(json_data=_wrap({"text": rewrite(user_text)}))
            raise AssertionError(f"unexpected schema {name}")
        if url.endswith("/v1/audio/speech"):
            tts_texts.append(json["input"])
            return FakeResponse(content=json["input"].encode("utf-8"))
        raise AssertionError(url)

    return fake_post, tts_texts, rewrite_inputs


def _client(delint_enabled: bool = True) -> PodcastApiClient:
    return PodcastApiClient(
        enabled=True,
        provider="openai",
        base_url="https://api.openai.com",
        api_key="test-key",
        timeout_seconds=60,
        poll_seconds=5,
        text_model="gpt-5.4-mini",
        tts_model="gpt-4o-mini-tts",
        tts_voice="alloy",
        delint_enabled=delint_enabled,
    )


def _ux(max_rewrite: int = 3, lint_enabled: bool = True, banned=None) -> PodcastUxConfig:
    bp = ShowBlueprint(
        sections=[
            SectionDef(kind="cold_open"),
            SectionDef(kind="story_block"),
            SectionDef(kind="closing"),
        ],
    )
    bp.style.lint_enabled = lint_enabled
    bp.style.max_rewrite_segments = max_rewrite
    if banned:
        bp.style.banned_phrases = banned
    return PodcastUxConfig(blueprint=bp)


def test_delint_rewrites_only_flagged_segment_and_never_tts_original():
    fake_post, tts_texts, rewrites = _make_fake_post(
        [
            {"role": "primary", "section": "cold_open", "text": "Let's dive in to today."},
            {"role": "primary", "section": "story_block", "text": "The bank raised rates."},
        ],
        rewrite=lambda _: "Here's today's briefing.",
    )
    import newsletter_pod.podcast_api as papi

    orig = papi.requests.post
    papi.requests.post = fake_post
    try:
        client = _client()
        client.generate(prompt="p", title="t", ux=_ux())
    finally:
        papi.requests.post = orig

    assert len(rewrites) == 1  # only the offending segment was rewritten
    assert "Here's today's briefing." in tts_texts
    assert "Let's dive in to today." not in tts_texts  # pre-rewrite text never TTS'd
    assert "The bank raised rates." in tts_texts  # clean segment untouched


def test_delint_bounded_by_max_rewrite_segments():
    fake_post, tts_texts, rewrites = _make_fake_post(
        [
            {"role": "primary", "section": "cold_open", "text": "Let's dive in now."},
            {"role": "primary", "section": "story_block", "text": "A rich tapestry of events."},
        ],
        rewrite=lambda _: "Clean rewrite.",
    )
    import newsletter_pod.podcast_api as papi

    orig = papi.requests.post
    papi.requests.post = fake_post
    try:
        client = _client()
        client.generate(prompt="p", title="t", ux=_ux(max_rewrite=1))
    finally:
        papi.requests.post = orig

    assert len(rewrites) == 1  # cap honored
    # The second offending segment keeps its original text.
    assert "A rich tapestry of events." in tts_texts


def test_delint_keeps_original_when_rewrite_does_not_clear_tic():
    fake_post, tts_texts, rewrites = _make_fake_post(
        [{"role": "primary", "section": "cold_open", "text": "Let's dive in."}],
        rewrite=lambda _: "Okay, let's dive in again.",  # still contains the tic
    )
    import newsletter_pod.podcast_api as papi

    orig = papi.requests.post
    papi.requests.post = fake_post
    try:
        client = _client()
        client.generate(prompt="p", title="t", ux=_ux())
    finally:
        papi.requests.post = orig

    assert len(rewrites) == 1
    assert "Let's dive in." in tts_texts  # original kept, bad rewrite rejected


def test_delint_disabled_makes_no_rewrite_calls():
    fake_post, tts_texts, rewrites = _make_fake_post(
        [{"role": "primary", "section": "cold_open", "text": "Let's dive in."}],
        rewrite=lambda _: "Clean.",
    )
    import newsletter_pod.podcast_api as papi

    orig = papi.requests.post
    papi.requests.post = fake_post
    try:
        client = _client(delint_enabled=False)
        client.generate(prompt="p", title="t", ux=_ux())
    finally:
        papi.requests.post = orig

    assert rewrites == []
    assert "Let's dive in." in tts_texts
