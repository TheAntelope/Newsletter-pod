"""Deterministic detector for the recurring "sounds like AI" tics in generated
scripts.

Pure, no I/O. ``scan_segments`` returns which segments contain a banned tic (and
which phrases matched); the podcast client uses that to rewrite only the
offending segments (see ``PodcastApiClient._delint_segments``). Keeping detection
deterministic means the rewrite pass can verify it actually cleared the tic
rather than trusting the model.

Phrases are matched as case-insensitive regexes against a whitespace-collapsed
copy of the text, so a pattern like ``less .{0,40}? and more`` catches the
"this is less X and more Y" construction across line breaks. A phrase that isn't
a valid regex falls back to a literal (escaped) match, so admins can type plain
strings without worrying about regex syntax.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, Optional

# Built-in tics, always applied. A blueprint's `style.banned_phrases` extends
# (not replaces) this list, so the defaults work before any admin edit.
DEFAULT_BANNED_PHRASES: tuple[str, ...] = (
    r"\blet'?s dive in\b",
    r"\bdive (?:in|into)\b",
    r"\btapestry\b",
    r"\bdelve\b",
    r"\bthis is less .{0,40}? and more\b",
    r"\bit'?s not just .{0,40}?,? it'?s\b",
    r"\bnot just .{0,40}? but (?:also )?\b",
    r"\bin today'?s fast-paced world\b",
    r"\bat the end of the day\b",
    r"\bwhen it comes to\b",
    r"\bin a world where\b",
    r"\bbuckle up\b",
    r"\bgame[- ]changer\b",
    r"\blet'?s unpack\b",
    r"\bthe reality is\b",
)

_WHITESPACE = re.compile(r"\s+")


@dataclass
class LintHit:
    segment_index: int
    matched: list[str]  # the source phrases that matched, for the rewrite prompt


def _compile(phrase: str) -> Optional[re.Pattern[str]]:
    cleaned = (phrase or "").strip()
    if not cleaned:
        return None
    try:
        return re.compile(cleaned, re.IGNORECASE)
    except re.error:
        return re.compile(re.escape(cleaned), re.IGNORECASE)


def _normalize(text: str) -> str:
    return _WHITESPACE.sub(" ", text or "").strip()


def matched_phrases(text: str, banned_phrases: Iterable[str]) -> list[str]:
    """Return the subset of ``banned_phrases`` that appear in ``text``."""
    normalized = _normalize(text)
    if not normalized:
        return []
    hits: list[str] = []
    for phrase in banned_phrases:
        pattern = _compile(phrase)
        if pattern is not None and pattern.search(normalized):
            hits.append(phrase.strip())
    return hits


def scan_segments(segments, banned_phrases: Iterable[str]) -> list[LintHit]:
    """Return one LintHit per segment whose ``text`` contains a banned tic.

    ``segments`` is any iterable of objects exposing a ``.text`` attribute
    (AudioSegment); the banned list is materialized once so callers can pass a
    generator.
    """
    phrases = [p for p in banned_phrases if (p or "").strip()]
    if not phrases:
        return []
    hits: list[LintHit] = []
    for index, segment in enumerate(segments):
        matched = matched_phrases(getattr(segment, "text", ""), phrases)
        if matched:
            hits.append(LintHit(segment_index=index, matched=matched))
    return hits
