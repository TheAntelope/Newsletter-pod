# ClawCast → Flutter (Option B) — Implementation Plan

> **Self-contained handoff.** This plan is written so a fresh Claude session (or this
> session after context compression) can execute it without re-deriving the analysis.
> Read this file plus [android-strategy-assessment.md](android-strategy-assessment.md)
> first; together they are the full context.

**Status:** Not started. Created 2026-06-01.
**Decision:** Option B (Flutter, one client for both platforms), executed **Android-first**
to avoid a big-bang replacement of the working iOS app.

---

## How to use this doc (fresh-session preamble)

1. The codebase is **ClawCast / `newsletter-pod`**: FastAPI backend (`newsletter_pod/`,
   ~14.8k LOC) on Cloud Run + a working SwiftUI iOS app (`ios/`, ~8.7k LOC) shipping to
   TestFlight via Codemagic. See [CLAUDE.md](../CLAUDE.md) and the assessment doc.
2. Work **one phase at a time**, in order. Each phase has **Tasks → Acceptance gate →
   Rollback**. Do not start a phase until the prior phase's acceptance gate is green.
3. **Never delete or modify Swift code** until Phase 3, and only then behind the parity
   gate. The SwiftUI app is the production iOS client and the safety net throughout.
4. All backend schema/auth/billing changes are **additive and reversible** until Phase 3.
5. Update the "Progress log" at the bottom of this file as you complete tasks, so the next
   session knows where things stand.

---

## Guiding principles (do not violate)

- **Android-first.** Zero existing Android users = zero blast radius. Prove the entire
  Flutter + RevenueCat + Firebase + FCM stack on Android before touching iOS.
- **Additive, never destructive.** Keep `apple_subject`, keep the StoreKit/ASN path, keep
  the Swift app — all running in parallel with the new paths.
- **Parity-gated, not date-gated.** The iOS swap (Phase 3) happens when a written parity
  checklist is met, never on a calendar deadline. It may be deferred indefinitely.
- **No big bang.** Every phase ships independently and rolls back by "delete a folder" or
  "re-point a pipeline," except the explicitly-gated Phase 3.

## Decision log (locked unless revisited with the user)

| Decision | Choice | Why |
|---|---|---|
| Client framework | Flutter (Dart) | One client, fast-churning UI, solo dev — see assessment §6/§8 |
| Sequencing | Android-first | Decouples risk; no existing Android users |
| Repo layout | Monorepo, new `flutter/` dir, path-filtered CI | Keeps API contract visible; reuse Codemagic |
| Billing | RevenueCat (source of truth on both platforms eventually) | Replaces App Store Server Notification verification; reuses backend subscription state machine |
| Identity | Firebase Auth (Google on Android, Apple kept on iOS) → neutral backend key | Backend session JWT already provider-neutral |
| Push (Android) | FCM | APNs path kept for iOS |
| Theme | Add Dart output to Style Dictionary | `design-tokens/build.js` already emits Swift + CSS |
| CI | Codemagic (already in use, builds Flutter natively) | Avoid new tooling; path filters for 3-way overlap |

## Open questions to resolve at kickoff (ask the user)

- Confirm Google Play Console account exists / will be created ($25 one-time).
- Confirm RevenueCat + Firebase projects to create (or existing GCP project to reuse).
- Bundle/package id for Android (suggest `com.newsletterpod.app` to match iOS).
- Where Dart DTOs live and whether to codegen them from a shared schema vs. hand-port from
  [APIModels.swift](../ios/NewsletterPodApp/APIModels.swift) (742 LOC, 35 endpoints in
  [APIClient.swift](../ios/NewsletterPodApp/APIClient.swift)).

---

## Phase 0 — Freeze a known-good baseline
**Goal:** an unambiguous, shippable Swift fallback before anything changes.

**Tasks**
- Tag the current shipping iOS release in git (e.g. `ios-baseline-pre-flutter`).
- Confirm the Codemagic iOS workflow ([codemagic.yaml](../codemagic.yaml)) is green and the
  backend ([cloudbuild.yaml](../cloudbuild.yaml)) deploys cleanly.
- Record current TestFlight build number and live Cloud Run revision in the Progress log.

**Acceptance gate:** tag exists; both pipelines green; baseline recorded.
**Rollback:** n/a (this *is* the rollback point).

---

## Phase 1 — Neutralize identity on the backend (additive, validated by the Swift app)
**Goal:** backend can authenticate a non-Apple client without breaking the Apple path.
Scope confirmed in assessment §5; coupling is at exactly two seams.

**Tasks**
- Add optional fields to [UserRecord](../newsletter_pod/user_models.py#L11):
  `identity_provider: Optional[str]`, `provider_subject: Optional[str]` (or `firebase_uid`).
  **Do not remove** `apple_subject` (still required-or-backfilled).
- Dual-write on Apple sign-in
  ([control_plane.py:272 `authenticate_with_apple`](../newsletter_pod/control_plane.py#L272)):
  set `provider="apple"`, `provider_subject=sub`, **and** keep `apple_subject`.
- Add `get_user_by_identity(provider, subject)` to the repository (abstract +
  in-memory + Firestore impls in [user_repository.py](../newsletter_pod/user_repository.py),
  see existing `get_user_by_apple_subject` at lines 68 / 556 / 1144). Falls back to the
  Apple lookup. Add the Firestore composite index.
- Add a Firebase token verifier alongside [AppleIdentityVerifier](../newsletter_pod/auth.py#L17)
  and a route `/v1/auth/firebase` (or generic `/v1/auth/exchange`) mirroring
  [`/v1/auth/apple`](../newsletter_pod/main.py#L315). Issue the **same** neutral session JWT
  ([auth.py:62](../newsletter_pod/auth.py#L62)).
- Tests: extend `tests/` to cover the new verifier + lookup; keep all existing auth tests green.

**Acceptance gate:** `pytest` green; the **unchanged** Swift app still signs in and `/v1/me`
works against the updated backend; a scripted Firebase token resolves/creates a user.
**Rollback:** the new fields are optional and the old `/v1/auth/apple` + `apple_subject`
lookup are untouched — revert the new route/verifier; no data migration needed.

---

## Phase 2 — Flutter Android app beside the iOS app (RevenueCat + Firebase + FCM)
**Goal:** a real, shipping Flutter Android app, with iOS users completely unaffected.

**Tasks**
- **Scaffold** a Flutter app under `flutter/` (package id e.g. `com.newsletterpod.app`).
  Target Android first; keep iOS target buildable but unused.
- **Theme:** add a Dart output format to [design-tokens/build.js](../design-tokens/build.js#L108)
  so the editorial palette/type/spacing match the Swift app from day one.
- **API layer:** port DTOs from [APIModels.swift](../ios/NewsletterPodApp/APIModels.swift)
  and the 35 endpoints from [APIClient.swift](../ios/NewsletterPodApp/APIClient.swift) to Dart.
- **Auth:** Firebase Auth + Google Sign-In on Android → exchange Firebase token at
  `/v1/auth/firebase` (Phase 1) for the app session JWT.
- **Build the screens** (rebuild, not port — see assessment §1 inventory): sign-in,
  dashboard/home, sources, Substack add, podcast setup + schedule editor, paywall,
  8-step onboarding wizard, library, swipe deck, next-episode queue. Reuse the Dart theme.
- **Billing (RevenueCat):** integrate RC Flutter SDK with `app_user_id = internal user.id`.
  Add a backend **RevenueCat webhook** handler that maps RC events into the existing
  [`_mutate_subscription_from_notification`](../newsletter_pod/control_plane.py#L1493) so the
  subscription state machine is reused. **Keep the App Store ASN path running** for iOS
  ([control_plane.py:1432](../newsletter_pod/control_plane.py#L1432)). Add a `billing_source`
  marker per subscription to avoid double-counting during overlap.
- **Push (FCM):** add an FCM branch to [PushSender](../newsletter_pod/push.py#L60); the
  device-token route ([main.py:485](../newsletter_pod/main.py#L485)) already stores
  `platform` ([user_models.py:201](../newsletter_pod/user_models.py#L201)) — set it to
  `"android"` and relax the APNs-shaped validation for FCM tokens.
- **CI:** add a path-filtered Codemagic workflow for `flutter/**` → Play Store internal
  track. Leave the `ios/**` Swift workflow and backend Cloud Build untouched.
- **Tests:** Flutter widget + integration tests (the local, Claude-drivable loop); backend
  tests for the RC webhook and FCM path.

**Acceptance gate:** Flutter Android app on the Play Store internal track does the full
happy path (sign in → onboarding → generate → receive push → see episode in feed →
purchase via RC → tier updates server-side). iOS users see **no change**. Backend
reconciles RC and ASN subscription state without double-counting.
**Rollback:** delete `flutter/` and its CI workflow; disable the RC webhook + FCM branch
(both additive). iOS + backend untouched.

---

## Phase 3 — (Optional, parity-gated) Replace the SwiftUI iOS app with Flutter
**Goal:** one Flutter codebase for both platforms. **Only** after Android is proven.

**Tasks**
- Enable the Flutter iOS target: Apple Sign-In via Firebase, RevenueCat on iOS (wraps
  StoreKit — existing subscribers migrate, do not re-purchase), APNs via `firebase_messaging`.
- Re-create the native-only pieces that Flutter cannot do in Dart (assessment §2/§7):
  the **Share Extension** (stays native Swift) and its **App-Group shared keychain**
  ([ShareViewController.swift](../ios/NewsletterPodShareExtension/ShareViewController.swift),
  [SharedSession.swift](../ios/NewsletterPodApp/SharedSession.swift)); push hooks; decide on
  speech-to-text dictation ([Screens.swift:3900](../ios/NewsletterPodApp/Screens.swift#L3900))
  — plugin vs. platform channel vs. drop.
- Ship Flutter-iOS to **TestFlight in parallel** with the production Swift app (do not replace).
- **Parity gate (write the checklist, then verify):** Flutter-iOS passes equivalents of the
  [XCUITest onboarding flow](../ios/NewsletterPodUITests/OnboardingFlowTests.swift); audio
  preview works; share extension works; push + verification-code tap behaviour works; billing
  reconciles RC↔StoreKit; design parity acceptable.
- Only when the gate is **fully green**: cut iOS billing to RC, promote Flutter-iOS to
  production, retire the Swift `ios/**` workflow. Collapse CI to backend + one Flutter pipeline.

**Acceptance gate:** the written parity checklist is 100% green on TestFlight before any
production promotion.
**Rollback:** ship the Swift build from the Phase 0 tag; backend still serves it (ASN path +
`apple_subject` were never removed). Reconcile any RC-side iOS subscriptions (the one sticky
step — see assessment §9).

---

## Do NOT do (hard rules)
- ❌ Delete `apple_subject` or the StoreKit/ASN verification path before RC is proven in prod.
- ❌ Retire the Swift app on a date instead of the parity gate.
- ❌ Build Flutter-iOS and Flutter-Android in the same first push — **Android alone first**.
- ❌ Combine identity + billing + new-client work in one branch — each phase is its own PR(s).
- ❌ Rebuild everything on every commit — use path-filtered CI from Phase 2 on.

## Progress log
_(Update as work proceeds.)_
- 2026-06-01 — Plan created. Phase 0 not yet started.
- 2026-06-01 — **Phase 0 baseline recorded (gate NOT yet green — see blocker).**
  - **Baseline tag:** `ios-baseline-pre-flutter` → `c6e691c` (annotated, **local only, not pushed**).
    This is the last build that actually shipped & was approved on TestFlight (Codemagic
    build #169, finished 2026-05-29, marketing version **1.0.4**). It is the genuine
    known-good Swift fallback, so the tag anchors the real rollback point.
  - **Backend pipeline: GREEN.** Cloud Build is all-SUCCESS through the latest commit
    `4f9cf20` (2026-06-01 16:51 UTC). Live Cloud Run revision **`newsletter-pod-00191-92h`**
    (`europe-west1`), 100% traffic, latestReady == latestCreated.
    URL `https://newsletter-pod-cdze2t26va-ew.a.run.app`.
  - **iOS pipeline: RED (blocker).** 15 consecutive Codemagic builds have failed since
    2026-05-30 — every one compiles fine (IPA + dSYM produced) and fails only at the
    **Publishing** step. ASC rejects the upload with **90062** (`CFBundleShortVersionString
    [1.0.4]` must be higher than the previously approved `[1.0.4]`) and **90186** (`Invalid
    Pre-Release Train. The train version '1.0.4' is closed for new build submissions`).
    Root cause: marketing version **1.0.4 was approved/closed on App Store Connect**, but the
    pipeline only auto-increments the *build number*, never `MARKETING_VERSION`. Pre-existing
    production issue, independent of this migration. Fix = bump `MARKETING_VERSION` 1.0.4→1.0.5.
  - **Local divergence noted:** local `main` is **15 commits behind** `origin/main`
    (`c6e691c` … `4f9cf20`); those 15 broadcast-feature commits are exactly the ones that
    have been failing to publish. Local checkout sits on the last-green commit.
  - **iOS fix:** PR **#33** bumped `MARKETING_VERSION` 1.0.4→1.0.5 in
    [ios/project.yml](../ios/project.yml); squash-merged to `main` (merge commit `128f8423`)
    at 19:05 UTC. Config-only; no Swift logic.
  - **Gate status: ✅ PHASE 0 CERTIFIED (2026-06-01 19:09 UTC).** tag ✅ (pushed) · backend
    green ✅ (Cloud Run `newsletter-pod-00191-92h`) · baseline recorded ✅ · **iOS pipeline
    green ✅** — Codemagic build `6a1dd7ff` finished, **Publishing passed**, shipping
    **v1.0.5** to TestFlight (clears the 15-commit backlog that was stuck behind the closed
    1.0.4 train). Both pipelines green → **Phase 1 may begin.**
  - **TestFlight confirmed:** build **#118** (v1.0.5) processed successfully on App Store
    Connect — upload accepted end-to-end, not just compiled.
- 2026-06-01 — **Phase 1 implemented (additive) — PR #35.** Branch
  `feature/phase1-neutral-identity` off `128f8423`. (This commit also tracks the two
  migration docs into git for durable cross-session handoff.)
  - `UserRecord.apple_subject` → `Optional`; added neutral `identity_provider` +
    `provider_subject` ([user_models.py](../newsletter_pod/user_models.py)). Apple users
    dual-write both; Firebase users have `apple_subject=None`. `user.id` stays canonical.
  - `FirebaseIdentityVerifier` beside `AppleIdentityVerifier`
    ([auth.py](../newsletter_pod/auth.py)); same neutral session JWT.
  - `get_user_by_identity(provider, subject)` (abstract + in-memory + Firestore, Apple
    fallback) ([user_repository.py](../newsletter_pod/user_repository.py)); equality+equality
    needs no composite index.
  - `authenticate_with_firebase` + dual-write + `_backfill_identity` self-heal on Apple
    sign-in + shared `_complete_sign_in` ([control_plane.py](../newsletter_pod/control_plane.py)).
  - `POST /v1/auth/firebase` ([main.py](../newsletter_pod/main.py)); new `FIREBASE_PROJECT_ID`
    config (unset → 400, no network).
  - Tests: [tests/test_auth_identity.py](../tests/test_auth_identity.py) (6, all green). Full
    suite green except 2 pre-existing env-dependent failures (live RSS fetch + broadcast
    feedback), verified to fail identically on `main`.
  - **Gate remaining (deploy/Phase-2 dependent):** after merge → Cloud Build deploys →
    re-verify the **unchanged Swift app** still signs in + `/v1/me` against the new revision;
    a **real Firebase token** end-to-end needs a Firebase project + `FIREBASE_PROJECT_ID`
    (Phase 2 setup). Code + unit-level gate is met.
  - **Merged + deployed:** PR #35 squash-merged (`2d4ada1`); Cloud Run rev
    `newsletter-pod-00194-vnm` live; smoke test passed (`/v1/auth/firebase`→400 configured-guard,
    `/v1/auth/apple`→400 invalid-token). TestFlight v1.0.5 build #118 accepted.
- 2026-06-01 — **Phase 2 started — Flutter Android local scaffold.** Branch
  `feature/phase2-flutter-android` (account-independent work; validated locally).
  - **Toolchain:** Flutter 3.44.1 installed at `C:\flutter` (no admin, git clone; invoke
    `C:\flutter\bin\flutter.bat`). `flutter doctor`: web + Windows-desktop run available;
    Android SDK is the only gap (deferred — only needed to run an APK).
  - **Scaffold:** `flutter/` (`flutter create --org com.newsletterpod --project-name app
    --platforms android,ios,web`), applicationId/namespace `com.newsletterpod.app`. Committed
    `0494074`. `flutter analyze` clean, `flutter test` green.
  - **Design tokens (done properly):** added a `dart/design-tokens` format + `flutter`
    platform to the **`clawcast-tokens` submodule** `build.js` → `dist/design_tokens.dart`
    (pushed `a1fbec9`); submodule pointer bumped here. Swift/CSS outputs unchanged (iOS CI
    staleness check stays green). Copied to `flutter/lib/design_tokens.dart`.
  - **Theme:** `flutter/lib/theme.dart` (editorial palette/type/spacing over the generated
    tokens, mirroring `Theme.swift`); themed app shell renders; widget test green.
  - **Next:** port `APIModels.swift` DTOs + the 35-endpoint `APIClient.swift` to Dart; build
    screens (dashboard, sources, onboarding, paywall, swipe deck, …). Auth/billing/push
    stubbed until the user creates Firebase / RevenueCat / Google Play accounts.
