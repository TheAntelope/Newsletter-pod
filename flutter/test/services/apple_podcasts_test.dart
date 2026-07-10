import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:app/services/apple_podcasts.dart';

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  group('ApplePodcasts.deepLinkFor', () {
    test('swaps https:// for the podcast:// subscribe scheme', () {
      final uri =
          ApplePodcasts.deepLinkFor('https://api.host/feeds/abc.xml');
      expect(uri.toString(), 'podcast://api.host/feeds/abc.xml');
      expect(uri.scheme, 'podcast');
      expect(uri.host, 'api.host');
      expect(uri.path, '/feeds/abc.xml');
    });

    test('swaps a plain http:// feed too', () {
      final uri = ApplePodcasts.deepLinkFor('http://api.host/feeds/abc.xml');
      expect(uri.toString(), 'podcast://api.host/feeds/abc.xml');
    });

    test('keeps the query string intact', () {
      final uri =
          ApplePodcasts.deepLinkFor('https://api.host/feeds/abc.xml?t=1');
      expect(uri.toString(), 'podcast://api.host/feeds/abc.xml?t=1');
    });
  });

  group('ApplePodcasts.openPlayer', () {
    const feed = 'https://api.host/feeds/abc.xml';
    final originalLauncher = ApplePodcasts.launcher;
    late List<Uri> launched;

    setUp(() {
      SharedPreferences.setMockInitialValues({});
      launched = [];
      ApplePodcasts.launcher = (uri) async {
        launched.add(uri);
        return true;
      };
    });

    tearDownAll(() {
      ApplePodcasts.launcher = originalLauncher;
    });

    test('first open runs the follow deep link and remembers the feed',
        () async {
      expect(await ApplePodcasts.openPlayer(feed), isTrue);
      expect(launched.map((u) => u.toString()),
          ['podcast://api.host/feeds/abc.xml']);
      expect(await ApplePodcasts.hasAddedFeed(feed), isTrue);
    });

    test('later opens skip the follow sheet and open the app itself',
        () async {
      SharedPreferences.setMockInitialValues(
          {'apple_podcasts_added_feed_url': feed});
      expect(await ApplePodcasts.openPlayer(feed), isTrue);
      expect(launched.map((u) => u.toString()), ['podcasts://']);
    });

    test('a regenerated feed URL re-runs the follow flow and re-remembers',
        () async {
      SharedPreferences.setMockInitialValues(
          {'apple_podcasts_added_feed_url': 'https://api.host/feeds/old.xml'});
      expect(await ApplePodcasts.openPlayer(feed), isTrue);
      expect(launched.map((u) => u.toString()),
          ['podcast://api.host/feeds/abc.xml']);
      expect(await ApplePodcasts.hasAddedFeed(feed), isTrue);
    });

    test('falls back to the follow link when the app-only schemes fail',
        () async {
      SharedPreferences.setMockInitialValues(
          {'apple_podcasts_added_feed_url': feed});
      ApplePodcasts.launcher = (uri) async {
        launched.add(uri);
        return uri.scheme == 'podcast'; // only the follow link has a handler
      };
      expect(await ApplePodcasts.openPlayer(feed), isTrue);
      expect(launched.map((u) => u.toString()),
          ['podcasts://', 'pcast://', 'podcast://api.host/feeds/abc.xml']);
    });

    test('does not remember the feed when the launch fails', () async {
      ApplePodcasts.launcher = (uri) async => false;
      expect(await ApplePodcasts.openPlayer(feed), isFalse);
      expect(await ApplePodcasts.hasAddedFeed(feed), isFalse);
    });
  });

  group('ApplePodcasts context flows', () {
    const feed = 'https://api.host/feeds/abc.xml';
    final originalLauncher = ApplePodcasts.launcher;
    late List<Uri> launched;

    setUp(() {
      launched = [];
      ApplePodcasts.launcher = (uri) async {
        launched.add(uri);
        return true;
      };
    });

    tearDownAll(() {
      ApplePodcasts.launcher = originalLauncher;
    });

    Future<BuildContext> pumpHost(WidgetTester tester) async {
      late BuildContext ctx;
      await tester.pumpWidget(MaterialApp(
        home: Scaffold(
          body: Builder(builder: (c) {
            ctx = c;
            return const SizedBox();
          }),
        ),
      ));
      return ctx;
    }

    testWidgets(
        'addFeed always re-runs the follow flow, even when the feed is '
        'remembered — it is the escape hatch for a cancelled follow sheet',
        (tester) async {
      SharedPreferences.setMockInitialValues(
          {'apple_podcasts_added_feed_url': feed});
      final ctx = await pumpHost(tester);

      expect(await ApplePodcasts.addFeed(ctx, feed), isTrue);

      expect(launched.map((u) => u.toString()),
          ['podcast://api.host/feeds/abc.xml']);
    });

    testWidgets('an app-only open offers a "Re-add feed" recovery action',
        (tester) async {
      SharedPreferences.setMockInitialValues(
          {'apple_podcasts_added_feed_url': feed});
      final ctx = await pumpHost(tester);

      expect(await ApplePodcasts.open(ctx, feed), isTrue);
      expect(launched.map((u) => u.toString()), ['podcasts://']);

      // Let the snackbar's entrance animation finish before tapping.
      await tester.pumpAndSettle();
      expect(find.text('Re-add feed'), findsOneWidget);

      await tester.tap(find.text('Re-add feed'));
      await tester.pump();
      expect(launched.map((u) => u.toString()),
          ['podcasts://', 'podcast://api.host/feeds/abc.xml']);

      // Let the snackbar's display timer elapse so no timer outlives the test.
      await tester.pumpAndSettle(const Duration(seconds: 9));
    });
  });
}
