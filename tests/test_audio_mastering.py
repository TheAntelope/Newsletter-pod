from __future__ import annotations

import pytest

from newsletter_pod import audio_mastering
from newsletter_pod.audio_mastering import (
    MasteringError,
    MasteringUnavailable,
    _build_filter_complex,
    ffmpeg_available,
    master_mp3_segments,
)
from newsletter_pod.podcast_api import PodcastApiClient


def _client(**overrides) -> PodcastApiClient:
    base = dict(
        enabled=True,
        provider="openai",
        base_url="https://api.openai.com",
        api_key="test-key",
        timeout_seconds=60,
        poll_seconds=5,
        text_model="gpt-5.4-mini",
        tts_model="gpt-4o-mini-tts",
        tts_voice="alloy",
    )
    base.update(overrides)
    return PodcastApiClient(**base)


# --- filter graph construction (pure Python, no ffmpeg) -----------------------


def test_filter_complex_single_segment_normalizes_without_crossfade():
    graph, label = _build_filter_complex(count=1, target_lufs=-16.0, crossfade_seconds=0.04)
    assert label == "[out]"
    assert graph == "[0:a]loudnorm=I=-16:TP=-1.5:LRA=11[out]"
    assert "acrossfade" not in graph


def test_filter_complex_two_segments_chains_one_crossfade():
    graph, label = _build_filter_complex(count=2, target_lufs=-16.0, crossfade_seconds=0.04)
    assert label == "[out]"
    # Each input loudnorm'd, then a single acrossfade producing [out].
    assert "[0:a]loudnorm=I=-16:TP=-1.5:LRA=11[n0]" in graph
    assert "[1:a]loudnorm=I=-16:TP=-1.5:LRA=11[n1]" in graph
    assert "[n0][n1]acrossfade=d=0.04:c1=tri:c2=tri[out]" in graph
    assert graph.count("acrossfade") == 1


def test_filter_complex_three_segments_uses_intermediate_labels():
    graph, label = _build_filter_complex(count=3, target_lufs=-14.0, crossfade_seconds=0.05)
    assert label == "[out]"
    assert graph.count("acrossfade") == 2
    # First join writes an intermediate [x1], final join writes [out].
    assert "[n0][n1]acrossfade=d=0.05:c1=tri:c2=tri[x1]" in graph
    assert "[x1][n2]acrossfade=d=0.05:c1=tri:c2=tri[out]" in graph
    # Target LUFS flows through.
    assert "loudnorm=I=-14:" in graph


# --- master_mp3_segments guard rails ------------------------------------------


def test_master_raises_unavailable_when_ffmpeg_missing(monkeypatch):
    monkeypatch.setattr(audio_mastering.shutil, "which", lambda _: None)
    with pytest.raises(MasteringUnavailable):
        master_mp3_segments([b"\xff\xfb\x90\x00data"])


def test_master_raises_when_no_usable_chunks(monkeypatch):
    # ffmpeg "present" so we get past the availability check to the empty guard.
    monkeypatch.setattr(audio_mastering.shutil, "which", lambda _: "/usr/bin/ffmpeg")
    with pytest.raises(MasteringError):
        master_mp3_segments([b"", b""])


# --- _assemble_audio routing on the client ------------------------------------


def test_assemble_audio_disabled_uses_raw_concat():
    # Two MP3-shaped chunks; with mastering off the result is the byte-concat
    # (no ffmpeg invoked). Non-MP3 chunks pass through _strip_mp3_container
    # unchanged, so the join is a plain concat.
    client = _client(audio_mastering_enabled=False)
    out = client._assemble_audio([b"alpha", b"beta"])
    assert out == b"alphabeta"


def test_assemble_audio_falls_back_to_concat_on_mastering_error(monkeypatch):
    client = _client(audio_mastering_enabled=True)

    def boom(*args, **kwargs):
        raise MasteringError("ffmpeg blew up")

    monkeypatch.setattr("newsletter_pod.podcast_api.master_mp3_segments", boom)
    out = client._assemble_audio([b"alpha", b"beta"])
    # Generation must never break: fall back to the legacy concat.
    assert out == b"alphabeta"


def test_assemble_audio_uses_mastered_bytes_when_enabled(monkeypatch):
    client = _client(
        audio_mastering_enabled=True, audio_target_lufs=-15.0, audio_crossfade_ms=30
    )
    seen = {}

    def fake_master(chunks, *, target_lufs, crossfade_ms, **kwargs):
        seen["chunks"] = chunks
        seen["target_lufs"] = target_lufs
        seen["crossfade_ms"] = crossfade_ms
        return b"MASTERED"

    monkeypatch.setattr("newsletter_pod.podcast_api.master_mp3_segments", fake_master)
    out = client._assemble_audio([b"alpha", b"beta"])
    assert out == b"MASTERED"
    # The client's configured target/crossfade are threaded through.
    assert seen["chunks"] == [b"alpha", b"beta"]
    assert seen["target_lufs"] == -15.0
    assert seen["crossfade_ms"] == 30


def test_assemble_audio_empty_list_skips_mastering(monkeypatch):
    client = _client(audio_mastering_enabled=True)

    def should_not_run(*args, **kwargs):
        raise AssertionError("master_mp3_segments should not run on empty input")

    monkeypatch.setattr("newsletter_pod.podcast_api.master_mp3_segments", should_not_run)
    assert client._assemble_audio([]) == b""


# --- real ffmpeg integration (skipped where ffmpeg is absent) -----------------


def _mpeg1_l3_frame() -> bytes:
    """A single valid MPEG-1 Layer III frame, 128 kbps / 44.1 kHz (length 417)."""
    frame_len = (144 * 128000) // 44100  # 417
    header = bytes([0xFF, 0xFB, 0x90, 0x00])
    return header + bytes(frame_len - len(header))


@pytest.mark.skipif(not ffmpeg_available(), reason="ffmpeg not installed on this host")
def test_master_real_ffmpeg_produces_playable_mp3():
    # ~1s of (silent) audio per segment so loudnorm/acrossfade have material.
    one_second_frames = round(44100 / 1152)  # frames per second at MPEG-1 L3
    seg = b"".join(_mpeg1_l3_frame() for _ in range(one_second_frames))

    mastered = master_mp3_segments([seg, seg], target_lufs=-16.0, crossfade_ms=40)

    assert isinstance(mastered, bytes) and len(mastered) > 0
    # Output is a real MP3 with decodable frames.
    from newsletter_pod.podcast_api import _measure_mp3_duration_seconds

    assert _measure_mp3_duration_seconds(mastered) is not None
