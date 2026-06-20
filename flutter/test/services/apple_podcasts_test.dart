import 'package:flutter_test/flutter_test.dart';

import 'package:app/services/apple_podcasts.dart';

void main() {
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
}
