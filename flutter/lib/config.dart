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
}
