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

**[you] — Play Console + RevenueCat**
- [ ] Google Play Console: create the app, then create the **in-app products / subscriptions** matching the launch-lock pricing:
  - Pro **$19.99/mo**, **$179.99/yr**
  - Max **$29.99/mo**, **$269.99/yr**
  - (Free trial: 5 pods → 1 premium/wk month 1 → 1 default/wk forever — model the trial in the product config.)
- [ ] Create a **RevenueCat** project, add the Play Store app, paste the **Play service-account JSON** so RC can read purchases.
- [ ] Map the Play products to RevenueCat **entitlements** (e.g. `pro`, `max`) and **offerings**.
- [ ] Grab the RevenueCat **public SDK key** (Android) and the **webhook signing secret**.

**[code] — Flutter + backend**
- [ ] Add `purchases_flutter`; init with the public key after sign-in (identify the RC user by the Firebase uid).
- [ ] Replace the stubbed "Choose Pro/Max" handlers in `paywall_screen.dart` with `Purchases.purchasePackage(...)`; gate premium features on the active entitlement.
- [ ] Backend: add a **RevenueCat webhook** endpoint (`/v1/webhooks/revenuecat` or similar) that verifies the signing secret and updates the user's plan/entitlement in Firestore. (There is no billing webhook today — this is net-new.)

**Acceptance:** a test purchase on Android flips the user's plan server-side and unlocks premium generation cadence.

---

## 3. FCM push (Android counterpart to the existing iOS APNs path)

> Backend reality today: `DeviceTokenRecord` **already has a `platform` field** (defaults `"ios"`),
> but `POST /v1/me/device-tokens` **hardcodes `platform="ios"`** and **validates an APNs hex token**,
> and `push.py` is **APNs-only**. So FCM needs both a client and a backend branch.

**[you] — Firebase / FCM**
- [ ] In the same Firebase project, FCM is enabled by default — confirm the **Cloud Messaging API (V1)** is on.
- [ ] Create/download a **service-account key** with FCM send permission for the backend (store in Cloud Run secrets).

**[code] — Flutter + backend**
- [ ] Add `firebase_messaging`; request the Android 13+ `POST_NOTIFICATIONS` runtime permission (reuse the just-in-time pre-prompt pattern already used on the Substack-add screen).
- [ ] On token grant, call `POST /v1/me/device-tokens` with **`platform: "android"`**.
- [ ] Backend: relax `register_device_token` to accept `platform="android"` and **skip the APNs-hex validation** for Android tokens (FCM tokens aren't 64-char hex).
- [ ] Backend: add an **FCM sender branch** in `push.py` (V1 HTTP API w/ the service account) and route Android tokens to it; keep APNs for iOS. The verification-code push + any future pushes should fan out per-platform.
- [ ] Mirror APNs's 410/`Unregistered` cleanup: FCM's `UNREGISTERED`/`INVALID_ARGUMENT` → mark token inactive.

**Acceptance:** Substack-verification-code push (the existing trigger) arrives on an Android device.

---

## 4. Codemagic → Play Store CI/CD

**[you] — keystore + Play + Codemagic**
- [ ] Generate an **upload keystore**; add its SHA-1/256 to Firebase (§1). Store the keystore + passwords in **Codemagic → code signing (Android)**.
- [ ] Play Console: create a **service account** (via Google Cloud), grant it release permissions, download JSON → add to Codemagic for **Google Play publishing**.
- [ ] Do the **first upload manually** (Play requires an initial build before API publishing works) and create an **internal testing** track.

**[code] — codemagic.yaml**
- [ ] Add an **Android workflow** to `codemagic.yaml`: `flutter build appbundle --release`, sign with the keystore, publish the `.aab` to the **internal** track.
- [ ] **Path-filter** it so Android builds trigger on `flutter/**` changes (don't rebuild iOS for Flutter-only commits and vice-versa).
- [ ] Wire `--build-number`/`--build-name` from Codemagic build vars (Android `versionCode` must monotonically increase — same discipline as the iOS build-number pitfall).

**Acceptance:** a push to `flutter/**` produces a signed `.aab` in Play internal testing.

---

## Suggested order
1. **Firebase + Google Sign-In** (unblocks live data + is the identity RevenueCat/FCM key off).
2. **Codemagic Android workflow** early (so every subsequent change ships to internal testing automatically).
3. **FCM** (smallest backend delta — `platform` field already exists).
4. **RevenueCat** (most moving parts: Play products + RC config + new webhook).
