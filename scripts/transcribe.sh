#!/usr/bin/env bash
# Transcribe an audio file using ElevenLabs Scribe.
#
# Usage:
#   ELEVENLABS_API_KEY=... scripts/transcribe.sh path/to/episode.mp3
#
# Prints the transcript text to stdout.
set -euo pipefail

if [[ $# -lt 1 ]]; then
  echo "usage: $0 <audio-file>" >&2
  exit 64
fi

if [[ -z "${ELEVENLABS_API_KEY:-}" ]]; then
  echo "ELEVENLABS_API_KEY is required" >&2
  exit 78
fi

audio="$1"
if [[ ! -f "$audio" ]]; then
  echo "audio file not found: $audio" >&2
  exit 66
fi

curl --silent --show-error --fail \
  --request POST \
  --url https://api.elevenlabs.io/v1/speech-to-text \
  --header "xi-api-key: ${ELEVENLABS_API_KEY}" \
  --form "model_id=scribe_v1" \
  --form "file=@${audio}" \
  | jq -r '.text'
