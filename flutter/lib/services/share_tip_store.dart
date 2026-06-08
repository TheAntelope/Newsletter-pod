import 'package:shared_preferences/shared_preferences.dart';

/// Persists the client-only UI flags ClawCast keeps across launches — currently
/// just whether the dashboard's "share from anywhere" teach card has been
/// dismissed. Injected into [AppState] so the demo build + widget tests use
/// [InMemoryShareTipStore] and never touch the shared_preferences platform
/// channel; the real-auth build loads [PrefsShareTipStore] in `main`.
abstract class ShareTipStore {
  bool get dismissed;
  Future<void> setDismissed(bool value);
}

/// Channel-free default for the demo build + widget tests — holds the flag in
/// memory only, so it resets each launch (matching the rest of [AppState]).
class InMemoryShareTipStore implements ShareTipStore {
  @override
  bool dismissed = false;

  @override
  Future<void> setDismissed(bool value) async => dismissed = value;
}

/// shared_preferences-backed store for the real-auth build. Construct via
/// [load], which reads the persisted value once at startup so [AppState] can
/// seed its flag synchronously.
class PrefsShareTipStore implements ShareTipStore {
  PrefsShareTipStore._(this._prefs, this.dismissed);

  static const _key = 'share_tip_dismissed';

  final SharedPreferences _prefs;

  @override
  bool dismissed;

  static Future<PrefsShareTipStore> load() async {
    final prefs = await SharedPreferences.getInstance();
    return PrefsShareTipStore._(prefs, prefs.getBool(_key) ?? false);
  }

  @override
  Future<void> setDismissed(bool value) async {
    dismissed = value;
    await _prefs.setBool(_key, value);
  }
}
