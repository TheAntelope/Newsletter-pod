# Flutter UI Parity Punch-List

> **Goal:** bring the Flutter Android screens to **visual + interaction parity** with the
> shipping SwiftUI app. The Flutter app is **functionally complete** (all flows work on demo
> data, 22 tests green) but the screens were built as *simplified rebuilds* — plain Material
> `Card`/`ListTile` over the shared theme. The editorial **component system** and the richer
> per-screen layouts from the Swift app are **not yet ported**. This doc is the resume point.

**Created 2026-06-02.** Branch: `feature/phase2-flutter-android` (pushed). See also
[flutter-migration-plan.md](flutter-migration-plan.md) (master plan) and
[android-strategy-assessment.md](android-strategy-assessment.md) §1 (Swift component inventory).

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
