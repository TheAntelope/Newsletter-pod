# Flutter Run-Status Polling / Generation-Progress — Port Plan

Status: planned (port in progress on `feat/flutter-run-polling`).
Source: branch `feature/phase2-flutter-android` (the iOS-parity subsystem stripped out during the 2026-06-21 branch drain).

## Summary

Today the Flutter app's `generateNow` is **fire-and-forget**: it flips a `_generating`
flag, kicks off the run, and never learns what happened — the progress bar can sit at
95% forever even if the run failed, hit quota, or finished while the app was
backgrounded. This subsystem makes the app actively track each generation run to a
terminal status, show the real outcome (a finished pod, a "no episode this time"
notice, or a timeout message), auto-refresh the dashboard when a run completes, and
resume tracking after the app returns to the foreground. iOS already has the
equivalent.

## Already on main (reused — no work)

- `ApiClient.fetchRun(token, runId)` → `GET /v1/me/runs/{id}` (the HTTP method).
- `RunStatusEnvelope` (`run` + optional `episode`), `UserRunDto`, `UserEpisodeDto`
  models (+ generated `.g.dart`).
- `GenerationProgressBar(startedAt:)` — already self-paces against a persistent start time.
- `root_view.dart` already mixes in `WidgetsBindingObserver` with a
  `didChangeAppLifecycleState` resumed branch.
- `home_screen.dart` already has `_GenerationBanner` + the `if (app.isGenerating)` block.
- Backend `GET /v1/me/runs/{run_id}` (`main.py` `get_user_run` → `control_plane.get_user_run_status`).
- The **stale-run reaper** (wired 2026-06-21) guarantees every run reaches a terminal
  status, so the poll loop and the attempt ceiling can never wedge the UI permanently.

## Components to port (net-new)

| File | Pieces | Depends on |
|---|---|---|
| `data/app_repository.dart` | `fetchRun(runId)` interface method | `RunStatusEnvelope` |
| `data/api_app_repository.dart` | `fetchRun` override → `_client.fetchRun` | `ApiClient.fetchRun` (on main) |
| `data/fake_app_repository.dart` | `fetchRun` override → terminal `published` demo run | `RunStatusEnvelope`, `UserRunDto` |
| `state/app_state.dart` | ctor params `pollInterval`(3s)/`pollMaxAttempts`(120); fields `_generationStartedAt`, `_runNotice`, `_pollTimer`, `_pollRunId`, `_pollAttempts`, `_terminalRunStatuses`; methods `_startPolling/_stopPolling/_pollTick/_timeoutPolling/_finishRun/_friendlyRunOutcome/clearRunNotice/resumePollingIfNeeded/debugDropPollTimer`; rewritten `generateNow`; `signOut`/`dispose` cleanup; `AppScope.maybeOf` | `fetchRun`, `RunStatusEnvelope` |
| `screens/root_view.dart` | resume hook: `AppScope.maybeOf(context)?.resumePollingIfNeeded()` | `AppScope.maybeOf` |
| `screens/home_screen.dart` | `_wasGenerating` + `_onAppStateChanged` finish-refresh listener; pass `startedAt` to `_GenerationBanner`; `_RunNoticeBanner` + the `else if (app.runNotice != null)` branch | `app.generationStartedAt`, `app.runNotice` |
| `test/state/app_state_resume_test.dart` | the 3 resume tests + fakes (verbatim) | the test-only seams above |

The **data-layer trio is the load-bearing trap**: the interface method + both impls must
land together with the call site, or HEAD won't compile — this exact omission was the
stranded `c6ad9fd` ("commit fetchRun interface + fake impl to unbreak the build").

## Backend contract

- `GET /v1/me/runs/{run_id}` → `{"run": <run>, "episode": <episode>?}` — matches
  `RunStatusEnvelope`; no backend change required.
- Terminal statuses: `published`, `skipped`, `no_content`, `pre_access`, `failed`.
  Non-terminal: `queued`, `in_progress`, `pending`. `_terminalRunStatuses` covers all
  terminal values and keeps polling on the rest.

## Wiring steps

1. Data layer (interface + both impls) — compiles standalone, no behavior change.
2. `app_state.dart` — defaulted ctor params (existing `AppState(repo)` call sites
   unaffected); polling state machine; rewritten `generateNow`; `signOut`/`dispose`
   cleanup; `AppScope.maybeOf`.
3. `root_view.dart` — add the resume hook to the existing resumed branch.
4. `home_screen.dart` — finish-refresh listener; `startedAt` into `_GenerationBanner`;
   `_RunNoticeBanner`.
5. Bring the resume test; add a `_RunNoticeBanner` widget test.
6. `flutter analyze` clean + `flutter test` green.

## Decisions (this round)

1. **Web (`kIsWeb`) out of scope** — exclude the web-support hunks that ride along in the
   branch's home_screen diff. iOS/Android only.
2. **Add a `_RunNoticeBanner` widget test** — the branch ships none.
3. **Poll cadence stays 3s × 120** (~6 min ceiling; typical generation ~4 min).
4. **Run-notice is manual-dismiss + next-`loadMe`** — no delivered-push interplay this
   round (revisit later).

## Risks / effort

- **Effort: M, low-risk.** Mostly port + wire; the model/HTTP/widget halves and the
  backend already exist on main, and the reaper backstops the no-hang invariant.
- The subsystem **extends** main's `_GenerationBanner` and adds a sibling
  `_RunNoticeBanner` — it does not replace existing generation UI.
- **Do not** pull in the unrelated branch churn that shares diff hunks (`_TrialGiftCard`
  relocation, `kIsWeb` web edits, voice-cast rework, weekday encoding, duration default).
- Land the data-layer trio atomically with the call site (the `c6ad9fd` trap).

## Deferred / open

- A delivered FCM push proactively clearing a lingering `runNotice` (currently manual
  dismiss + next-launch `loadMe`).
- Confirm the 3s × 120 ceiling against real production generation times before relying
  on the timeout copy.
