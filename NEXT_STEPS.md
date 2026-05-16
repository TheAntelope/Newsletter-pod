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

Status: not started. Decision logged 2026-05-11. Driver: user feedback that topic groupings only feel ~50% relevant — even within a chosen topic, half the items don't match what the user actually cares about.

**Today's behavior:** onboarding asks the user to pick from 12 topic groupings; every source attached to a chosen group is equally eligible during script generation. There is no per-user signal about *which* items inside a group resonate. No item-level embeddings, no per-user interest vector, no ranker — selection is essentially "everything in the chosen groups, recency-filtered."

**Target design:** the topic gate is replaced by an implicit interest vector learned from swipes. The user reveals themselves through ~10–15 swipes; the system scores candidate items by cosine similarity to their evolving vector and feeds the top-N into script generation. Topic groupings stay around as a Sources-tab UI affordance and a cold-start fallback, but they no longer drive item selection.

**Architectural prerequisite (Phase 1):** items today are *ephemeral* — `RSSIngestionService.fetch_new_items` returns an in-memory list per generation run and only a slim `SourceItemRef` (title + link) survives on `UserEpisodeRecord.source_item_refs` for show-notes attribution. There is no persistent item collection in Firestore. Phase 1 introduces a global `source_items` collection (keyed by `dedupe_key`) so items are first-class and can carry embeddings, support cross-user dedup, and ground future "more like this" features.

**Mechanism:**

1. **Persistent items + embeddings.** Introduce a `source_items` Firestore collection. At ingest time, every newly-fetched item is upserted (keyed by `dedupe_key`) with an embedding of `title + summary` from **OpenAI `text-embedding-3-small`** (1536 dims, ~$0.02 / 1M tokens). Embedding stored as `array<double>` on the same doc. No backfill needed — items have always been ephemeral; the corpus accrues from the first run after deploy.
2. **Swipe storage.** New Firestore collection: `{user_id, source_item_id, direction (+1/-1), embedding_snapshot, timestamp}`. Embedding is snapshotted onto the swipe so the vector survives even if the source item later rolls off / is repriced / is re-embedded with a different model.
3. **User interest vector.** Computed on demand (or cached per user with a short TTL) as `mean(right-swipe vectors) − mean(left-swipe vectors)`, L2-normalized. Cheap enough to recompute per generation run at expected scale.
4. **Ranker step in script generation.** Before `build_digest_prompt`, score each candidate item by cosine similarity to the user vector and take the top-N. Falls back to current group-membership filtering when the user has fewer than ~5 swipes.
5. **Cold-start deck.** Endpoint `GET /v1/swipe-deck/cold-start` returns ~15–20 items chosen as k-means cluster centers across the full corpus, so the first swipes deliberately probe different regions of interest space rather than reinforcing one. Refresh weekly via a Cloud Scheduler job.
6. **iOS swipe UI.** New onboarding step replaces the topics picker: card stack, swipe right = more like this, left = less. Post-onboarding, surface a "tune your pod" deck (3–5 candidate items from the next episode pool) after each episode to keep the signal fresh.

**Vector store choice:** Firestore (vectors as `array<double>` on the new `source_items` collection). Cosine similarity computed in app code. Fine up to ~10k items; revisit (pgvector on Cloud SQL) when corpus growth or per-generation latency makes the linear scan painful.

**Sequencing:**

1. Backend: persistent `source_items` collection + embedding at ingest. Ingestion still returns the in-memory list to the existing generation path; no selection-behavior change yet, but every fetched item is now stored and embedded.
2. Backend: swipe collection, user-vector computation, ranker step behind a feature flag. Topics-based selection stays default.
3. Backend: cold-start k-means deck endpoint + weekly refresh job.
4. iOS: swipe UI in onboarding (replacing topics step) + post-episode "tune your pod" deck.
5. Flip the flag; demote topic groupings to Sources-tab grouping + cold-start fallback only.

**Open questions:**

- How does this interact with the welcome episode? It currently covers "we have nothing yet" — does it stay generic, or do we wait for the first ~10 swipes before generating it?
- Negative-swipe weighting: does a left-swipe count as `−1` against the centroid, or does it just remove the item from candidate pools without poisoning the vector? (Strong negatives can drag the centroid into a meaningless region.)
- Source-level vs item-level: do users still want to add/remove *sources* explicitly (current Sources tab), or does swiping eventually subsume that too?
- Inbound-email items (per-user `<alias>@theclawcast.com`) — should they bypass the ranker and always be included, or compete with everything else?
- Does the swipe deck itself need topic labels on the cards, or is a clean title-only card the right UX (forces the user to react to the *content*, not the category)?

## Deferred (not on public roadmap)

Ideas that were scoped and **explicitly deferred** — parked here so future sessions don't re-propose them from scratch. Resurfacing one = update its **Revisit trigger** line, don't append a new section.

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

#### 4b — iOS Share Sheet extension

**The idea:** New iOS Share target. User reads an article anywhere (Twitter, Safari, Apple News, Reeder, etc.) → taps Share → ClawCast. Backend `POST /v1/items/from-share` fetches/extracts/embeds the URL and writes a synthetic positive swipe.

**Why deferred:** high value but it lifts episode #2-N, not the first-episode "wow" moment we were optimizing for. The first wave was specifically about making episode #1 jaw-dropping; the share extension shines on day 7+ when the system reacts to the user's reading week.

**Implementation sketch when we pick it up:**
- New iOS extension target (`NewsletterPodShareExtension`) bundled with the main app.
- Extension reads the shared URL via `NSExtensionItem.attachments[].loadItem(forTypeIdentifier: "public.url")`.
- POSTs to a new backend endpoint that fetches the URL, runs through the existing source-item pipeline (extract title + summary, embed), creates a `SourceItemRecord` if new, and writes a `SwipeRecord` with direction=+1 + a `source: "share_extension"` tag (new field on SwipeRecord; weight in the interest vector unchanged).
- iOS Share extensions use the parent app's keychain for the session token — no re-auth.

#### 4c — Calendar / location nudges

**The idea:** Use CoreLocation (already imported for weather) and EventKit to seed weak interest signals — e.g., a Copenhagen-locale user gets a small `da-DK` local-news cluster boost; a user with calendar events tagged "ML research review" gets a topic seed.

**Why deferred:** low signal-to-noise. Location can already drive RSS catalog selection at a coarser level (locale-specific feeds). Calendar is invasive and rarely accurate — meeting titles are noisy proxies for interest.

**Revisit trigger:** if we ever ship a "local news" pod variant where locality is the primary lens.

#### Personalized welcome-episode opener

**The idea:** Today the welcome MP3 is bundled and generic ([welcome_episode_architecture.md](memory/welcome_episode_architecture.md)). With voice intake on day one, we *could* generate a 30s personalized opener at signup time and stitch it onto the front of the bundled MP3 via ffmpeg concat.

**Why deferred:** episode #1 (first real generation run) already carries the personalization weight — voice transcript phrases land in `customGuidance`, name-check layer echoes them. The welcome-MP3 splice adds TTS+ffmpeg latency to signup (3-10s) and gives the user the "wow" moment one step earlier, but at the cost of a synchronous TTS call on the sign-in critical path.

**Revisit trigger:** if onboarding-to-first-episode-listen funnel data shows users dropping off before episode #1 generates. Then the splice becomes worth the latency.

## Useful files

- `codemagic.yaml`: hosted macOS build and TestFlight workflow.
- `ios/project.yml`: XcodeGen project definition.
- `ios/README.md`: iOS-specific setup notes.
- `ios/NewsletterPodApp/AppConfiguration.swift`: backend URL and product IDs.
- `README.md`: backend and deployment documentation.
