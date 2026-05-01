"""One-shot generator for the bundled welcome podcast.

Renders the two-host welcome script via ElevenLabs (Vinnie + Demi voices) and
writes a single MP3 to ./welcome_v1.mp3. Mirrors the segment-by-segment
synthesis the runtime uses in `podcast_api.py:_synthesize_speech` so the result
sounds like every other ClawCast episode.

Usage:
    export ELEVENLABS_API_KEY=...
    python scripts/generate_welcome_episode.py [--output welcome_v1.mp3]

Then upload the resulting MP3 to GCS at the configured `WELCOME_EPISODE_OBJECT_NAME`
key (e.g. `static/welcome-v1.mp3`) and set the matching env vars in your deployment:

    WELCOME_EPISODE_OBJECT_NAME=static/welcome-v1.mp3
    WELCOME_EPISODE_SIZE_BYTES=<the printed size>
    WELCOME_EPISODE_DURATION_SECONDS=<the printed duration>
    WELCOME_EPISODE_VERSION=v1
"""
from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass

import requests

ELEVENLABS_BASE_URL = "https://api.elevenlabs.io"
ELEVENLABS_MODEL = "eleven_multilingual_v2"

# Voice IDs match newsletter_pod/config.py defaults.
VOICE_VINNIE = os.environ.get("ELEVENLABS_VOICE_PRIMARY_ID", "suMMgpGbVcnihP1CcgFS")
VOICE_DEMI = os.environ.get("ELEVENLABS_VOICE_SECONDARY_ID", "RKCbSROXui75bk1SVpy8")


@dataclass
class Line:
    speaker: str  # "Vinnie" or "Demi"
    text: str


# Two-host welcome script. ~2:30 at conversational pace.
SCRIPT: list[Line] = [
    Line("Vinnie", "Hey there, and welcome to ClawCast. I'm Vinnie."),
    Line("Demi", "And I'm Demi. We're really glad you're here."),
    Line(
        "Vinnie",
        "So if this is the very first thing you're hearing from us — congrats, "
        "you found us early. Let us tell you what this whole thing is about.",
    ),
    Line(
        "Demi",
        "ClawCast turns the newsletters and feeds you actually want to read into "
        "a short, custom podcast. Just for you. Hosted by us.",
    ),
    Line(
        "Vinnie",
        "The way it works is pretty simple. You tell us what you're into — news, "
        "tech, sports, romantasy, whatever your thing is — and we pull from those "
        "sources every day or every week, depending on what you set up.",
    ),
    Line(
        "Demi",
        "Then we read through it, pick out the stuff that actually matters, and "
        "turn it into a quick episode. You'll hear it land in this exact podcast feed.",
    ),
    Line(
        "Vinnie",
        "And here's a fun trick — every ClawCast user gets a private email address. "
        "So if you subscribe to a newsletter that lands in your inbox, you can just "
        "forward it to your ClawCast address and we'll fold it into your next episode.",
    ),
    Line(
        "Demi",
        "It works with Substack, Beehiiv, your favorite indie writer — pretty much "
        "anything that arrives by email.",
    ),
    Line(
        "Vinnie",
        "The whole point is: you spend less time scrolling through a hundred tabs, "
        "and more time actually hearing the stuff you care about.",
    ),
    Line(
        "Demi",
        "And because it's a podcast, you can listen on a walk. In the car. At the gym. "
        "Doing the dishes. You know — whenever you'd usually be half-reading something on your phone.",
    ),
    Line(
        "Vinnie",
        "So go ahead and finish setting up your show. Pick your topics, pick your voices, "
        "pick your delivery schedule — and we'll be back in your feed real soon with your first real episode.",
    ),
    Line("Demi", "Thanks for being here. We're excited to have you."),
    Line("Vinnie", "Talk to you soon."),
    # Final line spoken by Demi (the warm "Welcome to the ClawCast" sign-off).
    Line("Demi", "Welcome to the ClawCast."),
]


def voice_for(speaker: str) -> str:
    s = speaker.strip().lower()
    if s == "vinnie":
        return VOICE_VINNIE
    if s == "demi":
        return VOICE_DEMI
    raise ValueError(f"unknown speaker {speaker!r}")


def synthesize(text: str, voice_id: str, api_key: str) -> bytes:
    url = f"{ELEVENLABS_BASE_URL}/v1/text-to-speech/{voice_id}"
    headers = {
        "xi-api-key": api_key,
        "Content-Type": "application/json",
        "Accept": "audio/mpeg",
    }
    payload = {"text": text, "model_id": ELEVENLABS_MODEL}
    resp = requests.post(url, json=payload, headers=headers, timeout=120)
    resp.raise_for_status()
    return resp.content


def estimate_duration_seconds(text: str) -> float:
    """Rough wpm-based estimate so we can print a sanity-check duration without
    decoding MP3 frames. 155 wpm ~= conversational two-host pace."""
    words = len(text.split())
    return words / 155.0 * 60.0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default="welcome_v1.mp3", help="local output path (default: welcome_v1.mp3)")
    args = parser.parse_args()

    api_key = os.environ.get("ELEVENLABS_API_KEY")
    if not api_key:
        print("ERROR: ELEVENLABS_API_KEY is not set", file=sys.stderr)
        return 1

    print(f"Rendering {len(SCRIPT)} segments...")
    chunks: list[bytes] = []
    estimated_seconds = 0.0
    for i, line in enumerate(SCRIPT, 1):
        voice_id = voice_for(line.speaker)
        print(f"  [{i:2d}/{len(SCRIPT)}] {line.speaker:6s} ({len(line.text):3d} chars)")
        chunks.append(synthesize(line.text, voice_id, api_key))
        estimated_seconds += estimate_duration_seconds(line.text)

    audio_bytes = b"".join(chunks)
    with open(args.output, "wb") as f:
        f.write(audio_bytes)

    size = len(audio_bytes)
    duration = int(round(estimated_seconds))
    print()
    print(f"Wrote {args.output}")
    print(f"  size:               {size:,} bytes")
    print(f"  estimated duration: ~{duration} seconds (~{duration / 60:.1f} min)")
    print()
    print("Next steps:")
    print(f"  1. Listen to {args.output} and confirm it sounds right.")
    print(f"  2. Upload to GCS, e.g.:")
    print(f"       gsutil cp {args.output} gs://<your-bucket>/static/welcome-v1.mp3")
    print(f"  3. Set deployment env vars:")
    print(f"       WELCOME_EPISODE_OBJECT_NAME=static/welcome-v1.mp3")
    print(f"       WELCOME_EPISODE_SIZE_BYTES={size}")
    print(f"       WELCOME_EPISODE_DURATION_SECONDS=<actual duration once you've measured>")
    print(f"       WELCOME_EPISODE_VERSION=v1")
    return 0


if __name__ == "__main__":
    sys.exit(main())
