# Newsletter Pod (mycast)

Multi-tenant private podcast backend powering the **mycast** iOS app. Each user gets their own briefing podcast generated from their chosen RSS sources, on their chosen schedule, in their chosen voice.

## What this service does

- Sign in with Apple → per-user account, subscription, and feed token
- Per-user RSS source catalog (curated + custom) with free/paid entitlements
- Per-user delivery schedule (any subset of weekdays at a local target time)
- Generates a personal briefing episode using OpenAI for the script and ElevenLabs for TTS
- Publishes a private RSS feed per user at `/feeds/{token}.xml`
- Serves audio through token-gated URLs at `/media/{token}/{episode_id}.mp3`

## Architecture

- **API/runtime:** FastAPI on Cloud Run (`europe-west1`)
- **State:** Firestore (per-user collections under `FIRESTORE_COLLECTION_PREFIX`)
- **Audio storage:** Google Cloud Storage
- **Script generation:** OpenAI Responses API → structured `audio_segments` + `show_notes`
- **Speech synthesis:** ElevenLabs `eleven_multilingual_v2` with two selectable voices
- **Secrets:** Google Secret Manager (`sm://...` references in `.env`, native `--set-secrets` on Cloud Run)
- **Dispatch:** `POST /jobs/dispatch-due-users` enumerates due users; `POST /jobs/process-user-podcast` runs one user at a time

## Endpoints

Job endpoints (require `X-Job-Trigger-Token` or OIDC bearer):
- `POST /jobs/dispatch-due-users`
- `POST /jobs/process-user-podcast`

User-facing API (require Apple session bearer token):
- `POST /v1/auth/apple`
- `GET/PATCH /v1/me`
- `GET /v1/sources/catalog`
- `POST /v1/sources/validate`
- `GET/PUT /v1/me/sources`
- `GET/PATCH /v1/me/podcast-config`
- `GET/PATCH /v1/me/schedule`
- `GET /v1/me/feed`
- `POST /v1/me/generate`
- `POST /v1/billing/app-store/notifications`

Public:
- `GET /healthz`, `GET /health`
- `GET /legal/terms`, `GET /legal/privacy`
- `GET /feeds/{token}.xml` (private per-user feed; the token *is* the auth)
- `GET /media/{token}/{episode_id}.mp3`

## Local development

```bash
python -m venv .venv
. .venv/Scripts/activate
pip install -e .[dev]
copy .env.example .env
```

Keep `USE_INMEMORY_ADAPTERS=true` in `.env` for local work — Firestore and GCS are stubbed.

```bash
uvicorn newsletter_pod.asgi:app --reload --port 8000
```

## Cloud Run deployment

Required environment for prod:

- `USE_INMEMORY_ADAPTERS=false`
- `GOOGLE_CLOUD_PROJECT`, `GCS_BUCKET_NAME`, `FIRESTORE_COLLECTION_PREFIX`
- `APP_BASE_URL` (your Cloud Run URL)
- `APPLE_CLIENT_ID` (your iOS bundle id)
- `SESSION_SIGNING_SECRET`, `JOB_TRIGGER_TOKEN` (`sm://...`)
- `PODCAST_API_ENABLED=true`, `PODCAST_API_KEY=sm://openai-api-key`
- `PODCAST_TTS_PROVIDER=elevenlabs`, `ELEVENLABS_API_KEY=sm://elevenlabs-api-key`

The Cloud Run service account needs `roles/datastore.user`, GCS object access on the audio bucket, and `roles/secretmanager.secretAccessor`.

## Voice configuration

Two ElevenLabs voices are exposed in the iOS app, each addressable by ElevenLabs voice ID:

- Demi Dreams (`ELEVENLABS_VOICE_PRIMARY_ID`, default)
- Vinnie Chase (`ELEVENLABS_VOICE_SECONDARY_ID`)

Override IDs via env vars; user selection is stored on `PodcastProfileRecord.voice_id`.

## iOS app

The SwiftUI scaffold lives in [ios/](./ios/) and builds via Codemagic to TestFlight. See [ios/README.md](./ios/README.md) for the App Store Connect, signing, and Codemagic setup checklist.

## Testing

```bash
pytest
```
