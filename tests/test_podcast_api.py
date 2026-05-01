from __future__ import annotations

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
                                        '{"speaker":"Elena","text":"Hello there."},'
                                        '{"speaker":"Marcus","text":"More detail here."}'
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

    generated = client.generate(prompt="Source content", title="Daily Newsletter Digest")

    assert generated.episode_title == "2026-03-09: AI and Markets"
    assert generated.mime_type == "audio/mpeg"
    assert generated.show_notes == "- Source A: https://example.com/a"
    assert generated.transcript == "Elena: Hello there.\n\nMarcus: More detail here."
    assert generated.audio_bytes == b"Hello there.More detail here."
    assert generated.audio_segments[0].speaker == "Elena"
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
                                        '{"speaker":"Demi Dreams","text":"Hello there."}'
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


def test_elevenlabs_routes_segments_to_two_voices_by_speaker(monkeypatch):
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
                                        '{"speaker":"Vinnie","text":"Top story today."},'
                                        '{"speaker":"Demi","text":"Quick reaction."},'
                                        '{"speaker":"Vinnie","text":"And here is the wrap-up."}'
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
        primary_speaker_name="Vinnie",
    )

    tts_urls = [call[0] for call in calls if "/v1/text-to-speech/" in call[0]]
    assert len(tts_urls) == 3
    assert tts_urls[0].endswith(f"/v1/text-to-speech/{primary_id}")
    assert tts_urls[1].endswith(f"/v1/text-to-speech/{secondary_id}")
    assert tts_urls[2].endswith(f"/v1/text-to-speech/{primary_id}")
    assert generated.audio_segments[0].speaker == "Vinnie"
    assert generated.audio_segments[1].speaker == "Demi"


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
