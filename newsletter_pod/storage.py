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

    @abstractmethod
    def delete_audio(self, object_name: str) -> bool:
        """Remove the object from the underlying store. Returns True if an
        object was deleted, False if it didn't exist. Idempotent: missing
        objects are not an error."""
        raise NotImplementedError

    @abstractmethod
    def upload_object(self, object_name: str, data: bytes, mime_type: str) -> tuple[str, int]:
        """Upload bytes at an explicit object name with a caller-chosen
        mime type. Unlike upload_audio, the prefix is the caller's
        responsibility — pass the full GCS-style key (e.g. "broadcast/<id>.mp4").
        """
        raise NotImplementedError

    @abstractmethod
    def get_object(self, object_name: str) -> bytes:
        """Read raw bytes at an explicit object name. Raises FileNotFoundError
        when the object doesn't exist."""
        raise NotImplementedError

    @abstractmethod
    def object_size(self, object_name: str) -> int:
        """Return the byte size of an object without downloading it. Raises
        FileNotFoundError when the object doesn't exist. Used to fill the RSS
        <enclosure length="…"> without pulling the whole asset into memory."""
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

    def delete_audio(self, object_name: str) -> bool:
        return self._objects.pop(object_name, None) is not None

    def upload_object(self, object_name: str, data: bytes, mime_type: str) -> tuple[str, int]:
        self._objects[object_name] = data
        return object_name, len(data)

    def get_object(self, object_name: str) -> bytes:
        data = self._objects.get(object_name)
        if data is None:
            raise FileNotFoundError(object_name)
        return data

    def object_size(self, object_name: str) -> int:
        data = self._objects.get(object_name)
        if data is None:
            raise FileNotFoundError(object_name)
        return len(data)


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

    def delete_audio(self, object_name: str) -> bool:
        blob = self._bucket.blob(object_name)
        if not blob.exists():
            return False
        blob.delete()
        return True

    def upload_object(self, object_name: str, data: bytes, mime_type: str) -> tuple[str, int]:
        blob = self._bucket.blob(object_name)
        blob.upload_from_string(data, content_type=mime_type)
        return object_name, len(data)

    def get_object(self, object_name: str) -> bytes:
        blob = self._bucket.blob(object_name)
        if not blob.exists():
            raise FileNotFoundError(object_name)
        return blob.download_as_bytes()

    def object_size(self, object_name: str) -> int:
        # get_blob() does a metadata GET (no payload download) and returns
        # None when the object is missing.
        blob = self._bucket.get_blob(object_name)
        if blob is None:
            raise FileNotFoundError(object_name)
        return blob.size or 0
