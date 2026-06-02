# Flutter UI Parity Punch-List

> **Goal:** bring the Flutter Android screens to **visual + interaction parity** with the
> shipping SwiftUI app. The Flutter app is **functionally complete** (all flows work on demo
> data, 22 tests green) but the screens were built as *simplified rebuilds* — plain Material
> `Card`/`ListTile` over the shared theme. The editorial **component system** and the richer
> per-screen layouts from the Swift app are **not yet ported**. This doc is the resume point.

**Created 2026-06-02.** Branch: `feature/phase2-flutter-android` (pushed). See also
[flutter-migration-plan.md](flutter-migration-plan.md) (master plan) and
[android-strategy-assessment.md](android-strategy-assessment.md) §1 (Swift component inventory).

## ✅ Parity pass complete (2026-06-02)

The editorial component library is built under [flutter/lib/widgets/](../flutter/lib/widgets/)
and **every screen below has been rebuilt on top of it.** `flutter analyze` is clean, the
22 widget tests are green, and `flutter build web` compiles. Committed per-screen on
`feature/phase2-flutter-android`.

- **Components ported** → `flutter/lib/widgets/`: `EditorialCard`, `MetaLabel`,
  `EditorialDivider`, `ChecklistRow`, `AmberButton` (filled/outlined),
  `GenerationProgressBar` (timer-driven, 95% cap), `OnboardingProgressDots`,
  `VoiceChoiceCard`, `DayToggle`. `HeroEpisodeCard` / `SetupChecklistCard` live as private
  widgets inside `home_screen.dart` (screen-specific). Theme gained flat cream
  AppBar/NavigationBar/input chrome.
- **Repository:** added `replaceSources` (interface + Fake + Api → `PUT /v1/me/sources`) so
  the Sources toggles persist.
- **Test deltas:** the generate test now pumps fixed steps + tears down the tree (the live
  progress bar never settles); the swipe test asserts the depth-3 stack + icon action buttons.

### Second pass — depth + the two missing screens (2026-06-02)

The "free wins + repo-backed" gaps from the §"what else to port" review are now done too
(24 tests green):

- **Repository plumbing:** surfaced the endpoints the `ApiClient` already had but
  `AppRepository` didn't (`updateProfile`, `resetAlgorithm`, `deleteAccount`, `fetchFeed`,
  `fetchCatalog`, `fetchInboundItems`, `submitFeedback`, `deleteSubstackIntent`); Fake gained
  demo data for each + mutable profile name.
- **PodcastSetup full config:** format picker, tone/humor pills, key-takeaways pills,
  greet/takeaways toggles, custom-guidance presets + free text, weather city.
- **AccountSheet** (home gear) + **FeedAccessView** (copyable private RSS URL + latest run),
  with reset/delete confirmation dialogs and sign-out.
- **Richer onboarding:** Show-format step + anchor/co-host voice roles (9 steps; the test now
  loops Next→Finish instead of a fixed count).
- **Home depth:** AboutPodcastCard, SourcesSummaryCard, FeedbackComposer, and a collapsible
  hero description + Show-transcript disclosure.
- **Sources depth:** catalog grouped by topic (collapsible, per-source toggles + N-of-M),
  Custom RSS add/remove, Recent Newsletters list.

**Still deferred (genuinely platform-/account-gated):** audio preview (`just_audio` — voice
samples + episode playback), speech-to-text dictation (`OnboardingVoiceIntakeStep` + the
feedback mic), the "Open in Apple Podcasts" deep link (Android pastes the URL instead), the
embedded onboarding swipe step, and the account-gated wiring (Firebase auth, RevenueCat, FCM,
Play CI). Cutoff-time is shown **read-only** — the `/v1/me/schedule` PATCH body doesn't accept it.

Original punch-list below is kept for reference.

## How to resume (toolchain)

- Flutter 3.44.1 lives at `C:\flutter` (not on PATH). Invoke `C:\flutter\bin\flutter.bat`.
- From `flutter/`: `C:\flutter\bin\flutter.bat run -d chrome` (web, hot reload) or `-d windows`.
  Android emulator is **not** installed (no Android SDK) — web/desktop is the iteration loop.
- Tests: `C:\flutter\bin\flutter.bat test` (22). Lint: `... analyze`. Codegen after DTO
  changes: `C:\flutter\bin\dart.bat run build_runner build`.
- Layout: screens in `flutter/lib/screens/`, theme in `flutter/lib/theme.dart`, generated
  tokens in `flutter/lib/design_tokens.dart`, data layer in `flutter/lib/data/` (Fake + Api
  repos behind `AppRepository`), single store in `flutter/lib/state/app_state.dart` (`AppScope`).

## What already matches

- **Palette / type / spacing / radii** — driven by `DesignTokens` (generated from the
  `clawcast-tokens` submodule, same source as iOS `Theme.swift`). Serif display headers, amber
  accent, cream background all match.
- **Information architecture / flows** — sign-in → onboarding → tabbed dashboard, and every
  secondary screen, exist and navigate correctly.

## What's NOT at parity — build an editorial component library first

The Swift app has a bespoke component set ([Theme.swift](../ios/NewsletterPodApp/Theme.swift) +
[Screens.swift](../ios/NewsletterPodApp/Screens.swift)). Port these to `flutter/lib/widgets/`
(new dir) and rebuild screens on top of them, replacing the plain Material `Card`s:

- `EditorialCard`, `EditorialBackground`, `EditorialDivider`, `MetaLabel` (the `LABEL` caps
  style), `ChecklistRow`, `AmberButtonStyle` (→ a styled button), `HeroEpisodeCard`,
  `SetupChecklistCard`, `VoiceChoiceCard`, `SubstackPreviewCard`, `NewsletterEmailCard`,
  `GenerationProgressBar` (Swift uses `TimelineView` interpolating elapsed/expected, caps 95% —
  [Screens.swift:4513](../ios/NewsletterPodApp/Screens.swift#L4513)), `OnboardingProgressDots`.

## Per-screen punch-list (Flutter file → gaps vs Swift)

| Flutter screen | Swift reference | Parity gaps |
|---|---|---|
| `sign_in_screen.dart` | `SignInView` | Editorial hero/layout; the real button becomes Google/Apple-via-Firebase (sign-in is stubbed now). |
| `onboarding_screen.dart` | `OnboardingFlowView` (~1,130 LOC, [Screens.swift:2922](../ios/NewsletterPodApp/Screens.swift#L2922)) | Steps are info-only placeholders. Need real per-step content: source picker, `VoiceChoiceCard` grid, weather location field, name persistence; richer shells + transitions. |
| `home_screen.dart` (Today) | `HomeView` (~795 LOC, [Screens.swift:145](../ios/NewsletterPodApp/Screens.swift#L145)) | Missing `HeroEpisodeCard` (latest episode + audio preview), `SetupChecklistCard`, `GenerationProgressBar` during generation. Currently just greeting + plan/schedule cards + buttons. |
| `sources_screen.dart` | `SourcesView` + `SubstackSubscriptionsList` | Toggles are **read-only** (no `replaceSources` persist); no editorial cards; Substack subs section not shown here (it's only in the add screen). |
| `library_screen.dart` | `LibraryView` | Plain cards; no source-item-refs detail, no audio preview, no editorial treatment. |
| `swipe_deck_screen.dart` | `SwipeDeckView` + 6 structs ([Screens.swift:4876](../ios/NewsletterPodApp/Screens.swift#L4876)) | Physics approximated (easeOut tween). Match Swift: spring snap-back, exact ±15°/110pt/600pt feel; card visual polish; drag-direction hint labels. |
| `next_episode_queue_screen.dart` | `NextEpisodeQueueView` | Functional; needs editorial styling + shared-item highlighting (shared items pinned at top). |
| `podcast_setup_screen.dart` | `PodcastSetupView` + `ScheduleSection` ([Screens.swift:2259](../ios/NewsletterPodApp/Screens.swift#L2259)) | Voice is a plain dropdown — Swift uses `VoiceChoiceCard`s with previews; schedule editor styling; cutoff-time control not exposed. |
| `paywall_screen.dart` | `PaywallView` ([Screens.swift:2588](../ios/NewsletterPodApp/Screens.swift#L2588)) | Presentational tiers; real purchase is RevenueCat (stubbed). Match editorial plan cards. |

## Not yet built (Swift has them)

- **AccountSheet** (account/settings sheet) and **FeedAccessView** (private RSS feed URL +
  token display) — no Flutter equivalents yet.
- **Audio preview** (`just_audio`/`audio_session`) for voice samples + episode hero card.
- **Speech-to-text dictation** for voice intake ([Screens.swift:3900](../ios/NewsletterPodApp/Screens.swift#L3900)) — hard on Flutter, decide plugin vs drop.

## After parity

Then the account-dependent Phase 2 finish (see migration plan): Firebase Auth + Google Sign-In
(swap the stub → `signInWithFirebase` + `ApiAppRepository`), RevenueCat billing + backend
webhook, FCM push + backend branch, and the path-filtered Codemagic → Play Store workflow.

## Kickoff prompt (paste into a new session)

> Resuming the ClawCast Flutter migration (Phase 2). The Flutter Android app is functionally
> complete on branch `feature/phase2-flutter-android` (10 screens, 22 tests green, pushed) but
> the screens are simplified rebuilds. This session: bring them to visual + interaction parity
> with the SwiftUI app.
>
> Read `docs/flutter-ui-parity.md` (the punch-list) first, then the Phase 2 section of
> `docs/flutter-migration-plan.md`, and skim `ios/NewsletterPodApp/Screens.swift` +
> `Theme.swift` for the editorial components to port.
>
> Toolchain: Flutter 3.44 at `C:\flutter` (not on PATH). From `flutter/`:
> `C:\flutter\bin\flutter.bat run -d chrome` (hot-reload loop), `... test` (the 22 tests),
> `C:\flutter\bin\dart.bat run build_runner build` (after DTO changes). No Android emulator
> installed — web/desktop is the loop.
>
> Plan: first build an editorial component library under `flutter/lib/widgets/` (EditorialCard,
> MetaLabel, EditorialDivider, GenerationProgressBar, HeroEpisodeCard, VoiceChoiceCard,
> OnboardingProgressDots, …), then rebuild the screens on top of it one at a time, keeping
> `flutter analyze` clean and widget tests green, committing per screen. Stay on the existing
> `feature/phase2-flutter-android` branch. Do NOT touch the uncommitted WIP
> (`AppViewModel.swift`, `scripts/looker/build_dashboard.py`).
