import 'package:flutter_test/flutter_test.dart';

import 'package:app/services/podcast_addict.dart';

void main() {
  const feed = 'https://api.host/feeds/abc.xml';
  final originalLauncher = PodcastAddict.launcher;
  late List<Uri> launched;

  setUp(() {
    launched = [];
    PodcastAddict.launcher = (uri) async {
      launched.add(uri);
      return true;
    };
  });

  tearDownAll(() {
    PodcastAddict.launcher = originalLauncher;
  });

  group('PodcastAddict.deepLinkFor', () {
    test('swaps https:// for the podcastaddict:// subscribe scheme', () {
      expect(PodcastAddict.deepLinkFor(feed).toString(),
          'podcastaddict://api.host/feeds/abc.xml');
    });
  });

  group('PodcastAddict.openPlayer', () {
    test('launches only the subscribe deep link on success', () async {
      expect(await PodcastAddict.openPlayer(feed), isTrue);
      expect(launched.map((u) => u.toString()),
          ['podcastaddict://api.host/feeds/abc.xml']);
    });

    test('stays in ClawCast when Podcast Addict is not installed — '
        'no Play-Store bounce and no armed install-retry', () async {
      PodcastAddict.launcher = (uri) async {
        launched.add(uri);
        return false;
      };

      expect(await PodcastAddict.openPlayer(feed), isFalse);
      // The notification-tap path must NOT do what subscribe() does on
      // failure: only the deep link, never market:// / play.google.com.
      expect(launched.map((u) => u.toString()),
          ['podcastaddict://api.host/feeds/abc.xml']);

      // And it must not have remembered a pending feed: nothing re-fires
      // when the app next resumes.
      launched.clear();
      PodcastAddict.launcher = (uri) async {
        launched.add(uri);
        return true;
      };
      await PodcastAddict.retryPendingOnResume();
      expect(launched, isEmpty);
    });
  });
}
