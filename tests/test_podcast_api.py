from __future__ import annotations

import requests

from newsletter_pod.models import PodcastUxConfig
from newsletter_pod.podcast_api import PodcastApiClient


class FakeResponse:
    def __init__(self, *, status_code: int = 200, json_data=None, content: bytes = b"", headers=None) -> None:
        self.status_code = status_code
        self._json_data = json_data
        self.content = content
        self.headers = headers or {}

    def json(self):
        return self._json_data

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


def test_openai_provider_generates_structured_script_and_chunked_speech(monkeypatch):
    calls: list[tuple[str, dict]] = []

    def fake_post(url, json, headers, timeout, params=None):
        calls.append((url, json))
        if url.endswith("/v1/responses"):
            return FakeResponse(
                json_data={
                    "output": [
                        {
                            "content": [
                                {
                                    "type": "output_text",
                                    "text": (
                                        '{"episode_title":"2026-03-09: AI and Markets",'
                                        '"show_notes":"- Source A: https://example.com/a",'
                                        '"audio_segments":['
                                        '{"role":"primary","text":"Hello there."},'
                                        '{"role":"secondary","text":"More detail here."}'
                                        "]}"
                                    ),
                                }
                            ]
                        }
                    ]
                }
            )
        if url.endswith("/v1/audio/speech"):
            return FakeResponse(content=json["input"].encode("utf-8"))
        raise AssertionError(url)

    monkeypatch.setattr("newsletter_pod.podcast_api.requests.post", fake_post)

    client = PodcastApiClient(
        enabled=True,
        provider="openai",
        base_url="https://api.openai.com",
        api_key="test-key",
        timeout_seconds=60,
        poll_seconds=5,
        text_model="gpt-5.4-mini",
        tts_model="gpt-4o-mini-tts",
        tts_voice="alloy",
    )

    generated = client.generate(
        prompt="Source content",
        title="Daily Newsletter Digest",
        primary_speaker_name="Elena",
        secondary_speaker_name="Marcus",
    )

    assert generated.episode_title == "2026-03-09: AI and Markets"
    assert generated.mime_type == "audio/mpeg"
    assert generated.show_notes == "- Source A: https://example.com/a"
    assert generated.transcript == "Elena: Hello there.\n\nMarcus: More detail here."
    assert generated.audio_bytes == b"Hello there.More detail here."
    assert generated.audio_segments[0].role == "primary"
    assert generated.audio_segments[0].speaker == "Elena"
    assert generated.audio_segments[1].role == "secondary"
    assert generated.audio_segments[1].speaker == "Marcus"
    assert len(calls) == 3
    assert calls[0][0].endswith("/v1/responses")
    assert calls[1][0].endswith("/v1/audio/speech")
    assert calls[2][0].endswith("/v1/audio/speech")


def test_lead_in_and_tail_framing_wraps_body_for_tts(monkeypatch):
    speech_inputs: list[str] = []

    def fake_post(url, json, headers, timeout, params=None):
        if url.endswith("/v1/responses"):
            return FakeResponse(
                json_data={
                    "output": [
                        {
                            "content": [
                                {
                                    "type": "output_text",
                                    "text": (
                                        '{"episode_title":"T",'
                                        '"show_notes":"- A",'
                                        '"audio_segments":['
                                        '{"role":"primary","text":"Body one."},'
                                        '{"role":"secondary","text":"Body two."}'
                                        "]}"
                                    ),
                                }
                            ]
                        }
                    ]
                }
            )
        if url.endswith("/v1/audio/speech"):
            speech_inputs.append(json["input"])
            return FakeResponse(content=json["input"].encode("utf-8"))
        raise AssertionError(url)

    monkeypatch.setattr("newsletter_pod.podcast_api.requests.post", fake_post)

    client = PodcastApiClient(
        enabled=True,
        provider="openai",
        base_url="https://api.openai.com",
        api_key="test-key",
        timeout_seconds=60,
        poll_seconds=5,
        text_model="gpt-5.4-mini",
        tts_model="gpt-4o-mini-tts",
        tts_voice="alloy",
    )

    generated = client.generate(
        prompt="Source content",
        title="T",
        primary_speaker_name="Elena",
        secondary_speaker_name="Marcus",
        lead_in_texts=["Hello!", "Welcome."],
        tail_texts=["Leave a comment.", "See you tomorrow."],
    )

    # Framing brackets the body, in order, each as its own TTS call.
    assert speech_inputs == [
        "Hello!",
        "Welcome.",
        "Body one.",
        "Body two.",
        "Leave a comment.",
        "See you tomorrow.",
    ]
    # Framing is voiced by the primary host and present in the transcript.
    assert generated.audio_segments[0].speaker == "Elena"
    assert generated.audio_bytes.startswith(b"Hello!Welcome.")
    assert generated.audio_bytes.endswith(b"Leave a comment.See you tomorrow.")


def test_elevenlabs_tts_uses_user_voice_id(monkeypatch):
    calls: list[tuple[str, dict, dict]] = []

    def fake_post(url, json, headers, timeout, params=None):
        calls.append((url, json, headers))
        if url.endswith("/v1/responses"):
            return FakeResponse(
                json_data={
                    "output": [
                        {
                            "content": [
                                {
                                    "type": "output_text",
                                    "text": (
                                        '{"episode_title":"2026-04-26: AI",'
                                        '"show_notes":"- Source A",'
                                        '"audio_segments":['
                                        '{"role":"primary","text":"Hello there."}'
                                        "]}"
                                    ),
                                }
                            ]
                        }
                    ]
                }
            )
        if "/v1/text-to-speech/" in url:
            return FakeResponse(content=b"mp3-bytes")
        raise AssertionError(url)

    monkeypatch.setattr("newsletter_pod.podcast_api.requests.post", fake_post)

    client = PodcastApiClient(
        enabled=True,
        provider="openai",
        base_url="https://api.openai.com",
        api_key="test-key",
        timeout_seconds=60,
        poll_seconds=5,
        text_model="gpt-5.4-mini",
        tts_model="ignored",
        tts_voice="ignored",
        tts_provider="elevenlabs",
        elevenlabs_api_key="el-key",
        elevenlabs_model="eleven_multilingual_v2",
    )

    generated = client.generate(
        prompt="Source content",
        title="Daily Briefing",
        voice_id="RKCbSROXui75bk1SVpy8",
    )

    assert generated.audio_bytes == b"mp3-bytes"
    tts_call = calls[1]
    assert tts_call[0].endswith("/v1/text-to-speech/RKCbSROXui75bk1SVpy8")
    assert tts_call[1]["model_id"] == "eleven_multilingual_v2"
    assert tts_call[2]["xi-api-key"] == "el-key"


def test_elevenlabs_routes_segments_to_two_voices_by_role(monkeypatch):
    calls: list[tuple[str, dict]] = []

    def fake_post(url, json, headers, timeout, params=None):
        calls.append((url, json))
        if url.endswith("/v1/responses"):
            return FakeResponse(
                json_data={
                    "output": [
                        {
                            "content": [
                                {
                                    "type": "output_text",
                                    "text": (
                                        '{"episode_title":"2026-04-28: AI",'
                                        '"show_notes":"- Source A",'
                                        '"audio_segments":['
                                        '{"role":"primary","text":"Top story today."},'
                                        '{"role":"secondary","text":"Quick reaction."},'
                                        '{"role":"primary","text":"And here is the wrap-up."}'
                                        "]}"
                                    ),
                                }
                            ]
                        }
                    ]
                }
            )
        if "/v1/text-to-speech/" in url:
            return FakeResponse(content=url.encode("utf-8"))
        raise AssertionError(url)

    monkeypatch.setattr("newsletter_pod.podcast_api.requests.post", fake_post)

    client = PodcastApiClient(
        enabled=True,
        provider="openai",
        base_url="https://api.openai.com",
        api_key="test-key",
        timeout_seconds=60,
        poll_seconds=5,
        text_model="gpt-5.4-mini",
        tts_model="ignored",
        tts_voice="ignored",
        tts_provider="elevenlabs",
        elevenlabs_api_key="el-key",
        elevenlabs_model="eleven_multilingual_v2",
    )

    primary_id = "suMMgpGbVcnihP1CcgFS"
    secondary_id = "RKCbSROXui75bk1SVpy8"
    generated = client.generate(
        prompt="Source content",
        title="Daily Briefing",
        voice_id=primary_id,
        secondary_voice_id=secondary_id,
        primary_speaker_name="Vinnie Chase",
        secondary_speaker_name="Demi Dreams",
    )

    # Segments synthesize concurrently, so assert routing by mapping each call's
    # text to the voice id in its URL rather than the order calls complete in.
    tts_calls = [call for call in calls if "/v1/text-to-speech/" in call[0]]
    assert len(tts_calls) == 3
    voice_by_text = {
        payload["text"]: url.rsplit("/v1/text-to-speech/", 1)[1].split("?", 1)[0]
        for url, payload in tts_calls
    }
    assert voice_by_text["Top story today."] == primary_id
    assert voice_by_text["Quick reaction."] == secondary_id
    assert voice_by_text["And here is the wrap-up."] == primary_id
    assert generated.audio_segments[0].role == "primary"
    assert generated.audio_segments[0].speaker == "Vinnie Chase"
    assert generated.audio_segments[1].role == "secondary"
    assert generated.audio_segments[1].speaker == "Demi Dreams"


def _fake_elevenlabs_post_factory(calls: list[tuple[str, dict]]):
    """Shared ElevenLabs fake: returns a one-segment script then bytes for
    each TTS call, capturing every payload into `calls`."""

    def fake_post(url, json, headers, timeout, params=None):
        calls.append((url, json))
        if url.endswith("/v1/responses"):
            return FakeResponse(
                json_data={
                    "output": [
                        {
                            "content": [
                                {
                                    "type": "output_text",
                                    "text": (
                                        '{"episode_title":"2026-05-19: AI",'
                                        '"show_notes":"- A",'
                                        '"audio_segments":['
                                        '{"role":"primary","text":"Hello there."}'
                                        "]}"
                                    ),
                                }
                            ]
                        }
                    ]
                }
            )
        if "/v1/text-to-speech/" in url:
            return FakeResponse(content=b"mp3-bytes")
        raise AssertionError(url)

    return fake_post


def test_elevenlabs_passes_voice_settings_speed_when_configured(monkeypatch):
    calls: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        "newsletter_pod.podcast_api.requests.post",
        _fake_elevenlabs_post_factory(calls),
    )

    vinnie = "suMMgpGbVcnihP1CcgFS"
    client = PodcastApiClient(
        enabled=True,
        provider="openai",
        base_url="https://api.openai.com",
        api_key="test-key",
        timeout_seconds=60,
        poll_seconds=5,
        text_model="gpt-5.4-mini",
        tts_model="ignored",
        tts_voice="ignored",
        tts_provider="elevenlabs",
        elevenlabs_api_key="el-key",
        elevenlabs_model="eleven_multilingual_v2",
        voice_speed_by_id={vinnie: 1.2},
    )
    client.generate(prompt="Source", title="t", voice_id=vinnie)

    tts_payload = next(payload for url, payload in calls if "/v1/text-to-speech/" in url)
    assert tts_payload["voice_settings"] == {"speed": 1.2}


def test_elevenlabs_omits_voice_settings_when_voice_has_no_speed(monkeypatch):
    calls: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        "newsletter_pod.podcast_api.requests.post",
        _fake_elevenlabs_post_factory(calls),
    )

    client = PodcastApiClient(
        enabled=True,
        provider="openai",
        base_url="https://api.openai.com",
        api_key="test-key",
        timeout_seconds=60,
        poll_seconds=5,
        text_model="gpt-5.4-mini",
        tts_model="ignored",
        tts_voice="ignored",
        tts_provider="elevenlabs",
        elevenlabs_api_key="el-key",
        elevenlabs_model="eleven_multilingual_v2",
        # Map populated, but our test voice isn't in it.
        voice_speed_by_id={"some-other-voice": 1.2},
    )
    client.generate(prompt="Source", title="t", voice_id="unmapped-voice")

    tts_payload = next(payload for url, payload in calls if "/v1/text-to-speech/" in url)
    assert "voice_settings" not in tts_payload


def test_elevenlabs_clamps_speed_to_api_range(monkeypatch):
    calls: list[tuple[str, dict]] = []
    monkeypatch.setattr(
        "newsletter_pod.podcast_api.requests.post",
        _fake_elevenlabs_post_factory(calls),
    )

    client = PodcastApiClient(
        enabled=True,
        provider="openai",
        base_url="https://api.openai.com",
        api_key="test-key",
        timeout_seconds=60,
        poll_seconds=5,
        text_model="gpt-5.4-mini",
        tts_model="ignored",
        tts_voice="ignored",
        tts_provider="elevenlabs",
        elevenlabs_api_key="el-key",
        elevenlabs_model="eleven_multilingual_v2",
        voice_speed_by_id={"v1": 1.9, "v2": 0.4},
    )
    client.generate(prompt="Source", title="t", voice_id="v1")
    client.generate(prompt="Source", title="t", voice_id="v2")

    tts_payloads = [payload for url, payload in calls if "/v1/text-to-speech/" in url]
    assert tts_payloads[0]["voice_settings"] == {"speed": 1.2}
    assert tts_payloads[1]["voice_settings"] == {"speed": 0.7}


def test_elevenlabs_failure_falls_back_to_openai_tts(monkeypatch):
    calls: list[tuple[str, dict]] = []

    def fake_post(url, json, headers, timeout, params=None):
        calls.append((url, json))
        if url.endswith("/v1/responses"):
            return FakeResponse(
                json_data={
                    "output": [
                        {
                            "content": [
                                {
                                    "type": "output_text",
                                    "text": (
                                        '{"episode_title":"2026-05-22: Briefing",'
                                        '"show_notes":"- A",'
                                        '"audio_segments":['
                                        '{"role":"primary","text":"Hello there."}'
                                        "]}"
                                    ),
                                }
                            ]
                        }
                    ]
                }
            )
        if "/v1/text-to-speech/" in url:
            # ElevenLabs is down — surface a real requests-level error.
            raise requests.ConnectionError("eleven down")
        if url.endswith("/v1/audio/speech"):
            return FakeResponse(content=b"openai-mp3-bytes")
        raise AssertionError(url)

    monkeypatch.setattr("newsletter_pod.podcast_api.requests.post", fake_post)

    client = PodcastApiClient(
        enabled=True,
        provider="openai",
        base_url="https://api.openai.com",
        api_key="test-key",
        timeout_seconds=60,
        poll_seconds=5,
        text_model="gpt-5.4-mini",
        tts_model="gpt-4o-mini-tts",
        tts_voice="alloy",
        tts_provider="elevenlabs",
        elevenlabs_api_key="el-key",
        elevenlabs_model="eleven_multilingual_v2",
    )

    generated = client.generate(
        prompt="Source content",
        title="Daily Briefing",
        voice_id="RKCbSROXui75bk1SVpy8",
    )

    assert generated.audio_bytes == b"openai-mp3-bytes"
    urls = [url for url, _ in calls]
    # Order: responses (script) -> elevenlabs (fails) -> openai audio (fallback).
    assert urls[0].endswith("/v1/responses")
    assert "/v1/text-to-speech/" in urls[1]
    assert urls[2].endswith("/v1/audio/speech")
    fallback_payload = calls[2][1]
    # Fallback must use the OpenAI default voice, not the ElevenLabs voice id.
    assert fallback_payload["voice"] == "alloy"
    assert fallback_payload["model"] == "gpt-4o-mini-tts"


def test_elevenlabs_failure_falls_back_when_api_key_missing(monkeypatch):
    """If the ElevenLabs key isn't configured the synth raises PodcastApiUnavailable;
    the fallback should still kick in as long as OpenAI is configured."""
    calls: list[tuple[str, dict]] = []

    def fake_post(url, json, headers, timeout, params=None):
        calls.append((url, json))
        if url.endswith("/v1/responses"):
            return FakeResponse(
                json_data={
                    "output": [
                        {
                            "content": [
                                {
                                    "type": "output_text",
                                    "text": (
                                        '{"episode_title":"E",'
                                        '"show_notes":"x",'
                                        '"audio_segments":['
                                        '{"role":"primary","text":"Hello."}'
                                        "]}"
                                    ),
                                }
                            ]
                        }
                    ]
                }
            )
        if url.endswith("/v1/audio/speech"):
            return FakeResponse(content=b"openai-mp3-bytes")
        raise AssertionError(url)

    monkeypatch.setattr("newsletter_pod.podcast_api.requests.post", fake_post)

    client = PodcastApiClient(
        enabled=True,
        provider="openai",
        base_url="https://api.openai.com",
        api_key="test-key",
        timeout_seconds=60,
        poll_seconds=5,
        text_model="gpt-5.4-mini",
        tts_model="gpt-4o-mini-tts",
        tts_voice="alloy",
        tts_provider="elevenlabs",
        elevenlabs_api_key=None,
        elevenlabs_model="eleven_multilingual_v2",
    )

    generated = client.generate(
        prompt="Source",
        title="Daily Briefing",
        voice_id="RKCbSROXui75bk1SVpy8",
    )

    assert generated.audio_bytes == b"openai-mp3-bytes"


def test_stage_two_closing_segment_is_appended_when_ux_provided(monkeypatch):
    responses_calls: list[dict] = []

    def fake_post(url, json, headers, timeout, params=None):
        if url.endswith("/v1/responses"):
            responses_calls.append(json)
            # First call = body script (no closing). Second call = stage-2 closing.
            if len(responses_calls) == 1:
                return FakeResponse(
                    json_data={
                        "output": [
                            {
                                "content": [
                                    {
                                        "type": "output_text",
                                        "text": (
                                            '{"episode_title":"2026-05-13: Briefing",'
                                            '"show_notes":"- A: https://example.com/a",'
                                            '"audio_segments":['
                                            '{"role":"primary","text":"Top story."},'
                                            '{"role":"secondary","text":"Reaction."}'
                                            "]}"
                                        ),
                                    }
                                ]
                            }
                        ]
                    }
                )
            return FakeResponse(
                json_data={
                    "output": [
                        {
                            "content": [
                                {
                                    "type": "output_text",
                                    "text": (
                                        '{"text":"Three takeaways today. First, A. '
                                        "Second, B. Third, C. That's the briefing — "
                                        'see you next time on ClawCast."}'
                                    ),
                                }
                            ]
                        }
                    ]
                }
            )
        if url.endswith("/v1/audio/speech"):
            return FakeResponse(content=json["input"].encode("utf-8"))
        raise AssertionError(url)

    monkeypatch.setattr("newsletter_pod.podcast_api.requests.post", fake_post)

    client = PodcastApiClient(
        enabled=True,
        provider="openai",
        base_url="https://api.openai.com",
        api_key="test-key",
        timeout_seconds=60,
        poll_seconds=5,
        text_model="gpt-5.4-mini",
        tts_model="gpt-4o-mini-tts",
        tts_voice="alloy",
    )

    generated = client.generate(
        prompt="Source content",
        title="Daily Briefing",
        primary_speaker_name="Vinnie",
        secondary_speaker_name="Demi",
        ux=PodcastUxConfig(key_findings_count=3, include_top_takeaways=True),
    )

    # Body produced 2 segments, stage-2 appended a third primary-host closing.
    assert len(generated.audio_segments) == 3
    assert generated.audio_segments[-1].role == "primary"
    assert generated.audio_segments[-1].speaker == "Vinnie"
    assert "ClawCast" in generated.audio_segments[-1].text
    # Two responses calls (body + closing) and three TTS calls.
    assert len(responses_calls) == 2


def test_stage_two_closing_falls_back_when_api_fails(monkeypatch):
    state = {"calls": 0}

    def fake_post(url, json, headers, timeout, params=None):
        if url.endswith("/v1/responses"):
            state["calls"] += 1
            if state["calls"] == 1:
                return FakeResponse(
                    json_data={
                        "output": [
                            {
                                "content": [
                                    {
                                        "type": "output_text",
                                        "text": (
                                            '{"episode_title":"E",'
                                            '"show_notes":"x",'
                                            '"audio_segments":['
                                            '{"role":"primary","text":"Body."}'
                                            "]}"
                                        ),
                                    }
                                ]
                            }
                        ]
                    }
                )
            # Stage-2 call fails — the closing must still appear via fallback.
            return FakeResponse(status_code=503)
        if url.endswith("/v1/audio/speech"):
            return FakeResponse(content=json["input"].encode("utf-8"))
        raise AssertionError(url)

    monkeypatch.setattr("newsletter_pod.podcast_api.requests.post", fake_post)

    client = PodcastApiClient(
        enabled=True,
        provider="openai",
        base_url="https://api.openai.com",
        api_key="test-key",
        timeout_seconds=60,
        poll_seconds=5,
        text_model="gpt-5.4-mini",
        tts_model="gpt-4o-mini-tts",
        tts_voice="alloy",
    )

    generated = client.generate(
        prompt="Source content",
        title="Daily Briefing",
        primary_speaker_name="Vinnie",
        ux=PodcastUxConfig(include_top_takeaways=False),
    )

    assert len(generated.audio_segments) == 2
    assert generated.audio_segments[-1].role == "primary"
    assert "ClawCast" in generated.audio_segments[-1].text


def test_openai_endpoint_builder_accepts_base_url_with_v1():
    client = PodcastApiClient(
        enabled=True,
        provider="openai",
        base_url="https://api.openai.com/v1",
        api_key="test-key",
        timeout_seconds=60,
        poll_seconds=5,
        text_model="gpt-5.4-mini",
        tts_model="gpt-4o-mini-tts",
        tts_voice="alloy",
    )

    assert client._build_openai_endpoint("/responses") == "https://api.openai.com/v1/responses"


def _one_segment_script_response() -> "FakeResponse":
    return FakeResponse(
        json_data={
            "output": [
                {
                    "content": [
                        {
                            "type": "output_text",
                            "text": (
                                '{"episode_title":"T","show_notes":"- A",'
                                '"audio_segments":[{"role":"primary","text":"Hi."}]}'
                            ),
                        }
                    ]
                }
            ]
        }
    )


def test_elevenlabs_requests_low_bitrate_output_format(monkeypatch):
    captured_params: list[dict] = []

    def fake_post(url, json, headers, timeout, params=None):
        if url.endswith("/v1/responses"):
            return _one_segment_script_response()
        if "/v1/text-to-speech/" in url:
            captured_params.append(params or {})
            return FakeResponse(content=b"mp3-bytes")
        raise AssertionError(url)

    monkeypatch.setattr("newsletter_pod.podcast_api.requests.post", fake_post)

    client = PodcastApiClient(
        enabled=True,
        provider="openai",
        base_url="https://api.openai.com",
        api_key="test-key",
        timeout_seconds=60,
        poll_seconds=5,
        text_model="gpt-5.4-mini",
        tts_model="ignored",
        tts_voice="ignored",
        tts_provider="elevenlabs",
        elevenlabs_api_key="el-key",
        elevenlabs_model="eleven_multilingual_v2",
    )

    client.generate(prompt="Source", title="Daily Briefing", voice_id="voice-1")

    assert captured_params == [{"output_format": "mp3_44100_64"}]


def test_elevenlabs_retries_on_429_then_succeeds(monkeypatch):
    sleeps: list[float] = []
    monkeypatch.setattr("newsletter_pod.podcast_api.time.sleep", lambda s: sleeps.append(s))

    attempts = {"count": 0}

    def fake_post(url, json, headers, timeout, params=None):
        if url.endswith("/v1/responses"):
            return _one_segment_script_response()
        if "/v1/text-to-speech/" in url:
            attempts["count"] += 1
            if attempts["count"] == 1:
                return FakeResponse(status_code=429, headers={"Retry-After": "0"})
            return FakeResponse(content=b"mp3-after-retry")
        # A fallback to OpenAI would hit /v1/audio/speech — fail loudly if so.
        raise AssertionError(url)

    monkeypatch.setattr("newsletter_pod.podcast_api.requests.post", fake_post)

    client = PodcastApiClient(
        enabled=True,
        provider="openai",
        base_url="https://api.openai.com",
        api_key="test-key",
        timeout_seconds=60,
        poll_seconds=5,
        text_model="gpt-5.4-mini",
        tts_model="gpt-4o-mini-tts",
        tts_voice="alloy",
        tts_provider="elevenlabs",
        elevenlabs_api_key="el-key",
        elevenlabs_model="eleven_multilingual_v2",
    )

    generated = client.generate(prompt="Source", title="Daily Briefing", voice_id="voice-1")

    assert attempts["count"] == 2  # one retry after the 429
    assert generated.audio_bytes == b"mp3-after-retry"  # ElevenLabs, not OpenAI fallback
    assert sleeps == [0.0]  # honored Retry-After: 0


# --- MP3 concatenation / duration measurement ---------------------------------

from newsletter_pod.podcast_api import (  # noqa: E402
    _concat_mp3_chunks,
    _measure_mp3_duration_seconds,
    _strip_mp3_container,
)


def _mpeg1_l3_frame(payload: bytes = b"") -> bytes:
    """A single valid MPEG-1 Layer III frame, 128 kbps / 44.1 kHz (length 417),
    zero-padded, with optional marker bytes embedded in the body."""
    frame_len = (144 * 128000) // 44100  # 417, no padding
    header = bytes([0xFF, 0xFB, 0x90, 0x00])
    body = bytearray(frame_len - len(header))
    body[: len(payload)] = payload
    return header + bytes(body)


def _id3v2_tag() -> bytes:
    # ID3v2.4, no flags, size 0 (syncsafe).
    return b"ID3\x04\x00\x00\x00\x00\x00\x00"


def _complete_mp3_chunk(num_audio_frames: int) -> bytes:
    """Mimic a real TTS response: ID3v2 tag + an Info (Xing) header frame that
    describes only this chunk + N audio frames + a trailing ID3v1 tag."""
    info_frame = _mpeg1_l3_frame(b"....Info....")  # marker inside the frame body
    audio = b"".join(_mpeg1_l3_frame() for _ in range(num_audio_frames))
    id3v1 = b"TAG" + bytes(125)
    return _id3v2_tag() + info_frame + audio + id3v1


def test_strip_mp3_container_removes_tags_and_xing_header():
    chunk = _complete_mp3_chunk(num_audio_frames=3)
    stripped = _strip_mp3_container(chunk)

    assert b"ID3" not in stripped
    assert b"Info" not in stripped
    assert b"TAG" not in stripped[-128:]
    # Only the 3 raw audio frames survive.
    assert len(stripped) == 3 * ((144 * 128000) // 44100)


def test_strip_mp3_container_passes_non_mp3_through_unchanged():
    assert _strip_mp3_container(b"Hello there.") == b"Hello there."
    assert _strip_mp3_container(b"") == b""


def test_concat_mp3_chunks_yields_single_clean_stream():
    chunks = [_complete_mp3_chunk(40), _complete_mp3_chunk(40), _complete_mp3_chunk(40)]
    joined = _concat_mp3_chunks(chunks)

    # No mid-stream container headers that would make a player stop early.
    assert joined.count(b"ID3") == 0
    assert joined.count(b"Info") == 0

    # Duration reflects all 120 frames, not just the first chunk's Xing count.
    per_frame = 1152 / 44100
    expected = round(120 * per_frame)
    assert _measure_mp3_duration_seconds(joined) == expected


def test_measure_mp3_duration_returns_none_for_non_mp3():
    assert _measure_mp3_duration_seconds(b"not audio") is None
    assert _measure_mp3_duration_seconds(b"") is None
