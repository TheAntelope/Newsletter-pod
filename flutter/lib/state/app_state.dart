import 'dart:async';

import 'package:flutter/widgets.dart';

import '../api/api_client.dart';
import '../api/models.dart';
import '../config.dart';
import '../data/api_app_repository.dart';
import '../data/app_repository.dart';
import '../services/auth_controller.dart';
import '../services/messaging_controller.dart';
import '../services/purchases_controller.dart';
import '../services/share_tip_store.dart';

/// Single observable app-state store (the Flutter analogue of iOS AppViewModel).
/// Holds session + the `/v1/me` snapshot and drives the screens via [AppScope].
class AppState extends ChangeNotifier {
  // `_apiClient` is assigned from a differently-named param in the initializer
  // list, so it can't be an initializing formal like the poll-timing fields.
  AppState(
    this._repository, {
    ApiClient? apiClient,
    ShareTipStore? shareTipStore,
    this._pollInterval = const Duration(seconds: 3),
    this._pollMaxAttempts = 120,
  })  : _apiClient = apiClient, // ignore: prefer_initializing_formals
        _shareTipStore = shareTipStore ?? InMemoryShareTipStore() {
    _shareTipDismissed = _shareTipStore.dismissed;
  }

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

  /// True from the moment a generation run is kicked off until the run reaches a
  /// terminal status (polled via [_repository.fetchRun]) or the poll times out.
  /// The progress bar caps at 95% while this is true and the run's real outcome
  /// is surfaced through [runNotice] (non-published) or a refreshed episode list.
  bool _generating = false;
  bool get isGenerating => _generating;

  /// Wall-clock moment the current run was kicked off, used by the self-pacing
  /// [GenerationProgressBar] to compute elapsed progress. Lives here (not in the
  /// bar's State) so the progress survives the bar being recycled out of the
  /// home ListView while scrolling — otherwise the bar restarts at 0% and the
  /// run appears to reset. Null whenever no run is in flight.
  DateTime? _generationStartedAt;
  DateTime? get generationStartedAt => _generationStartedAt;

  /// A user-facing message for a finished run that produced no episode (quota
  /// reached, no sources, no fresh content, or a failure). Null while a run is
  /// in flight or after a successful publish. Cleared on [clearRunNotice], the
  /// next [generateNow], and sign-out.
  String? _runNotice;
  String? get runNotice => _runNotice;

  /// Whether the early-adopter trial-gift card has been acknowledged this
  /// session. The card shows while `entitlements.trialGiftPending` is true and
  /// this flag is false; tapping "Got it" flips it optimistically so the card
  /// disappears immediately, ahead of the backend ack landing. Per-session (not
  /// persisted) — the durable state is the backend `trial_gift_acknowledged_at`,
  /// which clears `trialGiftPending` on the next `loadMe`. Reset on sign-out.
  bool _trialGiftDismissed = false;
  bool get trialGiftDismissed => _trialGiftDismissed;

  /// Acknowledges the trial gift: hides the card immediately, then fires the
  /// backend ack in the background. No-ops without a live ApiClient/session
  /// (demo build / widget tests), exactly like [_registerForPush]. The ack is
  /// idempotent server-side, so an unobserved failure just leaves the card to
  /// reappear on the next launch — acceptable for a one-time courtesy card.
  void acknowledgeTrialGift() {
    if (_trialGiftDismissed) return;
    _trialGiftDismissed = true;
    notifyListeners();
    final client = _apiClient;
    final session = _sessionToken;
    if (client == null || session == null) return;
    unawaited(
      client.acknowledgeTrialGift(session).catchError((_) {
        // Best-effort; the card stays hidden this session regardless.
      }),
    );
  }

  /// Redeems a promo code via the backend, then reloads `me` so the extended
  /// trial window (and the resulting Max entitlements) surface immediately.
  /// Returns the number of days granted. Throws [ApiException] (its `message` is
  /// a user-facing reason) so the caller can show it; requires a live session
  /// (real-auth build) — throws [ApiException] otherwise rather than silently
  /// no-op'ing, since the user is actively waiting on a result.
  Future<int> redeemPromoCode(String code) async {
    final client = _apiClient;
    final session = _sessionToken;
    if (client == null || session == null) {
      throw ApiException('Sign in to redeem a code.');
    }
    final days = await client.redeemPromoCode(session, code.trim());
    await loadMe();
    return days;
  }

  /// Whether the "where did you find us?" card has been answered or skipped
  /// this session. The card shows during generation while the user's
  /// `acquisitionSource` is still null and this flag is false; answering or
  /// skipping flips it optimistically so it disappears immediately, ahead of
  /// the backend write landing. Per-session — the durable state is the backend
  /// `acquisition_source`, which the response refreshes into `me`. Reset on
  /// sign-out so the next user is asked.
  bool _acquisitionPromptDismissed = false;
  bool get acquisitionPromptDismissed => _acquisitionPromptDismissed;

  /// Records where the user found us: hides the card immediately, then writes
  /// to the backend and folds the refreshed `me` back in (so the gate stays
  /// closed across a reload). No-ops without a live ApiClient/session (demo
  /// build / widget tests), like [acknowledgeTrialGift]. Best-effort: an
  /// unobserved failure just leaves the card hidden for this session.
  void recordAcquisitionSource(String source, {String? detail}) {
    if (_acquisitionPromptDismissed) return;
    _acquisitionPromptDismissed = true;
    notifyListeners();
    final client = _apiClient;
    final session = _sessionToken;
    if (client == null || session == null) return;
    unawaited(
      client
          .recordAcquisitionSource(session, source: source, detail: detail)
          .then((env) {
        _me = env;
        notifyListeners();
      }).catchError((_) {
        // Best-effort; the card stays hidden this session regardless.
      }),
    );
  }

  /// The "Skip" affordance on the acquisition card. Records a decline so the
  /// backend stops asking and we can measure the skip rate.
  void skipAcquisitionPrompt() => recordAcquisitionSource('skipped');

  /// Persists the share-tip dismissal across launches on the real-auth build
  /// (the demo build / tests use an in-memory stub — see [ShareTipStore]).
  final ShareTipStore _shareTipStore;

  /// Whether the dashboard's "share from anywhere" teach card has been
  /// dismissed. The share feature is invisible (it lives in the OS share sheet,
  /// not an in-app button), so the card educates users it exists. Seeded from
  /// [_shareTipStore] at construction and written back through it on dismiss, so
  /// once a user dismisses it on the real build it stays gone across launches.
  bool _shareTipDismissed = false;
  bool get shareTipDismissed => _shareTipDismissed;

  void dismissShareTip() {
    if (_shareTipDismissed) return;
    _shareTipDismissed = true;
    unawaited(_shareTipStore.setDismissed(true));
    notifyListeners();
  }

  /// Run-status polling cadence + ceiling. Defaults suit production; widget
  /// tests dispose the store before a tick fires, so they keep the defaults.
  final Duration _pollInterval;
  final int _pollMaxAttempts;

  Timer? _pollTimer;
  String? _pollRunId;
  int _pollAttempts = 0;

  static const _terminalRunStatuses = {
    'published',
    'skipped',
    'no_content',
    'pre_access',
    'failed',
  };

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
    // Never forward the provider name on the exchange — see [_applySession].
    final session = await client!.signInWithFirebase(idToken);
    await _applySession(session, displayName: displayName);
  }

  /// Real sign-in via **Sign in with Apple**: exchange the Apple identity token
  /// at [ApiClient.signInWithApple] (→ `/v1/auth/apple`, NOT Firebase) so an
  /// existing iOS user resolves to their same backend account by Apple `sub`,
  /// preserving subscription/sources/history. Mirrors the Firebase path; the
  /// backend's cross-provider linking unifies Apple+Google by verified email.
  Future<void> signInWithAppleToken(
    String identityToken, {
    String? displayName,
  }) async {
    final client = _apiClient;
    assert(client != null,
        'signInWithAppleToken requires an ApiClient (real-auth build only)');
    // Never forward the provider name on the exchange — see [_applySession].
    final session = await client!.signInWithApple(identityToken);
    await _applySession(session, displayName: displayName);
  }

  /// Shared post-exchange wiring for both real sign-in providers: swap in the
  /// live [ApiAppRepository], route new users into onboarding, load `me`, seed
  /// the greeting name for brand-new accounts, and kick off push + purchases.
  ///
  /// Never forward the Google/Apple display name on the token exchange itself:
  /// the app-entered value (onboarding / account settings) is authoritative, and
  /// re-sending the account name on returning sign-ins is what made greetings
  /// revert. The account name is only a one-time fallback for a brand-new
  /// account that hasn't picked a name yet (seeded below).
  Future<void> _applySession(
    SessionEnvelope session, {
    String? displayName,
  }) async {
    final client = _apiClient!;
    _repository = ApiAppRepository(client, session.sessionToken);
    _sessionToken = session.sessionToken;
    _signedIn = true;
    _onboardingComplete = !session.isNewUser;
    notifyListeners();
    await loadMe();
    final seed = displayName?.trim() ?? '';
    if (session.isNewUser &&
        seed.isNotEmpty &&
        !(_me?.user.hasFriendlyName ?? false)) {
      try {
        await _repository.updateProfile(
          displayName: seed,
          timezone: _me?.user.timezone ?? 'UTC',
        );
        await loadMe();
      } catch (_) {
        // Account-name seed is best-effort; ignore failures.
      }
    }
    // Best-effort: register this device for FCM push. Fire-and-forget so a
    // denied permission or messaging hiccup never blocks the signed-in UI.
    unawaited(_registerForPush());
    // Best-effort: identify the user to RevenueCat so purchases + the billing
    // webhook line up on our backend user id.
    unawaited(_configurePurchases());
  }

  /// Configures RevenueCat with our backend user id. No-ops unless the
  /// purchases flag + Android key are set; never throws into the sign-in flow.
  Future<void> _configurePurchases() async {
    final userId = _me?.user.id;
    if (userId == null) return;
    try {
      await PurchasesController.configureAndLogin(userId);
    } catch (_) {
      // Best-effort; billing init must never block the signed-in UI.
    }
  }

  /// Requests notification permission, registers the FCM token with the backend
  /// (platform from the device, transport=fcm on both), and wires foreground
  /// display + tap routing. No-ops without a live ApiClient/session, and never
  /// throws into the sign-in flow.
  Future<void> _registerForPush() async {
    final client = _apiClient;
    final session = _sessionToken;
    if (client == null || session == null) return;
    try {
      // Constructed inside the try because the constructor itself touches
      // FirebaseMessaging.instance, which throws when Firebase isn't
      // initialized (demo build / unit tests) — messaging init must never
      // surface into the sign-in flow.
      final messaging = MessagingController();
      // Wire foreground display + tap handling once; a tap on a "pod ready"
      // push refreshes the signed-in snapshot so the new episode shows up.
      await messaging.configure(onOpened: _handlePushOpened);
      final fcmToken = await messaging.requestPermissionAndToken();
      if (fcmToken == null || fcmToken.isEmpty) return;
      await client.registerDeviceToken(
        session,
        deviceToken: fcmToken,
        environment: 'production',
        bundleId: 'com.newsletterpod.app',
        platform: messaging.platform,
        transport: messaging.transport,
      );
    } catch (_) {
      // Push registration is best-effort; ignore failures.
    }
  }

  /// Handles a notification tap. For a "pod ready" push we just reload `me` so
  /// the freshly-published episode surfaces; the data map also carries
  /// `episode_id` / `feed_url` for future deep-linking.
  void _handlePushOpened(Map<String, dynamic> data) {
    if (data['type'] == 'pod_ready') {
      unawaited(loadMe());
    } else if (data['type'] == 'trial_gift') {
      // Refresh so `trial_gift_pending` is fresh and the gift card surfaces on
      // the home screen.
      unawaited(loadMe());
    }
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
    _runNotice = null;
    _generating = true;
    _generationStartedAt = DateTime.now();
    notifyListeners();
    final UserRunDto run;
    try {
      final result = await _repository.generateNow();
      run = result.run;
      _lastRunMessage = run.message;
    } catch (e) {
      _error = e.toString();
      _generating = false;
      _generationStartedAt = null;
      notifyListeners();
      return;
    }
    // A run can come back already terminal (e.g. an immediate quota skip); only
    // poll while it's still in flight, and only if we got an id to poll on.
    if (_terminalRunStatuses.contains(run.status)) {
      await _finishRun(run, null);
    } else if (run.id != null) {
      notifyListeners();
      _startPolling(run.id!);
    } else {
      notifyListeners();
    }
  }

  /// Called when the app returns to the foreground. If a generation run is still
  /// in flight, force an immediate status re-check (and restart the poll loop if
  /// its timer was lost while the isolate was suspended) so a run that finished —
  /// or was reaped server-side after stalling — while we were backgrounded
  /// surfaces right away instead of waiting for the next periodic tick. No-op
  /// when no run is in flight, so it's safe to call on every resume.
  ///
  /// The server-side stale-run reaper guarantees an orphaned run eventually
  /// reaches a terminal `failed` status, so this never leaves the UI stuck even
  /// if a long-backgrounded run keeps restarting the local poll loop.
  void resumePollingIfNeeded() {
    if (!_generating || _pollRunId == null) return;
    if (_pollTimer == null) {
      // The timer was cancelled/lost while suspended — restart it. This also
      // resets the attempt ceiling, intentionally extending the polling window
      // for a run that was backgrounded for a long time.
      _startPolling(_pollRunId!);
    }
    // Fire one tick now rather than waiting up to _pollInterval for the result.
    unawaited(_pollTick());
  }

  /// Test-only: simulate the OS killing the periodic poll timer while the
  /// isolate was suspended in the background — cancels the timer but leaves the
  /// in-flight run state intact, so [resumePollingIfNeeded] must restart it.
  @visibleForTesting
  void debugDropPollTimer() {
    _pollTimer?.cancel();
    _pollTimer = null;
  }

  void _startPolling(String runId) {
    _pollTimer?.cancel();
    _pollRunId = runId;
    _pollAttempts = 0;
    _pollTimer = Timer.periodic(_pollInterval, (_) => _pollTick());
  }

  void _stopPolling() {
    _pollTimer?.cancel();
    _pollTimer = null;
    _pollRunId = null;
  }

  Future<void> _pollTick() async {
    final runId = _pollRunId;
    if (runId == null || !_generating) {
      _stopPolling();
      return;
    }
    _pollAttempts++;
    RunStatusEnvelope env;
    try {
      env = await _repository.fetchRun(runId);
    } catch (_) {
      // Transient network error — keep polling until the attempt ceiling.
      if (_pollAttempts >= _pollMaxAttempts) _timeoutPolling();
      return;
    }
    // Bail if this tick was superseded (cancelled, signed out, or a newer run)
    // while fetchRun was in flight.
    if (_pollTimer == null || _pollRunId != runId) return;
    if (_terminalRunStatuses.contains(env.run.status)) {
      _stopPolling();
      await _finishRun(env.run, env.episode);
    } else if (_pollAttempts >= _pollMaxAttempts) {
      _timeoutPolling();
    }
  }

  void _timeoutPolling() {
    _stopPolling();
    _generating = false;
    _generationStartedAt = null;
    // The run may still finish server-side and arrive via push / next refresh.
    _runNotice = "Still working on your episode — it'll appear here and in your "
        'feed shortly.';
    notifyListeners();
  }

  /// Apply a terminal run outcome: drop the generating flag, surface a notice
  /// for non-published outcomes, and refresh `me` so episode + entitlement
  /// counts reflect the run.
  Future<void> _finishRun(UserRunDto run, UserEpisodeDto? episode) async {
    _generating = false;
    _generationStartedAt = null;
    _runNotice = run.status == 'published' ? null : _friendlyRunOutcome(run);
    notifyListeners();
    // Refresh entitlements (pods-left) and, on success, the latest episode.
    await loadMe();
  }

  String _friendlyRunOutcome(UserRunDto run) {
    switch (run.status) {
      case 'failed':
        return 'Something went wrong generating this episode. Please try again.';
      case 'no_content':
        return run.message.isNotEmpty
            ? run.message
            : "There wasn't enough fresh material for an episode yet.";
      default: // skipped, pre_access — backend messages here are user-facing.
        return run.message.isNotEmpty
            ? run.message
            : "Your episode wasn't generated.";
    }
  }

  void clearRunNotice() {
    if (_runNotice == null) return;
    _runNotice = null;
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
    // No-ops unless the purchases flag + key are set.
    unawaited(PurchasesController.logOut());
    _stopPolling();
    _signedIn = false;
    _onboardingComplete = false;
    _me = null;
    _sessionToken = null;
    _lastRunMessage = null;
    _generating = false;
    _generationStartedAt = null;
    _runNotice = null;
    // Per-user, per-session: the next signed-in user must see their own gift
    // card if the backend still reports it pending.
    _trialGiftDismissed = false;
    // Same — the next user gets their own "where did you find us?" prompt.
    _acquisitionPromptDismissed = false;
    // The tip is per-device education, not per-user state — keep whatever the
    // store persisted rather than forcing it back on for the next sign-in.
    _shareTipDismissed = _shareTipStore.dismissed;
    _error = null;
    notifyListeners();
  }

  @override
  void dispose() {
    _pollTimer?.cancel();
    super.dispose();
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

  /// Non-subscribing lookup for use OUTSIDE build — e.g. lifecycle callbacks and
  /// event handlers. Unlike [of] it uses [BuildContext.getInheritedWidgetOfExactType],
  /// which does NOT register the caller as a dependent of [AppScope], so reading
  /// it from a widget that doesn't depend on AppScope in build() won't silently
  /// subscribe it to rebuild on every notify. Returns null if no AppScope exists.
  static AppState? maybeOf(BuildContext context) {
    return context.getInheritedWidgetOfExactType<AppScope>()?.notifier;
  }
}
