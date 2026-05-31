from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional, Protocol

from ..models import GeneratedEpisode, PodcastUxConfig
from ..podcast_api import PodcastApiClient
from ..storage import AudioStorage
from .framing import build_framing
from .prompting import BroadcastBrief, build_broadcast_prompt
from .video import render_waveform_video

logger = logging.getLogger(__name__)

BROADCAST_PREFIX = "broadcast"


@dataclass(frozen=True)
class BroadcastSettings:
    """Subset of newsletter_pod.config.Settings the broadcast service needs.

    Pulled into a tiny dataclass so the service is trivial to unit-test
    without standing up the full Settings.from_env() chain.
    """

    app_base_url: str
    primary_voice_id: str
    secondary_voice_id: str
    primary_host_name: str
    secondary_host_name: str
    cover_image_path: Path


@dataclass(frozen=True)
class BroadcastResult:
    episode_id: str
    title: str
    show_notes: str
    audio_object_name: str
    audio_url: str
    audio_size_bytes: int
    video_object_name: str
    video_url: str
    video_size_bytes: int
    duration_seconds: Optional[int]
    transcript: Optional[str]


class _Renderer(Protocol):
    def __call__(self, *, audio_bytes: bytes, cover_image_bytes: bytes) -> bytes: ...


class BroadcastService:
    """Glue between the topic brief and a postable artifact.

    Phase 0 stays stateless — no Firestore writes. The episode_id is a
    random hex; the GCS object names embed it; the response contains
    everything needed to find or post the assets later.
    """

    def __init__(
        self,
        settings: BroadcastSettings,
        storage: AudioStorage,
        podcast_client: PodcastApiClient,
        renderer: _Renderer = render_waveform_video,
        episode_id_factory: Callable[[], str] = lambda: secrets.token_hex(8),
    ) -> None:
        self._settings = settings
        self._storage = storage
        self._podcast_client = podcast_client
        self._renderer = renderer
        self._episode_id_factory = episode_id_factory

    def generate_once(
        self,
        brief: BroadcastBrief,
        title: str,
        ux: Optional[PodcastUxConfig] = None,
        feedback_prompt_text: Optional[str] = None,
    ) -> BroadcastResult:
        prompt = build_broadcast_prompt(brief)

        # Wrap every broadcast episode in the standard spoken show framing.
        # This is a pure string-assembly step in front of the existing TTS
        # call — voice settings and audio assembly are unchanged.
        framing = build_framing(topic=brief.topic, feedback_text=feedback_prompt_text)

        logger.info("BroadcastService.generate_once: calling PodcastApiClient.generate")
        episode: GeneratedEpisode = self._podcast_client.generate(
            prompt=prompt,
            title=title,
            voice_id=self._settings.primary_voice_id,
            secondary_voice_id=self._settings.secondary_voice_id,
            primary_speaker_name=self._settings.primary_host_name,
            secondary_speaker_name=self._settings.secondary_host_name,
            ux=ux,
            lead_in_texts=framing.lead,
            tail_texts=framing.tail,
        )
        logger.info(
            "BroadcastService.generate_once: script+TTS done audio_bytes=%d segments=%d",
            len(episode.audio_bytes),
            len(episode.audio_segments),
        )

        cover_bytes = self._settings.cover_image_path.read_bytes()
        logger.info(
            "BroadcastService.generate_once: rendering waveform video cover_bytes=%d",
            len(cover_bytes),
        )
        video_bytes = self._renderer(
            audio_bytes=episode.audio_bytes,
            cover_image_bytes=cover_bytes,
        )
        logger.info(
            "BroadcastService.generate_once: video render done video_bytes=%d",
            len(video_bytes),
        )

        episode_id = self._episode_id_factory()
        audio_object_name = f"{BROADCAST_PREFIX}/{episode_id}.mp3"
        video_object_name = f"{BROADCAST_PREFIX}/{episode_id}.mp4"

        logger.info(
            "BroadcastService.generate_once: uploading to GCS episode_id=%s",
            episode_id,
        )
        _, audio_size = self._storage.upload_object(
            audio_object_name, episode.audio_bytes, episode.mime_type
        )
        _, video_size = self._storage.upload_object(
            video_object_name, video_bytes, "video/mp4"
        )
        logger.info(
            "BroadcastService.generate_once: GCS upload done episode_id=%s audio_size=%d video_size=%d",
            episode_id,
            audio_size,
            video_size,
        )

        base = self._settings.app_base_url.rstrip("/")
        return BroadcastResult(
            episode_id=episode_id,
            title=episode.episode_title,
            show_notes=episode.show_notes,
            audio_object_name=audio_object_name,
            audio_url=f"{base}/broadcast/{episode_id}.mp3",
            audio_size_bytes=audio_size,
            video_object_name=video_object_name,
            video_url=f"{base}/broadcast/{episode_id}.mp4",
            video_size_bytes=video_size,
            duration_seconds=episode.duration_seconds,
            transcript=episode.transcript,
        )
