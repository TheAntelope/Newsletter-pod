from __future__ import annotations

from dataclasses import dataclass

from newsletter_pod.text_lint import (
    DEFAULT_BANNED_PHRASES,
    matched_phrases,
    scan_segments,
)


@dataclass
class _Seg:
    text: str


def test_detects_named_default_tics():
    assert matched_phrases("So let's dive in, everyone.", DEFAULT_BANNED_PHRASES)
    assert matched_phrases(
        "This is less about the hype and more about the substance.",
        DEFAULT_BANNED_PHRASES,
    )
    assert matched_phrases("It weaves a rich tapestry of ideas.", DEFAULT_BANNED_PHRASES)


def test_clean_text_has_no_hits():
    assert matched_phrases("The central bank raised rates today.", DEFAULT_BANNED_PHRASES) == []


def test_scan_returns_offending_indices_only():
    segs = [_Seg("clean opening"), _Seg("Let's dive in."), _Seg("also clean")]
    hits = scan_segments(segs, DEFAULT_BANNED_PHRASES)
    assert [h.segment_index for h in hits] == [1]


def test_blueprint_phrases_extend_defaults():
    segs = [_Seg("Synergy was unlocked.")]
    assert scan_segments(segs, DEFAULT_BANNED_PHRASES) == []
    hits = scan_segments(segs, list(DEFAULT_BANNED_PHRASES) + ["synergy"])
    assert len(hits) == 1
    assert "synergy" in hits[0].matched


def test_matches_across_line_breaks():
    # whitespace is collapsed, so a tic split by a newline still matches.
    assert matched_phrases("this is less\nhype and more real", DEFAULT_BANNED_PHRASES)


def test_invalid_regex_phrase_falls_back_to_literal():
    segs = [_Seg("They said (this is great here.")]
    # "(this is great" is an invalid regex (unterminated group); it must still
    # match literally rather than raising.
    hits = scan_segments(segs, ["(this is great"])
    assert len(hits) == 1


def test_empty_banned_list_is_noop():
    assert scan_segments([_Seg("let's dive in")], []) == []
