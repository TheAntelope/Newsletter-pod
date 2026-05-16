"""Substack discovery: free-text user description -> validated publication cards.

Substack itself doesn't expose a public search API, so we use an LLM to
propose handles based on the user's interests and then *validate* each one
by hitting the publication's homepage with the existing `probe_publication`
helper. Hallucinated handles fail the probe and get dropped — only real,
reachable publications make it back to the iOS client.

The output shape mirrors `SubstackProbeResult` so the iOS layer can reuse
its existing intent-creation flow without a new DTO.
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Optional, Protocol

import requests

from .substack import SubstackProbeResult, canonicalize_pub_url, probe_publication

logger = logging.getLogger(__name__)

_OPENAI_CHAT_ENDPOINT = "https://api.openai.com/v1/chat/completions"
_DEFAULT_TIMEOUT_SECONDS = 30
_MAX_QUERY_CHARS = 1000
_MAX_CANDIDATES_REQUESTED = 8


@dataclass(frozen=True)
class DiscoveredPublication:
    probe: SubstackProbeResult
    why: Optional[str]  # Short LLM-written reason this matches the user's interests.


class _SuggestionProvider(Protocol):
    @property
    def model(self) -> str: ...

    def suggest(self, query: str) -> list[tuple[str, Optional[str]]]:
        """Return a list of (handle_or_host, why) suggestions.

        Handles can be raw (e.g. "stratechery"), full hosts
        ("stratechery.substack.com"), or custom domains ("platformer.news").
        Validation is the caller's job.
        """
        ...


_SYSTEM_PROMPT = (
    "You suggest real, currently-active Substack publications that match a "
    "user's interests. You output only structured JSON. Never fabricate a "
    "publication. If you are unsure whether a publication exists, omit it. "
    "Prefer well-known, high-quality writers over obscure ones."
)

_USER_PROMPT_TEMPLATE = """A user said this about their interests:
\"\"\"
{query}
\"\"\"

Suggest up to {max_n} real Substack publications that match. For each, give
its handle (the `xxx` in `xxx.substack.com`) OR full custom domain if the
publication uses one (e.g. "platformer.news"), and one short sentence on why
it matches.

Return ONLY a JSON object with this shape:
{{
  "suggestions": [
    {{"handle": "stratechery.com", "why": "Ben Thompson on AI strategy and compute economics."}},
    {{"handle": "platformer", "why": "Casey Newton on platform regulation."}}
  ]
}}

Rules:
- Only include publications you are confident actually exist.
- If you have no good matches, return {{"suggestions": []}}.
- Do not include the same publication twice.
- Do not invent handles."""


@dataclass
class OpenAISubstackSuggester:
    api_key: str
    model: str = "gpt-4o-mini"
    endpoint: str = _OPENAI_CHAT_ENDPOINT
    timeout_seconds: int = _DEFAULT_TIMEOUT_SECONDS

    def suggest(self, query: str) -> list[tuple[str, Optional[str]]]:
        cleaned = (query or "").strip()
        if not cleaned:
            return []
        if len(cleaned) > _MAX_QUERY_CHARS:
            cleaned = cleaned[:_MAX_QUERY_CHARS]
        payload = {
            "model": self.model,
            "response_format": {"type": "json_object"},
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {
                    "role": "user",
                    "content": _USER_PROMPT_TEMPLATE.format(
                        query=cleaned, max_n=_MAX_CANDIDATES_REQUESTED
                    ),
                },
            ],
            "temperature": 0.4,
        }
        try:
            response = requests.post(
                self.endpoint,
                json=payload,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
                timeout=self.timeout_seconds,
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            logger.warning("Substack-discovery HTTP call failed: %s", exc)
            return []
        choices = response.json().get("choices") or []
        if not choices:
            return []
        content = (choices[0].get("message") or {}).get("content") or ""
        try:
            parsed = json.loads(content)
        except json.JSONDecodeError:
            logger.warning("Substack-discovery returned non-JSON: %r", content[:200])
            return []
        return _coerce_suggestions(parsed)


def _coerce_suggestions(payload: dict) -> list[tuple[str, Optional[str]]]:
    if not isinstance(payload, dict):
        return []
    entries = payload.get("suggestions")
    if not isinstance(entries, list):
        return []
    suggestions: list[tuple[str, Optional[str]]] = []
    seen_handles: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        handle = entry.get("handle")
        why = entry.get("why")
        if not isinstance(handle, str):
            continue
        cleaned_handle = handle.strip().lower()
        if not cleaned_handle or cleaned_handle in seen_handles:
            continue
        seen_handles.add(cleaned_handle)
        cleaned_why: Optional[str] = None
        if isinstance(why, str):
            stripped = why.strip()
            if stripped:
                cleaned_why = stripped if len(stripped) <= 240 else (
                    stripped[:240].rsplit(" ", 1)[0].rstrip(",;:") + "…"
                )
        suggestions.append((cleaned_handle, cleaned_why))
        if len(suggestions) >= _MAX_CANDIDATES_REQUESTED:
            break
    return suggestions


class SubstackDiscoveryService:
    """Compose an LLM suggester with the probe step.

    `probe_fn` is injectable so tests can stub out the network round trip;
    production callers pass `probe_publication`.
    """

    def __init__(
        self,
        suggester: _SuggestionProvider,
        probe_fn=probe_publication,
    ) -> None:
        self._suggester = suggester
        self._probe_fn = probe_fn

    def discover(self, query: str) -> list[DiscoveredPublication]:
        suggestions = self._suggester.suggest(query)
        if not suggestions:
            return []

        results: list[DiscoveredPublication] = []
        seen_hosts: set[str] = set()
        for handle, why in suggestions:
            normalized = _normalize_handle(handle)
            if normalized is None:
                logger.info("Substack-discovery: bad handle suggested: %r", handle)
                continue
            try:
                _, host = canonicalize_pub_url(normalized)
            except ValueError:
                logger.info("Substack-discovery: canonicalize failed: %r", normalized)
                continue
            if host in seen_hosts:
                continue
            try:
                probe = self._probe_fn(f"https://{host}")
            except requests.RequestException as exc:
                logger.info(
                    "Substack-discovery: probe failed for host=%s err=%s",
                    host,
                    exc,
                )
                continue
            except Exception:  # pragma: no cover — defensive
                logger.warning(
                    "Substack-discovery: unexpected probe error host=%s",
                    host,
                    exc_info=True,
                )
                continue
            seen_hosts.add(probe.pub_host)
            results.append(DiscoveredPublication(probe=probe, why=why))
        return results


def _normalize_handle(raw: str) -> Optional[str]:
    """Map an LLM-style suggestion onto something canonicalize_pub_url accepts.

    The LLM is told it may return a bare handle (`stratechery`), a substack
    subdomain (`stratechery.substack.com`), or a custom domain
    (`platformer.news`). Bare handles fail canonicalize because they have no
    dot — we route them through the `@handle` shorthand here so they resolve
    to `<handle>.substack.com` as the user would expect.
    """
    if not isinstance(raw, str):
        return None
    cleaned = raw.strip()
    if not cleaned:
        return None
    if cleaned.startswith("@"):
        return cleaned
    if "://" in cleaned:
        return cleaned
    if "." in cleaned:
        return cleaned
    # Bare handle: treat as substack handle.
    return f"@{cleaned}"
