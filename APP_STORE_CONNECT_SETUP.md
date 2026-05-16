# App Store Connect setup guide

Everything you need to configure in App Store Connect (and adjacent Apple
properties) to launch ClawCast with the new Pro / Max tier model.

Reference: launch tier model decisions in
`.claude/projects/c--Users-vincemartin-repos-Newsletter-pod/memory/billing_model_2026_05.md`.

---

## 0. Prerequisites

- An Apple Developer Program membership ($99/yr).
- The bundle ID `com.newsletterpod.app` is registered in the [Apple
  Developer portal](https://developer.apple.com/account/resources/identifiers/list).
- The Cloud Run backend is deployed and reachable at
  `https://newsletter-pod-497154432194.europe-west1.run.app`. (The iOS
  build won't reject mismatches, but billing notifications won't reach a
  service that isn't running.)

---

## 1. Apple Small Business Program (do this first)

**This is load-bearing for the pricing math.** At Apple's default 30%
commission, Max at $29.99/mo runs at a loss. Small Business Program
(SBP) drops the commission to 15% from day one.

1. Open <https://developer.apple.com/app-store/small-business-program/>.
2. Click **Enroll**.
3. Sign in with the Apple ID for the developer account.
4. Confirm the legal entity name + tax info matches App Store Connect.
5. Submit. Apple usually approves within ~5 business days. Enrollment
   becomes effective the calendar quarter after approval — apply *now*
   so it's active by launch.

You qualify if total App Store Connect proceeds are under $1M USD/yr.
If you stay under that ceiling, you stay at 15%.

---

## 2. Create the App Store Connect app record

1. Go to <https://appstoreconnect.apple.com/apps>.
2. **My Apps** → **+** → **New App**.
3. Fill in:
   - **Platform:** iOS
   - **Name:** ClawCast
   - **Primary Language:** English (U.S.)
   - **Bundle ID:** `com.newsletterpod.app`
     - If it's not in the dropdown, register it first at
       <https://developer.apple.com/account/resources/identifiers/list>.
   - **SKU:** `clawcast-ios` (or any unique string; never shown to users)
   - **User Access:** Full Access
4. Create.

Once created, on the app's **App Information** page:
- Set **Category** → Primary: News. Secondary: Business (optional).
- Set **Content Rights Information** as needed (you don't include
  third-party content directly — ClawCast generates audio from
  user-attached newsletter sources, which the user already subscribes
  to. "No, it does not contain, show, or access third-party content"
  is the simplest answer; consult counsel if uncertain).

---

## 3. Enable Sign in with Apple

1. In the [Developer portal](https://developer.apple.com/account/resources/identifiers/list),
   open the `com.newsletterpod.app` identifier.
2. Check **Sign in with Apple** under **Capabilities**.
3. Save.
4. In App Store Connect → your app → **App Information** → **App
   Privacy**, declare what's collected via Sign in with Apple (email
   address, user ID) per Apple's prompts.

The backend already expects an Apple identity token at
`POST /v1/auth/apple`. No app-side code change needed once the capability is on.

---

## 4. Create the four subscription products

Subscriptions live in the app's **Monetization → Subscriptions** section.

### 4a. Create the subscription group

1. **Monetization** → **Subscriptions** → **Create**.
2. **Reference Name:** `ClawCast` (internal label, never shown).
3. Save. You now have an empty group.

> Why one group? Apple uses subscription groups to define mutually
> exclusive plans. Putting Pro Monthly, Pro Annual, Max Monthly, and
> Max Annual in the same group means a user can switch between them
> at will (e.g. upgrade Pro→Max, switch monthly→annual) and Apple
> handles proration. **Do not split Pro and Max into separate groups
> — switching tiers becomes a cancel+resubscribe instead of an
> upgrade.**

### 4b. Add each subscription

Repeat the **Create Subscription** flow four times. The exact reference
names + product IDs + prices to use:

| Reference Name | Product ID                          | Price (USD)  | Duration |
|---|---|---|---|
| Pro Monthly    | `com.newsletterpod.pro.monthly`     | $19.99 / mo  | 1 month  |
| Pro Annual     | `com.newsletterpod.pro.annual`      | $179.99 / yr | 1 year   |
| Max Monthly    | `com.newsletterpod.max.monthly`     | $29.99 / mo  | 1 month  |
| Max Annual     | `com.newsletterpod.max.annual`      | $269.99 / yr | 1 year   |

For each one, fill in:

- **Reference Name:** as above
- **Product ID:** **exact match** — the iOS app, the backend
  (`APP_STORE_PRO_MONTHLY_PRODUCT_ID` etc.), and the
  `Configuration.storekit` test config all hard-code these strings.
  Typos break the paywall in the live app.
- **Subscription Duration:** 1 month or 1 year per the table.
- **Price:** open the price picker; choose the matching USD tier.
  Apple auto-fills local prices in every storefront from your USD
  selection.
- **Localizations (English U.S.):**

  **Pro · Monthly:**
  - Display Name: `ClawCast Pro`
  - Description: `3 premium-voice pods/wk + 4 default-voice pods/wk. Daily delivery, every weekday and weekend.`

  **Pro · Annual:**
  - Display Name: `ClawCast Pro · Annual`
  - Description: `3 premium-voice pods/wk + 4 default-voice pods/wk. ~25% off vs monthly.`

  **Max · Monthly:**
  - Display Name: `ClawCast Max`
  - Description: `7 premium-voice pods/wk — every day, every episode in your selected voice.`

  **Max · Annual:**
  - Display Name: `ClawCast Max · Annual`
  - Description: `7 premium-voice pods/wk. ~25% off vs monthly.`

- **Review Information:**
  - Screenshot: a paywall screenshot from a TestFlight build is fine.
    The first one is the only one Apple really looks at; reuse it
    for the other three.
  - Review notes: `Subscription unlocks tier-based access to premium
    voice (ElevenLabs) and default voice (OpenAI) podcast generation.
    No external account required — purchase tied to the Apple ID via
    the in-app paywall.`

Save each subscription, then click **Submit for Review** on each one
(or batch them when you submit the first app build for review).

### 4c. Required server-side metadata

Once all four products exist, copy each subscription's **Apple-issued
product ID** (which is identical to the Product ID you entered — Apple
just confirms it). Verify it matches the four entries in:

- `newsletter_pod/config.py` (`app_store_pro_monthly_product_id` etc.)
- `ios/NewsletterPodApp/AppConfiguration.swift`
- `ios/NewsletterPodApp/Configuration.storekit`

If you used a different ID, override via env var on Cloud Run, e.g.

```bash
gcloud run services update newsletter-pod \
  --region=europe-west1 \
  --update-env-vars=APP_STORE_PRO_MONTHLY_PRODUCT_ID=com.yourorg.pro.monthly
```

---

## 5. Free trial — IMPORTANT scope note

**ClawCast's 5-podcast trial is enforced server-side, not by App
Store Connect.** The trial counter (`trial_premium_pods_remaining`)
lives on the user record in Firestore and is decremented each time the
backend generates a premium-voice episode.

This means:

- **Do not** configure an introductory offer (free trial period) on
  any of the four subscriptions. The server already grants the trial
  to every new account.
- StoreKit subscriptions begin charging on day one. That matches the
  product (trial happens *before* a user converts; the paywall pitches
  Pro/Max only after the trial deck is used up).

If you later want to add an additional Apple-native free trial — for
example, "7 days free, then $19.99/mo" — configure it as an
**Introductory Offer** on the subscription. That's separate from the
server-side trial counter; the two would compose (free Apple trial
window + then the server trial pods continue to count down).

---

## 6. Subscription server notifications (App Store Server Notifications V2)

So purchases / cancellations / renewals stay in sync between Apple and
your backend.

1. In App Store Connect → your app → **App Information** → scroll to
   **App Store Server Notifications**.
2. **Production Server URL:**
   `https://newsletter-pod-497154432194.europe-west1.run.app/v1/billing/app-store/notifications`
3. **Sandbox Server URL:** same URL — backend route handles both.
4. **Version:** V2 (recommended).
5. Save.

> ⚠️ The backend currently accepts notifications without verifying
> Apple's signed JWS payload (see `NEXT_STEPS.md` → "Backend
> follow-up" item 2). Before pushing to public release, complete the
> signed-payload verification — otherwise anyone can POST to that
> endpoint and flip a user's tier.

---

## 7. App-side privacy + legal

1. **App Privacy** → declare data collection. ClawCast collects:
   - Email (linked, from Sign in with Apple)
   - User ID (linked, from Sign in with Apple)
   - Audio listening data: **no** (the app is not a player — episodes
     play via Apple Podcasts subscribing to the private RSS feed)
   - Newsletter sources: the user types these in; treat as User
     Content, linked to identity, not used for tracking.
2. **Privacy Policy URL:**
   `https://newsletter-pod-497154432194.europe-west1.run.app/legal/privacy`
3. **Terms of Use (EULA):** Apple's standard EULA suffices unless you
   want to substitute custom Terms hosted at
   `https://newsletter-pod-497154432194.europe-west1.run.app/legal/terms`.

---

## 8. Pre-submission checklist

Before clicking **Submit for Review**:

- [ ] All four subscriptions show **Ready to Submit** (not Missing
      Metadata).
- [ ] Each subscription has at least one English localization with
      display name + description.
- [ ] Each subscription has a review screenshot attached.
- [ ] App Store Server Notifications URL is set and the Cloud Run
      service responds with `200` to a manual `curl` POST.
- [ ] Sign in with Apple capability is enabled on the bundle ID.
- [ ] Small Business Program enrollment is confirmed (or you've
      accepted the 30% commission cost).
- [ ] App Privacy questionnaire is completed.
- [ ] Privacy policy URL resolves to actual policy text.
- [ ] TestFlight build is live and the paywall loads all 4 products.
- [ ] Internal testers can subscribe in Sandbox and see their tier
      flip on `GET /v1/me`.

---

## 9. Common review-rejection traps

- **"Paid features not gated by purchase."** Apple wants to see that a
  user with no active subscription cannot use the premium-only
  features. The free tier serving 1 default-voice pod/week (and the
  trial counter granting 5 premium pods upfront) satisfies this — but
  reviewer notes should make the gating model explicit. Sample copy
  for the review notes field: *"Free tier delivers 1 default-voice
  podcast/week after a 5-pod trial. Pro and Max tiers unlock 3 and 7
  premium-voice podcasts/week respectively. Premium voices are
  ElevenLabs; default voice is OpenAI TTS."*
- **Auto-renew disclosure.** The paywall already shows
  "Subscriptions auto-renew until cancelled" but make sure this stays
  visible above the purchase button after any UI tweaks.
- **Restore button.** The paywall's `Restore` link calls
  `AppStore.sync()` and re-fetches the user — required by Apple
  guideline 3.1.1.

---

## 10. Post-launch monitoring

- **Sandbox transactions:** App Store Connect → **Users and Access**
  → **Sandbox Testers**. Create at least one tester per region you'll
  test in.
- **Subscription metrics:** App Store Connect → **Subscriptions**
  shows MRR, churn, cohort retention. The Small Business Program
  drops Apple's commission from 30% to 15% automatically — no manual
  re-pricing needed.
- **Cloud Run logs:** `gcloud logging read 'resource.type=cloud_run_revision
  AND jsonPayload.event="billing_event"'` to spot-check that
  notifications are being received and tier flips are landing on
  Firestore.

---

## Quick reference

| Thing                      | Value                                                                |
|---|---|
| Bundle ID                  | `com.newsletterpod.app`                                              |
| Subscription group         | `ClawCast` (one group, four products)                                |
| Server-notifications URL   | `https://newsletter-pod-497154432194.europe-west1.run.app/v1/billing/app-store/notifications` |
| Apple commission (with SBP)| 15%                                                                  |
| Privacy policy URL         | `https://newsletter-pod-497154432194.europe-west1.run.app/legal/privacy` |
| Terms URL                  | `https://newsletter-pod-497154432194.europe-west1.run.app/legal/terms`  |

| Product ID                          | Price (USD) | Duration |
|---|---|---|
| `com.newsletterpod.pro.monthly`     | $19.99      | 1 month  |
| `com.newsletterpod.pro.annual`      | $179.99     | 1 year   |
| `com.newsletterpod.max.monthly`     | $29.99      | 1 month  |
| `com.newsletterpod.max.annual`      | $269.99     | 1 year   |
