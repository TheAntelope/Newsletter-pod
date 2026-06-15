# Next Steps

## Current state

- Local git repository is initialized on `main`.
- Code is pushed to the private GitHub repository: `https://github.com/TheAntelope/Newsletter-pod`.
- Backend tests pass locally.
- iOS source scaffold exists under `ios/NewsletterPodApp`.
- Xcode project generation is configured with XcodeGen in `ios/project.yml`.
- Hosted macOS build and TestFlight publishing are configured in `codemagic.yaml`.
- Secrets and generated artifacts are ignored by git.

## TestFlight deployment

1. Create or confirm an Apple Developer account.
2. In App Store Connect, create a new iOS app record.
3. Use bundle ID `com.newsletterpod.app`, or update `PRODUCT_BUNDLE_IDENTIFIER` in `ios/project.yml` before creating the app record.
4. Enable **Sign in with Apple** for the bundle ID.
5. Create the StoreKit subscription products (see launch tier model in `.claude/.../memory/billing_model_2026_05.md`):
   - `com.newsletterpod.pro.monthly` — $19.99/mo
   - `com.newsletterpod.pro.annual` — $179.99/yr
   - `com.newsletterpod.max.monthly` — $29.99/mo
   - `com.newsletterpod.max.annual` — $269.99/yr
6. Apply for the [Apple Small Business Program](https://developer.apple.com/app-store/small-business-program/) — load-bearing. At the standard 30% commission these prices don't work (Max monthly goes negative).
7. In Codemagic, connect the GitHub repository:
   - `TheAntelope/Newsletter-pod`
8. In Codemagic, add an App Store Connect API key integration named `codemagic`.
9. In Codemagic, enable iOS App Store code signing for bundle ID `com.newsletterpod.app`.
10. Optional: set `APP_STORE_APPLE_ID` in Codemagic after the App Store Connect app record exists.
11. Run the `ios-testflight` workflow in Codemagic.

## Before the first real TestFlight build

1. Confirm the iOS app base URL points at the deployed backend in `ios/NewsletterPodApp/AppConfiguration.swift`.
2. Confirm the backend Cloud Run service is deployed and reachable.
3. Confirm Sign in with Apple backend settings are configured:
   - `APPLE_CLIENT_ID`
   - `SESSION_SIGNING_SECRET`
4. Confirm App Store subscription product IDs match the iOS app and backend defaults:
   - `com.newsletterpod.pro.monthly`
   - `com.newsletterpod.pro.annual`
   - `com.newsletterpod.max.monthly`
   - `com.newsletterpod.max.annual`
5. Decide whether to keep the placeholder app icon for TestFlight or replace it before external testing.
6. **APNs / Push Notifications setup (one-time)** — required before Phase B push delivery works. See the runbook section below.

## APNs setup runbook (one-time, before Phase B push lights up)

These steps are gated on Apple Developer Portal access — they can only be done by an account holder on the team. Complete them in order before merging `feature/apns-push` to `main`.

1. **Enable Push Notifications capability**
   - developer.apple.com → Identifiers → `com.newsletterpod.app` → Capabilities → enable Push Notifications → Save.
2. **Generate an APNs auth key**
   - developer.apple.com → Keys → "+" → name "ClawCast APNs", check **Apple Push Notifications service (APNs)** → Continue → Register.
   - Click **Download** to get `AuthKey_XXXXXXXXXX.p8`. **Do this NOW — Apple only lets you download once.**
   - Note the **Key ID** (10 chars, visible next to the key name).
   - Note the **Team ID** (developer.apple.com → Membership, 10 chars).
3. **Upload to Google Secret Manager**
   ```bash
   gcloud secrets create apns-auth-key --data-file=AuthKey_XXXXXXXXXX.p8 --project=$PROJECT_ID
   gcloud secrets create apns-key-id --replication-policy=automatic --project=$PROJECT_ID
   echo -n "XXXXXXXXXX" | gcloud secrets versions add apns-key-id --data-file=- --project=$PROJECT_ID
   ```
4. **Fill in the Team ID in cloudbuild.yaml** — replace `REPLACE_WITH_TEAM_ID` with the 10-char value.
5. **Codemagic provisioning profile refresh** — the entitlements file now carries `aps-environment=production`. Codemagic re-syncs profiles on each build via the App Store Connect API, so the next build should pick this up automatically. If signing fails, regenerate the provisioning profile manually in App Store Connect with Push Notifications enabled (see [[codemagic-multi-bundle-id-signing]]).
6. **Merge + deploy** `feature/apns-push`.
7. **Verify end-to-end** — Vince signs out and back in on his test device (so the iOS app re-asks for permission), triggers a Substack signup, expects a push to land within seconds of Substack sending the code email.

## Backend follow-up

1. Complete real Apple identity token verification for `POST /v1/auth/apple`.
2. Complete App Store Server Notification signed-payload verification for `POST /v1/billing/app-store/notifications`.
3. Configure the dispatcher in Cloud Scheduler to call `POST /jobs/dispatch-due-users` every 15 minutes.
4. Configure Cloud Tasks for per-user podcast generation if dispatch should enqueue work instead of processing inline.
5. Run an end-to-end test with one real user account:
   - Sign in with Apple
   - Configure sources
   - Configure podcast format
   - Configure weekly schedule
   - Generate an episode
   - Subscribe to the private feed in Apple Podcasts
   - Confirm the episode plays

## Roadmap

### Multi-language support

Status: not started. Treat as a major workstream — touches script generation, voice selection, RSS feed metadata, iOS UI, and the bundled welcome episode.

**Today's behavior:** non-English source items are silently translated to English by the LLM during script generation. The output podcast is always English. `PODCAST_LANGUAGE` is a single global `en-us` used only for the RSS `<language>` tag; `PodcastProfileRecord` has no language field; `build_digest_prompt` has no language directive; ElevenLabs `eleven_multilingual_v2` already supports the TTS side, so the model layer is ready.

**Two separable axes:**

1. **Output language** — the language the podcast is delivered in. Per-user setting on the podcast profile; threaded through the prompt and per-user RSS feed.
2. **Source/input language** — whether the system recognizes and handles non-English newsletters explicitly (detection at ingest, optional explicit translation pass, surfacing "source X is in French" in the UI).

**Recommended order:**

1. Per-user output language. Add `language` to `PodcastProfileRecord`, thread it through `build_digest_prompt`, and stamp it on the per-user RSS feed instead of using the global setting.
2. Voice catalog filtering. ElevenLabs voices have language affinity even on `eleven_multilingual_v2`; the iOS Podcast Setup picker should narrow to voices that pronounce the chosen language well.
3. iOS UI localization (separate from podcast language). All copy is currently inline English in `Screens.swift` — would need `Localizable.strings` and a string-extraction pass.
4. Source language handling. Detect language at ingest time, store on `SourceItem`, decide whether to keep implicit LLM translation or run an explicit translation step before script generation.
5. Welcome episode. The bundled MP3 is English-only; either ship per-language welcome MP3s or skip the welcome seed for non-English users (see `welcome_episode_architecture.md`).

**Open questions:**

- Does episode language follow the iOS app locale, or is it an explicit per-pod setting? (Probably explicit — leaves room for future "Spanish news pod + German tech pod" use cases.)
- Do we surface "this source is in French" in the UI so users understand what's being translated?
- When a user switches language, do we re-issue the welcome episode in the new language or leave the original?
- Mixed-artifact problem: `SourceItemRef.title` is stored verbatim and can leak the original language into otherwise-translated show notes and audio attribution. Translate at ingest, translate at script time, or accept the mix?

### Swipe-based interest learning (replaces topic groupings as the relevance signal)

Status: **shipped** (2026-05-18). End-to-end backend + iOS. Driver: user feedback that topic groupings only feel ~50% relevant — even within a chosen topic, half the items don't match what the user actually cares about.

**Shipped components:**

- Persistent `source_items` Firestore collection, OpenAI `text-embedding-3-small` (1536d) embedded at ingest (`source_persistence.py`, `embeddings.py`, wired in `control_plane.py:1375-1383`).
- `swipes` collection + `POST /v1/me/swipes` endpoint (`user_models.py:206-231`, `main.py:438-458`).
- User interest vector (mean R − mean L, L2-normalized) computed on demand (`interest_vector.py`).
- Ranker step in script generation, on by default behind `SWIPE_RANKER_ENABLED` (min 3 swipes, `control_plane.py:_apply_swipe_ranker`).
- Cold-start k-means swipe deck endpoint + lazy refresh on access (`swipe_deck.py`, `clustering.py`).
- iOS swipe UI: onboarding card stack + post-episode "Tune your pod" deck (`Screens.swift`).
- Weekly cold-start deck refresh job: `POST /jobs/refresh-cold-start-deck` (Cloud Scheduler target, idempotent, returns `{status, deck_size, corpus_size, computed_at}`).
- Ranker observability: structured log line per generation pass (`swipe_ranker user=... used=... reason=... swipes=... candidates=... embeddings_resolved=... top_n=...`) so we can answer "is the ranker firing, and how often do users have <3 swipes" from Cloud Logging.

**Notes on the "<min_swipes" fallback:** the spec called for a topic-group fallback when the user has too few swipes. In practice items reaching the ranker are already filtered to the user's enabled sources (which carry the topic membership), so the chronological-top-N fallback IS topic-filtered. No separate code path needed.

**Cloud Scheduler wiring (operational TODO):** add a weekly job that POSTs to `/jobs/refresh-cold-start-deck` with the job-trigger token. Same pattern as `/jobs/send-feedback-digest`.

**Open follow-ups:**

- Negative-swipe weighting: today every left-swipe drags the centroid in proportion to its magnitude. Strong negatives could pull the vector into meaningless territory once we have power users. Revisit if we see vector quality drop with deep swipe histories.
- Inbound-email items currently compete with everything else in the ranker. Decide whether to force-include them as a separate slot.

### Analytics stack (events, BigQuery views, admin metrics, churn + cohort jobs)

Status: **shipped** (2026-05-26). End-to-end first-party telemetry from
the iOS/backend → Cloud Logging → BigQuery → operator dashboards.
Replaces the "no analytics SDK" hole that meant we had no way to
answer DAU / activation / retention / churn questions without
hand-querying Firestore.

**Shipped in three phases:**

1. **Phase 1 — Events.** `newsletter_pod/events.py` (`EventName` enum
   + `log_event` helper) emits structured `app_event` JSON log lines
   wired at every meaningful boundary: sign-in, onboarding step,
   swipe, sources saved, schedule change, episode requested,
   episode generated, episode failed, episode play pulse (via new
   `POST /v1/me/episodes/{id}/play-pulse`), subscription started/
   changed, feedback submitted, churn-risk scored. PII rule enforced
   in code (`EventPIIError` rejects forbidden property keys at call
   time so a regression can't leak email/text/subject/etc into the
   stream).
2. **Phase 2 — Reporting infra.** `infra/bigquery_setup.md` (gcloud
   commands to create `analytics` dataset + Cloud Logging sink +
   daily Firestore→GCS→BigQuery export of 5 collections);
   `infra/bigquery_views.sql` (six BigQuery views — DAU/WAU/MAU,
   activation funnel, cohort retention, tier+MRR breakdown, episode
   completion, churn-risk users — all partition-pruned via the
   sink's `timestamp` column). `GET /admin/metrics` renders a
   Firestore-derived summary HTML page + per-user timeline at
   `?user_id=`, gated by `ADMIN_USER_IDS` env var. Tiles that
   *require* the BigQuery sink render as placeholders pointing at
   their view name (so the page is honest about what's live).
   `docs/looker_studio_setup.md` walks through the 6-tile dashboard
   build with Monday email delivery.
3. **Phase 3 — Scheduled jobs.** `POST /jobs/score-churn-risk`
   (daily 04:00 Europe/Amsterdam) walks active paid users, computes
   a weighted score from `days_since_last_episode`, `swipes_14d`,
   `schedule_underuse_fraction`, `feedback_negative_30d`, persists
   `ChurnRiskRecord`, and emits `CHURN_RISK_SCORED` per at-risk
   user. `POST /jobs/weekly-cohort-report` (Mondays 07:00) emails
   the operator: last-week signups, activation %, paid conversion,
   top 3 churn-risk users. `scripts/schedule_analytics_jobs.sh`
   provisions both Cloud Scheduler jobs (`--dry-run` supported).

**Phase 3 data-source caveat:** churn scoring uses
`days_since_last_episode` as the proxy for "play recency" — actual
play data lives only in Cloud Logging until the BigQuery sink lands.
Same story for `schedule_underuse_fraction` standing in for
`schedule_day_count_delta_30d`. Both signals upgrade automatically
once `vw_churn_risk_users` flows.

**Recovery action on churn-risk users — deliberately deferred.** See
"Deferred" section below.

**Cloud Scheduler wiring (operational TODO):** run
`./scripts/schedule_analytics_jobs.sh` once Phase 1+2+3 are deployed.
Requires `GCP_PROJECT`, `SERVICE_URL`, `JOB_TRIGGER_TOKEN` env vars.
Also: set `ADMIN_USER_IDS` on the Cloud Run service (cloudbuild.yaml
doesn't propagate it) or `/admin/metrics` 403s for everyone.

### Share-to-ClawCast (iOS Share extension + backend pinning)

Status: **code-complete** (2026-05-28). Backend live and tested. iOS share extension target wired into XcodeGen + Codemagic. App Store Connect bundle-id registration is the only manual step left before TestFlight. Driver: users want the "Send to Kindle"-style affordance — any document they're reading should be able to land in their next pod.

**Shipped backend:**

- `POST /v1/items/shared` (multipart). Accepts `kind` ∈ {`url`, `pdf`, `epub`, `docx`, `text`} plus either `url` form-field or `file` upload, with optional `title` override. 25 MB upload cap (`SHARED_MAX_UPLOAD_BYTES`); 50k-char body cap after extraction (`MAX_EXTRACTED_CHARS`). 413 on oversize uploads.
- `newsletter_pod/shared_items.py` extractors: `pypdf` for PDF, `ebooklib` for EPUB, `python-docx` for DOCX, stdlib `HTMLParser` for URLs (skips `<script>`/`<style>`/`<nav>`/`<footer>`/etc., prefers `<article>` > `<main>` > `<body>`, falls back to `og:description`).
- Persistence: shared items are stored as `InboundEmailItem(kind="share")` with `from_email="share@theclawcast.com"`. Deterministic id from `(user_id, article_url, title, body[:1000])` so re-sharing the same content is idempotent (returns `duplicate: true`).
- Generation hook (`control_plane.py` `process_user_generation`): `kind="share"` items split off from the candidate pool early, skip swipe-filtering and the ranker, and are appended unconditionally — they **bypass the per-tier `max_items_per_episode` cap**. A free user (cap=1) who shares 3 things gets 1 RSS + 3 shares = 4 items in the next pod. The existing `mark_inbound_items_consumed` path drops them off after the episode publishes.
- Observability: `SHARED_ITEM_RECEIVED` event (`events.py`) with `share_kind`, `body_len_bucket` (coarse), `has_article_url`. No PII in the event stream — the body and title are deliberately not logged.

**Shipped iOS:**

- `ios/NewsletterPodShareExtension/` (new target, type `app-extension`, bundle id `com.newsletterpod.app.share`) wired into `ios/project.yml` as a dependency of the main app and into the `NewsletterPod` build scheme.
- `ShareViewController.swift` (UIKit; `Social` framework) reads the first `NSExtensionItem.attachments` entry, dispatches on UTI (`public.url`, `com.adobe.pdf`, `public.plain-text`, `org.idpf.epub-container`, `org.openxmlformats.wordprocessingml.document`), and POSTs multipart to `/v1/items/shared` directly via `URLSession`. Shows "Pinning to your next pod…" then dismisses; 401/413 surface inline.
- `NSExtensionActivationRule` configured for URL + text + 1 attachment + 1 file (Safari, Mail, Files, Reeder, Apple News, Substack iOS, etc.).
- `SharedSession.swift` keychain helper compiled into BOTH targets. Stores token in access group `$(AppIdentifierPrefix)com.newsletterpod.shared` so the extension can read what the main app wrote at sign-in. App Group `group.com.newsletterpod.shared` declared in both `.entitlements` files. `AppViewModel.signIn` now persists the token and `init` restores it on cold launch — *side effect: fixes the existing "users get signed out on every cold launch" UX gap.*
- `codemagic.yaml` documented for the new bundle id; signing is auto-discovered by `xcode-project use-profiles` once the bundle id is registered in App Store Connect.

**Before the first TestFlight build with the extension:**

1. Register bundle id `com.newsletterpod.app.share` in App Store Connect → Certificates, Identifiers & Profiles → Identifiers. Use the same team id (`R7HS2T53Z8`).
2. Register App Group `group.com.newsletterpod.shared` in Identifiers → App Groups.
3. Add the App Group to both bundle ids' capability list.
4. The Codemagic `app_store_connect` integration provisions matching profiles automatically; no profile-creation needed.

**Known limitations of the v1 backend:**

- Paywalled URLs return whatever the unauthenticated fetch sees (often nothing, sometimes a paywall page). The endpoint stores it anyway so the user sees their share land; the LLM segment will be brief. **Future:** plumb a "reader-mode HTML" body field into the request so the iOS share sheet can paste the *rendered* Safari Reader content when the URL is unauthenticated.
- URL extractor is regex-based, not `readability-lxml`. Good enough for most blog/article pages; loses on JS-heavy SPAs that render content client-side. Upgrade path is one `pip install` away.
- Scanned PDFs (no text layer) raise `SharedItemError` with a clear message rather than silently storing the filename. No OCR fallback.

### Per-item sub-topic tags via emergent clustering (option C — layering on D)

Status: not started. Logged 2026-05-18. Driver: D handles per-user selection well, but cards (and show-notes attribution) still lack a visible category, and users have no manual lever like "less AI, more finance this week."

**Approach:** run k-means periodically over the same `source_items` embeddings the ranker uses; expose cluster IDs as opaque tags first, label them (LLM or by hand) once they stabilize. No upfront taxonomy. New sources flow through the same embed-at-ingest pipeline; between full re-cluster runs, new items get a tag by argmin-distance to existing centroids. Full re-cluster rides the existing weekly cold-start scheduler.

**Sequencing:**

1. Backend: add cluster-assignment field to `SourceItemRecord` + a `clusters` collection (centroid + member count + provisional label). Re-cluster job hooked into the weekly refresh.
2. Backend: nearest-cluster assignment at ingest for new items (cheap argmin).
3. Backend: surface tags on swipe-card payload (`/v1/me/swipe-deck/*`) and on episode show-notes attribution.
4. Backend: cluster labeling pass (one LLM call per cluster, cached).
5. iOS: render tag on swipe cards + a per-tag filter sheet ("less of this", "more of this") that writes synthetic swipes against the cluster centroid.

**Gating:** Don't start until we have ~2 weeks of ranker observability data (need to confirm D is actually shifting episode relevance before we layer on UI complexity).

## Deferred (not on public roadmap)

Ideas that were scoped and **explicitly deferred** — parked here so future sessions don't re-propose them from scratch. Resurfacing one = update its **Revisit trigger** line, don't append a new section.

### Unify iOS billing under RevenueCat at the Flutter cutover (logged 2026-06-04)

**Context:** today billing is two separate integrations — iOS uses **native StoreKit 2** (`SubscriptionStoreView`, products `com.newsletterpod.{pro,max}.{monthly,annual}`) posting to `/v1/billing/app-store/notifications` (`apply_app_store_notification`); Android (Flutter) uses **RevenueCat** (`pro:monthly` ids → `/webhooks/revenuecat`). When Flutter replaces the SwiftUI iOS app, the native Swift paywall disappears and the Flutter `purchases_controller` (Android-only, hardcoded `tier:period` ids) has no iOS path — so iOS payments do **not** carry over as-is.

**The plan (Option A — adopt RevenueCat for iOS too):**
- Backend: **no change** — `/webhooks/revenuecat` + entitlement-based (`pro`/`max`) tier resolution is already platform-agnostic; one webhook serves both stores. Eventually retire `apply_app_store_notification`.
- RevenueCat dashboard: add an iOS app (App Store Connect App-Specific Shared Secret + In-App Purchase Key), import the `com.newsletterpod.*` products, map to the same `pro`/`max` entitlements.
- App Store Connect: repoint App Store Server Notifications from our endpoint to RevenueCat.
- Flutter: add the iOS RC key (`appl_…`) and **move the purchase flow off hardcoded `tier:period` ids onto RevenueCat Offerings/packages** (per-store product ids differ; Offerings is the abstraction). This refactor is small and worth doing on the Android side *first*.
- **Migration risk (the real work):** existing iOS subscribers have live StoreKit subs tied to Apple, not RevenueCat. RevenueCat picks up existing entitlements on first SDK configure (receipt validation) so they keep access, but the cutover must be clean so events flow via RevenueCat afterward without double-counting.

Option B (keep native StoreKit on iOS via `in_app_purchase`) avoids migration but leaves two billing code paths + two webhooks forever — rejected unless migration proves too risky.

**Revisit trigger:** once **Android RevenueCat is confirmed working end-to-end** (a real Play purchase flips the user's tier via `/webhooks/revenuecat`) — currently blocked on Play product propagation, see [[revenuecat_android_setup]]. Start the iOS unification immediately after that's green and before the Flutter-iOS cutover.

### Cold-start personalization — extras (logged 2026-05-15)

Context: stacked recommendation 1+2+3a+3b+4a+5 was shipped (voice intake, swipe onboarding, Substack paste, forwarded-mail weighting, alias-prominence, name-check). The items below were scoped at the same time but deferred.

#### 3c — Gmail OAuth scan

**The idea:** Google Sign-In with `gmail.readonly` scope → scan the last 30-90 days for newsletter-like senders (List-Unsubscribe header, stable sender domains) → surface a "subscribe to these in ClawCast?" picker. Substack ones route through the existing autosubscribe flow; others get a one-tap "create Gmail filter forwarding to your alias" instruction.

**Why deferred:**
- Gmail readonly is a [Google restricted scope](https://developers.google.com/identity/protocols/oauth2/production-readiness/restricted-scope-verification) — requires an annual CASA security audit ($15-25k/year).
- Apple Review pushback risk: requiring a Google login for an app that already supports Sign-In with Apple invites scrutiny.
- Heavier privacy disclosure friction at sign-in.
- The active-paste (3a) + forwarded-mail (3b) flows already get ~70% of the same signal at <5% of the cost.

**Revisit trigger:** when paid retention numbers justify the audit cost (probably >5000 paying users, or when the per-user value of "I never have to manage subscriptions" becomes the dominant retention lever).

#### 4c — Calendar / location nudges

**The idea:** Use CoreLocation (already imported for weather) and EventKit to seed weak interest signals — e.g., a Copenhagen-locale user gets a small `da-DK` local-news cluster boost; a user with calendar events tagged "ML research review" gets a topic seed.

**Why deferred:** low signal-to-noise. Location can already drive RSS catalog selection at a coarser level (locale-specific feeds). Calendar is invasive and rarely accurate — meeting titles are noisy proxies for interest.

**Revisit trigger:** if we ever ship a "local news" pod variant where locality is the primary lens.

#### Recovery action on churn-risk users (logged 2026-05-26)

**The idea:** Phase 3 scoring (`/jobs/score-churn-risk`) flags
at-risk paid users daily and emits a `CHURN_RISK_SCORED` event per
user. The natural next move is an automated intervention — push
notification, "you might like this" re-engagement email, or
auto-generating a tighter / shorter / off-cadence episode tuned to
their recent swipe vector.

**Why deferred:**

- The expensive option (re-generating an episode) costs ~$0.10-0.30
  per pod in OpenAI + ElevenLabs spend. Firing it on the wrong
  user is real money and adds load to the daily generation pipeline.
- The cheap options (push, email) require a re-engagement copy
  surface that doesn't exist yet — and "you haven't played in a
  week" is a deeply annoying message if the heuristic mislabels.
- The Phase 3 scoring heuristic itself is *unvalidated* against
  actual churn outcomes. Need at least one cohort cycle of
  CHURN_RISK_SCORED → cancellation-or-not data before designing the
  recovery action — otherwise we'd be acting on a score that may
  not predict anything.

**Revisit trigger:** when we have ≥10 cohort weeks of churn-risk
scoring + subscription-cancellation outcome data and the score
correlates ≥0.6 with 14-day cancel rate. Until then, the operator
triages from `/admin/metrics?user_id=...` manually.

#### Personalized welcome-episode opener

**The idea:** Today the welcome MP3 is bundled and generic ([welcome_episode_architecture.md](memory/welcome_episode_architecture.md)). With voice intake on day one, we *could* generate a 30s personalized opener at signup time and stitch it onto the front of the bundled MP3 via ffmpeg concat.

**Why deferred:** episode #1 (first real generation run) already carries the personalization weight — voice transcript phrases land in `customGuidance`, name-check layer echoes them. The welcome-MP3 splice adds TTS+ffmpeg latency to signup (3-10s) and gives the user the "wow" moment one step earlier, but at the cost of a synchronous TTS call on the sign-in critical path.

**Revisit trigger:** if onboarding-to-first-episode-listen funnel data shows users dropping off before episode #1 generates. Then the splice becomes worth the latency.

### Podcast self-transcription (Phase 1b) (logged 2026-06-15)

**Context:** Phase 1a shipped podcasts as a first-class source type (live in prod; see [[podcasts_source_type_phase1a]]). It ingests each episode's **show notes** as the item summary, exactly like an article, and already captures `audio_url` + `audio_duration_seconds` + `kind="podcast"` on `SourceItem`/`SourceItemRecord` as groundwork. The original 1b plan was "use the Podcasting 2.0 `<podcast:transcript>` tag when the feed provides it (free, exact text)." **That path is mostly dead on arrival:** validating the 16 catalog feeds (`scripts/validate_candidate_podcasts.py`) showed **zero** expose `<podcast:transcript>` on recent items. So to get real episode *content* (not just a one-line show note), we have to **transcribe the audio ourselves.** This is the deferred, more expensive path.

**Why it matters:** show-note quality is wildly inconsistent. The news/curated feeds write rich notes (Up First ~1775c, Planet Money ~2843c) and produce good briefing lines today; thin-note shows (The Daily ~390c, Freakonomics ~227c) currently yield "X released an episode about Y." Transcription closes that gap and is the unlock for an eventual in-app player / "key moments" feature.

**The work (layered, cheap → universal):**
1. **Tag fallback first (already designed):** in `ingestion._entry_to_item`, read `entry.get("podcast_transcript")` → store `transcript_url`+`transcript_type` on the record (cheap, no network). When present (rare), fetch + strip to plain text by type (VTT/SRT → drop timestamps; HTML → strip tags; JSON → join segments). feedparser only surfaces the *last* `<podcast:transcript>` element, so format choice is limited — accept whatever it gives.
2. **Audio transcription (the real work):** download the `<enclosure>` audio (`audio_url`, already captured) → transcribe via OpenAI (`whisper-1` or `gpt-4o-transcribe`, consistent with the existing OpenAI generation/embedding stack) → **condense** to a ~150-word synopsis (one LLM call) → cache on the record. A raw 60-min transcript is ~50KB and cannot go verbatim into `build_digest_prompt` (the 1200-char `summary` cap exists for exactly this), so the condense step is mandatory.
3. **Where it runs — NOT synchronous generation.** Per-user generation (`control_plane.process_user_generation`) does a synchronous RSS fetch; a 1–3hr episode download + transcribe + condense is minutes + dollars and would wreck generation latency. Do the heavy work in the **hourly global poll** (`candidate_queue.run_poll`, where persistence + embedding already happen) or a dedicated async job, and **cache** the condensed text on `SourceItemRecord` (add e.g. `content_digest` + `transcribed_at` + `transcript_model`, mirroring the existing lazy-cached `card_summary` pattern). Transcribe each episode **once globally** (dedupe by `dedupe_key`), never per-user.
4. **Overlay into generation:** generation builds its own in-memory `SourceItem` list, so after `fetch_new_items` batch-look-up the matching `SourceItemRecord`s (`repository.get_source_items([keys])` already exists) and swap `content_digest` in as the prompt summary when present. Keeps the hot path fast — the expensive work is cached, not on the critical path.
5. **Cost gating (load-bearing):** do **not** blindly transcribe every episode of every catalog podcast — a 3hr Lex Fridman nobody will hear about is pure waste. Gate to high-value episodes: e.g. only episodes from sources a user actually has **enabled**, or only **pinned** items in the next-episode queue, and/or a `MAX_TRANSCRIBE_DURATION_SECONDS` cap. `log()` anything skipped so coverage isn't silently truncated.

**Why deferred:** recurring per-hour-of-audio transcription cost + storage + a new async job + the dedupe/cache/overlay plumbing — material build and ongoing spend for a feature whose functional core (podcasts in the feed, briefed from show notes) is already live. Phase 1a deliberately chose the free, synchronous show-notes path first.

**Open questions:**
- **Model + cost:** benchmark `whisper-1` vs `gpt-4o-transcribe` $/hr and accuracy; estimate monthly spend from catalog size × episodes/week × avg duration *after* gating.
- **Audio egress/storage:** download to a tmp/GCS staging path; cap size; handle tracking-prefix 302s (the `audio_url` is stored raw precisely so playback/transcription can follow the redirect).
- **Copyright/ToS posture:** transcribing + summarizing *full audio* is a heavier IP stance than summarizing publisher-provided show notes. Worth a deliberate call (analogous to the `jurisdiction_sensitive` flag for press publishers) before turning it on broadly — possibly limit to summary/synopsis output, never republishing verbatim transcript.
- **Backfill:** existing `SourceItemRecord`s won't have `content_digest`; decide lazy-on-next-poll vs a one-off backfill job.

**Revisit trigger:** when podcast engagement justifies the spend — e.g. podcast sources show meaningful attach/listen rates in the platform analytics (`vw_engagement_by_platform` / play-pulse data), OR a user-facing in-app podcast player lands and needs transcript/"key moments" data. Until then, show-notes (1a) stands.

## Useful files

- `codemagic.yaml`: hosted macOS build and TestFlight workflow.
- `ios/project.yml`: XcodeGen project definition.
- `ios/README.md`: iOS-specific setup notes.
- `ios/NewsletterPodApp/AppConfiguration.swift`: backend URL and product IDs.
- `README.md`: backend and deployment documentation.
