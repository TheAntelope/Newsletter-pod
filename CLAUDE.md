# CLAUDE.md

## Project Context

**ClawCast** (codename `newsletter-pod`) is a cross-platform app (iOS + Android) that delivers customized briefing podcasts to each user.

- **Backend:** FastAPI on Cloud Run (`europe-west1`); Firestore for state; GCS for audio; OpenAI for script generation; ElevenLabs (`eleven_multilingual_v2`) for TTS. Secrets in Google Secret Manager.
- **Apps:** Flutter is the go-forward cross-platform client (under [flutter/](flutter)), shipping to TestFlight and Google Play via Codemagic (`ios-flutter-testflight`, `android-playstore`). A legacy native iOS app (SwiftUI + XcodeGen, [ios/NewsletterPodApp](ios/NewsletterPodApp), `ios-testflight`) still exists and ships — being replaced by Flutter as a major App Store version (cutover in progress).
- **Generation:** per-user dispatch (`POST /jobs/dispatch-due-users` → `POST /jobs/process-user-podcast`); legacy shared `run-digest` paths are paused.
- **Auth & delivery:** Sign in with Apple and Google (cross-provider email-linking); per-user private RSS feed at `/feeds/{token}.xml`; token-gated audio at `/media/{token}/{episode_id}.mp3`.

Roadmap and deferred ideas live in [NEXT_STEPS.md](NEXT_STEPS.md). Live operational notes (incidents, scripts, voice IDs, test aliases, etc.) live in the auto-memory under `.claude/projects/.../memory/`.

## Values

These govern judgment calls. When they pull in different directions, the tie-breaker resolves it.

- **Simple at the surface.** Default to the least UI that solves the user's actual problem; any added surface has to justify itself. When in doubt, cut UI rather than add it.
- **Robust underneath.** On any user-facing, money, or data path, choose the durable solution over the quick one — fail loudly (no silent fallbacks), bound your queries, handle the error case. For throwaway spikes, optimize for speed instead — but say so explicitly.
- **Tie-breaker:** simple at the surface, robust underneath. Never trade surface simplicity for a fragile shortcut, and never let robustness leak complexity up into the UX.

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

## Git workflow

This repo frequently has **concurrent/parallel sessions** running against the same working tree. To avoid clobbering each other's work:

- **Never `git stash`** — it has swept up another session's uncommitted work before, forcing lengthy recovery.
- **Never `git add -A` / `git add .`** — stage each file individually, and stage only the files relevant to the current task.
- **Check `git status` before staging.** If you see uncommitted changes you didn't make this session, STOP and surface them — don't assume they're yours.
- **Re-read changed view files immediately before committing.** A linter can silently revert SwiftUI/Dart edits between Write and commit (this is how the "Coming in your next pod" card failed to ship once).
- **Analyze/test before committing.** Dart → `cd flutter && flutter analyze`; Python → relevant `pytest`. Don't commit on a red analyzer (watch for const-constructor and Android build-config errors: JVM target, core library desugaring).
- **Design tokens are generated — never hand-edit the outputs.** The source of truth is the `design-tokens/` git submodule (`clawcast-tokens` repo); `tokens.json` there builds `DesignTokens.swift` (copied to `ios/NewsletterPodApp/`), `design_tokens.dart`, and `tokens.css`. Edit `tokens.json` + rebuild (`cd design-tokens && npm run build`), don't touch the generated files. CI fails the build if the committed copies are stale.
- Commit/push to `main` only when asked. The `/ship` skill encodes this full loop.
