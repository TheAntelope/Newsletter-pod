# iOS Share Extension setup (Flutter cut-over, Workstream E)

Parity for the native `NewsletterPodShareExtension`: let users push a link / article /
document into ClawCast from another app's share sheet. Backend is unchanged — both clients
hit `POST /v1/items/shared`. The Flutter flow differs from native: the extension just stashes
the shared item in the App Group and **reopens the app**, which reads it via
`receive_sharing_intent` and shows `ShareIntakeScreen` (so the upload happens in-app, where the
session token already lives — **the extension itself needs no auth**, which is why it
deliberately has **no** `keychain-access-groups` entitlement, unlike the native one).

> **Status (2026-06):** the Xcode **target is now committed** in
> `flutter/ios/Runner.xcodeproj/project.pbxproj` — it was hand-wired into the pbxproj (no Mac
> required). The only remaining manual step is the one-time **Apple Developer Portal** App-Group
> assignment (no API exists for it). See *Portal* below.

## Design: self-contained extension (do NOT re-add a plugin dependency)

`ShareViewController.swift` is **self-contained** — it does **not** `import receive_sharing_intent`
and subclasses `SLComposeServiceViewController` directly. This is deliberate:

- `receive_sharing_intent` ships **only a CocoaPods podspec** (no `Package.swift`), and this app
  integrates Flutter plugins via **Swift Package Manager** (`FlutterGeneratedPluginSwiftPackage`,
  no committed Podfile). A CocoaPods-only plugin module therefore cannot be linked into an
  app-extension target without bolting CocoaPods onto the build *just* for the extension.
- Instead the extension **vendors** the tiny (MIT) extension-side logic from the plugin and
  reproduces its **App-Group wire format byte-for-byte**: it writes a JSON `[SharedMediaFile]` to
  `UserDefaults(suiteName: group.com.newsletterpod.shared)` under key **`ShareKey`** (+ the post
  message under `ShareMessageKey`), then reopens the host via `ShareMedia-<hostbundleid>:share`.
  The **host app still uses the plugin normally** to read that payload
  (`SwiftReceiveSharingIntentPlugin.handleUrl`).

⚠️ Keep the wire format in `ShareViewController.swift` (the `kUserDefaultsKey` constants, the
`SharedMediaFile` coding keys, and the `SharedMediaType` raw values) in lock-step with the pinned
`receive_sharing_intent` version (`pubspec.yaml`: `^1.8.0`). If you bump the plugin, re-diff
`RSIShareViewController.swift` / `SwiftReceiveSharingIntentPlugin.swift`. **Do not** "fix" the
extension by adding a framework dependency — its Frameworks build phase is intentionally empty
(only system frameworks `Social`/`UIKit`, auto-linked via Clang modules).

## Committed (no action needed)
- `flutter/ios/Runner.xcodeproj/project.pbxproj` — the **`Share Extension`** app-extension target
  (bundle id `com.newsletterpod.app.share`): Sources/Resources/Frameworks phases; Debug/Release/
  Profile configs whose `baseConfigurationReference` is Flutter's Debug/Release `.xcconfig` so
  `$(FLUTTER_BUILD_NUMBER)`/`$(FLUTTER_BUILD_NAME)` resolve (keeps the appex version in lockstep
  with the app — required for App Store validation); `DEVELOPMENT_TEAM` pinned; embedded into
  Runner via an **Embed Foundation Extensions** copy-files phase (`dstSubfolderSpec = 13`, PlugIns)
  placed **before** Flutter's *Thin Binary* phase; Runner has a target dependency on the extension.
- `flutter/ios/Share Extension/ShareViewController.swift` — self-contained capture + redirect (see above).
- `flutter/ios/Share Extension/Info.plist` — `NSExtension` activation for **text + web URL + attachment/file** (pdf/epub/docx; no image/video); App Group **hardcoded**; version pinned to the app.
- `flutter/ios/Share Extension/Share Extension.entitlements` — App Group `group.com.newsletterpod.shared` (and nothing else).
- `flutter/ios/Share Extension/Base.lproj/MainInterface.storyboard` — instantiates `ShareViewController` (customModuleProvider = target).
- `flutter/ios/Runner/Info.plist` — `AppGroupId` (hardcoded) + `CFBundleURLTypes` (`ShareMedia-$(PRODUCT_BUNDLE_IDENTIFIER)`).
- `flutter/ios/Runner/Runner.entitlements` — App Group `group.com.newsletterpod.shared`.
- `flutter/ios/Runner/AppDelegate.swift` — routes the `ShareMedia-<bundleid>` reopen URL to the
  plugin and falls through to `super` for other URLs (e.g. Google Sign-In). `main` runs the classic
  (pre-UIScene) Flutter lifecycle — deliberately, because the UIScene template crashes at launch on
  iOS 26 (PR #62) — so this `application(_:open:options:)` override is the active delivery path for
  shares (not a no-op).

The App Group id is **hardcoded** to `group.com.newsletterpod.shared` in both Info.plists and both
entitlements (the plugin reads the `AppGroupId` Info.plist key directly). So there is **no
`CUSTOM_GROUP_ID` build setting** to configure — one less thing to get wrong.

## Apple Developer Portal (one-time, manual — the only thing CI can't do)
The App Group `group.com.newsletterpod.shared` and bundle id `com.newsletterpod.app.share` are
**already registered** (the native build uses them). Confirm the App Group is **assigned to both**
`com.newsletterpod.app` **and** `com.newsletterpod.app.share`: Identifiers → each bundle id → App
Groups → Configure → tick `group.com.newsletterpod.shared` → Continue → **Save** (the Save at the
top-right of the bundle-id page, not just the popup's Continue — easy to miss). App-Group
assignment has **no API** — this manual click is the single most likely first-build signing
failure. The `ios-flutter-testflight` signing step now **dumps `bundle-ids capabilities` for both
ids**, so a missing App Group shows up in the log instead of as an opaque codesign rejection.

## Codemagic
`codemagic.yaml` → `ios-flutter-testflight` (manual-trigger; the native `ios-testflight` stays the
production pipeline during coexistence). The signing step regenerates fresh App Store profiles for
**both** bundle ids against the newest distribution cert (exact-identifier match to avoid the
`--bundle-id-identifier` *prefix* trap) and runs `xcode-project use-profiles`, which injects manual
signing per target by bundle id. Both bundle ids are **mandatory** — a missing
`com.newsletterpod.app.share` fails the cheap signing step rather than the archive ~20 min later.

## Verify on a real device (acceptance)
Install the Flutter TestFlight build (uninstall the native app first to avoid two installs sharing
the App Group container). From another app, Share → **ClawCast** with (a) a link, (b) selected
text, (c) a PDF. Each should reopen ClawCast on `ShareIntakeScreen`, then "Pinned to your next pod."
after upload — the same end state the Android share flow produces. Sharing a **photo** (unsupported)
should simply dismiss without hanging or opening an empty app.
