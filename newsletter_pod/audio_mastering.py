"""Post-render audio mastering for multi-segment TTS episodes.

Each spoken segment is synthesized as an independent TTS call (see
``podcast_api._synthesize_speech``), so the per-segment MP3s arrive at whatever
loudness the provider happened to render — different ElevenLabs voices land at
different perceived levels, the OpenAI fallback differs again, and the legacy
``_concat_mp3_chunks`` byte-joins them with no level matching. The result is the
"hosts aren't at the same volume / don't sound like the same room" complaint.

This module re-assembles the segments through ffmpeg instead of byte-joining:
every segment is loudness-normalized to one shared target (EBU R128 / LUFS) and
the segments are stitched with short crossfades, then encoded once to a uniform
MP3. That equalizes host-to-host volume, smooths the abrupt segment cuts, and
incidentally reconciles any mixed-provider/sample-rate chunks into one format.

It is deliberately a drop-in alternative to ``_concat_mp3_chunks``: the caller
gates it behind a flag and falls back to the raw byte-concat on ANY failure, so
a missing/blowing-up ffmpeg can never break episode generation. ffmpeg ships in
the container image (see Dockerfile); locally it may be absent, which raises
``MasteringUnavailable`` and triggers the caller's fallback.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

# EBU R128 / podcast-delivery defaults. Integrated loudness -16 LUFS is the
# common streaming/podcast target (broadcast is -23); true-peak -1.5 dBTP and
# loudness range 11 are loudnorm's documented sane defaults. Overridable via
# env so the values can be tuned during the trial without a code change.
DEFAULT_TARGET_LUFS = -16.0
DEFAULT_TRUE_PEAK_DBTP = -1.5
DEFAULT_LOUDNESS_RANGE = 11.0
# Crossfade at each segment join. 40 ms de-clicks the hard byte-cut without an
# audible blend; long enough to remove the "two separate takes" seam, short
# enough not to swallow speech onsets.
DEFAULT_CROSSFADE_MS = 40

# Uniform output format. ElevenLabs' default (mp3_44100_128) and OpenAI TTS are
# both mono; pinning these makes the master format-consistent regardless of
# which provider rendered any given segment.
_OUTPUT_SAMPLE_RATE = 44100
_OUTPUT_CHANNELS = 1
_OUTPUT_BITRATE = "128k"


class MasteringError(RuntimeError):
    """Mastering could not produce output; caller should fall back to concat."""


class MasteringUnavailable(MasteringError):
    """ffmpeg is not installed / not on PATH."""


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def master_mp3_segments(
    chunks: list[bytes],
    *,
    target_lufs: float = DEFAULT_TARGET_LUFS,
    crossfade_ms: int = DEFAULT_CROSSFADE_MS,
    timeout_seconds: int = 300,
) -> bytes:
    """Loudness-normalize each MP3 segment to ``target_lufs`` and stitch them
    with ``crossfade_ms`` crossfades into one uniform MP3.

    Raises ``MasteringUnavailable`` if ffmpeg is missing and ``MasteringError``
    on any ffmpeg failure/timeout, so the caller can fall back to the raw
    byte-concat. Empty/whitespace chunks are dropped; a single non-empty chunk
    is still normalized (no crossfade needed).
    """
    if shutil.which("ffmpeg") is None:
        raise MasteringUnavailable(
            "ffmpeg is not installed or not on PATH; cannot master audio"
        )

    usable = [c for c in chunks if c]
    if not usable:
        raise MasteringError("No non-empty audio chunks to master")

    crossfade_seconds = max(0.0, crossfade_ms / 1000.0)

    with tempfile.TemporaryDirectory(prefix="pod_master_") as tmpdir:
        tmp_path = Path(tmpdir)
        input_args: list[str] = []
        for idx, chunk in enumerate(usable):
            seg_path = tmp_path / f"seg_{idx}.mp3"
            seg_path.write_bytes(chunk)
            input_args += ["-i", str(seg_path)]

        output_path = tmp_path / "master.mp3"
        filter_complex, final_label = _build_filter_complex(
            count=len(usable),
            target_lufs=target_lufs,
            crossfade_seconds=crossfade_seconds,
        )

        cmd = ["ffmpeg", "-y", *input_args]
        if filter_complex:
            cmd += ["-filter_complex", filter_complex, "-map", final_label]
        else:
            # Single segment, no filtergraph labels — map the lone input.
            cmd += ["-map", "0:a"]
        cmd += [
            "-c:a", "libmp3lame",
            "-b:a", _OUTPUT_BITRATE,
            "-ar", str(_OUTPUT_SAMPLE_RATE),
            "-ac", str(_OUTPUT_CHANNELS),
            str(output_path),
        ]

        try:
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )
        except subprocess.TimeoutExpired as exc:
            raise MasteringError(
                f"ffmpeg mastering timed out after {timeout_seconds}s"
            ) from exc

        if result.returncode != 0:
            tail = (result.stderr or "")[-2048:]
            raise MasteringError(f"ffmpeg mastering exited {result.returncode}: {tail}")

        data = output_path.read_bytes()
        if not data:
            raise MasteringError("ffmpeg produced an empty master")
        return data


def splice_music(
    speech_mp3: bytes,
    *,
    intro_mp3: bytes | None = None,
    outro_mp3: bytes | None = None,
    intro_bed_seconds: float = 4.0,
    music_gain_db: float = -18.0,
    fade_ms: int = 800,
    timeout_seconds: int = 300,
) -> bytes:
    """Splice an intro and/or outro music bed onto a finished speech MP3.

    v1 keeps this cheap on Cloud Run's 2 vCPU: rather than full-episode sidechain
    ducking, the intro plays alone for ``intro_bed_seconds`` then mixes (at
    ``music_gain_db``) under the opening while fading out, and the outro
    crossfades in under the tail. Any absent side is skipped; if neither is
    supplied the input is returned unchanged.

    Raises ``MasteringUnavailable`` if ffmpeg is missing and ``MasteringError``
    on any ffmpeg failure/timeout, so the caller can fall back to the un-music'd
    audio.
    """
    if not intro_mp3 and not outro_mp3:
        return speech_mp3
    if not speech_mp3:
        raise MasteringError("No speech audio to splice music onto")
    if shutil.which("ffmpeg") is None:
        raise MasteringUnavailable(
            "ffmpeg is not installed or not on PATH; cannot splice music"
        )

    with tempfile.TemporaryDirectory(prefix="pod_music_") as tmpdir:
        tmp_path = Path(tmpdir)
        # Fixed input order: speech first, then intro (if any), then outro (if
        # any) — _build_music_filter assumes exactly this ordering.
        speech_path = tmp_path / "speech.mp3"
        speech_path.write_bytes(speech_mp3)
        input_args = ["-i", str(speech_path)]
        if intro_mp3:
            intro_path = tmp_path / "intro.mp3"
            intro_path.write_bytes(intro_mp3)
            input_args += ["-i", str(intro_path)]
        if outro_mp3:
            outro_path = tmp_path / "outro.mp3"
            outro_path.write_bytes(outro_mp3)
            input_args += ["-i", str(outro_path)]

        filter_complex, final_label = _build_music_filter(
            has_intro=bool(intro_mp3),
            has_outro=bool(outro_mp3),
            intro_bed_seconds=max(0.0, intro_bed_seconds),
            music_gain_db=music_gain_db,
            fade_ms=max(0, fade_ms),
        )

        output_path = tmp_path / "with_music.mp3"
        cmd = [
            "ffmpeg", "-y", *input_args,
            "-filter_complex", filter_complex,
            "-map", final_label,
            "-c:a", "libmp3lame",
            "-b:a", _OUTPUT_BITRATE,
            "-ar", str(_OUTPUT_SAMPLE_RATE),
            "-ac", str(_OUTPUT_CHANNELS),
            str(output_path),
        ]

        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=timeout_seconds
            )
        except subprocess.TimeoutExpired as exc:
            raise MasteringError(
                f"ffmpeg music splice timed out after {timeout_seconds}s"
            ) from exc

        if result.returncode != 0:
            tail = (result.stderr or "")[-2048:]
            raise MasteringError(f"ffmpeg music splice exited {result.returncode}: {tail}")

        data = output_path.read_bytes()
        if not data:
            raise MasteringError("ffmpeg produced an empty music-spliced file")
        return data


def _build_music_filter(
    *,
    has_intro: bool,
    has_outro: bool,
    intro_bed_seconds: float,
    music_gain_db: float,
    fade_ms: int,
) -> tuple[str, str]:
    """Build the ``(filter_complex, final_label)`` for the music splice.

    Input order is [0]=speech, [1]=intro (if present), [2 or 1]=outro (if
    present). Pure/deterministic so it can be unit-tested without ffmpeg.
    """
    if not has_intro and not has_outro:
        return "", ""

    fade_s = fade_ms / 1000.0
    bed_ms = int(round(intro_bed_seconds * 1000))
    gain = f"{music_gain_db:g}dB"
    parts: list[str] = []

    intro_index = 1 if has_intro else None
    outro_index = (2 if has_intro else 1) if has_outro else None

    if has_intro:
        # Intro at reduced gain, fading out once the voice comes in; speech is
        # delayed so the intro plays alone for the bed, then they overlap.
        parts.append(
            f"[{intro_index}:a]volume={gain},"
            f"afade=t=out:st={intro_bed_seconds:g}:d={fade_s:g}[introbed]"
        )
        parts.append(f"[0:a]adelay={bed_ms}:all=1[spd]")
        # normalize=0 keeps the speech at full level (default amix halves it).
        body_label = "[body]" if has_outro else "[out]"
        parts.append(
            f"[introbed][spd]amix=inputs=2:normalize=0:duration=longest{body_label}"
        )
        body_src = body_label
    else:
        body_src = "[0:a]"

    if has_outro:
        parts.append(f"[{outro_index}:a]volume={gain}[outrobed]")
        parts.append(
            f"{body_src}[outrobed]acrossfade=d={fade_s:g}:c1=tri:c2=tri[out]"
        )

    return ";".join(parts), "[out]"


def _build_filter_complex(
    *,
    count: int,
    target_lufs: float,
    crossfade_seconds: float,
) -> tuple[str, str]:
    """Return ``(filter_complex, final_label)`` for ``count`` inputs.

    Each input is loudnorm'd to the shared target, then the normalized streams
    are folded together with ``acrossfade``. A single input is still loudnorm'd
    (no crossfade). ``count`` is always >= 1 here (the caller drops empty
    chunks and errors on none), so a non-empty graph is always returned.
    """
    norm = (
        f"loudnorm=I={target_lufs:g}:"
        f"TP={DEFAULT_TRUE_PEAK_DBTP:g}:LRA={DEFAULT_LOUDNESS_RANGE:g}"
    )

    if count == 1:
        return f"[0:a]{norm}[out]", "[out]"

    parts = [f"[{i}:a]{norm}[n{i}]" for i in range(count)]

    # Fold-left the normalized streams with acrossfade. Triangular fade curves
    # keep constant power across the join so the crossfade itself adds no dip.
    prev = "[n0]"
    for i in range(1, count):
        out_label = "[out]" if i == count - 1 else f"[x{i}]"
        parts.append(
            f"{prev}[n{i}]acrossfade=d={crossfade_seconds:g}:c1=tri:c2=tri{out_label}"
        )
        prev = out_label

    return ";".join(parts), "[out]"
