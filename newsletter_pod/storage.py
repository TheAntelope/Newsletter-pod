from __future__ import annotations

from abc import ABC, abstractmethod

from google.cloud import storage


class AudioStorage(ABC):
    @abstractmethod
    def upload_audio(self, episode_id: str, audio_bytes: bytes, mime_type: str) -> tuple[str, int]:
        raise NotImplementedError

    @abstractmethod
    def download_audio(self, object_name: str) -> bytes:
        raise NotImplementedError


class InMemoryAudioStorage(AudioStorage):
    def __init__(self) -> None:
        self._objects: dict[str, bytes] = {}

    def upload_audio(self, episode_id: str, audio_bytes: bytes, mime_type: str) -> tuple[str, int]:
        object_name = f"episodes/{episode_id}.mp3"
        self._objects[object_name] = audio_bytes
        return object_name, len(audio_bytes)

    def download_audio(self, object_name: str) -> bytes:
        data = self._objects.get(object_name)
        if data is None:
            raise FileNotFoundError(object_name)
        return data


class GCSAudioStorage(AudioStorage):
    def __init__(self, bucket_name: str, prefix: str = "episodes") -> None:
        self._client = storage.Client()
        self._bucket = self._client.bucket(bucket_name)
        self._prefix = prefix.strip("/")

    def upload_audio(self, episode_id: str, audio_bytes: bytes, mime_type: str) -> tuple[str, int]:
        object_name = f"{self._prefix}/{episode_id}.mp3"
        blob = self._bucket.blob(object_name)
        blob.upload_from_string(audio_bytes, content_type=mime_type)
        return object_name, len(audio_bytes)

    def download_audio(self, object_name: str) -> bytes:
        blob = self._bucket.blob(object_name)
        if not blob.exists():
            raise FileNotFoundError(object_name)
        return blob.download_as_bytes()
