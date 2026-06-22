import 'dart:async';

import 'package:flutter_test/flutter_test.dart';

import 'package:app/api/models.dart';
import 'package:app/data/fake_app_repository.dart';
import 'package:app/state/app_state.dart';

/// Counts fetchRun calls so a test can prove the resume hook actively re-checks
/// the run rather than relying on the periodic timer. Also signals when fetchMe
/// has been called, so a test can wait for the terminal-run follow-up
/// (`_finishRun -> loadMe -> fetchMe`) to settle before disposing — otherwise
/// loadMe's notifyListeners can land after dispose. fetchRun delegates to the
/// demo fake (which resolves to a terminal 'published' run).
class _CountingRepository extends FakeAppRepository {
  int fetchRunCalls = 0;
  final Completer<void> _fetchMeCompleter = Completer<void>();

  /// Completes the first time loadMe's fetchMe is invoked.
  Future<void> get fetchMeCalled => _fetchMeCompleter.future;

  @override
  Future<RunStatusEnvelope> fetchRun(String runId) {
    fetchRunCalls++;
    return super.fetchRun(runId);
  }

  @override
  Future<MeEnvelope> fetchMe() async {
    final me = await super.fetchMe();
    if (!_fetchMeCompleter.isCompleted) _fetchMeCompleter.complete();
    return me;
  }
}

/// Like [_CountingRepository] but fetchRun NEVER returns a terminal status, so
/// the poll loop keeps running — lets a test observe that a restarted periodic
/// timer actually ticks (rather than just the one-off resume tick firing).
class _NeverTerminatingRepository extends FakeAppRepository {
  int fetchRunCalls = 0;

  @override
  Future<RunStatusEnvelope> fetchRun(String runId) async {
    fetchRunCalls++;
    return RunStatusEnvelope(
      run: UserRunDto(
        id: runId,
        status: 'in_progress',
        message: 'Still generating…',
        candidateCount: 0,
        capHit: false,
      ),
    );
  }
}

void main() {
  test('resumePollingIfNeeded re-syncs an in-flight run on app resume', () async {
    // A long poll interval means the periodic timer will NOT fire during the
    // test, so the only thing that can resolve the run is the resume hook.
    final repo = _CountingRepository();
    final app = AppState(repo, pollInterval: const Duration(seconds: 30));

    await app.generateNow(); // fake returns a non-terminal 'queued' run + polls
    expect(app.isGenerating, isTrue);
    final callsAfterStart = repo.fetchRunCalls;

    app.resumePollingIfNeeded(); // simulates returning to the foreground
    // The terminal poll drives _finishRun -> loadMe -> fetchMe; wait for that
    // whole chain (plus one event-loop turn for loadMe's finally) to settle so
    // no notifyListeners lands after dispose.
    await repo.fetchMeCalled;
    await Future<void>.delayed(Duration.zero);

    expect(repo.fetchRunCalls, greaterThan(callsAfterStart));
    expect(app.isGenerating, isFalse); // fetchRun returned 'published' (terminal)

    app.dispose();
  });

  test('resumePollingIfNeeded restarts a poll timer lost while suspended',
      () async {
    // Drive the branch the hook exists for: the OS killed the periodic timer
    // while the isolate was suspended (_pollTimer == null), so resume must
    // re-create a live Timer.periodic — not just fire one ad-hoc tick.
    final repo = _NeverTerminatingRepository();
    final app = AppState(repo, pollInterval: const Duration(milliseconds: 20));

    await app.generateNow(); // starts polling; run never reaches a terminal state
    expect(app.isGenerating, isTrue);

    app.debugDropPollTimer(); // simulate the timer being lost on suspend
    final before = repo.fetchRunCalls;

    app.resumePollingIfNeeded();
    // Let the restarted periodic timer tick several times.
    await Future<void>.delayed(const Duration(milliseconds: 120));

    expect(app.isGenerating, isTrue); // never terminal, so still polling
    // More than the single one-off resume tick => the periodic timer was
    // genuinely restarted and is firing on its own.
    expect(repo.fetchRunCalls, greaterThan(before + 1));

    app.dispose();
  });

  test('resumePollingIfNeeded is a no-op when no run is in flight', () async {
    final repo = _CountingRepository();
    final app = AppState(repo, pollInterval: const Duration(seconds: 30));

    app.resumePollingIfNeeded();
    await Future<void>.delayed(const Duration(milliseconds: 20));

    expect(app.isGenerating, isFalse);
    expect(repo.fetchRunCalls, 0);

    app.dispose();
  });
}
