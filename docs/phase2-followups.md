# Phase 2 follow-ups

Two items left open when Phase 2 (Android via Flutter) was called done on 2026-06-04. Both
are **verification / pre-existing-system** work, not new feature code. Phase 2 itself —
Firebase Google Sign-In, Codemagic→Play CI, FCM push backend, RevenueCat webhook + paywall —
is shipped to `main` and live (see the `flutter_phase2_env` + `firebase_android_setup`
auto-memories for the full state).

> **Status 2026-06-04 (investigated):**
> - **Task 1 — BLOCKED on Google Play product propagation, not our code.** Everything we own
>   verified correct: webhook live + auth-gated (401 on unauth probe), tier resolves from `pro`/`max`
>   entitlements, build 242 has flag+key, Play products configured (`pro`/`max` + `monthly`/`annual`
>   base plans Active). Symptom: tapping Choose Pro does *nothing* because
>   `Purchases.getProducts(['pro:monthly'])` returns **empty** — and on Android that queries the
>   device's Play Billing client directly, so it's a device↔Play propagation/caching issue (products
>   created/edited Jun 3–4). Retry after propagation (hours). Two side-issues found:
>   **(i)** RevenueCat Play service-account has a **Pub/Sub permission error** (RTDN/renewals — fix for
>   prod, not blocking the first purchase); **(ii)** the annual base plan was recreated as `annualmax`
>   (Yearly) + left **Draft**, so `max:annual` won't resolve until renamed/activated — fine for now
>   since the paywall only buys `:monthly`. See `revenuecat_android_setup` memory.
> - **Task 2 — DONE.** Root cause: Flutter `substack_add_screen._add()` created the intent + RSS-prefetch
>   but never opened the deep-link subscribe form / copied the alias, so the alias was never subscribed
>   and no mail ever reached `/webhooks/mailgun/inbound` (a parity gap vs iOS `handleContinue`). Fixed +
>   regression test added. Suspects (a) stale signing key and (b) alias change were ruled out with logs/Firestore.

## Context / access
- **Prod backend:** Cloud Run `newsletter-pod` (`europe-west1`), base URL
  `https://newsletter-pod-cdze2t26va-ew.a.run.app`. `gcloud` is authed to project
  `newsletter-pod`; read prod logs with `gcloud logging read`.
- **Codemagic:** REST token in `~/.bashrc` as `CODEMAGIC_API_TOKEN` (`source ~/.bashrc`
  first). App id `69e52c89613af952372ba110`; Android workflow `android-playstore`. Trigger a
  branch build: `POST https://api.codemagic.io/builds` with
  `{"appId":"69e52c89613af952372ba110","workflowId":"android-playstore","branch":"<branch>"}`.
- **Test user id:** `05a58a0f0744443eaccd37cbe922d6b6`.
- Relevant memories: `flutter_phase2_env`, `firebase_android_setup`, `inbound_email_bridge`,
  `mailgun_signing_key_stale_2026_05_25`, `alias_regenerate_orphans_substack_subs`,
  `vince_test_alias`, `substack_verification_codes`.

## Task 1 — verify the RevenueCat purchase end-to-end (on device)
The billing build (versionCode ≥ 242, built with `ENABLE_PURCHASES_REVENUECAT=true` +
`REVENUECAT_ANDROID_KEY=goog_wmyyscxLmKwzOOzLHfOnruzAbnv`) is on the Play **internal testing**
track. Vince updates the ClawCast app on his Android phone to that build — he was on build
**237**, which shows *"Purchases arrive with RevenueCat — coming soon"* because purchases
were flag-off there — and taps **Choose Pro** (or Max). As an internal tester there's no charge.

**Goal:** confirm the round trip — `POST /webhooks/revenuecat` fires and the user's
`SubscriptionRecord.tier` flips to `pro`/`max`. The backend resolves tier from the RevenueCat
**entitlement ids** (`pro`/`max`), not the product ids.

**Verify:** watch Cloud Run logs for the webhook hit + the subscription mutation, and/or
confirm `GET /v1/me` reflects the new tier.

**If it doesn't fire/flip, debug:** RevenueCat dashboard webhook config (URL
`…/webhooks/revenuecat` + the Authorization secret stored as `revenuecat-webhook-auth-secret`),
the RevenueCat↔Play service-account propagation, and the Flutter purchase flow
(`flutter/lib/services/purchases_controller.dart` — buys the product directly by id
`pro:monthly`/`pro:annual`/`max:monthly`/`max:annual`).

## Task 2 — why does the inbound email bridge receive nothing?
**Symptom:** Vince added 3 Substacks (semianalysis.com, thehustle, sundayletters…) but there
are **zero `POST /webhooks/mailgun/inbound` calls** in the logs over 2h+. So the
verification-code → FCM push can't be exercised. RSS prefetch (`Substack latest-post
prefetched`) makes the adds *look* successful and **masks** the dead path — the same masking
pattern as the May 2026 stale-signing-key incident. FCM itself is verified as far as config:
the device token is registered (`platform=android`) and the sender is live.

**Investigate the cause. Suspects:**
- **(a) Stale Mailgun webhook signing key** — a past incident caused ~24 days of silent 401s.
  Check Secret Manager `mailgun-webhook-signing-key` vs the Mailgun dashboard, and whether
  Mailgun is even routing mail to `/webhooks/mailgun/inbound`.
- **(b) Alias changed** — Vince did an **Account reset** earlier today, which regenerates the
  inbound alias and can orphan existing subscriptions. Verify his *current* alias in Firestore
  vs what's actually subscribed.
- **(c) "Add Substack" may not actually subscribe the alias** — it might only create an intent
  + RSS-prefetch the latest post, without subscribing the alias to the publication. Trace the
  intended flow in `inbound.py` / `control_plane.py`.
- **(d)** Substack may send confirm-**links** to the personal inbox rather than 6-digit
  **codes** to the alias (publication-dependent) — in which case no code-push fires regardless.

**Deliverable:** what's broken + the fix. This is a pre-existing backend issue, separate from
the Android work.

## Suggested order
Task 1 first (it just needs Vince to update the app — prompt him, then watch live), then Task 2.
