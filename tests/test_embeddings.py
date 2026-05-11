from __future__ import annotations

from typing import Any

import pytest
import requests

from newsletter_pod.embeddings import (
    DeterministicFakeEmbeddingProvider,
    OpenAIEmbeddingProvider,
)


class _FakeResponse:
    def __init__(self, payload: dict[str, Any], status_code: int = 200) -> None:
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise requests.HTTPError(f"status={self.status_code}")

    def json(self) -> dict[str, Any]:
        return self._payload


def test_openai_provider_returns_vectors_in_input_order(monkeypatch):
    captured: dict[str, Any] = {}

    def fake_post(url: str, json: dict[str, Any], headers: dict[str, str], timeout: int):
        captured["url"] = url
        captured["json"] = json
        captured["headers"] = headers
        # Intentionally return entries out of order to confirm the provider
        # re-sorts by 'index' before yielding the result.
        return _FakeResponse(
            {
                "data": [
                    {"index": 1, "embedding": [0.4, 0.5, 0.6]},
                    {"index": 0, "embedding": [0.1, 0.2, 0.3]},
                ]
            }
        )

    monkeypatch.setattr(requests, "post", fake_post)

    provider = OpenAIEmbeddingProvider(api_key="sk-test", model="text-embedding-3-small")
    result = provider.embed_texts(["alpha", "beta"])

    assert result == [[0.1, 0.2, 0.3], [0.4, 0.5, 0.6]]
    assert captured["json"]["model"] == "text-embedding-3-small"
    assert captured["json"]["input"] == ["alpha", "beta"]
    assert captured["headers"]["Authorization"] == "Bearer sk-test"


def test_openai_provider_returns_none_per_input_when_request_fails(monkeypatch):
    def fake_post(url, json, headers, timeout):
        raise requests.ConnectionError("network down")

    monkeypatch.setattr(requests, "post", fake_post)

    provider = OpenAIEmbeddingProvider(api_key="sk-test")
    result = provider.embed_texts(["a", "b", "c"])

    assert result == [None, None, None]


def test_openai_provider_batches_inputs(monkeypatch):
    calls: list[list[str]] = []

    def fake_post(url, json, headers, timeout):
        calls.append(list(json["input"]))
        return _FakeResponse(
            {
                "data": [
                    {"index": idx, "embedding": [float(idx)]}
                    for idx in range(len(json["input"]))
                ]
            }
        )

    monkeypatch.setattr(requests, "post", fake_post)

    provider = OpenAIEmbeddingProvider(api_key="sk-test", batch_size=2)
    result = provider.embed_texts(["a", "b", "c", "d", "e"])

    assert [len(batch) for batch in calls] == [2, 2, 1]
    assert result == [[0.0], [1.0], [0.0], [1.0], [0.0]]


def test_openai_provider_truncates_long_inputs(monkeypatch):
    captured: dict[str, Any] = {}

    def fake_post(url, json, headers, timeout):
        captured["input"] = json["input"]
        return _FakeResponse(
            {
                "data": [
                    {"index": idx, "embedding": [0.0]}
                    for idx in range(len(json["input"]))
                ]
            }
        )

    monkeypatch.setattr(requests, "post", fake_post)

    provider = OpenAIEmbeddingProvider(api_key="sk-test")
    long_input = "x" * 12000
    provider.embed_texts([long_input])

    assert len(captured["input"][0]) == 6000


def test_openai_provider_requires_api_key():
    with pytest.raises(ValueError):
        OpenAIEmbeddingProvider(api_key="")


def test_deterministic_fake_is_stable_and_unit_norm():
    provider = DeterministicFakeEmbeddingProvider(dimensions=16)
    result_a = provider.embed_texts(["hello"])
    result_b = provider.embed_texts(["hello"])
    assert result_a == result_b
    assert result_a[0] is not None
    norm_squared = sum(value * value for value in result_a[0])
    assert abs(norm_squared - 1.0) < 1e-9


def test_deterministic_fake_distinguishes_inputs():
    provider = DeterministicFakeEmbeddingProvider(dimensions=16)
    vector_a = provider.embed_texts(["alpha"])[0]
    vector_b = provider.embed_texts(["beta"])[0]
    assert vector_a != vector_b
