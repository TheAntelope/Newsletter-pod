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
5. Create the StoreKit subscription products:
   - `com.newsletterpod.paid.monthly`
   - `com.newsletterpod.paid.annual`
6. In Codemagic, connect the GitHub repository:
   - `TheAntelope/Newsletter-pod`
7. In Codemagic, add an App Store Connect API key integration named `codemagic`.
8. In Codemagic, enable iOS App Store code signing for bundle ID `com.newsletterpod.app`.
9. Optional: set `APP_STORE_APPLE_ID` in Codemagic after the App Store Connect app record exists.
10. Run the `ios-testflight` workflow in Codemagic.

## Before the first real TestFlight build

1. Confirm the iOS app base URL points at the deployed backend in `ios/NewsletterPodApp/AppConfiguration.swift`.
2. Confirm the backend Cloud Run service is deployed and reachable.
3. Confirm Sign in with Apple backend settings are configured:
   - `APPLE_CLIENT_ID`
   - `SESSION_SIGNING_SECRET`
4. Confirm App Store subscription product IDs match the iOS app and backend defaults:
   - `com.newsletterpod.paid.monthly`
   - `com.newsletterpod.paid.annual`
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

## Useful files

- `codemagic.yaml`: hosted macOS build and TestFlight workflow.
- `ios/project.yml`: XcodeGen project definition.
- `ios/README.md`: iOS-specific setup notes.
- `ios/NewsletterPodApp/AppConfiguration.swift`: backend URL and product IDs.
- `README.md`: backend and deployment documentation.
