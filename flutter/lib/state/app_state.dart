import 'dart:async';

import 'package:flutter/widgets.dart';

import '../api/api_client.dart';
import '../api/models.dart';
import '../config.dart';
import '../data/api_app_repository.dart';
import '../data/app_repository.dart';
import '../services/auth_controller.dart';

/// Single observable app-state store (the Flutter analogue of iOS AppViewModel).
/// Holds session + the `/v1/me` snapshot and drives the screens via [AppScope].
class AppState extends ChangeNotifier {
  // A private field can't be a named initializing formal (`this._apiClient`),
  // so it's assigned in the initializer list instead.
  // ignore: prefer_initializing_formals
  AppState(this._repository, {ApiClient? apiClient}) : _apiClient = apiClient;

  /// Swapped from the demo [FakeAppRepository] to a live [ApiAppRepository] by
  /// [applySession] once a real sign-in returns a session token.
  AppRepository _repository;

  /// Present only in the real-auth build (passed from `main`); used to build the
  /// live repository on sign-in. Null in the demo build and widget tests.
  final ApiClient? _apiClient;

  String? _sessionToken;
  String? get sessionToken => _sessionToken;

  /// Exposed so list screens can fetch their own data (sources, episodes, …)
  /// without funnelling every collection through this store.
  AppRepository get repository => _repository;

  bool _signedIn = false;
  bool get signedIn => _signedIn;

  bool _onboardingComplete = false;
  bool get onboardingComplete => _onboardingComplete;

  MeEnvelope? _me;
  MeEnvelope? get me => _me;

  bool _loading = false;
  bool get loading => _loading;

  String? _error;
  String? get error => _error;

  String? _lastRunMessage;
  String? get lastRunMessage => _lastRunMessage;

  /// True from the moment a generation run is kicked off. There's no run-status
  /// polling in this build, so it stays true (the progress bar caps at 95% and
  /// shows "you can leave the app") until sign-out — matching the iOS copy that
  /// the episode lands in the feed asynchronously.
  bool _generating = false;
  bool get isGenerating => _generating;

  /// Stubbed/demo sign-in (flag off): flips signed-in and loads `me` from the
  /// injected fake repository, then runs the onboarding wizard. The real path
  /// goes through [applySession] instead.
  Future<void> signIn() async {
    _signedIn = true;
    _onboardingComplete = false; // new sign-in runs the onboarding wizard
    notifyListeners();
    await loadMe();
  }

  /// Real sign-in: exchange a Firebase ID token for an app session via
  /// [ApiClient.signInWithFirebase], swap the demo repository for the live
  /// [ApiAppRepository] backed by the returned session token, route brand-new
  /// users into onboarding (existing users skip straight to the dashboard), and
  /// load `me`. Throws on a failed exchange so the caller can surface it.
  Future<void> signInWithFirebaseToken(
    String idToken, {
    String? displayName,
  }) async {
    final client = _apiClient;
    assert(client != null,
        'signInWithFirebaseToken requires an ApiClient (real-auth build only)');
    final session =
        await client!.signInWithFirebase(idToken, givenName: displayName);
    _repository = ApiAppRepository(client, session.sessionToken);
    _sessionToken = session.sessionToken;
    _signedIn = true;
    _onboardingComplete = !session.isNewUser;
    notifyListeners();
    await loadMe();
  }

  void completeOnboarding() {
    _onboardingComplete = true;
    notifyListeners();
  }

  /// Re-run the onboarding wizard (after a server-side algorithm reset) without
  /// signing the user out.
  void restartOnboarding() {
    _onboardingComplete = false;
    notifyListeners();
  }

  Future<void> loadMe() async {
    _loading = true;
    _error = null;
    notifyListeners();
    try {
      _me = await _repository.fetchMe();
    } catch (e) {
      _error = e.toString();
    } finally {
      _loading = false;
      notifyListeners();
    }
  }

  Future<void> generateNow() async {
    _error = null;
    _generating = true;
    notifyListeners();
    try {
      final result = await _repository.generateNow();
      _lastRunMessage = result.run.message;
    } catch (e) {
      _error = e.toString();
      _generating = false;
    }
    notifyListeners();
  }

  void signOut() {
    // Real-auth build: also clear the Firebase + cached Google account so the
    // next sign-in re-shows the picker (otherwise it silently reuses the
    // signed-in account). Fire-and-forget — routing reacts to the state change
    // below immediately. Skipped when the flag is off, so the demo build and
    // widget tests never touch a platform channel.
    if (FeatureFlags.googleSignIn) {
      unawaited(AuthController().signOut());
    }
    _signedIn = false;
    _onboardingComplete = false;
    _me = null;
    _sessionToken = null;
    _lastRunMessage = null;
    _generating = false;
    _error = null;
    notifyListeners();
  }
}

/// Exposes [AppState] to the widget tree and rebuilds dependents on notify.
class AppScope extends InheritedNotifier<AppState> {
  const AppScope({
    super.key,
    required AppState super.notifier,
    required super.child,
  });

  static AppState of(BuildContext context) {
    final scope = context.dependOnInheritedWidgetOfExactType<AppScope>();
    assert(scope != null, 'No AppScope found in the widget tree');
    return scope!.notifier!;
  }
}
