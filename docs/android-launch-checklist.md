# Android launch checklist — the account-gated Phase 2 finish

> The Flutter Android app is at UI parity and feature-complete on demo data
> (`FakeAppRepository`). What remains is wiring the four external services. None of
> this can be done from the dev box without provisioning accounts/keys first — this
> doc is the ordered to-do list. Package id: **`com.newsletterpod.app`**. Backend:
> FastAPI on Cloud Run `europe-west1` (`https://newsletter-pod-cdze2t26va-ew.a.run.app`).
>
> Created 2026-06-02. See [flutter-migration-plan.md](flutter-migration-plan.md) (master plan)
> and [flutter-ui-parity.md](flutter-ui-parity.md) (parity punch-list, now complete).

Legend: **[you]** = console/account/portal work only you can do · **[code]** = I can do once [you] is unblocked.

---

## 1. Firebase project + Google Sign-In (do this first — everything else hangs off the Firebase project)

> **Status 2026-06-02 — largely DONE.** Firebase project `theclawcast-9a045` created;
> Android app registered (`com.newsletterpod.app`); debug SHA-1 generated + registered (Google
> Sign-In OAuth clients present); `google-services.json` committed at `flutter/android/app/`.
> Backend was already built (`FirebaseIdentityVerifier` + `/v1/auth/firebase`) — and
> **`FIREBASE_PROJECT_ID=theclawcast-9a045` is now set on Cloud Run** (rev 00198) + pinned in
> `cloudbuild.yaml`. Flutter client wired behind `--dart-define=ENABLE_GOOGLE_SIGN_IN=true`
> (default off): `AuthController` (Google→Firebase→ID token) → `signInWithFirebaseToken` →
> swap to `ApiAppRepository`. **Remaining:** add the **release/upload-key SHA-1** when Play
> signing is set up (§4); first **real on-device sign-in** test needs an APK/device (see below);
> iOS Firebase config deferred (Android-first).

**[you] — Firebase / Google Cloud console**
- [ ] Create (or reuse) a Firebase project and **add an Android app** with package name `com.newsletterpod.app`.
- [ ] Add your debug + release **SHA-1 and SHA-256** fingerprints (required for Google Sign-In). Debug: from the `~/.android/debug.keystore`; release: from your upload keystore (see §4).
- [ ] Download **`google-services.json`** → it goes in `flutter/android/app/`.
- [ ] In **Authentication → Sign-in method**, enable **Google** (and Apple if you want cross-platform parity later).
- [ ] Decide the **token-verification story**: the backend must validate the Firebase ID token. Confirm which Firebase project the backend trusts and set its project id / service-account creds in Cloud Run secrets.

**[code] — Flutter + backend**
- [ ] Add deps: `firebase_core`, `firebase_auth`, `google_sign_in`. Run `flutterfire configure` (or hand-add `google-services.json` + the Gradle plugin).
- [ ] Replace the stubbed sign-in in `sign_in_screen.dart` with a real Google→Firebase flow that yields a Firebase **ID token**.
- [ ] Flip the app from `FakeAppRepository` → `ApiAppRepository` once a session exists (the Api repo already exists; it just needs the bearer token wired in).
- [ ] Backend: verify the Firebase ID token on protected routes (mirror however Sign-in-with-Apple is verified today) and map it to the existing user record.

**Acceptance:** real Google account signs in on an Android device, lands on the dashboard backed by live `/v1/me/*` data (not the Fake).

---

## 2. RevenueCat billing (Google Play Billing)

> **Status 2026-06-02 — code DONE, blocked on Play/RevenueCat setup + secret.**
> Backend: `POST /webhooks/revenuecat` (constant-time Authorization-header check
> against `REVENUECAT_WEBHOOK_AUTH_SECRET`; 503 until set, 401 on mismatch) →
> `apply_revenuecat_event` maps RC events to the existing subscription mutation
> (INITIAL_PURCHASE/RENEWAL/PRODUCT_CHANGE/UNCANCELLATION → activate,
> EXPIRATION → revoke; CANCELLATION keeps access until expiry), resolving tier
> from RC product ids (config) with an entitlement-id fallback; records a
> BillingEventRecord + reuses `_log_subscription_mutation`. Config gained the
> webhook secret + 4 RC product-id settings. Flutter: `purchases_flutter`,
> `PurchasesController` (configure/logIn/logOut/purchase), paywall "Choose" runs
> a real purchase + `loadMe()` (behind `ENABLE_PURCHASES_REVENUECAT`, default
> off → stub "coming soon" preserved). Tests: `tests/test_revenuecat_webhook.py`
> (auth, activate via product-id + entitlement fallback, revoke, keep-on-cancel,
> unknown-user) + paywall widget test. RevenueCat's `app_user_id` must be our
> backend user id — the client calls `Purchases.logIn(userId)` after sign-in.

**[you] — Play Console + RevenueCat (the remaining work)**
- [ ] Google Play Console: create the app + **subscriptions** for the launch pricing:
  Pro **$19.99/mo + $179.99/yr**, Max **$29.99/mo + $269.99/yr** (trial: 5 pods → 1 premium/wk month 1 → 1 default/wk).
- [ ] RevenueCat project: add the Play app + the **Play service-account JSON**; create entitlements named **`pro`** and **`max`**; build an **offering** whose packages are identified `pro_monthly`/`pro_annual`/`max_monthly`/`max_annual` (or set the matching `REVENUECAT_*_PRODUCT_ID` env vars to your Play product ids).
- [ ] Grab the **Android public SDK key** (`goog_…`) and set a **webhook Authorization header value** in RevenueCat → Integrations → Webhooks.
- [ ] Hand me the SDK key + the webhook secret value. I'll then: create Secret Manager secret `revenuecat-webhook-auth-secret`, add it to `cloudbuild.yaml` `--update-secrets`, set it on Cloud Run, and build the app with `--dart-define=ENABLE_PURCHASES_REVENUECAT=true --dart-define=REVENUECAT_ANDROID_KEY=goog_…`.

> ⚠️ Don't add the `revenuecat-webhook-auth-secret` binding to `cloudbuild.yaml` until the secret exists (a deploy would fail on the missing binding — same rule as APNs/X/FCM).

**[code] — DONE** (per the status block). The webhook 503s and the paywall stays stubbed until the secret + flag/key are set, so this shipped safely ahead of setup.

**Acceptance:** with the secret + flag/key set, a test purchase on Android flips the user's plan server-side (webhook → SubscriptionRecord) and the paywall reflects it after `loadMe()`.

---

## 3. FCM push (Android counterpart to the existing iOS APNs path)

> **Status 2026-06-02 — code DONE, blocked on the service-account JSON + flip.**
> `FcmSender` (HTTP v1) + `build_fcm_sender_from_settings` added to `push.py`;
> `send_substack_verification_push` now fans out per token (iOS→APNs, Android→FCM);
> `register_device_token` accepts `platform="android"` and preserves token case
> (FCM tokens aren't hex); config gained `FCM_ENABLED` + `FCM_SERVICE_ACCOUNT_JSON`.
> Flutter: `firebase_messaging` added, `POST_NOTIFICATIONS` in the manifest,
> `MessagingController` + `AppState._registerForPush()` registers the FCM token
> (`platform: android`) after a real sign-in. Backend + Flutter tests cover it.

**[you] — Firebase / FCM (the only thing left)**
- [ ] In Firebase, confirm **Cloud Messaging API (V1)** is on (it is by default).
- [ ] **Generate the service-account private key** (Project Settings → Service accounts → Generate new private key) and hand it over. I'll then:
  1. create Secret Manager secret `fcm-service-account` from the JSON,
  2. add `FCM_SERVICE_ACCOUNT_JSON=fcm-service-account:latest` to `cloudbuild.yaml`'s `--update-secrets` and `FCM_ENABLED=true` to `--update-env-vars`,
  3. set both on Cloud Run so push goes live.

> ⚠️ Don't add the `fcm-service-account` secret binding to `cloudbuild.yaml` *before* the secret exists — a deploy would fail on the missing binding (same rule as the APNs/X secrets noted in that file).

**[code] — DONE** (per the status block above). The FCM sender no-ops until `FCM_ENABLED=true` + the JSON are set, so this shipped safely ahead of the key.

**Acceptance:** with the key set + `FCM_ENABLED=true`, a Substack-verification-code push arrives on an Android device.

---

## 4. Codemagic → Play Store CI/CD

> **Status 2026-06-02 — codemagic.yaml DONE, blocked on Codemagic/Play setup.**
> Added the `android-playstore` workflow (`instance_type: linux_x2`, `flutter:
> stable`): submodule + design-token refresh & staleness guard → writes
> `key.properties` from the Codemagic keystore → versionCode = Play-latest+1
> (falls back to the monotonic build counter) → `flutter build appbundle
> --release --dart-define=ENABLE_GOOGLE_SIGN_IN=true` → publishes the `.aab` to
> the **internal** track (`changes_not_sent_for_review: true`). Path-filtered
> with `when.changeset.includes: [flutter/**, design-tokens/**]`; the iOS
> workflow gained `when.changeset.excludes: [flutter/**]` so neither rebuilds on
> the other's commits. `build.gradle.kts` now has a real release signingConfig
> that reads `key.properties` (falls back to debug locally).

**[you] — Codemagic + keystore + Play (the remaining setup)**
- [ ] Generate an **upload keystore** (`keytool -genkey -v -keystore upload-keystore.jks -keyalg RSA -keysize 2048 -validity 10000 -alias upload`). Add its **SHA-1/256 to Firebase** (§1) so Google Sign-In works on the released build.
- [ ] In Codemagic → **Teams → Code signing identities → Android keystores**, upload it with reference name **`clawcast_upload_keystore`** (+ store password, key alias, key password).
- [ ] Google Cloud → create a **Play Developer API service account**, grant it release perms in Play Console; put its JSON in a Codemagic **variable group `google_play`** as **`GCLOUD_SERVICE_ACCOUNT_CREDENTIALS`** (mark secure). (Optional in that group: `REVENUECAT_ANDROID_KEY` + `ENABLE_PURCHASES_REVENUECAT=true` to ship billing.)
- [ ] Play Console: create the app + do the **first `.aab` upload manually** (Play requires one manual upload before API publishing works), create the **internal testing** track.

**[code] — DONE** (per the status block).

**Acceptance:** after the one-time manual upload, a push touching `flutter/**` on `main` produces a signed `.aab` in Play internal testing.

---

## Suggested order
1. **Firebase + Google Sign-In** (unblocks live data + is the identity RevenueCat/FCM key off).
2. **Codemagic Android workflow** early (so every subsequent change ships to internal testing automatically).
3. **FCM** (smallest backend delta — `platform` field already exists).
4. **RevenueCat** (most moving parts: Play products + RC config + new webhook).
