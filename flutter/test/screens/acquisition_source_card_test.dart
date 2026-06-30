import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:app/data/fake_app_repository.dart';
import 'package:app/main.dart';
import 'package:app/state/app_state.dart';

/// The "where did you find us?" card shows during the first-pod generation wait
/// (gated on the user's acquisitionSource being null, which the fake leaves
/// unset) and disappears the moment the user answers or skips. The fake
/// AppState has no ApiClient, so recordAcquisitionSource just flips the local
/// dismiss flag — exactly the demo/offline path.

void _useTallViewport(WidgetTester tester) {
  tester.view.physicalSize = const Size(1000, 2400);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.reset);
}

/// Boots the app, skips onboarding, and kicks off a generation so the dashboard
/// is showing the generation banner (isGenerating == true) with the prompt
/// eligible. Stops short of pumping the 3s status poll so the run stays in
/// flight and the card stays mounted.
Future<AppState> _toGeneratingDashboard(WidgetTester tester) async {
  _useTallViewport(tester);
  final appState = AppState(FakeAppRepository());
  await tester.pumpWidget(
    AppScope(notifier: appState, child: const ClawcastApp()),
  );

  await tester.tap(find.text('Get started'));
  await tester.pumpAndSettle();
  appState.completeOnboarding(); // skip the wizard
  appState.dismissShareTip(); // keep its card out of the way
  await tester.pumpAndSettle();

  final generate = find.text('Generate now');
  await tester.ensureVisible(generate);
  await tester.pumpAndSettle();
  await tester.tap(generate);
  await tester.pump(); // isGenerating -> banner + prompt mount
  await tester.pump(const Duration(milliseconds: 400)); // generateNow resolves
  return appState;
}

void main() {
  testWidgets('prompt shows during generation; a chip selection dismisses it',
      (tester) async {
    final appState = await _toGeneratingDashboard(tester);

    final prompt = find.text('Where did you find us?');
    expect(prompt, findsOneWidget);
    expect(appState.acquisitionPromptDismissed, isFalse);

    final chip = find.text('Reddit');
    await tester.ensureVisible(chip);
    await tester.tap(chip);
    await tester.pumpAndSettle();

    expect(appState.acquisitionPromptDismissed, isTrue);
    expect(find.text('Where did you find us?'), findsNothing);

    await _drainGeneration(tester);
  });

  testWidgets('Other reveals a text box; Done dismisses the prompt',
      (tester) async {
    final appState = await _toGeneratingDashboard(tester);

    // Scoped to the acquisition card's own field — the dashboard already has the
    // feedback composer's TextField, so byType(TextField) isn't specific enough.
    final otherField = find.byWidgetPredicate((w) =>
        w is TextField &&
        w.decoration?.hintText == 'Where did you hear about us?');
    expect(otherField, findsNothing);

    final other = find.text('Other');
    await tester.ensureVisible(other);
    await tester.tap(other);
    // Single pump (not pumpAndSettle): the revealed field autofocuses, and its
    // blinking cursor reschedules frames forever, which would let pumpAndSettle
    // advance past the 3s generation poll and unmount the whole card.
    await tester.pump();

    // The free-text box is revealed but the card is still up (not yet recorded).
    expect(otherField, findsOneWidget);
    expect(appState.acquisitionPromptDismissed, isFalse);

    await tester.enterText(otherField, "a friend's newsletter");
    await tester.pump();
    await tester.tap(find.text('Done'));
    await tester.pump();

    expect(appState.acquisitionPromptDismissed, isTrue);
    expect(find.text('Where did you find us?'), findsNothing);

    await _drainGeneration(tester);
  });
}

/// Runs the still-in-flight generation poll to completion and tears down the
/// tree, so no Future.delayed timers from the fake's fetchRun/fetchMe/
/// fetchEpisodes remain pending when the test ends.
Future<void> _drainGeneration(WidgetTester tester) async {
  await tester.pump(const Duration(seconds: 4)); // fire the poll -> run finishes
  await tester.pumpAndSettle(); // drain the follow-up fetches
  await tester.pumpWidget(const SizedBox());
}
