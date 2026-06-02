import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:app/data/fake_app_repository.dart';
import 'package:app/main.dart';
import 'package:app/state/app_state.dart';

/// Tall viewport so long ListView-based screens fully build (avoids lazy-list
/// cache-extent flakiness when tapping items near the bottom).
void _useTallViewport(WidgetTester tester) {
  tester.view.physicalSize = const Size(1000, 2200);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.reset);
}

Future<void> _signIn(WidgetTester tester) async {
  _useTallViewport(tester);
  final appState = AppState(FakeAppRepository());
  await tester.pumpWidget(
    AppScope(notifier: appState, child: const ClawcastApp()),
  );
  await tester.tap(find.text('Get started'));
  await tester.pumpAndSettle();
  // Skip the onboarding wizard for dashboard-focused tests.
  appState.completeOnboarding();
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('stub sign-in routes to the dashboard and generates', (tester) async {
    _useTallViewport(tester);
    final appState = AppState(FakeAppRepository());
    await tester.pumpWidget(
      AppScope(notifier: appState, child: const ClawcastApp()),
    );

    // Sign-in screen first.
    expect(find.text('ClawCast'), findsOneWidget);
    expect(find.text('Get started'), findsOneWidget);

    await tester.tap(find.text('Get started'));
    await tester.pumpAndSettle();

    appState.completeOnboarding(); // skip the wizard
    await tester.pumpAndSettle();

    // Today tab: greeting + generate.
    expect(find.textContaining('Vince'), findsWidgets);
    final generate = find.text('Generate now');
    expect(generate, findsOneWidget);

    await tester.ensureVisible(generate);
    await tester.pumpAndSettle();
    await tester.tap(generate);
    // Generation starts a live (never-settling) progress bar, so pump fixed
    // steps to flush the fake run instead of pumpAndSettle.
    await tester.pump(); // isGenerating -> banner + progress bar mount
    await tester.pump(const Duration(milliseconds: 400)); // fake run resolves
    expect(find.textContaining('being generated'), findsOneWidget);

    // Tear the tree down so the progress bar's periodic timer is cancelled.
    await tester.pumpWidget(const SizedBox());
  });

  testWidgets('dashboard tabs load sources and library', (tester) async {
    await _signIn(tester);

    expect(find.text('Generate now'), findsOneWidget); // Today tab

    await tester.tap(find.text('Sources'));
    await tester.pumpAndSettle();
    expect(find.text('News'), findsOneWidget); // a catalog topic group header

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
    await _signIn(tester);

    await tester.tap(find.byIcon(Icons.tune));
    await tester.pumpAndSettle();

    expect(find.text('Podcast & schedule'), findsOneWidget); // app bar title
    expect(find.text('5 min'), findsOneWidget);

    // Decrement the length (5 -> 4; min is 3).
    await tester.tap(find.byIcon(Icons.remove));
    await tester.pumpAndSettle();
    expect(find.text('4 min'), findsOneWidget);

    // Save sits below the now-longer config form; scroll the outer list to it
    // (the form's multiline fields add their own Scrollables, so target the first).
    await tester.scrollUntilVisible(
      find.text('Save'),
      400,
      scrollable: find.byType(Scrollable).first,
    );
    await tester.tap(find.text('Save'));
    await tester.pumpAndSettle();
    expect(find.text('Saved'), findsOneWidget);
  });

  testWidgets('swipe deck keeps a card and advances', (tester) async {
    await _signIn(tester);

    await tester.tap(find.text('Discover'));
    await tester.pumpAndSettle();

    // Depth-3 stack: the top card and the two behind it all render.
    expect(find.text('The state of open-source LLMs'), findsOneWidget); // top
    expect(find.text('Why latency is the new moat'), findsOneWidget); // peeking

    // Keep is the filled heart action button (icon-only, like iOS).
    await tester.tap(find.byIcon(Icons.favorite));
    await tester.pumpAndSettle();

    // Top card flew off; the deck advanced.
    expect(find.text('The state of open-source LLMs'), findsNothing); // swiped
    expect(find.text('Why latency is the new moat'), findsOneWidget); // new top
  });

  testWidgets('sources shows the catalog grouped by topic', (tester) async {
    await _signIn(tester);

    await tester.tap(find.text('Sources'));
    await tester.pumpAndSettle();

    // The real ~90-source catalog renders as collapsible topic groups.
    expect(find.text('News'), findsOneWidget);
    expect(find.text('Tech'), findsOneWidget);
    expect(find.text('Business'), findsOneWidget);

    // Expanding a group reveals its sources.
    await tester.tap(find.text('Tech'));
    await tester.pumpAndSettle();
    expect(find.textContaining('Stratechery'), findsOneWidget);
  });

  testWidgets('substack add lists intents and discovers candidates',
      (tester) async {
    await _signIn(tester);

    await tester.tap(find.text('Sources'));
    await tester.pumpAndSettle();
    await tester.tap(find.byIcon(Icons.add));
    await tester.pumpAndSettle();

    expect(find.text('Add Substack'), findsOneWidget); // app bar
    expect(find.text('The Pragmatic Engineer'), findsOneWidget); // existing intent
    expect(find.textContaining('481920'), findsOneWidget); // live code

    await tester.enterText(find.byType(TextField), 'tech');
    await tester.tap(find.text('Find'));
    await tester.pumpAndSettle();
    expect(find.text('Platformer'), findsOneWidget); // discovered candidate
  });

  testWidgets('account opens and reaches feed access', (tester) async {
    await _signIn(tester);

    await tester.tap(find.byIcon(Icons.settings_outlined));
    await tester.pumpAndSettle();
    expect(find.text('Account'), findsOneWidget); // app bar
    expect(find.text('Reset my algorithm'), findsOneWidget);

    await tester.tap(find.text('Add your briefings to any podcast app'));
    await tester.pumpAndSettle();
    expect(find.text('Feed access'), findsOneWidget); // app bar
    expect(find.textContaining('theclawcast.com/feeds'), findsOneWidget);
  });

  testWidgets('paywall shows plans and stubs purchase', (tester) async {
    await _signIn(tester);

    await tester.tap(find.text('See plans'));
    await tester.pumpAndSettle();

    expect(find.text('Choose your plan'), findsOneWidget);
    expect(find.text('Pro'), findsOneWidget);
    expect(find.text('Max'), findsOneWidget);
    expect(find.text('Current plan'), findsOneWidget); // free is current

    final choosePro = find.text('Choose Pro');
    await tester.ensureVisible(choosePro);
    await tester.pumpAndSettle();
    await tester.tap(choosePro);
    await tester.pumpAndSettle();
    expect(find.textContaining('coming soon'), findsOneWidget); // stub snackbar
  });

  testWidgets('onboarding wizard advances to the dashboard', (tester) async {
    _useTallViewport(tester);
    final appState = AppState(FakeAppRepository());
    await tester.pumpWidget(
      AppScope(notifier: appState, child: const ClawcastApp()),
    );

    await tester.tap(find.text('Get started'));
    await tester.pumpAndSettle();

    // Onboarding (not the dashboard) shows first.
    expect(find.text('Welcome to ClawCast'), findsOneWidget);

    // Advance through every step until only Finish remains (step count varies).
    for (var guard = 0; guard < 20 && find.text('Next').evaluate().isNotEmpty; guard++) {
      await tester.tap(find.text('Next'));
      await tester.pumpAndSettle();
    }
    expect(find.textContaining('all set'), findsOneWidget); // final step
    expect(find.text('Next'), findsNothing);

    await tester.tap(find.text('Finish'));
    await tester.pumpAndSettle();

    // Lands on the dashboard.
    expect(find.text('Generate now'), findsOneWidget);
  });
}
