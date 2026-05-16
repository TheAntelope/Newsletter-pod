# CLAUDE.md

## Project Context

**ClawCast** (codename `newsletter-pod`) is an iOS app that delivers customized briefing podcasts to each user.

- **Backend:** FastAPI on Cloud Run (`europe-west1`); Firestore for state; GCS for audio; OpenAI for script generation; ElevenLabs (`eleven_multilingual_v2`) for TTS. Secrets in Google Secret Manager.
- **iOS app:** SwiftUI scaffold under [ios/NewsletterPodApp](ios/NewsletterPodApp), generated via XcodeGen, shipped to TestFlight via Codemagic.
- **Generation:** per-user dispatch (`POST /jobs/dispatch-due-users` → `POST /jobs/process-user-podcast`); legacy shared `run-digest` paths are paused.
- **Auth & delivery:** Sign in with Apple; per-user private RSS feed at `/feeds/{token}.xml`; token-gated audio at `/media/{token}/{episode_id}.mp3`.

Roadmap and deferred ideas live in [NEXT_STEPS.md](NEXT_STEPS.md). Live operational notes (incidents, scripts, voice IDs, test aliases, etc.) live in the auto-memory under `.claude/projects/.../memory/`.

## Commands

Local dev (PowerShell):

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -e .[dev]
copy .env.example .env
uvicorn newsletter_pod.asgi:app --reload --port 8000
```

Keep `USE_INMEMORY_ADAPTERS=true` in `.env` for local work — Firestore and GCS are stubbed.

Tests:

```powershell
pytest
```

Useful scripts under [scripts/](scripts/):

- `validate_candidate_sources.py` / `..._round2.py` — RSS health checks before adding to defaults
- `reset_user.py` — reset a single user's state
- `reset_onboarding_state.py` — reset onboarding flags
- `generate_welcome_episode.py` — re-render the bundled welcome MP3
- `render_voice_samples.py` — produce voice preview clips
- `snapshot_weekly_changes.py` — feed the weekly feedback digest job

## Workflow rules

- **Roadmap items** (anything we plan to ship publicly) → [NEXT_STEPS.md](NEXT_STEPS.md) under `## Roadmap`.
- **Deferred ideas** (considered, scoped, chosen not to build now) → [NEXT_STEPS.md](NEXT_STEPS.md) under `## Deferred (not on public roadmap)`. Resurfacing a deferred idea = update its **Revisit trigger** line, don't append a new section. Read this list before proposing anything new.
- **Project state, incidents, conventions, "how X works"** → auto-memory under `.claude/projects/.../memory/`, not CLAUDE.md.
- **Validate new RSS sources end-to-end** before adding them to default catalogs (`scripts/validate_candidate_sources.py`). Unvalidated sources have caused user-facing generation errors in the past.
