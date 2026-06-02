/// App configuration.
///
/// Override the API base URL at build/run time with
/// `--dart-define=CLAWCAST_API_BASE_URL=https://...`. Defaults to the production
/// Cloud Run service (europe-west1).
class AppConfig {
  AppConfig._();

  static const String apiBaseUrl = String.fromEnvironment(
    'CLAWCAST_API_BASE_URL',
    defaultValue: 'https://newsletter-pod-cdze2t26va-ew.a.run.app',
  );

  /// The Firebase project's **Web** OAuth client id (client_type 3 in
  /// `google-services.json`). google_sign_in needs this as `serverClientId` on
  /// Android to mint an ID token that Firebase will accept. Project
  /// `theclawcast-9a045`.
  static const String googleServerClientId =
      '650971509352-gjk0vjlo6e24slghbkpp53il7vbo30ra.apps.googleusercontent.com';
}

/// Compile-time feature flags (set via `--dart-define`).
class FeatureFlags {
  FeatureFlags._();

  /// When true, the sign-in screen runs the real Google→Firebase flow and the
  /// app swaps to the live [ApiAppRepository]. Defaults to **false** so the
  /// demo build (and all widget tests) stay on the in-memory FakeAppRepository
  /// and never initialize Firebase or touch a platform channel. Enable with
  /// `--dart-define=ENABLE_GOOGLE_SIGN_IN=true`.
  static const bool googleSignIn =
      bool.fromEnvironment('ENABLE_GOOGLE_SIGN_IN', defaultValue: false);
}
