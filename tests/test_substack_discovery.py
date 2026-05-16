from __future__ import annotations

from typing import Optional

import pytest
import requests

from newsletter_pod.substack import SubstackProbeResult
from newsletter_pod.substack_discovery import (
    DiscoveredPublication,
    SubstackDiscoveryService,
    _coerce_suggestions,
)


def test_coerce_suggestions_dedupes_and_caps():
    payload = {
        "suggestions": [
            {"handle": "stratechery", "why": "AI strategy."},
            {"handle": "Stratechery", "why": "duplicate"},
            {"handle": "platformer.news", "why": "platforms"},
            {"handle": "", "why": "empty"},
            {"handle": "valid", "why": "x" * 400},  # long why
            {"why": "no handle"},  # missing handle
            "string-not-dict",
        ]
    }
    out = _coerce_suggestions(payload)
    handles = [h for h, _w in out]
    assert handles == ["stratechery", "platformer.news", "valid"]
    long_why = next(w for h, w in out if h == "valid")
    assert long_why is not None and long_why.endswith("…")


def test_coerce_suggestions_empty_when_payload_malformed():
    assert _coerce_suggestions({"suggestions": "not-a-list"}) == []
    assert _coerce_suggestions({}) == []
    assert _coerce_suggestions("garbage") == []  # type: ignore[arg-type]


class _StubSuggester:
    def __init__(self, suggestions: list[tuple[str, Optional[str]]]) -> None:
        self._suggestions = suggestions
        self.last_query: Optional[str] = None
        self.model = "stub"

    def suggest(self, query: str) -> list[tuple[str, Optional[str]]]:
        self.last_query = query
        return self._suggestions


def _make_probe(host: str, *, title: str | None = None) -> SubstackProbeResult:
    return SubstackProbeResult(
        pub_url=f"https://{host}",
        pub_host=host,
        title=title,
        author=None,
        icon_url=None,
        has_paid_tier=False,
        feed_url=f"https://{host}/feed",
    )


def test_discovery_validates_each_suggestion_via_probe():
    suggester = _StubSuggester(
        [("stratechery", "AI strategy"), ("platformer.news", "platforms")]
    )
    probe_calls: list[str] = []

    def fake_probe(url, session=None):
        probe_calls.append(url)
        host = url.removeprefix("https://")
        return _make_probe(host, title=host.split(".")[0].title())

    service = SubstackDiscoveryService(suggester=suggester, probe_fn=fake_probe)
    results = service.discover("AI and platforms")

    assert suggester.last_query == "AI and platforms"
    assert [r.probe.pub_host for r in results] == [
        "stratechery.substack.com",
        "platformer.news",
    ]
    assert [r.why for r in results] == ["AI strategy", "platforms"]
    assert len(probe_calls) == 2


def test_discovery_drops_suggestions_whose_probe_fails():
    suggester = _StubSuggester(
        [("good", "ok"), ("bad", "ok"), ("alsogood", "ok")]
    )

    def fake_probe(url, session=None):
        if "bad" in url:
            raise requests.RequestException("HTTP 404")
        host = url.removeprefix("https://")
        return _make_probe(host)

    service = SubstackDiscoveryService(suggester=suggester, probe_fn=fake_probe)
    results = service.discover("anything")
    hosts = [r.probe.pub_host for r in results]
    assert "good.substack.com" in hosts
    assert "alsogood.substack.com" in hosts
    assert not any("bad" in host for host in hosts)


def test_discovery_dedupes_handles_resolving_to_same_host():
    """Two LLM suggestions that canonicalize to the same host should only
    produce one probe call and one result."""
    suggester = _StubSuggester(
        [("@stratechery", "first"), ("stratechery.substack.com", "second")]
    )
    probe_calls: list[str] = []

    def fake_probe(url, session=None):
        probe_calls.append(url)
        host = url.removeprefix("https://")
        return _make_probe(host)

    service = SubstackDiscoveryService(suggester=suggester, probe_fn=fake_probe)
    results = service.discover("ai")
    # canonicalize_pub_url maps "@stratechery" -> stratechery.substack.com,
    # which collides with the second suggestion. Either suggester order is
    # acceptable as long as we get one result + one probe.
    assert len(results) == 1
    assert len(probe_calls) == 1


def test_discovery_handles_invalid_handle_gracefully():
    """A suggestion that can't be canonicalized (e.g. empty string) is
    skipped without raising; the rest still get processed."""
    suggester = _StubSuggester([("", "garbage"), ("stratechery", "real")])

    def fake_probe(url, session=None):
        host = url.removeprefix("https://")
        return _make_probe(host)

    service = SubstackDiscoveryService(suggester=suggester, probe_fn=fake_probe)
    results = service.discover("anything")
    assert [r.probe.pub_host for r in results] == ["stratechery.substack.com"]


def test_discovery_empty_query_returns_empty():
    suggester = _StubSuggester([])
    service = SubstackDiscoveryService(
        suggester=suggester,
        probe_fn=lambda url, session=None: _make_probe("x"),
    )
    assert service.discover("") == []
