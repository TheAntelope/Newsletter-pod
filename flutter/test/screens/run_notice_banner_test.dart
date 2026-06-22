import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:app/api/models.dart';
import 'package:app/data/fake_app_repository.dart';
import 'package:app/main.dart';
import 'package:app/state/app_state.dart';

/// A fake whose generation run finishes terminal-but-not-published, so the
/// run-status poll resolves into a [AppState.runNotice] and the dashboard
/// surfaces the `_RunNoticeBanner` instead of silently dropping the progress
/// bar. fetchRun returns `no_content` (a non-published terminal status).
class _NoContentRepository extends FakeAppRepository {
  @override
  Future<RunStatusEnvelope> fetchRun(String runId) async {
    return RunStatusEnvelope(
      run: UserRunDto(
        id: runId,
        status: 'no_content',
        message: "There wasn't enough fresh material for an episode yet.",
        candidateCount: 0,
        capHit: false,
      ),
    );
  }
}

void _useTallViewport(WidgetTester tester) {
  tester.view.physicalSize = const Size(1000, 2200);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.reset);
}

void main() {
  testWidgets(
    'a non-published run surfaces the run-notice banner, dismissable',
    (tester) async {
      _useTallViewport(tester);
      final appState = AppState(_NoContentRepository());
      await tester.pumpWidget(
        AppScope(notifier: appState, child: const ClawcastApp()),
      );

      await tester.tap(find.text('Get started'));
      await tester.pumpAndSettle();
      appState.completeOnboarding(); // skip the wizard
      // Dismiss the share-tip teach card so its close icon doesn't collide with
      // the run-notice banner's dismiss icon below.
      appState.dismissShareTip();
      await tester.pumpAndSettle();

      // Kick off a run; the fake start returns a non-terminal 'queued' run, so
      // AppState polls fetchRun, which resolves to 'no_content' -> runNotice.
      final generate = find.text('Generate now');
      await tester.ensureVisible(generate);
      await tester.pumpAndSettle();
      await tester.tap(generate);
      await tester.pump(); // isGenerating -> progress banner mounts
      await tester.pump(const Duration(milliseconds: 400)); // start resolves
      // Let the 3s poll timer fire and the terminal fetchRun + loadMe settle.
      await tester.pump(const Duration(seconds: 4));
      await tester.pumpAndSettle();

      // The run finished without an episode -> notice is set, banner shows.
      expect(appState.runNotice, isNotNull);
      expect(find.text('No episode this time'), findsOneWidget);
      expect(
        find.textContaining('enough fresh material'),
        findsOneWidget,
      );

      // Dismissing clears the notice and removes the banner.
      await tester.tap(find.byIcon(Icons.close));
      await tester.pumpAndSettle();
      expect(appState.runNotice, isNull);
      expect(find.text('No episode this time'), findsNothing);

      await tester.pumpWidget(const SizedBox()); // cancel any timers
    },
  );
}
