from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import pytest

from newsletter_pod.broadcast.prompting import BroadcastBrief
from newsletter_pod.broadcast.service import BroadcastService, BroadcastSettings
from newsletter_pod.models import AudioSegment, GeneratedEpisode, PodcastUxConfig
from newsletter_pod.storage import InMemoryAudioStorage


@dataclass
class _RecordedGenerate:
    prompt: str
    title: str
    voice_id: Optional[str]
    secondary_voice_id: Optional[str]
    primary_speaker_name: Optional[str]
    secondary_speaker_name: Optional[str]


class _FakePodcastClient:
    def __init__(self, audio_bytes: bytes = b"fake-mp3", title: str = "Generated Title") -> None:
        self.audio_bytes = audio_bytes
        self.title = title
        self.calls: list[_RecordedGenerate] = []

    def generate(
        self,
        prompt,
        title,
        voice_id=None,
        secondary_voice_id=None,
        primary_speaker_name=None,
        secondary_speaker_name=None,
        ux=None,
        force_default_voice=False,
    ) -> GeneratedEpisode:
        self.calls.append(
            _RecordedGenerate(
                prompt=prompt,
                title=title,
                voice_id=voice_id,
                secondary_voice_id=secondary_voice_id,
                primary_speaker_name=primary_speaker_name,
                secondary_speaker_name=secondary_speaker_name,
            )
        )
        return GeneratedEpisode(
            episode_title=self.title,
            audio_bytes=self.audio_bytes,
            mime_type="audio/mpeg",
            show_notes="Notes",
            audio_segments=[
                AudioSegment(role="primary", speaker="Vinnie", text="hello"),
                AudioSegment(role="secondary", speaker="Demi", text="hi"),
            ],
            transcript="Vinnie: hello\n\nDemi: hi",
            duration_seconds=42,
        )


def _settings(cover_path: Path) -> BroadcastSettings:
    return BroadcastSettings(
        app_base_url="https://example.test",
        primary_voice_id="voice-primary",
        secondary_voice_id="voice-secondary",
        primary_host_name="Vinnie",
        secondary_host_name="Demi",
        cover_image_path=cover_path,
    )


def _fake_renderer(*, audio_bytes: bytes, cover_image_bytes: bytes) -> bytes:
    # Return something that proves both inputs reached the renderer.
    return b"video:" + cover_image_bytes + b":" + audio_bytes


def test_generate_once_uploads_both_assets_and_returns_urls(tmp_path):
    cover = tmp_path / "cover.png"
    cover.write_bytes(b"cover-pixels")

    storage = InMemoryAudioStorage()
    client = _FakePodcastClient(audio_bytes=b"mp3-bytes")
    service = BroadcastService(
        settings=_settings(cover),
        storage=storage,
        podcast_client=client,
        renderer=_fake_renderer,
        episode_id_factory=lambda: "deadbeef" * 2,
    )

    result = service.generate_once(
        brief=BroadcastBrief(topic="The state of agent evals"),
        title="Eval landscape",
        ux=PodcastUxConfig(),
    )

    assert result.episode_id == "deadbeefdeadbeef"
    assert result.audio_object_name == "broadcast/deadbeefdeadbeef.mp3"
    assert result.video_object_name == "broadcast/deadbeefdeadbeef.mp4"
    assert result.audio_url == "https://example.test/broadcast/deadbeefdeadbeef.mp3"
    assert result.video_url == "https://example.test/broadcast/deadbeefdeadbeef.mp4"
    assert result.audio_size_bytes == len(b"mp3-bytes")
    assert result.video_size_bytes == len(b"video:cover-pixels:mp3-bytes")
    assert result.duration_seconds == 42

    assert storage.get_object("broadcast/deadbeefdeadbeef.mp3") == b"mp3-bytes"
    assert storage.get_object("broadcast/deadbeefdeadbeef.mp4") == b"video:cover-pixels:mp3-bytes"


def test_generate_once_passes_brief_into_prompt(tmp_path):
    cover = tmp_path / "cover.png"
    cover.write_bytes(b"x")
    client = _FakePodcastClient()
    service = BroadcastService(
        settings=_settings(cover),
        storage=InMemoryAudioStorage(),
        podcast_client=client,
        renderer=_fake_renderer,
    )

    service.generate_once(
        brief=BroadcastBrief(
            topic="open-weights ecosystem",
            audience_hint="ML engineers",
        ),
        title="Open weights",
    )

    assert len(client.calls) == 1
    call = client.calls[0]
    assert "open-weights ecosystem" in call.prompt
    assert "ML engineers" in call.prompt
    assert call.title == "Open weights"
    assert call.voice_id == "voice-primary"
    assert call.secondary_voice_id == "voice-secondary"
    assert call.primary_speaker_name == "Vinnie"
    assert call.secondary_speaker_name == "Demi"


def test_generate_once_trailing_slash_in_base_url(tmp_path):
    cover = tmp_path / "cover.png"
    cover.write_bytes(b"x")
    settings = BroadcastSettings(
        app_base_url="https://example.test/",  # trailing slash
        primary_voice_id="v1",
        secondary_voice_id="v2",
        primary_host_name="Vinnie",
        secondary_host_name="Demi",
        cover_image_path=cover,
    )
    service = BroadcastService(
        settings=settings,
        storage=InMemoryAudioStorage(),
        podcast_client=_FakePodcastClient(),
        renderer=_fake_renderer,
        episode_id_factory=lambda: "0123456789abcdef",
    )

    result = service.generate_once(
        brief=BroadcastBrief(topic="x"),
        title="t",
    )

    # No double slash in the URL even when base ends in /
    assert result.audio_url == "https://example.test/broadcast/0123456789abcdef.mp3"
    assert result.video_url == "https://example.test/broadcast/0123456789abcdef.mp4"
