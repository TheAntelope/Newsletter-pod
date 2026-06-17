import Flutter
import UIKit
import receive_sharing_intent

// Classic (pre-UIScene) Flutter lifecycle. We intentionally do NOT adopt the
// UIScene lifecycle (no FlutterImplicitEngineDelegate / FlutterSceneDelegate),
// because Flutter 3.44's UIScene template crashes at launch on iOS 26 in scene
// state-restoration. Plugins are registered here in didFinishLaunchingWithOptions;
// the window is created from Main.storyboard via UIMainStoryboardFile. See the
// note in pubspec.yaml (enable-uiscene-migration: false) and flutter#183586.
@main
@objc class AppDelegate: FlutterAppDelegate {
  override func application(
    _ application: UIApplication,
    didFinishLaunchingWithOptions launchOptions: [UIApplication.LaunchOptionsKey: Any]?
  ) -> Bool {
    GeneratedPluginRegistrant.register(with: self)
    return super.application(application, didFinishLaunchingWithOptions: launchOptions)
  }

  // Route the share extension's `ShareMedia-<bundleid>` reopen URL to
  // receive_sharing_intent so the shared item is read out of the App Group and
  // delivered to ShareIntakeController. Other URLs (notably Google Sign-In's
  // OAuth callback) fall through to super, which forwards them to the right
  // plugin. This explicit routing is required precisely because more than one
  // plugin implements application(_:open:options:) — without it the first
  // delegate to claim the URL wins and shares are silently dropped.
  override func application(
    _ app: UIApplication,
    open url: URL,
    options: [UIApplication.OpenURLOptionsKey: Any] = [:]
  ) -> Bool {
    let sharingIntent = SwiftReceiveSharingIntentPlugin.instance
    if sharingIntent.hasMatchingSchemePrefix(url: url) {
      return sharingIntent.application(app, open: url, options: options)
    }
    return super.application(app, open: url, options: options)
  }
}
