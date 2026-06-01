import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:app/data/fake_app_repository.dart';
import 'package:app/main.dart';
import 'package:app/state/app_state.dart';

Future<void> _signIn(WidgetTester tester) async {
  final appState = AppState(FakeAppRepository());
  await tester.pumpWidget(
    AppScope(notifier: appState, child: const ClawcastApp()),
  );
  await tester.tap(find.text('Get started'));
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('stub sign-in routes to the dashboard and generates', (tester) async {
    final appState = AppState(FakeAppRepository());
    await tester.pumpWidget(
      AppScope(notifier: appState, child: const ClawcastApp()),
    );

    // Sign-in screen first.
    expect(find.text('ClawCast'), findsOneWidget);
    expect(find.text('Get started'), findsOneWidget);

    await tester.tap(find.text('Get started'));
    await tester.pumpAndSettle();

    // Today tab: greeting + generate.
    expect(find.textContaining('Vince'), findsWidgets);
    final generate = find.text('Generate now');
    expect(generate, findsOneWidget);

    await tester.ensureVisible(generate);
    await tester.pumpAndSettle();
    await tester.tap(generate);
    await tester.pumpAndSettle();
    expect(find.textContaining('being generated'), findsOneWidget);
  });

  testWidgets('dashboard tabs load sources and library', (tester) async {
    await _signIn(tester);

    expect(find.text('Generate now'), findsOneWidget); // Today tab

    await tester.tap(find.text('Sources'));
    await tester.pumpAndSettle();
    expect(find.text('Stratechery'), findsOneWidget);

    await tester.tap(find.text('Library'));
    await tester.pumpAndSettle();
    expect(find.text('Your Tuesday Briefing'), findsOneWidget);
  });

  testWidgets('next-pod queue opens and pins a story', (tester) async {
    await _signIn(tester);

    final entry = find.text('Preview & pin the stories');
    await tester.ensureVisible(entry);
    await tester.pumpAndSettle();
    await tester.tap(entry);
    await tester.pumpAndSettle();

    expect(
      find.text('The agentic web and the next platform shift'),
      findsOneWidget,
    );
    expect(find.text('Pinned'), findsOneWidget); // c1 starts pinned

    final firstPin = find.text('Pin').first;
    await tester.ensureVisible(firstPin);
    await tester.pumpAndSettle();
    await tester.tap(firstPin);
    await tester.pumpAndSettle();

    expect(find.text('Pinned'), findsNWidgets(2));
  });

  testWidgets('podcast setup loads, edits length, and saves', (tester) async {
    // Tall viewport so the whole form (incl. Save) fits without scrolling.
    tester.view.physicalSize = const Size(1000, 2400);
    tester.view.devicePixelRatio = 1.0;
    addTearDown(tester.view.reset);

    await _signIn(tester);

    await tester.tap(find.byIcon(Icons.tune));
    await tester.pumpAndSettle();

    expect(find.text('Podcast & schedule'), findsOneWidget); // app bar title
    expect(find.text('5 min'), findsOneWidget);

    // Decrement the length (5 -> 4; min is 3).
    await tester.tap(find.byIcon(Icons.remove));
    await tester.pumpAndSettle();
    expect(find.text('4 min'), findsOneWidget);

    await tester.tap(find.text('Save'));
    await tester.pumpAndSettle();
    expect(find.text('Saved'), findsOneWidget);
  });
}
