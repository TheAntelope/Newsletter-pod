import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

import 'package:app/api/api_client.dart';

String? _authHeader(http.Request r) {
  for (final e in r.headers.entries) {
    if (e.key.toLowerCase() == 'authorization') return e.value;
  }
  return null;
}

void main() {
  group('ApiClient', () {
    test('signInWithFirebase posts the id token and decodes the session', () async {
      late http.Request captured;
      final mock = MockClient((req) async {
        captured = req;
        return http.Response(
          jsonEncode({
            'session_token': 'tok',
            'is_new_user': true,
            'user': {'id': 'u1', 'display_name': 'A', 'timezone': 'UTC'},
            'subscription': {'user_id': 'u1', 'tier': 'free', 'status': 'active'},
          }),
          200,
        );
      });
      final api = ApiClient(baseUrl: 'https://api.test', client: mock);

      final session = await api.signInWithFirebase('id-token', givenName: 'Vince');

      expect(captured.method, 'POST');
      expect(captured.url.path, '/v1/auth/firebase');
      final body = jsonDecode(captured.body) as Map<String, dynamic>;
      expect(body['id_token'], 'id-token');
      expect(body['given_name'], 'Vince');
      expect(session.sessionToken, 'tok');
      expect(session.isNewUser, isTrue);
      expect(session.user.id, 'u1');
    });

    test('attaches the bearer token on authenticated calls', () async {
      late http.Request captured;
      final mock = MockClient((req) async {
        captured = req;
        return http.Response(
          jsonEncode({
            'user': {'id': 'u1', 'display_name': 'A', 'timezone': 'UTC'},
            'profile': {
              'title': 'ClawCast',
              'format_preset': 'two_hosts',
              'host_primary_name': 'Vinnie',
              'guest_names': <String>[],
              'desired_duration_minutes': 3,
            },
            'schedule': {
              'timezone': 'UTC',
              'weekdays': ['mon'],
              'local_time': '07:00',
              'cutoff_time': '23:00',
            },
            'subscription': {'user_id': 'u1', 'tier': 'free', 'status': 'active'},
            'entitlements': {
              'tier': 'free',
              'max_delivery_days': 7,
              'min_duration_minutes': 3,
              'max_duration_minutes': 5,
              'max_items_per_episode': 25,
            },
          }),
          200,
        );
      });
      final api = ApiClient(baseUrl: 'https://api.test', client: mock);

      final me = await api.fetchMe('session-tok');

      expect(captured.method, 'GET');
      expect(_authHeader(captured), 'Bearer session-tok');
      expect(me.user.id, 'u1');
      expect(me.profile.title, 'ClawCast');
      expect(me.entitlements.maxDeliveryDays, 7);
    });

    test('updateSchedule sends full weekday names and decodes back to codes',
        () async {
      late http.Request captured;
      final mock = MockClient((req) async {
        captured = req;
        return http.Response(
          jsonEncode({
            'schedule': {
              'timezone': 'UTC',
              // Backend echoes canonical full names.
              'weekdays': ['tuesday', 'thursday'],
              'local_time': '07:00',
              'cutoff_time': '11:00',
            },
            'entitlements': {
              'tier': 'free',
              'max_delivery_days': 7,
              'min_duration_minutes': 3,
              'max_duration_minutes': 5,
              'max_items_per_episode': 25,
            },
          }),
          200,
        );
      });
      final api = ApiClient(baseUrl: 'https://api.test', client: mock);

      final env = await api.updateSchedule(
        'tok',
        timezone: 'UTC',
        weekdays: ['tue', 'thu'],
        localTime: '07:00',
      );

      // Outgoing body carries the full names the backend requires.
      final body = jsonDecode(captured.body) as Map<String, dynamic>;
      expect(body['weekdays'], ['tuesday', 'thursday']);
      // Response is mapped back to the app's 3-letter codes.
      expect(env.schedule.weekdays, ['tue', 'thu']);
    });

    test('encodes query parameters (probeSubstack)', () async {
      late http.Request captured;
      final mock = MockClient((req) async {
        captured = req;
        return http.Response(
          jsonEncode({
            'pub_url': 'https://x.substack.com',
            'pub_host': 'x.substack.com',
            'has_paid_tier': false,
            'feed_url': 'https://x.substack.com/feed',
          }),
          200,
        );
      });
      final api = ApiClient(baseUrl: 'https://api.test', client: mock);

      final probe = await api.probeSubstack('https://x.substack.com');

      expect(captured.url.path, '/v1/substack/probe');
      expect(captured.url.queryParameters['url'], 'https://x.substack.com');
      expect(probe.pubHost, 'x.substack.com');
    });

    test('maps non-2xx to ApiException with the backend detail', () async {
      final mock = MockClient(
        (req) async => http.Response(jsonEncode({'detail': 'nope'}), 400),
      );
      final api = ApiClient(baseUrl: 'https://api.test', client: mock);

      await expectLater(
        () => api.fetchMe('t'),
        throwsA(isA<ApiException>()
            .having((e) => e.message, 'message', 'nope')
            .having((e) => e.statusCode, 'statusCode', 400)),
      );
    });
  });
}
