from __future__ import annotations

import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)


# X-friendly 720x720 square. We dropped from 1080 to 720 because libx264 was
# spending 7+ minutes encoding 2-minute videos at 1080p on Cloud Run's 2 vCPU
# — 720 brings render time under 30 seconds with no visible loss when the
# tweet plays in a feed (X compresses on its end anyway). Reverse this if
# we ever publish to a quality-sensitive target.
DEFAULT_WIDTH = 720
DEFAULT_HEIGHT = 720
WAVEFORM_RATE = 15  # frames/sec — static cover doesn't need higher.


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

    # Static cover scaled to a 720x720 square — no waveform overlay. The
    # showwaves+overlay path was burning 4-5 minutes per 2-min video on
    # 2 vCPU because both filters run pixel-by-pixel per output frame
    # (sequential audio sample reads + per-frame alpha compositing).
    # Visual is now a static branded card behind the audio; we can layer
    # a waveform back in if it turns out to drive engagement on X.
    filter_complex = (
        f"[0:v]scale={DEFAULT_WIDTH}:{DEFAULT_HEIGHT}:force_original_aspect_ratio=increase,"
        f"crop={DEFAULT_WIDTH}:{DEFAULT_HEIGHT}[v]"
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
            # ultrafast preset trades some bitrate efficiency for ~10x encode
            # speed; tune stillimage further drops compute since the cover
            # never changes frame-to-frame. CRF 28 keeps the file under
            # ~15MB for a 2-min clip without visible artifacts.
            "-c:v", "libx264", "-preset", "ultrafast", "-tune", "stillimage",
            "-crf", "28", "-pix_fmt", "yuv420p",
            "-r", str(WAVEFORM_RATE),
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
