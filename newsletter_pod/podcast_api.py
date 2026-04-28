from __future__ import annotations

import base64
import json
import time
from dataclasses import dataclass
from typing import Any, Optional

import requests

from .models import AudioSegment, GeneratedEpisode

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

    def generate(
        self,
        prompt: str,
        title: str,
        voice_id: Optional[str] = None,
        secondary_voice_id: Optional[str] = None,
        primary_speaker_name: Optional[str] = None,
    ) -> GeneratedEpisode:
        if not self.enabled:
            raise PodcastApiUnavailable("Podcast API is disabled")

        provider = self.provider.strip().lower()
        if provider == "openai":
            return self._generate_with_openai(
                prompt=prompt,
                title=title,
                voice_id=voice_id,
                secondary_voice_id=secondary_voice_id,
                primary_speaker_name=primary_speaker_name,
            )
        if provider == "generic":
            return self._generate_with_generic(prompt=prompt, title=title)
        raise PodcastApiError(f"Unsupported podcast provider: {self.provider}")

    def _generate_with_openai(
        self,
        prompt: str,
        title: str,
        voice_id: Optional[str] = None,
        secondary_voice_id: Optional[str] = None,
        primary_speaker_name: Optional[str] = None,
    ) -> GeneratedEpisode:
        if not self.api_key:
            raise PodcastApiUnavailable("OpenAI API key is not configured")

        structured = self._generate_openai_script(prompt=prompt, title=title)
        episode_title = (structured.get("episode_title") or title).strip()
        show_notes = structured.get("show_notes", "").strip()
        audio_segments = self._parse_audio_segments(structured.get("audio_segments", []))
        if not audio_segments:
            raise PodcastApiError("Structured response missing audio segments")

        speech_max_chars = self._speech_max_chars()
        for segment in audio_segments:
            if len(segment.text) > speech_max_chars:
                raise PodcastApiError(
                    f"Audio segment exceeds speech input limit ({speech_max_chars} chars)"
                )

        primary_key = (primary_speaker_name or "").strip().casefold()

        def _voice_for(segment: AudioSegment) -> Optional[str]:
            if not secondary_voice_id or not primary_key:
                return voice_id
            if segment.speaker.strip().casefold() == primary_key:
                return voice_id
            return secondary_voice_id

        audio_chunks = [self._synthesize_speech(segment.text, _voice_for(segment)) for segment in audio_segments]
        transcript = "\n\n".join(f"{segment.speaker}: {segment.text}" for segment in audio_segments)

        return GeneratedEpisode(
            episode_title=episode_title,
            audio_bytes=b"".join(audio_chunks),
            mime_type="audio/mpeg",
            show_notes=show_notes,
            audio_segments=audio_segments,
            transcript=transcript,
            duration_seconds=_estimate_duration_seconds(transcript),
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
                                "You write concise spoken-word daily business and technology digests. "
                                "Return valid JSON only. "
                                f"Split the narration into 1-6 audio_segments, each at most {OPENAI_SPEECH_MAX_CHARS} "
                                "characters because they will be sent separately to a text-to-speech endpoint. "
                                "Preserve natural transitions across segments. "
                                "Keep the total script compact enough for a short daily episode, and write show_notes "
                                "as markdown with source attributions and links."
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
                                "maxItems": 6,
                                "items": {
                                    "type": "object",
                                    "additionalProperties": False,
                                    "properties": {
                                        "speaker": {"type": "string"},
                                        "text": {
                                            "type": "string",
                                            "maxLength": OPENAI_SPEECH_MAX_CHARS,
                                        },
                                    },
                                    "required": ["speaker", "text"],
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

    def _synthesize_speech(self, script: str, voice_id: Optional[str]) -> bytes:
        provider = (self.tts_provider or "openai").strip().lower()
        if provider == "elevenlabs":
            return self._generate_elevenlabs_speech(script, voice_id)
        return self._generate_openai_speech(script, voice_id)

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
    ) -> list[AudioSegment]:
        segments: list[AudioSegment] = []
        for raw_segment in raw_segments:
            if isinstance(raw_segment, dict):
                speaker = str(raw_segment.get("speaker") or "").strip()
                text = str(raw_segment.get("text") or "").strip()
                if speaker and text:
                    segments.append(AudioSegment(speaker=speaker, text=text))
                continue
            if allow_plain_strings and isinstance(raw_segment, str) and raw_segment.strip():
                segments.append(AudioSegment(speaker="Narrator", text=raw_segment.strip()))
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
