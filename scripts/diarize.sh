#!/usr/bin/env bash
# Diarize an audio file using ElevenLabs Scribe and print speaker turns.
#
# Usage:
#   ELEVENLABS_API_KEY=... scripts/diarize.sh path/to/episode.mp3
#
# Output format (one turn per line):
#   [start-end] speaker_id: text
#
# Followed by a summary line:
#   summary: <n> distinct speakers across <m> turns
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

response="$(curl --silent --show-error --fail \
  --request POST \
  --url https://api.elevenlabs.io/v1/speech-to-text \
  --header "xi-api-key: ${ELEVENLABS_API_KEY}" \
  --form "model_id=scribe_v1" \
  --form "diarize=true" \
  --form "file=@${audio}")"

# Group consecutive words by speaker_id into turns.
echo "$response" | jq -r '
  (.words // [])
  | map(select(.type == "word" or .type == null))
  | reduce .[] as $w (
      [];
      if (length == 0) or (.[-1].speaker != ($w.speaker_id // "spk_0"))
      then . + [{
        speaker: ($w.speaker_id // "spk_0"),
        start: $w.start,
        end: $w.end,
        text: $w.text
      }]
      else .[0:-1] + [
        .[-1] + {
          end: $w.end,
          text: ((.[-1].text) + " " + $w.text)
        }
      ]
      end
    )
  | (
      map("[\(.start | tostring)-\(.end | tostring)] \(.speaker): \(.text)")[],
      "---",
      "summary: \(map(.speaker) | unique | length) distinct speakers across \(length) turns"
    )
'
