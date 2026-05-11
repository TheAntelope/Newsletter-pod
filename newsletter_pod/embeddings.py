from __future__ import annotations

import hashlib
import logging
import math
from typing import Optional, Protocol

import requests

logger = logging.getLogger(__name__)

OPENAI_EMBEDDINGS_ENDPOINT = "https://api.openai.com/v1/embeddings"
DEFAULT_BATCH_SIZE = 96
MAX_INPUT_CHARS = 6000


class EmbeddingProvider(Protocol):
    @property
    def model(self) -> str:
        ...

    def embed_texts(self, texts: list[str]) -> list[Optional[list[float]]]:
        ...


def _truncate(text: str) -> str:
    if len(text) <= MAX_INPUT_CHARS:
        return text
    return text[:MAX_INPUT_CHARS]


class OpenAIEmbeddingProvider:
    def __init__(
        self,
        api_key: str,
        model: str = "text-embedding-3-small",
        endpoint: str = OPENAI_EMBEDDINGS_ENDPOINT,
        timeout_seconds: int = 30,
        batch_size: int = DEFAULT_BATCH_SIZE,
    ) -> None:
        if not api_key:
            raise ValueError("OpenAIEmbeddingProvider requires an api_key")
        self._api_key = api_key
        self._model = model
        self._endpoint = endpoint
        self._timeout_seconds = timeout_seconds
        self._batch_size = max(1, batch_size)

    @property
    def model(self) -> str:
        return self._model

    def embed_texts(self, texts: list[str]) -> list[Optional[list[float]]]:
        if not texts:
            return []
        results: list[Optional[list[float]]] = [None] * len(texts)
        for batch_start in range(0, len(texts), self._batch_size):
            batch = texts[batch_start : batch_start + self._batch_size]
            normalized = [_truncate(text or " ") for text in batch]
            try:
                vectors = self._embed_batch(normalized)
            except requests.RequestException as exc:
                logger.warning(
                    "OpenAI embeddings request failed for batch of %d (offset=%d): %s",
                    len(batch),
                    batch_start,
                    exc,
                )
                continue
            for offset, vector in enumerate(vectors):
                results[batch_start + offset] = vector
        return results

    def _embed_batch(self, inputs: list[str]) -> list[Optional[list[float]]]:
        response = requests.post(
            self._endpoint,
            json={"model": self._model, "input": inputs},
            headers={
                "Authorization": f"Bearer {self._api_key}",
                "Content-Type": "application/json",
            },
            timeout=self._timeout_seconds,
        )
        response.raise_for_status()
        payload = response.json()
        data = payload.get("data") or []
        if not isinstance(data, list):
            logger.warning("OpenAI embeddings response missing 'data' list: %r", payload)
            return [None] * len(inputs)
        # OpenAI returns one entry per input in the same order. Re-sort by
        # 'index' defensively in case that contract changes.
        ordered: list[Optional[list[float]]] = [None] * len(inputs)
        for entry in data:
            if not isinstance(entry, dict):
                continue
            index = entry.get("index")
            embedding = entry.get("embedding")
            if not isinstance(index, int) or not 0 <= index < len(inputs):
                continue
            if not isinstance(embedding, list):
                continue
            ordered[index] = [float(value) for value in embedding]
        return ordered


class DeterministicFakeEmbeddingProvider:
    """Test fake. Produces a stable unit-norm vector per input via SHA-256."""

    def __init__(self, model: str = "fake-embedding-v1", dimensions: int = 32) -> None:
        if dimensions <= 0:
            raise ValueError("dimensions must be positive")
        self._model = model
        self._dimensions = dimensions

    @property
    def model(self) -> str:
        return self._model

    def embed_texts(self, texts: list[str]) -> list[Optional[list[float]]]:
        return [self._embed_one(text) for text in texts]

    def _embed_one(self, text: str) -> list[float]:
        digest = hashlib.sha256((text or "").encode("utf-8")).digest()
        # Repeat the digest to fill the requested dimensionality, then map to
        # signed floats in [-1, 1] and L2-normalize.
        raw = (digest * ((self._dimensions // len(digest)) + 1))[: self._dimensions]
        values = [(byte / 127.5) - 1.0 for byte in raw]
        norm = math.sqrt(sum(value * value for value in values)) or 1.0
        return [value / norm for value in values]
