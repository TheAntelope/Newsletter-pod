from __future__ import annotations

import base64
import json
import logging
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Iterator, Optional

import requests

from .audio_mastering import MasteringError, master_mp3_segments
from .models import AudioSegment, GeneratedEpisode, PodcastUxConfig
from .prompting import build_closing_prompt, fallback_closing_text

logger = logging.getLogger(__name__)

OPENAI_DEFAULT_BASE_URL = "https://api.openai.com"
OPENAI_SPEECH_MAX_CHARS = 4096
ELEVENLABS_BASE_URL = "https://api.elevenlabs.io"
ELEVENLABS_SPEECH_MAX_CHARS = 4096


class PodcastApiError(RuntimeError):
    pass


class PodcastApiUnavailable(PodcastApiError):
    pass


@dataclass
class PodcastApiClient:
    enabled: bool
    provider: str
    base_url: Optional[str]
    api_key: Optional[str]
    timeout_seconds: int
    poll_seconds: int
    text_model: str
    tts_model: str
    tts_voice: str
    tts_instructions: Optional[str] = None
    tts_provider: str = "openai"
    elevenlabs_api_key: Optional[str] = None
    elevenlabs_model: str = "eleven_multilingual_v2"
    # Per-voice ElevenLabs voice_settings.speed (range 0.7-1.2). Populated
    # from voices.yml at container construction; voices without an entry are
    # synthesized at ElevenLabs' default speed.
    voice_speed_by_id: dict[str, float] = field(default_factory=dict)
    # Post-render audio mastering (see audio_mastering.py). When enabled, the
    # per-segment MP3s are loudness-normalized to a shared target and crossfaded
    # instead of byte-concatenated, so the two hosts land at the same volume and
    # the joins stop sounding like separate takes. Defaults keep the legacy
    # byte-concat path so existing behaviour/tests are unchanged until opted in.
    audio_mastering_enabled: bool = False
    audio_target_lufs: float = -16.0
    audio_crossfade_ms: int = 40

    def generate(
        self,
        prompt: str,
        title: str,
        voice_id: Optional[str] = None,
        secondary_voice_id: Optional[str] = None,
        primary_speaker_name: Optional[str] = None,
        secondary_speaker_name: Optional[str] = None,
        ux: Optional[PodcastUxConfig] = None,
        force_default_voice: bool = False,
        lead_in_texts: Optional[list[str]] = None,
        tail_texts: Optional[list[str]] = None,
    ) -> GeneratedEpisode:
        if not self.enabled:
            raise PodcastApiUnavailable("Podcast API is disabled")

        provider = self.provider.strip().lower()
        if provider == "openai":
            # `force_default_voice` is the per-episode override used by the
            # generation gate when a user's premium quota for the week is
            # exhausted. It pins TTS to OpenAI with the bundled voice,
            # regardless of self.tts_provider / the requested voice_id.
            effective_voice_id = None if force_default_voice else voice_id
            effective_secondary_voice_id = None if force_default_voice else secondary_voice_id
            with self._tts_provider_override("openai" if force_default_voice else None):
                return self._generate_with_openai(
                    prompt=prompt,
                    title=title,
                    voice_id=effective_voice_id,
                    secondary_voice_id=effective_secondary_voice_id,
                    primary_speaker_name=primary_speaker_name,
                    secondary_speaker_name=secondary_speaker_name,
                    ux=ux,
                    lead_in_texts=lead_in_texts,
                    tail_texts=tail_texts,
                )
        if provider == "generic":
            return self._generate_with_generic(prompt=prompt, title=title)
        raise PodcastApiError(f"Unsupported podcast provider: {self.provider}")

    @contextmanager
    def _tts_provider_override(self, override: Optional[str]) -> Iterator[None]:
        if override is None:
            yield
            return
        prior = self.tts_provider
        self.tts_provider = override
        try:
            yield
        finally:
            self.tts_provider = prior

    def _generate_with_openai(
        self,
        prompt: str,
        title: str,
        voice_id: Optional[str] = None,
        secondary_voice_id: Optional[str] = None,
        primary_speaker_name: Optional[str] = None,
        secondary_speaker_name: Optional[str] = None,
        ux: Optional[PodcastUxConfig] = None,
        lead_in_texts: Optional[list[str]] = None,
        tail_texts: Optional[list[str]] = None,
    ) -> GeneratedEpisode:
        if not self.api_key:
            raise PodcastApiUnavailable("OpenAI API key is not configured")

        structured = self._generate_openai_script(prompt=prompt, title=title)
        episode_title = (structured.get("episode_title") or title).strip()
        show_notes = structured.get("show_notes", "").strip()
        audio_segments = self._parse_audio_segments(
            structured.get("audio_segments", []),
            primary_speaker_name=primary_speaker_name,
            secondary_speaker_name=secondary_speaker_name,
        )
        if not audio_segments:
            raise PodcastApiError("Structured response missing audio segments")

        if ux is not None:
            primary_display = (primary_speaker_name or "").strip() or "Host"
            body_transcript = "\n\n".join(
                f"{segment.speaker}: {segment.text}" for segment in audio_segments
            )
            closing_segment = self._build_closing_segment(
                body_transcript=body_transcript,
                ux=ux,
                primary_display=primary_display,
            )
            audio_segments.append(closing_segment)

        speech_max_chars = self._speech_max_chars()
        for segment in audio_segments:
            if len(segment.text) > speech_max_chars:
                raise PodcastApiError(
                    f"Audio segment exceeds speech input limit ({speech_max_chars} chars)"
                )

        # Wrap the generated body in spoken framing *after* length validation
        # so the framing (e.g. greeting/outro) is never subject to truncation.
        # Each framing line is its own segment, giving a natural pause between
        # sections, and is voiced by the primary host.
        if lead_in_texts or tail_texts:
            primary_display = (primary_speaker_name or "").strip() or "Host"

            def _framing_segments(texts: Optional[list[str]]) -> list[AudioSegment]:
                return [
                    AudioSegment(role="primary", speaker=primary_display, text=text)
                    for text in (texts or [])
                    if text and text.strip()
                ]

            audio_segments = (
                _framing_segments(lead_in_texts)
                + audio_segments
                + _framing_segments(tail_texts)
            )

        def _voice_for(segment: AudioSegment) -> Optional[str]:
            if not secondary_voice_id:
                return voice_id
            return voice_id if segment.role == "primary" else secondary_voice_id

        audio_chunks = [self._synthesize_speech(segment.text, _voice_for(segment)) for segment in audio_segments]
        transcript = "\n\n".join(f"{segment.speaker}: {segment.text}" for segment in audio_segments)
        audio_bytes = self._assemble_audio(audio_chunks)

        # Prefer the duration decoded from the rendered MP3 frames; fall back to a
        # word-count estimate only if frame parsing finds nothing (e.g. a stub
        # synthesizer in tests). The measured value is what the player and our RSS
        # ``itunes:duration`` should agree on.
        duration_seconds = _measure_mp3_duration_seconds(audio_bytes)
        if duration_seconds is None:
            duration_seconds = _estimate_duration_seconds(transcript)

        return GeneratedEpisode(
            episode_title=episode_title,
            audio_bytes=audio_bytes,
            mime_type="audio/mpeg",
            show_notes=show_notes,
            audio_segments=audio_segments,
            transcript=transcript,
            duration_seconds=duration_seconds,
        )

    def _generate_openai_script(self, prompt: str, title: str) -> dict[str, Any]:
        payload = {
            "model": self.text_model,
            "input": [
                {
                    "role": "system",
                    "content": [
                        {
                            "type": "input_text",
                            "text": (
                                "You write spoken-word daily digests on the user's selected sources. "
                                "Return valid JSON only. "
                                f"Split the narration into 1-12 audio_segments, each at most {OPENAI_SPEECH_MAX_CHARS} "
                                "characters because they will be sent separately to a text-to-speech endpoint. "
                                "Preserve natural transitions across segments. "
                                "The anchor must always round off and close out the podcast with a clear sign-off so the listener knows the episode is over. "
                                "Write show_notes as markdown with source attributions and links."
                            ),
                        }
                    ],
                },
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_text",
                            "text": f"Episode title: {title}\n\nSource material:\n{prompt}",
                        }
                    ],
                },
            ],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "newsletter_digest",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "episode_title": {"type": "string"},
                            "show_notes": {"type": "string"},
                            "audio_segments": {
                                "type": "array",
                                "minItems": 1,
                                "maxItems": 12,
                                "items": {
                                    "type": "object",
                                    "additionalProperties": False,
                                    "properties": {
                                        "role": {
                                            "type": "string",
                                            "enum": ["primary", "secondary"],
                                        },
                                        "text": {
                                            "type": "string",
                                            "maxLength": OPENAI_SPEECH_MAX_CHARS,
                                        },
                                    },
                                    "required": ["role", "text"],
                                },
                            },
                        },
                        "required": ["episode_title", "show_notes", "audio_segments"],
                    },
                }
            },
        }

        response = requests.post(
            self._build_openai_endpoint("/responses"),
            json=payload,
            headers=self._build_openai_headers(),
            timeout=60,
        )
        self._raise_for_availability(response)
        response.raise_for_status()

        output_text = _extract_output_text(response.json())
        try:
            data = json.loads(output_text)
        except json.JSONDecodeError as exc:
            raise PodcastApiError("OpenAI structured response was not valid JSON") from exc

        if not isinstance(data, dict):
            raise PodcastApiError("OpenAI structured response was not an object")
        return data

    def _build_closing_segment(
        self,
        body_transcript: str,
        ux: PodcastUxConfig,
        primary_display: str,
    ) -> AudioSegment:
        """Stage-2: generate a dedicated closing segment.

        Falls back to a deterministic sign-off if the API call fails for any
        reason so episodes always end with a wrap.
        """
        try:
            text = self._generate_closing_text(body_transcript=body_transcript, ux=ux)
        except Exception as exc:  # noqa: BLE001 — closing must never block publish
            logger.warning("Stage-2 closing call failed, using fallback: %s", exc)
            text = fallback_closing_text()
        text = text.strip() or fallback_closing_text()
        if len(text) > OPENAI_SPEECH_MAX_CHARS:
            text = text[:OPENAI_SPEECH_MAX_CHARS]
        return AudioSegment(role="primary", speaker=primary_display, text=text)

    def _generate_closing_text(self, body_transcript: str, ux: PodcastUxConfig) -> str:
        if not self.api_key:
            raise PodcastApiUnavailable("OpenAI API key is not configured")
        user_prompt = build_closing_prompt(body_transcript=body_transcript, ux=ux)
        payload = {
            "model": self.text_model,
            "input": [
                {
                    "role": "system",
                    "content": [
                        {
                            "type": "input_text",
                            "text": (
                                "You write the closing segment for a podcast "
                                "episode. Return valid JSON only. The text "
                                "field is one spoken segment delivered by the "
                                "primary host: a brief lead-in, the requested "
                                "takeaways as single spoken sentences, and a "
                                "sign-off naming the show. No stage "
                                "directions, no speaker labels."
                            ),
                        }
                    ],
                },
                {
                    "role": "user",
                    "content": [{"type": "input_text", "text": user_prompt}],
                },
            ],
            "text": {
                "format": {
                    "type": "json_schema",
                    "name": "closing_segment",
                    "strict": True,
                    "schema": {
                        "type": "object",
                        "additionalProperties": False,
                        "properties": {
                            "text": {
                                "type": "string",
                                "maxLength": OPENAI_SPEECH_MAX_CHARS,
                            },
                        },
                        "required": ["text"],
                    },
                }
            },
        }
        response = requests.post(
            self._build_openai_endpoint("/responses"),
            json=payload,
            headers=self._build_openai_headers(),
            timeout=60,
        )
        self._raise_for_availability(response)
        response.raise_for_status()
        output_text = _extract_output_text(response.json())
        data = json.loads(output_text)
        if not isinstance(data, dict) or not isinstance(data.get("text"), str):
            raise PodcastApiError("Closing response missing text field")
        return data["text"]

    def _synthesize_speech(self, script: str, voice_id: Optional[str]) -> bytes:
        provider = (self.tts_provider or "openai").strip().lower()
        if provider == "elevenlabs":
            try:
                return self._generate_elevenlabs_speech(script, voice_id)
            except (PodcastApiError, requests.RequestException) as exc:
                if not self.api_key:
                    # No OpenAI key configured — can't fall back.
                    raise
                # ElevenLabs voice IDs are not valid OpenAI voices, so we let
                # the OpenAI call use its configured default voice.
                logger.warning(
                    "ElevenLabs TTS failed (%s); falling back to OpenAI TTS",
                    exc,
                )
                return self._generate_openai_speech(script, voice_id=None)
        return self._generate_openai_speech(script, voice_id)

    def _assemble_audio(self, audio_chunks: list[bytes]) -> bytes:
        """Combine per-segment TTS MP3s into the final episode audio.

        When mastering is enabled, loudness-normalize each segment to a shared
        target and crossfade the joins (audio_mastering.master_mp3_segments).
        On ANY mastering failure — including ffmpeg being unavailable — fall
        back to the legacy raw byte-concat so generation never breaks. With
        mastering disabled this is exactly the old behaviour.
        """
        if self.audio_mastering_enabled and audio_chunks:
            try:
                return master_mp3_segments(
                    audio_chunks,
                    target_lufs=self.audio_target_lufs,
                    crossfade_ms=self.audio_crossfade_ms,
                )
            except MasteringError as exc:
                logger.warning(
                    "Audio mastering failed (%s); falling back to raw concat", exc
                )
        return _concat_mp3_chunks(audio_chunks)

    def _speech_max_chars(self) -> int:
        provider = (self.tts_provider or "openai").strip().lower()
        if provider == "elevenlabs":
            return ELEVENLABS_SPEECH_MAX_CHARS
        return OPENAI_SPEECH_MAX_CHARS

    def _generate_openai_speech(self, script: str, voice_id: Optional[str] = None) -> bytes:
        payload: dict[str, Any] = {
            "model": self.tts_model,
            "voice": voice_id or self.tts_voice,
            "input": script,
            "response_format": "mp3",
        }
        if self.tts_instructions:
            payload["instructions"] = self.tts_instructions

        response = requests.post(
            self._build_openai_endpoint("/audio/speech"),
            json=payload,
            headers=self._build_openai_headers(),
            timeout=60,
        )
        self._raise_for_availability(response)
        response.raise_for_status()
        return response.content

    def _generate_elevenlabs_speech(self, script: str, voice_id: Optional[str]) -> bytes:
        if not self.elevenlabs_api_key:
            raise PodcastApiUnavailable("ElevenLabs API key is not configured")
        if not voice_id:
            raise PodcastApiError("ElevenLabs voice_id is required")

        url = f"{ELEVENLABS_BASE_URL}/v1/text-to-speech/{voice_id}"
        headers = {
            "xi-api-key": self.elevenlabs_api_key,
            "Content-Type": "application/json",
            "Accept": "audio/mpeg",
        }
        payload: dict[str, Any] = {
            "text": script,
            "model_id": self.elevenlabs_model,
        }
        speed = self.voice_speed_by_id.get(voice_id)
        if speed is not None:
            # ElevenLabs accepts speed in [0.7, 1.2]; clamp defensively so a
            # bad voices.yml entry doesn't 4xx the synth call.
            payload["voice_settings"] = {"speed": max(0.7, min(1.2, float(speed)))}

        response = requests.post(
            url,
            json=payload,
            headers=headers,
            timeout=120,
        )
        self._raise_for_availability(response)
        response.raise_for_status()
        return response.content

    def _build_openai_headers(self) -> dict[str, str]:
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        return headers

    def _build_openai_endpoint(self, path: str) -> str:
        base_url = (self.base_url or OPENAI_DEFAULT_BASE_URL).rstrip("/")
        if base_url.endswith("/v1"):
            return f"{base_url}{path}"
        return f"{base_url}/v1{path}"

    def _generate_with_generic(self, prompt: str, title: str) -> GeneratedEpisode:
        if not self.base_url:
            raise PodcastApiUnavailable("Podcast API base URL is not configured")

        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        payload = {
            "title": title,
            "prompt": prompt,
            "output_format": "mp3",
        }

        endpoint = f"{self.base_url.rstrip('/')}/v1/podcasts:generate"
        response = requests.post(endpoint, json=payload, headers=headers, timeout=30)
        self._raise_for_availability(response)
        response.raise_for_status()

        data = response.json()
        if "audio_base64" in data:
            return self._parse_generic_generated(data)

        operation_name = data.get("operation") or data.get("operation_name") or data.get("name")
        if not operation_name:
            raise PodcastApiError("Podcast API response did not include audio or operation id")

        operation_endpoint = f"{self.base_url.rstrip('/')}/{operation_name.lstrip('/')}"
        deadline = time.time() + self.timeout_seconds

        while time.time() < deadline:
            op_response = requests.get(operation_endpoint, headers=headers, timeout=30)
            self._raise_for_availability(op_response)
            op_response.raise_for_status()
            op_data = op_response.json()

            if op_data.get("done"):
                if op_data.get("error"):
                    raise PodcastApiError(str(op_data["error"]))
                result = op_data.get("response") or op_data.get("result") or {}
                return self._parse_generic_generated(result)

            time.sleep(self.poll_seconds)

        raise TimeoutError("Podcast generation timed out")

    def _parse_generic_generated(self, data: dict[str, Any]) -> GeneratedEpisode:
        audio_b64 = data.get("audio_base64")
        if not audio_b64:
            raise PodcastApiError("Generated response missing audio_base64")

        episode_title = data.get("episode_title") or data.get("title") or "Daily Newsletter Digest"
        show_notes = data.get("show_notes") or data.get("summary") or ""
        transcript = data.get("transcript")
        duration = data.get("duration_seconds")
        mime_type = data.get("mime_type") or "audio/mpeg"
        audio_segments = self._parse_audio_segments(data.get("audio_segments", []), allow_plain_strings=True)

        return GeneratedEpisode(
            episode_title=episode_title,
            audio_bytes=base64.b64decode(audio_b64),
            mime_type=mime_type,
            show_notes=show_notes,
            audio_segments=audio_segments,
            transcript=transcript,
            duration_seconds=duration,
        )

    def _raise_for_availability(self, response: requests.Response) -> None:
        if response.status_code in (401, 403):
            raise PodcastApiUnavailable(f"Podcast API unavailable ({response.status_code})")

    def _parse_audio_segments(
        self,
        raw_segments: list[Any],
        allow_plain_strings: bool = False,
        primary_speaker_name: Optional[str] = None,
        secondary_speaker_name: Optional[str] = None,
    ) -> list[AudioSegment]:
        primary_display = (primary_speaker_name or "").strip() or "Host"
        secondary_display = (secondary_speaker_name or "").strip() or "Co-host"

        def _resolve(raw_role: str, raw_speaker: str) -> tuple[str, str]:
            role = raw_role.strip().casefold()
            if role in ("primary", "secondary"):
                return role, primary_display if role == "primary" else secondary_display
            # Legacy/free-form speaker name — keep prior behaviour by mapping
            # known names back to a role and falling through to primary otherwise.
            speaker_key = raw_speaker.strip().casefold()
            if speaker_key and speaker_key == primary_display.casefold():
                return "primary", primary_display
            if speaker_key and speaker_key == secondary_display.casefold():
                return "secondary", secondary_display
            return "primary", raw_speaker.strip() or primary_display

        segments: list[AudioSegment] = []
        for raw_segment in raw_segments:
            if isinstance(raw_segment, dict):
                raw_role = str(raw_segment.get("role") or "").strip()
                raw_speaker = str(raw_segment.get("speaker") or "").strip()
                text = str(raw_segment.get("text") or "").strip()
                if not text:
                    continue
                role, speaker = _resolve(raw_role, raw_speaker)
                segments.append(AudioSegment(role=role, speaker=speaker, text=text))
                continue
            if allow_plain_strings and isinstance(raw_segment, str) and raw_segment.strip():
                segments.append(
                    AudioSegment(role="primary", speaker=primary_display, text=raw_segment.strip())
                )
        return segments


def _extract_output_text(data: dict[str, Any]) -> str:
    parts: list[str] = []
    for item in data.get("output", []):
        for content in item.get("content", []):
            if content.get("type") == "output_text" and content.get("text"):
                parts.append(content["text"])

    output_text = "".join(parts).strip()
    if output_text:
        return output_text
    raise PodcastApiError("OpenAI response did not include output_text")


def _estimate_duration_seconds(text: str) -> int:
    words = len(text.split())
    if words == 0:
        return 0
    return max(1, round(words / 150 * 60))


# MPEG audio frame tables (Layer III only — everything we synthesize is MP3).
_MP3_BITRATES_KBPS = {
    "1": [0, 32, 40, 48, 56, 64, 80, 96, 112, 128, 160, 192, 224, 256, 320, 0],
    "2": [0, 8, 16, 24, 32, 40, 48, 56, 64, 80, 96, 112, 128, 144, 160, 0],
}
_MP3_SAMPLE_RATES = {
    "1": [44100, 48000, 32000, 0],  # MPEG-1
    "2": [22050, 24000, 16000, 0],  # MPEG-2
    "2.5": [11025, 12000, 8000, 0],
}
_MP3_VERSION = {0: "2.5", 2: "2", 3: "1"}


def _mp3_frame_length(buf: bytes, i: int) -> Optional[int]:
    """Byte length of the MPEG Layer III frame whose header starts at ``i``,
    or None if there is no valid Layer III frame there."""
    if i + 4 > len(buf) or buf[i] != 0xFF or (buf[i + 1] & 0xE0) != 0xE0:
        return None
    version = _MP3_VERSION.get((buf[i + 1] >> 3) & 0x3)
    layer_bits = (buf[i + 1] >> 1) & 0x3
    bitrate_idx = (buf[i + 2] >> 4) & 0xF
    srate_idx = (buf[i + 2] >> 2) & 0x3
    padding = (buf[i + 2] >> 1) & 0x1
    if version is None or layer_bits != 1 or srate_idx == 3 or bitrate_idx in (0, 15):
        return None
    bitrate = _MP3_BITRATES_KBPS["1" if version == "1" else "2"][bitrate_idx] * 1000
    sample_rate = _MP3_SAMPLE_RATES[version][srate_idx]
    if bitrate == 0 or sample_rate == 0:
        return None
    if version == "1":
        return (144 * bitrate) // sample_rate + padding
    return (72 * bitrate) // sample_rate + padding


def _strip_mp3_container(chunk: bytes) -> bytes:
    """Strip a single TTS chunk's MP3 container framing so multiple chunks can be
    safely concatenated into one stream.

    Each ElevenLabs/OpenAI TTS response is a *complete* MP3: a leading ID3v2 tag,
    a Xing/Info header frame that declares the duration of *that chunk only*, the
    audio frames, then sometimes a trailing ID3v1 tag. Byte-joining complete MP3s
    buries those headers mid-stream, and spec-compliant players (e.g. Podcast
    Addict) trust the first chunk's Xing frame count and stop after just that
    chunk — the episode appears to cut off after a few seconds. We keep only the
    raw audio frames; with no Xing header the joined result is read as CBR and its
    duration is computed correctly from size/bitrate.

    Non-MP3 input (e.g. a stub synthesizer in tests) is returned unchanged.
    """
    if not chunk:
        return b""
    n = len(chunk)
    i = 0
    if n >= 10 and chunk[:3] == b"ID3":
        size = (chunk[6] << 21) | (chunk[7] << 14) | (chunk[8] << 7) | chunk[9]
        i = 10 + size
    # Advance to the first MPEG audio frame sync.
    j = i
    while j < n - 4 and not (chunk[j] == 0xFF and (chunk[j + 1] & 0xE0) == 0xE0):
        j += 1
    if j >= n - 4:
        # No MPEG frames found — not an MP3 we recognize; leave it untouched.
        return chunk
    i = j
    # Drop a leading Xing/Info/VBRI header frame (it describes only this chunk).
    frame_len = _mp3_frame_length(chunk, i)
    if frame_len and (
        b"Xing" in chunk[i : i + frame_len]
        or b"Info" in chunk[i : i + frame_len]
        or b"VBRI" in chunk[i : i + frame_len]
    ):
        i += frame_len
    # Strip a trailing ID3v1 tag (128 bytes starting with "TAG").
    end = n
    if end >= 128 and chunk[end - 128 : end - 125] == b"TAG":
        end -= 128
    return chunk[i:end]


def _concat_mp3_chunks(chunks: list[bytes]) -> bytes:
    """Join per-segment TTS MP3s into one playable stream by stripping each
    chunk's container framing first (see :func:`_strip_mp3_container`)."""
    return b"".join(_strip_mp3_container(chunk) for chunk in chunks)


def _measure_mp3_duration_seconds(audio: bytes) -> Optional[int]:
    """Measure the real duration of a (possibly concatenated) MP3 by walking its
    frame headers and summing per-frame durations. Returns None if no valid
    frames are found so callers can fall back to a transcript-based estimate.

    Our episodes are byte-concatenated TTS chunks, so the only reliable duration
    is the one decoded from the actual frames — a word-count estimate drifts from
    what the player reports (and what we put in the RSS ``itunes:duration``).
    """
    if not audio:
        return None

    i = 0
    n = len(audio)
    # Skip a leading ID3v2 tag (syncsafe size, 4 bytes) if present.
    if n >= 10 and audio[:3] == b"ID3":
        size = (
            (audio[6] << 21) | (audio[7] << 14) | (audio[8] << 7) | audio[9]
        )
        i = 10 + size

    total = 0.0
    frames = 0
    while i < n - 4:
        if audio[i] != 0xFF or (audio[i + 1] & 0xE0) != 0xE0:
            i += 1
            continue
        header = audio[i + 1]
        ver_bits = (header >> 3) & 0x3
        layer_bits = (header >> 1) & 0x3
        b2 = audio[i + 2]
        bitrate_idx = (b2 >> 4) & 0xF
        srate_idx = (b2 >> 2) & 0x3
        padding = (b2 >> 1) & 0x1

        version = _MP3_VERSION.get(ver_bits)
        # layer_bits 01 == Layer III; bail on anything else / reserved fields.
        if (
            version is None
            or layer_bits != 1
            or srate_idx == 3
            or bitrate_idx in (0, 15)
        ):
            i += 1
            continue

        bitrate = _MP3_BITRATES_KBPS["1" if version == "1" else "2"][bitrate_idx] * 1000
        sample_rate = _MP3_SAMPLE_RATES[version][srate_idx]
        if bitrate == 0 or sample_rate == 0:
            i += 1
            continue

        if version == "1":
            samples_per_frame = 1152
            frame_len = (144 * bitrate) // sample_rate + padding
        else:
            samples_per_frame = 576
            frame_len = (72 * bitrate) // sample_rate + padding

        if frame_len <= 0:
            i += 1
            continue

        total += samples_per_frame / sample_rate
        frames += 1
        i += frame_len

    if frames == 0:
        return None
    return max(1, round(total))
