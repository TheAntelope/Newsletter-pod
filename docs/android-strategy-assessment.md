# Android Strategy Assessment — Native-Twice (A) vs Flutter Rewrite (B)

_Assessment only. No app code written, no migration started. Every claim below is
grounded in specific files in this repo as of `main` @ `c6e691c` (2026-05-30)._

**The two options under review**

- **Option A** — Keep the existing native SwiftUI iOS app as-is; build a second
  native Android app in Kotlin/Jetpack Compose.
- **Option B** — Discard the SwiftUI client; rewrite the client once in Flutter
  for both platforms.

In **both** options: billing moves to RevenueCat, identity moves to a neutral
provider (Firebase Auth + Google Sign-In, keeping Apple on iOS), and the FastAPI
backend stays. The identity and billing rework (sections 4 and 5) is therefore
**common to both options** and is not a differentiator — it is sunk cost either way.

---

## 1. iOS client size & complexity (what Option B discards)

The iOS client is **8,681 lines of Swift** across 13 source files plus 2 test
files. It is unusually concentrated: one file holds 62% of it.

| File | LOC | Role |
|---|---:|---|
| [Screens.swift](../ios/NewsletterPodApp/Screens.swift) | 5,423 | Every screen + every custom component |
| [AppViewModel.swift](../ios/NewsletterPodApp/AppViewModel.swift) | 833 | Single observable app-state store |
| [APIModels.swift](../ios/NewsletterPodApp/APIModels.swift) | 742 | DTOs mirroring the backend |
| [APIClient.swift](../ios/NewsletterPodApp/APIClient.swift) | 647 | 35 endpoint methods |
| [ShareViewController.swift](../ios/NewsletterPodShareExtension/ShareViewController.swift) | 320 | Share-extension target (separate process) |
| [Theme.swift](../ios/NewsletterPodApp/Theme.swift) | 146 | Editorial theme primitives |
| [PushManager.swift](../ios/NewsletterPodApp/PushManager.swift) | 133 | APNs / UNUserNotificationCenter bridge |
| [SharedSession.swift](../ios/NewsletterPodApp/SharedSession.swift) | 95 | Shared-keychain token store |
| [PodcastSetupCaptureTests.swift](../ios/NewsletterPodUITests/PodcastSetupCaptureTests.swift) + [OnboardingFlowTests.swift](../ios/NewsletterPodUITests/OnboardingFlowTests.swift) | 211 | XCUITest harness |
| Others (App, Config, Tokens, Purchase) | ~131 | Glue |

### Screens / views

**67 SwiftUI `View` structs** total; 62 of them in `Screens.swift`. Roughly
**15 are full screens or sheets**:

`RootView` (router) · `SignInView` · `DashboardTabView` (tab host) · `HomeView`
(~795 LOC, the largest screen, [Screens.swift:145](../ios/NewsletterPodApp/Screens.swift#L145)) ·
`SourcesView` · `SubstackSubscriptionsList` · `AddSubstackSheet` · `PodcastSetupView`
(schedule editor lives inside it) · `AccountSheet` · `FeedAccessView` · `PaywallView` ·
`OnboardingFlowView` (~1,130 LOC, an **8-step** wizard — see "Step 1 of 8" in
[OnboardingFlowTests.swift:35](../ios/NewsletterPodUITests/OnboardingFlowTests.swift#L35)) ·
`LibraryView` · `SwipeDeckView` · `NextEpisodeQueueView`.

### Named custom components requested

| Component | Location | Notes |
|---|---|---|
| Swipe deck | `SwipeDeckView` + 6 supporting structs, [Screens.swift:4876–5240](../ios/NewsletterPodApp/Screens.swift#L4876) | Bespoke `DragGesture` physics: 110pt threshold, rotation clamped ±15°, spring snap-back, 600pt fly-off ([Screens.swift:4995](../ios/NewsletterPodApp/Screens.swift#L4995)) |
| Onboarding wizard | `OnboardingFlowView`, [Screens.swift:2922](../ios/NewsletterPodApp/Screens.swift#L2922) | 8 steps, `OnboardingProgressDots`, per-step shells, optimistic advance |
| Schedule editor | `ScheduleSection`, [Screens.swift:2259](../ios/NewsletterPodApp/Screens.swift#L2259) | Weekday/time/cutoff picker |
| Paywall | `PaywallView`, [Screens.swift:2588](../ios/NewsletterPodApp/Screens.swift#L2588) | Built on StoreKit 2 `SubscriptionStoreView` (see §2/§4) |
| Generation progress bar | `GenerationProgressBar`, [Screens.swift:4513](../ios/NewsletterPodApp/Screens.swift#L4513) | `TimelineView` interpolating elapsed/expected, caps at 95% |
| Editorial theme system | [Theme.swift](../ios/NewsletterPodApp/Theme.swift) + [DesignTokens.swift](../ios/NewsletterPodApp/DesignTokens.swift) | `EditorialCard`, `MetaLabel`, `AmberButtonStyle`, `EditorialBackground`, `EditorialDivider`, `ChecklistRow` |

Plus ~25 more private card/row components (`HeroEpisodeCard`, `SetupChecklistCard`,
`VoiceChoiceCard`, `SubstackPreviewCard`, `NewsletterEmailCard`, etc.).

### XCUITest harness

Two files, **211 LOC**, that drive the onboarding wizard end-to-end and capture a
screenshot per step. There is purpose-built test plumbing in production code: the
`-uiTestMode` launch argument seeds a fake session and disables UIView animations
to keep the iOS 26 Liquid-Glass animation loop from hanging XCUITest's
"wait for idle" ([NewsletterPodApp.swift:9–19](../ios/NewsletterPodApp/NewsletterPodApp.swift#L9)).
This harness, and the matching Codemagic screenshot pipeline, **does not transfer**
to either a Kotlin or a Flutter client and would be rebuilt from scratch in both A and B.

### The theme system is already half-portable

The editorial palette/typography/spacing is **not** hand-coded in Swift — it is
generated from [design-tokens/tokens.json](../design-tokens/tokens.json) by Style
Dictionary, which today emits `DesignTokens.swift` **and** `dist/tokens.css`
([design-tokens/build.js:108–120](../design-tokens/build.js#L108)). `Theme.*` is a
thin alias over the generated values. Adding a Dart/Compose output format is a small
build.js change, so the **design language** survives both options cheaply; what gets
rebuilt is the **layout code that consumes** the tokens.

---

## 2. iOS-specific surface — port difficulty

These are the places the client leans on Apple frameworks. "Difficulty" is relative
to a Flutter (Option B) port; for Option A the same capabilities are simply rebuilt
natively in Kotlin and are mostly routine on Android.

| Surface | Where | Port to Flutter |
|---|---|---|
| **StoreKit 2 paywall** — `SubscriptionStoreView`, `.inAppPurchaseOptions`, `.onInAppPurchaseCompletion` | [Screens.swift:2588–2746](../ios/NewsletterPodApp/Screens.swift#L2588) | **Easy** — but only because RevenueCat replaces it anyway in both options; its Flutter/Kotlin SDKs ship paywall UIs. This code is deleted regardless (§4). |
| **Background audio playback** — `AVPlayer` + `AVAudioSession` `.playback`/`.duckOthers` | `VoiceSamplePlayer`, [Screens.swift:3998–4049](../ios/NewsletterPodApp/Screens.swift#L3998) | **Moderate** — `just_audio` + `audio_session` cover it; ducking/interruption config and lock-screen controls must be re-tuned per platform. Note the app is "not a player" (memory: product scope); this is voice-sample preview, not a full player, which lowers the stakes. |
| **Speech-to-text dictation** — `SFSpeechRecognizer` + `AVAudioEngine` for voice intake | [Screens.swift:3900–3996](../ios/NewsletterPodApp/Screens.swift#L3900) | **Hard** — no first-class Flutter equivalent; `speech_to_text` plugin exists but partial-results UX and permission flows differ across iOS/Android, and the live-transcript binding here is non-trivial. Likely a platform-channel or degraded UX. |
| **CoreLocation + CLGeocoder** — resolve "City, Country" for weather | `LocationResolver`, [Screens.swift:4055–4121](../ios/NewsletterPodApp/Screens.swift#L4055) | **Easy–Moderate** — `geolocator` + `geocoding` plugins map cleanly; permission state machine re-implemented. |
| **APNs push** — `UIApplicationDelegate` device-token capture, tap-handling (clipboard copy + open pub URL) | [PushManager.swift](../ios/NewsletterPodApp/PushManager.swift) | **Moderate** — in Flutter this becomes `firebase_messaging`; the custom tap behaviour (copy verification code to pasteboard, open Substack URL — [PushManager.swift:69–87](../ios/NewsletterPodApp/PushManager.swift#L69)) is re-done in Dart + native. Note the **backend push sender is APNs-only** (§3), so a new FCM path is needed in both options anyway. |
| **Share extension + App-Group keychain** — separate target, reads session token from a shared keychain access group | [ShareViewController.swift](../ios/NewsletterPodShareExtension/ShareViewController.swift), [SharedSession.swift](../ios/NewsletterPodApp/SharedSession.swift) | **Hard** — Flutter cannot implement an iOS Share Extension in Dart; it remains a native Swift target (or a plugin like `receive_sharing_intent` that ships its own native code). The shared-keychain access group (`R7HS2T53Z8.com.newsletterpod.shared`, [SharedSession.swift:27](../ios/NewsletterPodApp/SharedSession.swift#L27)) is iOS-native regardless of UI framework. **Flutter does not escape this native plumbing.** |
| **iOS 26 Liquid Glass / system materials** — `.thinMaterial`/`.regularMaterial` backgrounds, `toolbarBackground`, the animation workaround | [Screens.swift:1504](../ios/NewsletterPodApp/Screens.swift#L1504), [Screens.swift:1714](../ios/NewsletterPodApp/Screens.swift#L1714), [NewsletterPodApp.swift:10](../ios/NewsletterPodApp/NewsletterPodApp.swift#L10) | **Moderate (cosmetic)** — Flutter renders its own widgets and will not reproduce the native Liquid-Glass look; the custom editorial chrome is mostly portable, but anywhere the app relies on the system material look it will diverge. Option A on Android also won't have Liquid Glass (it's iOS-only), so this is a look-and-feel divergence in both. |

**Net:** the genuinely hard-to-port items (share extension + shared keychain,
speech dictation) are hard in Flutter specifically because they **still require
native code** — Flutter narrows but does not eliminate the native surface.

---

## 3. Backend coupling to Apple/iOS

The FastAPI service (14,837 LOC across `newsletter_pod/`) is **mostly
client-agnostic**, with a small number of concrete Apple assumptions:

**Client-agnostic (no change needed for Android/Flutter):**
- Private RSS feed and token-gated audio are pure HTTP, keyed off feed tokens, not
  device or platform. `FeedTokenRecord` / `UserEpisodeRecord` reference `user_id`
  only ([user_models.py:73,106](../newsletter_pod/user_models.py#L73)).
- Entitlements, trial counters, and weekly quotas are computed **server-side** on
  `UserRecord` ([user_models.py:22–34](../newsletter_pod/user_models.py#L22)) and
  `SubscriptionRecord` — the client just renders them. No client trust.
- The canonical user key is an internal `uuid4().hex`
  ([control_plane.py:2407](../newsletter_pod/control_plane.py#L2407)); `user_id`
  appears in 20 places across `user_models.py` and every per-user record hangs off
  it, **not** off the Apple subject.

**Apple-specific assumptions (would force change):**
1. **`apple_subject` is a _required_ field on `UserRecord`**
   ([user_models.py:13](../newsletter_pod/user_models.py#L13)). A non-Apple user has
   no value to put here. This is the single biggest schema coupling.
2. **The only sign-in path is Apple.** `authenticate_with_apple` →
   `get_user_by_apple_subject` ([control_plane.py:272–295](../newsletter_pod/control_plane.py#L272))
   is the sole account-resolution route (`POST /v1/auth/apple`,
   [main.py:315](../newsletter_pod/main.py#L315)). The Firestore lookup is a
   `where("apple_subject", "==", …)` query
   ([user_repository.py:1144](../newsletter_pod/user_repository.py#L1144)).
3. **Push is APNs-only.** `PushSender` signs an ES256 JWT and sets `apns-topic`/
   `apns-push-type`, targeting Apple's hosts over HTTP/2
   ([push.py:88–116](../newsletter_pod/push.py#L88)). The device-token route
   validates APNs-style tokens (`len < 32` reject, `production|sandbox` only —
   [main.py:492–503](../newsletter_pod/main.py#L485)). Android needs an FCM path.
   **Forward-looking detail:** `DeviceTokenRecord` already carries a
   `platform: str = "ios"` field ([user_models.py:201–223](../newsletter_pod/user_models.py#L201)),
   so the data model anticipated multi-platform even though the sender doesn't yet.
4. **Billing is keyed to Apple's `appAccountToken`** — see §4. (It maps back to the
   internal `user_id`, which softens the coupling.)

**Important:** items 1–4 are forced by **adding any non-Apple client at all** —
they are identical work in Option A and Option B. The backend does not care whether
the new client is Kotlin or Dart.

---

## 4. Billing retirement under RevenueCat

RevenueCat becomes the source of truth on both platforms. What changes:

**Server — REPLACED (~440 LOC retired/rerouted):**
- [app_store_verifier.py](../newsletter_pod/app_store_verifier.py) (192 LOC) — Apple
  `SignedDataVerifier` wrapper. No longer the verification authority.
- In [control_plane.py](../newsletter_pod/control_plane.py):
  `apply_app_store_notification` ([:1432](../newsletter_pod/control_plane.py#L1432)),
  `_apply_verified_app_store_notification` ([:1455](../newsletter_pod/control_plane.py#L1455)),
  `apply_client_verified_transaction` ([:1512](../newsletter_pod/control_plane.py#L1512)),
  `_apply_legacy_app_store_notification` ([:1599](../newsletter_pod/control_plane.py#L1599)),
  and `_normalize_app_account_token` ([:3106](../newsletter_pod/control_plane.py#L3106)).
- Routes `POST /v1/billing/app-store/notifications` and
  `POST /v1/me/subscription/verify` ([main.py:897,912](../newsletter_pod/main.py#L897)).
- Config: `app_store_*` product IDs / bundle / environment / `require_signed`
  ([config.py:275+](../newsletter_pod/config.py#L275)).
- These are **replaced by a single RevenueCat webhook handler** that maps RC events
  to tier/status.

**Server — KEPT (the valuable part):**
- `SubscriptionRecord` ([user_models.py:79](../newsletter_pod/user_models.py#L79)),
  the `tier`/`status` model, `_get_subscription`, the entitlements computation, and
  the weekly-quota state machine. Crucially, `_mutate_subscription_from_notification`
  ([control_plane.py:1493](../newsletter_pod/control_plane.py#L1493)) — the logic that
  turns a billing event into a tier change — is **reusable**: the RC webhook feeds the
  same mutation. Only the _verification front-end_ changes, not the subscription
  state machine.
- A nice simplification falls out: with RC's `app_user_id` set to our internal
  `user_id`, the whole `appAccountToken` ↔ hyphen-normalization dance
  ([control_plane.py:3106](../newsletter_pod/control_plane.py#L3106), and the iOS
  `PurchaseManager.uuidFromHex` helper) **disappears**.

**Client — REPLACED:**
- `PaywallView`'s `SubscriptionStoreView` + `.inAppPurchaseOptions`/
  `.onInAppPurchaseCompletion` ([Screens.swift:2592–2746](../ios/NewsletterPodApp/Screens.swift#L2592)).
- [PurchaseManager.swift](../ios/NewsletterPodApp/PurchaseManager.swift) (19 LOC,
  just the UUID helper).
- `APIClient.verifySubscription` ([APIClient.swift:352](../ios/NewsletterPodApp/APIClient.swift#L352)).
- `Configuration.storekit` + the four product IDs in
  [AppConfiguration.swift:9–22](../ios/NewsletterPodApp/AppConfiguration.swift#L9).

**Takeaway:** billing is one of the _cheaper_ pieces to migrate. The client billing
code is thin (StoreKit 2 did the heavy lifting), and the server's subscription logic
survives. This is true regardless of A vs B.

---

## 5. Identity rework (common to both options)

Today the account model is welded to Sign in with Apple at exactly two seams, and —
helpfully — **only** those two:

1. **Auth entry:** [AppleIdentityVerifier](../newsletter_pod/auth.py#L17) validates the
   Apple identity token (JWKS, RS256, audience = `APPLE_CLIENT_ID`) and extracts
   `sub` → `AppleIdentity.subject`. The session JWT issued afterwards
   ([auth.py:62–79](../newsletter_pod/auth.py#L62)) is **already provider-neutral** —
   it carries the internal `user_id`, nothing Apple-specific. So everything
   _downstream of sign-in_ is already identity-agnostic.
2. **Account resolution:** `apple_subject` is a required `UserRecord` field and the
   sole lookup key (`get_user_by_apple_subject`, Firestore index on `apple_subject`).

**Scope to go neutral (Firebase Auth + Google, Apple kept on iOS):**
- Make `apple_subject` optional and add a generic identity pair (e.g.
  `identity_provider` + `provider_subject`, or a `firebase_uid`) on `UserRecord`.
- Add a Firebase token verifier alongside `AppleIdentityVerifier` and a route
  (`/v1/auth/firebase` or a generic `/v1/auth/exchange`) that mirrors
  `authenticate_with_apple`.
- Generalize `get_user_by_apple_subject` → `get_user_by_identity(provider, subject)`
  and add the Firestore composite index. Migrate existing rows
  (apple_subject → provider="apple").
- The internal `user_id` stays canonical, so feed tokens, episodes, subscriptions,
  device tokens, inbound aliases — **none** need re-keying. Blast radius is contained
  to the auth seam plus one schema field.

This is real work but **modest and well-contained**, and it is **identical in
Option A and Option B**. It should be sequenced _first_, before any new client, so
the new client targets the neutral auth from day one.

---

## 6. Effort & risk — A vs B

Identity (§5) and billing (§4) rework are excluded from the comparison below since
they are equal in both options. The comparison is purely about the **client**.

### Upfront build

| | Option A (native twice) | Option B (Flutter once) |
|---|---|---|
| iOS client | **Untouched** — 8,681 LOC of working, shipping Swift retained | **Discarded** — rewrite ~8,000 LOC of UI in Dart |
| Android client | Build new Kotlin/Compose app, ≈ parity with the Swift client (call it a comparable LOC budget) | Covered by the shared Dart client |
| Native surfaces (§2) | Rebuilt once on Android (routine on Android: ExoPlayer, FCM, Android share intents) | Rebuilt once via plugins **+ still need native iOS/Android shells** for share extension, push, keychain |
| Theme | Re-emit tokens → Compose; rebuild layouts in Compose | Re-emit tokens → Dart; rebuild layouts in Dart |
| Test harness | New Android instrumentation tests; **XCUITest kept** | New Flutter integration tests; **XCUITest discarded** |
| CI/CD | Add Android pipeline; **keep working Codemagic iOS pipeline** | Rework Codemagic for Flutter; iOS signing + share-extension multi-bundle-id work partly redone |

**Rough upfront ordering:** B's "rewrite once" is less _total_ code than A's "two
native clients," but B pays a **throwaway tax** (a working, TestFlight-deployed iOS
app with a solved share-extension signing story — see the team's hard-won
`codemagic_multi_bundle_id_signing` notes — is scrapped) **plus** the cost of
re-deriving native plumbing it cannot avoid. A preserves 100% of the iOS sunk cost
but commits to building the Android half from zero.

### Ongoing per-feature maintenance

This is where they diverge sharply, and it is the crux.

- **Option A:** every client feature is implemented **twice, forever** — once in
  SwiftUI, once in Compose — and kept in sync. The repo shows a **fast-moving
  client**: swipe-based interest learning Phase 1 just shipped, the billing model
  was just locked, APNs "Phase B" is mid-flight, onboarding is an evolving 8-step
  wizard. At this churn rate, 2× client cost compounds every sprint.
- **Option B:** one Dart implementation per feature. Native shells (share extension,
  push) change rarely once built. For a solo/small developer, this roughly halves
  steady-state client cost.

### Biggest execution risks

**Option A**
- **Permanent 2× client tax** and inevitable feature drift between platforms — the
  dominant long-term risk, not a technical one.
- Requires sustained Kotlin/Compose fluency in addition to Swift/SwiftUI.
- Bespoke pieces (swipe physics at [Screens.swift:4995](../ios/NewsletterPodApp/Screens.swift#L4995),
  generation progress interpolation, the editorial card system) get hand-re-tuned on
  Android and will subtly differ.
- **Low technical risk, high sustained cost.**

**Option B**
- **Throwing away a working, shipping product** — 8,681 LOC, a green XCUITest
  harness, and a Codemagic pipeline whose share-extension/App-Group signing was
  notoriously painful to get right. Regression risk on a live TestFlight app.
- **Flutter doesn't escape native:** the share extension stays a native Swift target,
  the App-Group shared keychain stays native, push needs native hooks, and
  speech-to-text dictation ([Screens.swift:3900](../ios/NewsletterPodApp/Screens.swift#L3900))
  has no clean Dart story. You take on a Flutter toolchain **and** keep maintaining
  native code — a two-language reality dressed as one.
- Liquid-Glass / native-material fidelity on iOS is lost; the app will look like a
  Flutter app, not a SwiftUI one.
- **Higher upfront risk, lower ongoing cost.**

---

## 7. Steelman — keep native, go native-twice (Option A)

The strongest case for A, using this repo's evidence:

1. **You're discarding a genuinely working, non-trivial asset.** 8,681 LOC, 67
   views, an 8-step onboarding wizard, a custom swipe deck, a working XCUITest
   harness, and — per the team's own memory notes — a Codemagic multi-bundle-id
   signing setup that was hard-won (`codemagic_multi_bundle_id_signing`,
   `share_extension_app_store_setup`). Rewrites of working software are where
   regressions and lost edge-cases live. A keeps every bit of that.
2. **Flutter never actually gets you to "one codebase."** The two hardest surfaces
   here — the Share Extension ([ShareViewController.swift](../ios/NewsletterPodShareExtension/ShareViewController.swift))
   and its App-Group shared keychain ([SharedSession.swift](../ios/NewsletterPodApp/SharedSession.swift)) —
   **remain native Swift in Flutter too**, and you'd add an Android-native share
   handler regardless. So B's headline benefit is partial: you'd run Dart **plus**
   native Swift **plus** native Kotlin. A is honestly two-native; B is
   Dart-plus-two-natives.
3. **The backend already prices in multi-platform without a UI rewrite.**
   `DeviceTokenRecord.platform` defaults to `"ios"` but exists precisely so a second
   platform slots in ([user_models.py:201](../newsletter_pod/user_models.py#L201)); the
   session JWT is provider-neutral ([auth.py:62](../newsletter_pod/auth.py#L62));
   entitlements are server-computed. Nothing about adding Android _requires_ touching
   the iOS UI — so why rewrite it?
4. **Native gets you the platform's best self.** iOS 26 Liquid Glass, StoreKit/
   SubscriptionStoreView polish, `SFSpeechRecognizer` dictation quality, and proper
   `AVAudioSession` ducking are all first-class in Swift and degraded-or-bespoke in
   Flutter. For an audio-first product, the native audio/voice stack is not
   incidental.
5. **The risk profile fits a live product.** A is additive (build Android beside a
   shipping iOS app); B is a big-bang replacement of the thing that currently works.
   Additive change is safer to ship incrementally.

The honest weakness of A — and it's a big one — is item §6's permanent 2× client
maintenance against a client that is **visibly churning fast**.

---

## 8. Recommendation

**Lean Option B (Flutter), but the lean is conditional — and the condition is the
whole decision.**

The findings cut both ways and roughly cancel on _upfront_ cost: B's smaller
total codebase is offset by the throwaway of a working iOS app and the native
plumbing Flutter can't shed (§2, §7.2). The tie-breaker is **ongoing cost**, and
there the evidence is one-sided: this is a **fast-moving client** (swipe learning,
billing lock, APNs Phase B, evolving onboarding all in recent history) maintained
by a **small team**. Under those conditions Option A's 2×-per-feature tax compounds
indefinitely, while Option B pays its big bill once.

### The single variable that should decide it

> **Is the client a living, fast-evolving surface you'll keep changing on both
> platforms for years — or is it approaching feature-stable?**

- If the client keeps churning at its current rate (the repo strongly suggests it
  will) → the recurring 2× tax dominates → **choose B (Flutter)**, sequenced after
  the identity/billing neutralization, and budget explicitly for the unavoidable
  native iOS/Android shells (share extension, push, keychain, dictation).
- If the client is near feature-freeze and Android is a one-and-done port of a
  stable surface → the throwaway of a working iOS app is pure waste and there's no
  recurring tax to amortize → **choose A (native twice)**, keeping the SwiftUI app
  and its working pipeline intact.

Everything else — identity rework (§5), billing retirement (§4), the FCM push path
(§3) — is the same bill in either option and should be done first regardless.

---

## 9. Concerns & safeguards (pre-commit Q&A)

Captured before starting, so the rationale survives.

### Rollback to Swift
- **Phases 0–2 (Android-first):** nothing to roll back. The [SwiftUI app](../ios/NewsletterPodApp/)
  is never deleted or modified and keeps shipping via [codemagic.yaml](../codemagic.yaml).
  Abandoning Flutter = delete a folder. **Zero pain.**
- **Phase 3 (retiring Swift) is the only step with real rollback cost**, and it stays
  bounded: the Swift target is git-tagged (Phase 0) and never removed; backend schema
  changes are additive (`apple_subject` kept, StoreKit/ASN path kept running). Re-point
  the iOS pipeline at the Swift target and ship — hours. The one sticky bit is billing
  reconciliation if iOS users re-subscribed through RevenueCat; RC wraps StoreKit so it's
  recoverable, and this is exactly why Phase 3 is deferred and parity-gated.

### Cost to ship Android
- **Google Play Console: one-time $25** (vs Apple's $99/yr, already paid).
- RevenueCat: free under ~$2,500/mo tracked revenue, then ~1%. Firebase Auth + FCM: free
  at this scale. **Marginal cash cost ≈ $25.**

### Flutter credibility
Production Flutter apps include Google Pay, BMW (*My BMW*), Nubank, Alibaba (Xianyu),
eBay Motors, Philips Hue, SNCF Connect. ClawCast's UI (card lists, onboarding wizard,
paywall, audio preview) is squarely in Flutter's sweet spot.

### Local iteration on Windows
- **Yes for Android/desktop/web** — `flutter run` with sub-second hot reload on a Windows
  box + Android emulator/device. **iOS builds still require macOS/Xcode** (Phase 3, via
  Codemagic's Mac builders). Today there is **zero** local iOS build ability on Windows —
  every iOS change round-trips through Codemagic. Android-first means full-speed local
  iteration during Phases 1–2.

### Claude-driven build loop
- For Android/desktop/web targets, Claude can drive `flutter run`/`flutter test`/
  `flutter analyze`/`flutter build apk`, hot reload, read logs, run headless integration
  tests, and capture screenshots — locally, seconds-scale. This **directly removes the
  Codemagic→TestFlight lag** for client iteration; the slow cloud path is only needed for
  iOS-specific behavior in Phase 3.

### Build pipeline (2 frontends + backend)
- Today: [cloudbuild.yaml](../cloudbuild.yaml)→Cloud Run (backend) and
  [codemagic.yaml](../codemagic.yaml)→TestFlight (iOS).
- Phase 2 adds a **third, path-filtered** workflow in the **same monorepo**:

  | Changed path | Triggers | Target |
  |---|---|---|
  | `newsletter_pod/**` | Cloud Build | Cloud Run |
  | `ios/**` (Swift) | Codemagic (existing) | TestFlight |
  | `flutter/**` (new) | Codemagic Flutter workflow | Play Store |

- Phase 3 collapses back to **two**: one Flutter project builds both iOS + Android
  artifacts; the Swift `ios/**` workflow is retired. Monorepo keeps the API contract
  ([APIModels.swift](../ios/NewsletterPodApp/APIModels.swift) ↔ new Dart models) visible
  in one place.

**The cost of doing this safely:** the Phase 2 overlap is the period of maximum surface —
Swift iOS + Flutter Android + backend + two reconciling billing sources. It is temporary
and it is the price that makes every rollback above cheap.

---

> **Implementation plan:** see [flutter-migration-plan.md](flutter-migration-plan.md) for
> the phased, self-contained execution plan (designed to be picked up by a fresh session).
