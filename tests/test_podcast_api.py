from __future__ import annotations

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


def test_openai_provider_generates_structured_script_and_chunked_speech(monkeypatch):
    calls: list[tuple[str, dict]] = []

    def fake_post(url, json, headers, timeout):
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


def test_elevenlabs_tts_uses_user_voice_id(monkeypatch):
    calls: list[tuple[str, dict, dict]] = []

    def fake_post(url, json, headers, timeout):
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

    def fake_post(url, json, headers, timeout):
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

    tts_urls = [call[0] for call in calls if "/v1/text-to-speech/" in call[0]]
    assert len(tts_urls) == 3
    assert tts_urls[0].endswith(f"/v1/text-to-speech/{primary_id}")
    assert tts_urls[1].endswith(f"/v1/text-to-speech/{secondary_id}")
    assert tts_urls[2].endswith(f"/v1/text-to-speech/{primary_id}")
    assert generated.audio_segments[0].role == "primary"
    assert generated.audio_segments[0].speaker == "Vinnie Chase"
    assert generated.audio_segments[1].role == "secondary"
    assert generated.audio_segments[1].speaker == "Demi Dreams"


def _fake_elevenlabs_post_factory(calls: list[tuple[str, dict]]):
    """Shared ElevenLabs fake: returns a one-segment script then bytes for
    each TTS call, capturing every payload into `calls`."""

    def fake_post(url, json, headers, timeout):
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


def test_stage_two_closing_segment_is_appended_when_ux_provided(monkeypatch):
    responses_calls: list[dict] = []

    def fake_post(url, json, headers, timeout):
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

    def fake_post(url, json, headers, timeout):
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
