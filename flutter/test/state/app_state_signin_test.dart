import 'dart:convert';

import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';

import 'package:app/api/api_client.dart';
import 'package:app/data/fake_app_repository.dart';
import 'package:app/state/app_state.dart';

/// Regression coverage for the greeting-name revert bug: the account name pulled
/// from Google/Apple must NEVER overwrite the app-entered display name on a
/// returning sign-in. It is only a fallback seed for a brand-new account that
/// has not picked a name yet.

Map<String, dynamic> _meJson(String displayName) => {
      'user': {'id': 'u1', 'display_name': displayName, 'timezone': 'UTC'},
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
    };

Map<String, dynamic> _sessionJson({
  required bool isNewUser,
  required String displayName,
}) =>
    {
      'session_token': 'tok',
      'is_new_user': isNewUser,
      'user': {'id': 'u1', 'display_name': displayName, 'timezone': 'UTC'},
      'subscription': {'user_id': 'u1', 'tier': 'free', 'status': 'active'},
    };

AppState _buildApp(MockClient mock) => AppState(
      FakeAppRepository(),
      apiClient: ApiClient(baseUrl: 'https://api.test', client: mock),
      pollInterval: const Duration(seconds: 30),
    );

void main() {
  test('returning sign-in never re-seeds the name from the account', () async {
    http.Request? patch;
    final mock = MockClient((req) async {
      if (req.method == 'POST' && req.url.path == '/v1/auth/firebase') {
        // The account name is NOT forwarded on the exchange.
        final body = jsonDecode(req.body) as Map<String, dynamic>;
        expect(body.containsKey('given_name'), isFalse);
        return http.Response(
            jsonEncode(_sessionJson(isNewUser: false, displayName: 'SophCorp')),
            200);
      }
      if (req.method == 'GET' && req.url.path == '/v1/me') {
        return http.Response(jsonEncode(_meJson('SophCorp')), 200);
      }
      if (req.method == 'PATCH' && req.url.path == '/v1/me') {
        patch = req;
        return http.Response(jsonEncode(_meJson('SophCorp')), 200);
      }
      return http.Response('{}', 200);
    });

    final app = _buildApp(mock);
    await app.signInWithFirebaseToken('id', displayName: 'Real Google Name');

    expect(patch, isNull,
        reason: 'a returning user must not have their name PATCHed');
    expect(app.me?.user.displayName, 'SophCorp');
  });

  test('brand-new account with no name is seeded from the account name',
      () async {
    var current = 'Listener'; // backend default before any name is picked
    Map<String, dynamic>? patchBody;
    final mock = MockClient((req) async {
      if (req.method == 'POST' && req.url.path == '/v1/auth/firebase') {
        return http.Response(
            jsonEncode(_sessionJson(isNewUser: true, displayName: 'Listener')),
            200);
      }
      if (req.method == 'GET' && req.url.path == '/v1/me') {
        return http.Response(jsonEncode(_meJson(current)), 200);
      }
      if (req.method == 'PATCH' && req.url.path == '/v1/me') {
        patchBody = jsonDecode(req.body) as Map<String, dynamic>;
        current = patchBody!['display_name'] as String;
        return http.Response(jsonEncode(_meJson(current)), 200);
      }
      return http.Response('{}', 200);
    });

    final app = _buildApp(mock);
    await app.signInWithFirebaseToken('id', displayName: 'Real Google Name');

    expect(patchBody?['display_name'], 'Real Google Name');
    expect(app.me?.user.displayName, 'Real Google Name');
  });

  test('new account that already has a friendly name is not seeded', () async {
    http.Request? patch;
    final mock = MockClient((req) async {
      if (req.method == 'POST' && req.url.path == '/v1/auth/firebase') {
        return http.Response(
            jsonEncode(_sessionJson(isNewUser: true, displayName: 'Custom')),
            200);
      }
      if (req.method == 'GET' && req.url.path == '/v1/me') {
        return http.Response(jsonEncode(_meJson('Custom')), 200);
      }
      if (req.method == 'PATCH' && req.url.path == '/v1/me') {
        patch = req;
        return http.Response(jsonEncode(_meJson('Custom')), 200);
      }
      return http.Response('{}', 200);
    });

    final app = _buildApp(mock);
    await app.signInWithFirebaseToken('id', displayName: 'Real Google Name');

    expect(patch, isNull,
        reason: 'an existing friendly name must not be overwritten');
    expect(app.me?.user.displayName, 'Custom');
  });
}
