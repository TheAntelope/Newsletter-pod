import 'dart:convert';

import 'package:flutter/foundation.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:http/http.dart' as http;
import 'package:http/testing.dart';
import 'package:shared_preferences/shared_preferences.dart';

import 'package:app/api/api_client.dart';
import 'package:app/data/fake_app_repository.dart';
import 'package:app/services/apple_podcasts.dart';
import 'package:app/services/podcast_addict.dart';
import 'package:app/state/app_state.dart';

/// Notification-tap behaviour: every tap reports a push-opened analytics
/// event, and a pod_ready tap additionally hands the user to the platform's
/// podcast player (Apple Podcasts / Podcast Addict).

const _feedUrl = 'https://api.test/feeds/abc.xml';

Map<String, dynamic> _subscriptionJson() =>
    {'user_id': 'u1', 'tier': 'free', 'status': 'active'};

Map<String, dynamic> _entitlementsJson() => {
      'tier': 'free',
      'max_delivery_days': 7,
      'min_duration_minutes': 3,
      'max_duration_minutes': 5,
      'max_items_per_episode': 25,
    };

Map<String, dynamic> _meJson() => {
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
      'subscription': _subscriptionJson(),
      'entitlements': _entitlementsJson(),
    };

Map<String, dynamic> _sessionJson() => {
      'session_token': 'tok',
      'is_new_user': false,
      'user': {'id': 'u1', 'display_name': 'A', 'timezone': 'UTC'},
      'subscription': _subscriptionJson(),
    };

Map<String, dynamic> _feedJson() => {
      'feed_url': _feedUrl,
      'token': 'feed-tok',
      'subscription': _subscriptionJson(),
      'entitlements': _entitlementsJson(),
    };

void main() {
  TestWidgetsFlutterBinding.ensureInitialized();

  final originalAppleLauncher = ApplePodcasts.launcher;
  final originalAddictLauncher = PodcastAddict.launcher;
  late List<Uri> launched;

  setUp(() {
    SharedPreferences.setMockInitialValues({});
    launched = [];
    Future<bool> record(Uri uri) async {
      launched.add(uri);
      return true;
    }

    ApplePodcasts.launcher = record;
    PodcastAddict.launcher = record;
  });

  tearDown(() {
    debugDefaultTargetPlatformOverride = null;
  });

  tearDownAll(() {
    ApplePodcasts.launcher = originalAppleLauncher;
    PodcastAddict.launcher = originalAddictLauncher;
  });

  /// Signs in against a MockClient and returns the AppState plus the request
  /// log (cleared of the sign-in traffic).
  Future<(AppState, List<http.Request>)> signedInApp() async {
    final requests = <http.Request>[];
    final mock = MockClient((req) async {
      requests.add(req);
      if (req.url.path == '/v1/auth/firebase') {
        return http.Response(jsonEncode(_sessionJson()), 200);
      }
      if (req.url.path == '/v1/me/push-opened') {
        return http.Response(jsonEncode({'ok': true}), 200);
      }
      if (req.url.path == '/v1/me/feed') {
        return http.Response(jsonEncode(_feedJson()), 200);
      }
      return http.Response(jsonEncode(_meJson()), 200);
    });
    final app = AppState(
      FakeAppRepository(),
      apiClient: ApiClient(baseUrl: 'https://api.test', client: mock),
      pollInterval: const Duration(seconds: 30),
    );
    await app.signInWithFirebaseToken('id');
    requests.clear();
    return (app, requests);
  }

  List<http.Request> pushReports(List<http.Request> requests) =>
      requests.where((r) => r.url.path == '/v1/me/push-opened').toList();

  test('pod_ready tap reports the open and launches Apple Podcasts on iOS',
      () async {
    debugDefaultTargetPlatformOverride = TargetPlatform.iOS;
    final (app, requests) = await signedInApp();

    app.handlePushOpened({'type': 'pod_ready', 'feed_url': _feedUrl});
    await pumpEventQueue();

    final reports = pushReports(requests);
    expect(reports, hasLength(1));
    expect(jsonDecode(reports.single.body)['push_type'], 'pod_ready');
    // First-ever open: the follow deep link (feed not added yet).
    expect(launched.map((u) => u.toString()),
        contains('podcast://api.test/feeds/abc.xml'));
    // The tap also refreshes /v1/me so the new episode surfaces on Home
    // (the only outcome the user gets if the player launch fails).
    expect(
        requests.where((r) => r.method == 'GET' && r.url.path == '/v1/me'),
        isNotEmpty);
  });

  test('pod_ready tap launches Podcast Addict on Android', () async {
    debugDefaultTargetPlatformOverride = TargetPlatform.android;
    final (app, _) = await signedInApp();

    app.handlePushOpened({'type': 'pod_ready', 'feed_url': _feedUrl});
    await pumpEventQueue();

    expect(launched.map((u) => u.toString()),
        contains('podcastaddict://api.test/feeds/abc.xml'));
  });

  test('pod_ready tap without a feed_url fetches the feed first', () async {
    debugDefaultTargetPlatformOverride = TargetPlatform.iOS;
    final (app, _) = await signedInApp();

    app.handlePushOpened({'type': 'pod_ready'});
    await pumpEventQueue();

    expect(launched.map((u) => u.toString()),
        contains('podcast://api.test/feeds/abc.xml'));
  });

  test('trial_gift tap reports the open but launches no player', () async {
    debugDefaultTargetPlatformOverride = TargetPlatform.iOS;
    final (app, requests) = await signedInApp();

    app.handlePushOpened({'type': 'trial_gift'});
    await pumpEventQueue();

    final reports = pushReports(requests);
    expect(reports, hasLength(1));
    expect(jsonDecode(reports.single.body)['push_type'], 'trial_gift');
    expect(launched, isEmpty);
    // The tap refreshes /v1/me so the gift card surfaces on Home.
    expect(
        requests.where((r) => r.method == 'GET' && r.url.path == '/v1/me'),
        isNotEmpty);
  });

  test('a tap with no type is not reported', () async {
    final (app, requests) = await signedInApp();

    app.handlePushOpened(<String, dynamic>{});
    await pumpEventQueue();

    expect(pushReports(requests), isEmpty);
    expect(launched, isEmpty);
  });
}
