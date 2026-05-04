"""One-shot generator for the in-app voice picker samples.

For each voice in voices.yml, renders a short personalized intro via
ElevenLabs and uploads the MP3 to the audio bucket at
`static/voice-samples/<voice_id>.mp3`. The public URL is then printed so
it can be copy/pasted into voices.yml as `preview_url:`.

Usage:
    python scripts/render_voice_samples.py [--bucket NAME] [--dry-run]

Auth:
    - ElevenLabs key pulled from GCP Secret Manager `elevenlabs-api-key`
      (or set ELEVENLABS_API_KEY in the environment to override).
    - Cloud Storage upload uses application-default credentials
      (`gcloud auth application-default login`).

The bucket defaults to the production audio bucket
(`newsletter-pod-audio-newsletter-pod`). Objects are made publicly
readable so AVPlayer on iOS can stream them without signed URLs.
"""
from __future__ import annotations

import argparse
import os
import sys
from dataclasses import dataclass
from pathlib import Path

import requests
import yaml

ELEVENLABS_BASE_URL = "https://api.elevenlabs.io"
ELEVENLABS_MODEL = "eleven_multilingual_v2"
DEFAULT_BUCKET = "newsletter-pod-audio-newsletter-pod"
SAMPLE_PREFIX = "static/voice-samples"

# Personalized intro per voice. Keep these short (~10–15s spoken) so the
# preview plays back near-instantly when the user taps a card.
SAMPLE_SCRIPTS: dict[str, str] = {
    "suMMgpGbVcnihP1CcgFS": (  # Vinnie Chase
        "Hey, I'm Vinnie Chase. I'll be your anchor — clear, "
        "confident, and on-mic with everything you need to hear."
    ),
    "RKCbSROXui75bk1SVpy8": (  # Demi Dreams
        "Hi, I'm Demi Dreams. I'll be your color commentator — warm, "
        "conversational, the friend who breaks down what just happened."
    ),
    "5e3JKXK83vvgQqBcdUol": (  # Chaz Cobalt
        "I'm Chaz Cobalt. Drive-time-DJ vibes — confident, warm, "
        "and a little swaggery. Pick me when you want your morning "
        "to feel like a road trip."
    ),
    "Fxt4GZnlXkUGMtWSYIcm": (  # Rocky Reverb
        "I'm Rocky Reverb. Smooth, low, unhurried — late-night radio "
        "energy. Pick me when you've got time to sit with it."
    ),
    "rPMkKgdwgIwqv4fXgR6N": (  # Marlon Midnight
        "I'm Marlon Midnight. Deep, reflective — the voice you want "
        "when the story matters and the drive is long."
    ),
    "eXpIbVcVbLo8ZJQDlDnl": (  # Lola Lumen
        "Hey, I'm Lola Lumen. Bright, quick-witted, and full of takes. "
        "Pick me when you want the news with a little heat."
    ),
    "GaCzJ7BKVn8XQp1mZYIn": (  # Stella Static
        "Hi, I'm Stella Static. Cool, a little edgy — broadcasting "
        "like pirate radio from somewhere you'd rather be."
    ),
    "0S5oIfi8zOZixuSj8K6n": (  # Ruby Rebel
        "I'm Ruby Rebel. Bold, punchy — I read the headlines like "
        "I mean them. Buckle up."
    ),
}


@dataclass
class Voice:
    id: str
    name: str


def load_voices(voices_yaml_path: Path) -> list[Voice]:
    data = yaml.safe_load(voices_yaml_path.read_text(encoding="utf-8"))
    return [
        Voice(id=item["id"], name=item["name"])
        for item in data.get("voices", [])
        if item.get("enabled", True)
    ]


def resolve_elevenlabs_key() -> str:
    if env := os.environ.get("ELEVENLABS_API_KEY"):
        return env.strip()
    from google.cloud import secretmanager

    client = secretmanager.SecretManagerServiceClient()
    name = "projects/newsletter-pod/secrets/elevenlabs-api-key/versions/latest"
    response = client.access_secret_version(request={"name": name})
    return response.payload.data.decode("utf-8").strip()


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


def upload_public(bucket_name: str, object_name: str, audio: bytes) -> str:
    from google.cloud import storage

    client = storage.Client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(object_name)
    blob.cache_control = "public, max-age=86400"
    blob.upload_from_string(audio, content_type="audio/mpeg")
    blob.make_public()
    return blob.public_url


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bucket", default=DEFAULT_BUCKET)
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Render audio locally to ./voice_samples/ without uploading.",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent.parent
    voices = load_voices(repo_root / "voices.yml")
    if not voices:
        print("No enabled voices in voices.yml", file=sys.stderr)
        return 1

    missing_scripts = [v for v in voices if v.id not in SAMPLE_SCRIPTS]
    if missing_scripts:
        names = ", ".join(f"{v.name} ({v.id})" for v in missing_scripts)
        print(f"ERROR: no SAMPLE_SCRIPTS entry for: {names}", file=sys.stderr)
        return 1

    api_key = resolve_elevenlabs_key()

    if args.dry_run:
        out_dir = repo_root / "voice_samples"
        out_dir.mkdir(exist_ok=True)

    public_urls: dict[str, str] = {}
    for voice in voices:
        text = SAMPLE_SCRIPTS[voice.id]
        print(f"Rendering {voice.name} ({voice.id}, {len(text)} chars)…")
        audio = synthesize(text, voice.id, api_key)
        if args.dry_run:
            path = out_dir / f"{voice.id}.mp3"
            path.write_bytes(audio)
            print(f"  -> wrote {path} ({len(audio):,} bytes)")
            continue
        object_name = f"{SAMPLE_PREFIX}/{voice.id}.mp3"
        url = upload_public(args.bucket, object_name, audio)
        public_urls[voice.id] = url
        print(f"  -> {url} ({len(audio):,} bytes)")

    if args.dry_run:
        print("\nDry run complete. Inspect MP3s in voice_samples/.")
        return 0

    print()
    print("Add these to voices.yml as `preview_url:` per voice:")
    print()
    for voice in voices:
        print(f"  {voice.id}  ({voice.name})")
        print(f"    preview_url: {public_urls[voice.id]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
