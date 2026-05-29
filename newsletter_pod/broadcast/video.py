from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)


# X-friendly 1080x1080 square. Same dimensions for feed and reels-style placement.
# 200px tall waveform band sits at the bottom of the frame on top of the cover.
DEFAULT_WIDTH = 1080
DEFAULT_HEIGHT = 1080
WAVEFORM_HEIGHT = 200
WAVEFORM_COLOR = "white"
WAVEFORM_RATE = 25  # frames/sec; matches output fps


class FfmpegUnavailable(RuntimeError):
    pass


class FfmpegFailed(RuntimeError):
    pass


def render_waveform_video(
    *,
    audio_bytes: bytes,
    cover_image_bytes: bytes,
    cover_suffix: str = ".png",
    timeout_seconds: int = 600,
) -> bytes:
    """Render an MP4 with the cover image as background and an audio waveform
    overlaid at the bottom.

    Returns the encoded MP4 bytes. Requires ffmpeg on PATH; raises
    FfmpegUnavailable if it's missing, FfmpegFailed if the encode fails.
    """
    if shutil.which("ffmpeg") is None:
        raise FfmpegUnavailable(
            "ffmpeg is not installed or not on PATH. Install it locally for dev; "
            "the container ships it via the Dockerfile."
        )

    overlay_y = DEFAULT_HEIGHT - WAVEFORM_HEIGHT
    filter_complex = (
        f"[0:v]scale={DEFAULT_WIDTH}:{DEFAULT_HEIGHT}:force_original_aspect_ratio=increase,"
        f"crop={DEFAULT_WIDTH}:{DEFAULT_HEIGHT}[bg];"
        f"[1:a]showwaves=s={DEFAULT_WIDTH}x{WAVEFORM_HEIGHT}:colors={WAVEFORM_COLOR}:"
        f"mode=cline:rate={WAVEFORM_RATE}[wave];"
        f"[bg][wave]overlay=0:{overlay_y}:format=auto[v]"
    )

    with tempfile.TemporaryDirectory(prefix="broadcast_video_") as tmpdir:
        tmp_path = Path(tmpdir)
        cover_path = tmp_path / f"cover{cover_suffix}"
        audio_path = tmp_path / "audio.mp3"
        output_path = tmp_path / "out.mp4"

        cover_path.write_bytes(cover_image_bytes)
        audio_path.write_bytes(audio_bytes)

        cmd = [
            "ffmpeg", "-y",
            "-loop", "1", "-i", str(cover_path),
            "-i", str(audio_path),
            "-filter_complex", filter_complex,
            "-map", "[v]", "-map", "1:a",
            "-c:v", "libx264", "-tune", "stillimage", "-pix_fmt", "yuv420p",
            "-c:a", "aac", "-b:a", "128k", "-ar", "44100",
            "-shortest",
            "-movflags", "+faststart",
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
            raise FfmpegFailed(f"ffmpeg timed out after {timeout_seconds}s") from exc

        if result.returncode != 0:
            # ffmpeg writes everything useful to stderr. Last ~2KB is enough
            # to diagnose without flooding logs.
            tail = (result.stderr or "")[-2048:]
            raise FfmpegFailed(f"ffmpeg exited {result.returncode}: {tail}")

        return output_path.read_bytes()
