# Newsletter Pod

Private Apple Podcasts podcast infrastructure with both:

- the original single-feed daily digest service
- a new multi-tenant weekly iOS control-plane backend

## What this service does

- Ingests multiple newsletter RSS feeds (`sources.yml`)
- Produces one short daily digest episode
- Publishes a private RSS feed at `/feed/{secret_token}.xml`
- Serves audio through token-gated media URLs (`/media/{secret_token}/{episode_id}.mp3`)
- Runs with retry windows from 06:30 to 23:00 (Europe/Copenhagen)
- Sends email alerts if no successful publish by cutoff

## Architecture

- API/runtime: FastAPI on Cloud Run
- State: Firestore (`runs`, `episodes`, `cursors`)
- Audio storage: Cloud Storage
- Audio generation: OpenAI Responses API for structured script generation plus OpenAI Audio Speech for MP3 output
- Secrets: Secret Manager (`sm://...` env references)
- Scheduler: Cloud Scheduler hitting `POST /jobs/run-digest`
- Multi-tenant control plane: Sign in with Apple, per-user feed tokens, per-user schedules, subscriptions, and cost records

## Endpoints

- `GET /health`
- `GET /healthz`
- `POST /jobs/run-digest`
- `GET /feed/{secret_token}.xml`
- `GET /feeds/{token}.xml`
- `GET /media/{secret_token}/{episode_id}.mp3`
- `POST /jobs/dispatch-weekly-podcasts`
- `POST /jobs/process-user-podcast`
- `POST /v1/auth/apple`
- `GET/PATCH /v1/me`
- `GET /v1/sources/catalog`
- `POST /v1/sources/validate`
- `GET/PUT /v1/me/sources`
- `GET/PATCH /v1/me/podcast-config`
- `GET/PATCH /v1/me/schedule`
- `GET /v1/me/feed`
- `POST /v1/billing/app-store/notifications`

## Local development

```bash
python -m venv .venv
. .venv/Scripts/activate
pip install -e .[dev]
copy .env.example .env
```

For local testing, keep `USE_INMEMORY_ADAPTERS=true` in `.env`.

Run:

```bash
uvicorn newsletter_pod.asgi:app --reload --port 8000
```

## Configure sources

Edit `sources.yml`:

```yaml
sources:
  - id: my-source
    name: My Newsletter
    rss_url: https://example.com/rss
    enabled: true
```

## Cloud Run deployment notes

1. Set environment variables from `.env.example`.
2. Set `USE_INMEMORY_ADAPTERS=false`.
3. Configure:
   - `GCS_BUCKET_NAME`
   - `FIRESTORE_COLLECTION_PREFIX`
   - `APP_BASE_URL`
   - `PODCAST_PROVIDER=openai`
   - secret-backed tokens and credentials (`sm://...`)
   - `JOB_TRIGGER_TOKEN` for `POST /jobs/run-digest` when the Cloud Run service is public
4. Grant Cloud Run service account access to Firestore, Storage, and Secret Manager.

## Scheduler setup

Create the retry-window scheduler jobs:

```powershell
./scripts/setup_scheduler.ps1 `
  -ProjectId <gcp-project> `
  -Region <scheduler-region> `
  -ServiceUrl https://<cloud-run-url> `
  -OidcServiceAccount <scheduler-sa@project.iam.gserviceaccount.com> `
  -JobTriggerToken <optional-app-token>
```

This creates:

- Initial trigger at 06:30
- Rapid retries every 5 minutes through 06:59
- Periodic retries every 30 minutes from 07:00 to 23:00

Set `JOB_TRIGGER_TOKEN` to a Secret Manager-backed value for public Cloud Run services so the scheduler sends both OIDC and the app-level bearer token.

After a successful scheduled run:

- the episode is added to the private Apple Podcasts feed
- a publish summary email is sent if SMTP delivery is enabled

## Delivery model

The intended delivery path is:

- Private Apple Podcasts feed as the canonical listening surface
- Email summary after a successful publish with the episode title, feed URL, direct audio URL, and show notes

## Multi-tenant weekly product

The weekly product adds:

- Sign in with Apple session issuance
- One private Apple Podcasts feed per user
- Curated plus custom RSS sources
- Free and paid entitlement limits
- Per-user weekly schedules at 7:00 local time with retries through 11:00
- Per-user generation cost telemetry
- StoreKit/App Store notification integration points

The iOS source scaffold lives in [ios/README.md](./ios/README.md).

## iOS TestFlight deployment

This repo includes a hosted macOS build path for teams without a local Mac:

- `ios/project.yml` generates the Xcode project with XcodeGen
- `codemagic.yaml` builds the iOS app on Codemagic and publishes to TestFlight
- `ios/README.md` contains the App Store Connect, signing, and Codemagic setup checklist

Before running the hosted build, set the production backend URL in `ios/NewsletterPodApp/AppConfiguration.swift` and configure the Apple Developer bundle ID, Sign in with Apple capability, subscriptions, and Codemagic App Store Connect integration.

## Multi-tenant scheduling

The weekly flow is separate from the original daily scheduler:

- `POST /jobs/dispatch-weekly-podcasts` finds due users every 15 minutes
- `POST /jobs/process-user-podcast` processes one user run at a time
- Cloud Tasks is the intended worker queue when configured

Required settings for the weekly flow:

- `SESSION_SIGNING_SECRET`
- `APPLE_CLIENT_ID`
- `WEEKLY_TARGET_LOCAL`
- `WEEKLY_CUTOFF_LOCAL`
- `DISPATCH_INTERVAL_MINUTES`
- free/paid entitlement settings from `.env.example`
- optional Cloud Tasks settings if dispatch should enqueue HTTP tasks

## Apple Podcasts setup

1. Open Apple Podcasts on iPhone.
2. Library -> `...` -> **Follow a Show by URL**.
3. Paste your private feed URL:
   - `https://<your-domain>/feed/<FEED_TOKEN>.xml`

After one-time setup, new episodes appear naturally in your podcast app feed.

## Email summary setup

When `PUBLISH_SUMMARY_EMAIL_ENABLED=true`, the app sends a summary email after a successful daily digest publish.

Required settings:

- `ALERT_EMAIL_TO`
- `ALERT_EMAIL_FROM`
- `SMTP_HOST`
- `SMTP_PORT`
- `SMTP_USERNAME`
- `SMTP_PASSWORD`

This uses the same SMTP transport as alert emails. If you want publish summaries but not failure alerts, keep:

- `PUBLISH_SUMMARY_EMAIL_ENABLED=true`
- `ALERT_EMAIL_ENABLED=false`

## Podcast generation contract

When `PODCAST_PROVIDER=openai`, the app uses:

- `POST /v1/responses` to generate structured `show_notes` plus `audio_segments`
- `POST /v1/audio/speech` once per segment to synthesize MP3 audio

This chunked flow is deliberate: OpenAI speech input is length-limited per request, so longer episodes are synthesized segment-by-segment and concatenated before publishing.

## Podcast UX defaults

The default show shape is:

- Calm analyst tone
- Named primary host plus occasional secondary-host interjections
- Daily dated briefing
- 6-8 minute target runtime
- Shorter 2-4 minute episodes on thin-news days
- Dynamic episode titles in date-plus-main-theme style

You can tune this with:

- `PODCAST_HOST_PRIMARY_NAME`
- `PODCAST_HOST_SECONDARY_NAME`
- `PODCAST_FORMAT`
- `PODCAST_TONE`
- `PODCAST_TARGET_MINUTES`
- `PODCAST_MAX_MINUTES`
- `PODCAST_THIN_DAY_MINUTES`

## Bootstrap behavior

On day 1 for a new source, the app does not fully backfill the entire RSS history.
Instead, it bootstraps from only the latest few entries per source and then advances the cursor.

Default:

- Up to the latest 3 items per source on first run

You can tune this with:

- `PODCAST_BOOTSTRAP_MAX_ITEMS_PER_SOURCE`

## Pre-allowlist mode

When `PODCAST_API_ENABLED=false` or API access is unavailable:

- Ingestion still runs
- No episode is published
- Status email is sent
- Day is marked complete to avoid unnecessary retries

## Testing

```bash
pytest
```
