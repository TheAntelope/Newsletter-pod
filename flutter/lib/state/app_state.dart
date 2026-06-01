import 'package:flutter/widgets.dart';

import '../api/models.dart';
import '../data/app_repository.dart';

/// Single observable app-state store (the Flutter analogue of iOS AppViewModel).
/// Holds session + the `/v1/me` snapshot and drives the screens via [AppScope].
class AppState extends ChangeNotifier {
  AppState(this._repository);

  final AppRepository _repository;

  /// Exposed so list screens can fetch their own data (sources, episodes, …)
  /// without funnelling every collection through this store.
  AppRepository get repository => _repository;

  bool _signedIn = false;
  bool get signedIn => _signedIn;

  MeEnvelope? _me;
  MeEnvelope? get me => _me;

  bool _loading = false;
  bool get loading => _loading;

  String? _error;
  String? get error => _error;

  String? _lastRunMessage;
  String? get lastRunMessage => _lastRunMessage;

  /// Stubbed sign-in. The real flow exchanges a Firebase ID token via
  /// `ApiClient.signInWithFirebase` and swaps in an `ApiAppRepository`; for now
  /// it flips signed-in and loads `me` from the injected (fake) repository.
  Future<void> signIn() async {
    _signedIn = true;
    notifyListeners();
    await loadMe();
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
    try {
      final result = await _repository.generateNow();
      _lastRunMessage = result.run.message;
    } catch (e) {
      _error = e.toString();
    }
    notifyListeners();
  }

  void signOut() {
    _signedIn = false;
    _me = null;
    _lastRunMessage = null;
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
