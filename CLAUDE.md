# CLAUDE.md

Internal scratch for ideas that are explicitly **not** on the public roadmap (`NEXT_STEPS.md`) — parking lot for things we considered, scoped, and chose to defer. Future Claude sessions should read this before proposing something that already lives here.

## Deferred ideas — cold-start personalization (logged 2026-05-15)

Context: stacked recommendation 1+2+3a+3b+4a+5 was shipped (voice intake, swipe onboarding, Substack paste, forwarded-mail weighting, alias-prominence, name-check). The items below were scoped at the same time but **explicitly deferred**.

### 3c — Gmail OAuth scan

**The idea:** Google Sign-In with `gmail.readonly` scope → scan the last 30-90 days for newsletter-like senders (List-Unsubscribe header, stable sender domains) → surface a "subscribe to these in ClawCast?" picker. Substack ones route through the existing autosubscribe flow; others get a one-tap "create Gmail filter forwarding to your alias" instruction.

**Why deferred:**
- Gmail readonly is a [Google restricted scope](https://developers.google.com/identity/protocols/oauth2/production-readiness/restricted-scope-verification) — requires an annual CASA security audit ($15-25k/year).
- Apple Review pushback risk: requiring a Google login for an app that already supports Sign-In with Apple invites scrutiny.
- Heavier privacy disclosure friction at sign-in.
- The active-paste (3a) + forwarded-mail (3b) flows already get ~70% of the same signal at <5% of the cost.

**Revisit trigger:** when paid retention numbers justify the audit cost (probably >5000 paying users, or when the per-user value of "I never have to manage subscriptions" becomes the dominant retention lever).

### 4b — iOS Share Sheet extension

**The idea:** New iOS Share target. User reads an article anywhere (Twitter, Safari, Apple News, Reeder, etc.) → taps Share → ClawCast. Backend `POST /v1/items/from-share` fetches/extracts/embeds the URL and writes a synthetic positive swipe.

**Why deferred:** high value but it lifts episode #2-N, not the first-episode "wow" moment we were optimizing for. The first wave was specifically about making episode #1 jaw-dropping; the share extension shines on day 7+ when the system reacts to the user's reading week.

**Implementation sketch when we pick it up:**
- New iOS extension target (`NewsletterPodShareExtension`) bundled with the main app.
- Extension reads the shared URL via `NSExtensionItem.attachments[].loadItem(forTypeIdentifier: "public.url")`.
- POSTs to a new backend endpoint that fetches the URL, runs through the existing source-item pipeline (extract title + summary, embed), creates a `SourceItemRecord` if new, and writes a `SwipeRecord` with direction=+1 + a `source: "share_extension"` tag (new field on SwipeRecord; weight in the interest vector unchanged).
- iOS Share extensions use the parent app's keychain for the session token — no re-auth.

### 4c — Calendar / location nudges

**The idea:** Use CoreLocation (already imported for weather) and EventKit to seed weak interest signals — e.g., a Copenhagen-locale user gets a small `da-DK` local-news cluster boost; a user with calendar events tagged "ML research review" gets a topic seed.

**Why deferred:** low signal-to-noise. Location can already drive RSS catalog selection at a coarser level (locale-specific feeds). Calendar is invasive and rarely accurate — meeting titles are noisy proxies for interest.

**Revisit trigger:** if we ever ship a "local news" pod variant where locality is the primary lens.

### Personalized welcome-episode opener

**The idea:** Today the welcome MP3 is bundled and generic ([welcome_episode_architecture.md](memory/welcome_episode_architecture.md)). With voice intake on day one, we *could* generate a 30s personalized opener at signup time and stitch it onto the front of the bundled MP3 via ffmpeg concat.

**Why deferred:** episode #1 (first real generation run) already carries the personalization weight — voice transcript phrases land in `customGuidance`, name-check layer echoes them. The welcome-MP3 splice adds TTS+ffmpeg latency to signup (3-10s) and gives the user the "wow" moment one step earlier, but at the cost of a synchronous TTS call on the sign-in critical path.

**Revisit trigger:** if onboarding-to-first-episode-listen funnel data shows users dropping off before episode #1 generates. Then the splice becomes worth the latency.

### What NOT to add here

This file is for ideas the current session **considered and chose to defer**. It is not a general notebook. Roadmap items belong in `NEXT_STEPS.md`. Active project context belongs in memory (`.claude/projects/.../memory/`). Resurfacing a deferred idea = update the entry's "Revisit trigger" line, don't append a new section.
