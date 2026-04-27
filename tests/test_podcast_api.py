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
                                        '{"speaker":"Demi","text":"Hello there."},'
                                        '{"speaker":"Vinnie","text":"More detail here."}'
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
    assert generated.transcript == "Demi: Hello there.\n\nVinnie: More detail here."
    assert generated.audio_bytes == b"Hello there.More detail here."
    assert generated.audio_segments[0].speaker == "Demi"
    assert generated.audio_segments[1].speaker == "Vinnie"
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
        voice_id="suMMgpGbVcnihP1CcgFS",
    )

    assert generated.audio_bytes == b"mp3-bytes"
    tts_call = calls[1]
    assert tts_call[0].endswith("/v1/text-to-speech/suMMgpGbVcnihP1CcgFS")
    assert tts_call[1]["model_id"] == "eleven_multilingual_v2"
    assert tts_call[2]["xi-api-key"] == "el-key"


def test_elevenlabs_dual_voice_routes_speakers_to_distinct_voices(monkeypatch):
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
                                        '{"episode_title":"2026-04-27: Dual Voice",'
                                        '"show_notes":"- Source A",'
                                        '"audio_segments":['
                                        '{"speaker":"Demi","text":"Anchor here."},'
                                        '{"speaker":"Vinnie","text":"Reaction here."},'
                                        '{"speaker":"demi","text":"Wrap up."}'
                                        "]}"
                                    ),
                                }
                            ]
                        }
                    ]
                }
            )
        if "/v1/text-to-speech/" in url:
            return FakeResponse(content=url.rsplit("/", 1)[-1].encode("utf-8"))
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
        voice_id="primary-voice",
        speaker_voice_map={"Demi": "primary-voice", "Vinnie": "secondary-voice"},
    )

    tts_urls = [call[0] for call in calls if "/v1/text-to-speech/" in call[0]]
    assert tts_urls == [
        "https://api.elevenlabs.io/v1/text-to-speech/primary-voice",
        "https://api.elevenlabs.io/v1/text-to-speech/secondary-voice",
        "https://api.elevenlabs.io/v1/text-to-speech/primary-voice",
    ]
    assert generated.audio_bytes == b"primary-voicesecondary-voiceprimary-voice"


def test_speaker_voice_map_falls_back_to_voice_id_for_unknown_speaker(monkeypatch):
    calls: list[str] = []

    def fake_post(url, json, headers, timeout):
        calls.append(url)
        if url.endswith("/v1/responses"):
            return FakeResponse(
                json_data={
                    "output": [
                        {
                            "content": [
                                {
                                    "type": "output_text",
                                    "text": (
                                        '{"episode_title":"t","show_notes":"n",'
                                        '"audio_segments":['
                                        '{"speaker":"Stranger","text":"hi"}'
                                        "]}"
                                    ),
                                }
                            ]
                        }
                    ]
                }
            )
        if "/v1/text-to-speech/" in url:
            return FakeResponse(content=b"x")
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

    client.generate(
        prompt="p",
        title="t",
        voice_id="primary-voice",
        speaker_voice_map={"Demi": "primary-voice", "Vinnie": "secondary-voice"},
    )

    tts_urls = [url for url in calls if "/v1/text-to-speech/" in url]
    assert tts_urls == ["https://api.elevenlabs.io/v1/text-to-speech/primary-voice"]


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
