import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
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

  testWidgets('dashboard share tip teaches the share sheet and dismisses',
      (tester) async {
    await _signIn(tester);

    // The teach card surfaces the otherwise-invisible OS share-sheet feature.
    final tip = find.text('Add anything you read');
    await tester.ensureVisible(tip);
    await tester.pumpAndSettle();
    expect(tip, findsOneWidget);
    expect(find.textContaining('work it into your next pod'), findsOneWidget);

    // Dismissing hides it for the session.
    await tester.tap(find.byIcon(Icons.close));
    await tester.pumpAndSettle();
    expect(find.text('Add anything you read'), findsNothing);
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
    // ElevenLabs grant attribution sits at the bottom of the welcome screen.
    expect(find.byKey(const ValueKey('elevenlabs-grant-badge')), findsOneWidget);

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

  testWidgets('onboarding teaches the share sheet with the ClawCast target',
      (tester) async {
    _useTallViewport(tester);
    final appState = AppState(FakeAppRepository());
    await tester.pumpWidget(
      AppScope(notifier: appState, child: const ClawcastApp()),
    );

    await tester.tap(find.text('Get started'));
    await tester.pumpAndSettle();

    // Walk forward until the share-sheet teach step appears (its position
    // depends on the conditional steps, so don't hardcode a count).
    for (var guard = 0;
        guard < 20 && find.text('Add from anywhere').evaluate().isEmpty;
        guard++) {
      await tester.tap(find.text('Next'));
      await tester.pumpAndSettle();
    }

    expect(find.text('Add from anywhere'), findsOneWidget);
    // The mock highlights ClawCast as the share destination.
    expect(find.text('ClawCast'), findsWidgets);
    expect(find.textContaining('Pick ClawCast from the share sheet'),
        findsOneWidget);
  });

  testWidgets('onboarding topic step lists every catalog category and toggles',
      (tester) async {
    _useTallViewport(tester);
    final appState = AppState(FakeAppRepository());
    await tester.pumpWidget(
      AppScope(notifier: appState, child: const ClawcastApp()),
    );

    await tester.tap(find.text('Get started'));
    await tester.pumpAndSettle();
    expect(find.text('Welcome to ClawCast'), findsOneWidget);

    // Advance to the topics step. The number of intervening steps varies
    // (voice, style, format, optional name), so tap Next until it appears
    // rather than hardcoding a count.
    for (var guard = 0;
        guard < 20 && find.text('Pick your topics').evaluate().isEmpty;
        guard++) {
      await tester.tap(find.text('Next'));
      await tester.pumpAndSettle();
    }

    expect(find.text('Pick your topics'), findsOneWidget);
    // The full catalog set is offered, not just the old hardcoded four — topics
    // that only exist deeper in the catalog must render as chips.
    expect(find.text('Romantasy'), findsOneWidget);
    expect(find.text('Family Life'), findsOneWidget);
    expect(find.text('Personal Finance'), findsOneWidget);

    // Chips are tappable (toggling selection rebuilds without throwing).
    await tester.tap(find.text('Science'));
    await tester.pumpAndSettle();
    expect(find.text('Pick your topics'), findsOneWidget);
  });

  testWidgets('style step folds in weather with the current-location option',
      (tester) async {
    _useTallViewport(tester);
    final appState = AppState(FakeAppRepository());
    await tester.pumpWidget(
      AppScope(notifier: appState, child: const ClawcastApp()),
    );

    await tester.tap(find.text('Get started'));
    await tester.pumpAndSettle();

    // Walk to the Style step (step 2: welcome, voice, style). Weather is folded
    // in here, just below the tone/humor/takeaways controls.
    await tester.tap(find.text('Next'));
    await tester.pumpAndSettle();
    await tester.tap(find.text('Next'));
    await tester.pumpAndSettle();
    expect(find.text('Style your show'), findsOneWidget);
    expect(find.text('WEATHER'), findsOneWidget); // MetaLabel uppercases

    // The weather toggle is the last switch in the step (after greeting +
    // top-takeaways). Turning it on reveals the city field + location option.
    final weatherSwitch = find.byType(Switch).last;
    await tester.ensureVisible(weatherSwitch);
    await tester.pumpAndSettle();
    await tester.tap(weatherSwitch);
    await tester.pumpAndSettle();
    expect(find.text('Use my current location'), findsOneWidget);
    expect(find.byIcon(Icons.my_location), findsOneWidget);
  });

  testWidgets('adding a substack copies the alias and opens its subscribe form',
      (tester) async {
    // Capture url_launcher channel calls so we can assert the deep-link fires.
    // (Creating the intent alone never subscribes the alias — the user must
    // complete Substack's own subscribe form, so the screen MUST open it.)
    final launched = <String>[];
    const launcherChannel = MethodChannel('plugins.flutter.io/url_launcher');
    final messenger = tester.binding.defaultBinaryMessenger;
    messenger.setMockMethodCallHandler(launcherChannel, (call) async {
      final args = call.arguments;
      if (args is Map && args['url'] is String) {
        launched.add(args['url'] as String);
      }
      return true; // launch/canLaunch/supportsMode all expect a bool
    });
    // Capture the alias the screen copies to the clipboard.
    String? copied;
    messenger.setMockMethodCallHandler(SystemChannels.platform, (call) async {
      if (call.method == 'Clipboard.setData') {
        copied = (call.arguments as Map)['text'] as String?;
      }
      return null;
    });
    addTearDown(() {
      messenger.setMockMethodCallHandler(launcherChannel, null);
      messenger.setMockMethodCallHandler(SystemChannels.platform, null);
    });

    await _signIn(tester);
    await tester.tap(find.text('Sources'));
    await tester.pumpAndSettle();
    await tester.tap(find.byIcon(Icons.add));
    await tester.pumpAndSettle();

    await tester.enterText(find.byType(TextField), 'tech');
    await tester.tap(find.text('Find'));
    await tester.pumpAndSettle();

    // Add the first discovered candidate (Platformer → www.platformer.news).
    final add = find.text('Add').first;
    await tester.ensureVisible(add);
    await tester.tap(add);
    await tester.pumpAndSettle();

    // The two behaviors that were missing before the fix: the alias is copied
    // and the publication's subscribe form is opened (so Substack mails it).
    expect(copied, 'demo@theclawcast.com');
    expect(launched, isNotEmpty);
    expect(launched.single, endsWith('/subscribe'));
  });
}
