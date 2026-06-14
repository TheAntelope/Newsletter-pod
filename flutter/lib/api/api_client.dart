// Dart port of ios/NewsletterPodApp/APIClient.swift.
//
// Same backend contract: Bearer-token auth, JSON bodies, a `{detail}` error
// envelope, ISO8601 dates (DateTime.parse handles both fractional and plain).
// Adds signInWithFirebase for the Android/Flutter client (Phase 1 endpoint);
// the Apple path is kept for parity.
import 'dart:async';
import 'dart:convert';
import 'dart:io' show Platform;

import 'package:http/http.dart' as http;

import '../config.dart';
import 'models.dart';
import 'responses.dart';

/// Stack this build is running on, sent as `X-Client-Platform` so the backend
/// can tag every analytics event with its platform and we can analyse the iOS
/// and Flutter/Android users in one view. Computed once; null on any other
/// host (e.g. tests on desktop) so we simply omit the header there.
final String? _clientPlatform = Platform.isAndroid
    ? 'android'
    : Platform.isIOS
        ? 'ios'
        : null;

/// Thrown for non-2xx responses and transport/shape errors. `message` is the
/// backend `detail` when present.
class ApiException implements Exception {
  final String message;
  final int? statusCode;

  ApiException(this.message, {this.statusCode});

  @override
  String toString() => message;
}

/// One source entry for PUT /v1/me/sources. Null fields are omitted (matching
/// the Swift `encodeIfPresent` behaviour).
class SourcePayload {
  final String? sourceId;
  final String? rssUrl;
  final bool? isCustom;

  SourcePayload({this.sourceId, this.rssUrl, this.isCustom});

  Map<String, dynamic> toJson() => {
        if (sourceId != null) 'source_id': sourceId,
        if (rssUrl != null) 'rss_url': rssUrl,
        if (isCustom != null) 'is_custom': isCustom,
      };
}

/// Result of `POST /v1/items/shared` (the share-to-ClawCast endpoint). Hand
/// -rolled (no json_serializable codegen) since it's only used by the share
/// flow. `duplicate` is true when an identical share was already queued.
class SharedItemResult {
  final String itemId;
  final String title;
  final String shareKind;
  final bool duplicate;

  SharedItemResult({
    required this.itemId,
    required this.title,
    required this.shareKind,
    required this.duplicate,
  });

  factory SharedItemResult.fromJson(Map<String, dynamic> json) =>
      SharedItemResult(
        itemId: json['item_id']?.toString() ?? '',
        title: json['title']?.toString() ?? '',
        shareKind: json['share_kind']?.toString() ?? '',
        duplicate: json['duplicate'] == true,
      );
}

class ApiClient {
  /// Upper bound on any single request. Generous enough for the slowest first
  /// reads (cold-start deck, corpus warm) yet short enough that a genuinely
  /// stuck request fails fast instead of leaving the UI spinning.
  static const _requestTimeout = Duration(seconds: 30);

  final String _baseUrl;
  final http.Client _client;

  ApiClient({String? baseUrl, http.Client? client})
      : _baseUrl = baseUrl ?? AppConfig.apiBaseUrl,
        _client = client ?? http.Client();

  void close() => _client.close();

  // -------------------------------------------------------------------------
  // Auth
  // -------------------------------------------------------------------------

  /// Android/Flutter sign-in: exchange a Firebase ID token for an app session.
  Future<SessionEnvelope> signInWithFirebase(
    String idToken, {
    String? givenName,
  }) async {
    final json = await _send('/v1/auth/firebase', method: 'POST', body: {
      'id_token': idToken,
      if (givenName != null) 'given_name': givenName,
    });
    return SessionEnvelope.fromJson(json);
  }

  /// Apple sign-in (kept for parity; the iOS Flutter target uses this via Firebase).
  Future<SessionEnvelope> signInWithApple(
    String identityToken, {
    String? givenName,
  }) async {
    final json = await _send('/v1/auth/apple', method: 'POST', body: {
      'identity_token': identityToken,
      if (givenName != null) 'given_name': givenName,
    });
    return SessionEnvelope.fromJson(json);
  }

  // -------------------------------------------------------------------------
  // Account / profile
  // -------------------------------------------------------------------------

  Future<MeEnvelope> fetchMe(String token) async =>
      MeEnvelope.fromJson(await _send('/v1/me', method: 'GET', token: token));

  Future<MeEnvelope> updateProfile(
    String token, {
    required String displayName,
    required String timezone,
  }) async =>
      MeEnvelope.fromJson(await _send('/v1/me', method: 'PATCH', token: token, body: {
        'display_name': displayName,
        'timezone': timezone,
      }));

  Future<AccountDeletionAck> deleteAccount(String token) async =>
      AccountDeletionAck.fromJson(
          await _send('/v1/me', method: 'DELETE', token: token));

  Future<AccountResetAck> resetAlgorithm(String token) async =>
      AccountResetAck.fromJson(
          await _send('/v1/me/reset', method: 'POST', token: token));

  /// Acknowledges the early-adopter trial gift (the "Got it" tap on the home
  /// card). Idempotent on the backend — it stamps `trial_gift_acknowledged_at`
  /// once and no-ops thereafter, so a retry is harmless. Returns nothing; the
  /// caller refreshes `me` to clear `trial_gift_pending`.
  Future<void> acknowledgeTrialGift(String token) async {
    await _send('/v1/me/trial-gift/ack', method: 'POST', token: token);
  }

  // -------------------------------------------------------------------------
  // Catalogs
  // -------------------------------------------------------------------------

  Future<CatalogEnvelope> fetchCatalog() async =>
      CatalogEnvelope.fromJson(await _send('/v1/sources/catalog', method: 'GET'));

  Future<VoiceCatalogEnvelope> fetchVoiceCatalog() async =>
      VoiceCatalogEnvelope.fromJson(
          await _send('/v1/voices/catalog', method: 'GET'));

  // -------------------------------------------------------------------------
  // Sources
  // -------------------------------------------------------------------------

  Future<SourcesEnvelope> fetchSources(String token) async =>
      SourcesEnvelope.fromJson(
          await _send('/v1/me/sources', method: 'GET', token: token));

  Future<SourcesEnvelope> replaceSources(
    String token,
    List<SourcePayload> sources,
  ) async =>
      SourcesEnvelope.fromJson(await _send('/v1/me/sources',
          method: 'PUT',
          token: token,
          body: {'sources': sources.map((s) => s.toJson()).toList()}));

  // -------------------------------------------------------------------------
  // Podcast config
  // -------------------------------------------------------------------------

  Future<PodcastConfigEnvelope> fetchPodcastConfig(String token) async =>
      PodcastConfigEnvelope.fromJson(
          await _send('/v1/me/podcast-config', method: 'GET', token: token));

  Future<PodcastConfigEnvelope> updatePodcastConfig(
    String token, {
    required String title,
    required String formatPreset,
    required String hostPrimaryName,
    String? hostSecondaryName,
    required List<String> guestNames,
    required int desiredDurationMinutes,
    String? voiceId,
    String? secondaryVoiceId,
    String? tone,
    int? keyFindingsCount,
    String? humorStyle,
    bool? personalizedGreeting,
    bool? includeTopTakeaways,
    bool? includeWeather,
    String? weatherLocation,
    double? weatherLat,
    double? weatherLon,
    String? weatherCountryCode,
    String? customGuidance,
    String? customGuidancePresetId,
  }) async =>
      PodcastConfigEnvelope.fromJson(
          await _send('/v1/me/podcast-config', method: 'PATCH', token: token, body: {
        'title': title,
        'format_preset': formatPreset,
        'host_primary_name': hostPrimaryName,
        if (hostSecondaryName != null) 'host_secondary_name': hostSecondaryName,
        'guest_names': guestNames,
        'desired_duration_minutes': desiredDurationMinutes,
        if (voiceId != null) 'voice_id': voiceId,
        if (secondaryVoiceId != null) 'secondary_voice_id': secondaryVoiceId,
        if (tone != null) 'tone': tone,
        if (keyFindingsCount != null) 'key_findings_count': keyFindingsCount,
        if (humorStyle != null) 'humor_style': humorStyle,
        if (personalizedGreeting != null)
          'personalized_greeting': personalizedGreeting,
        if (includeTopTakeaways != null)
          'include_top_takeaways': includeTopTakeaways,
        if (includeWeather != null) 'include_weather': includeWeather,
        if (weatherLocation != null) 'weather_location': weatherLocation,
        if (weatherLat != null) 'weather_lat': weatherLat,
        if (weatherLon != null) 'weather_lon': weatherLon,
        if (weatherCountryCode != null)
          'weather_country_code': weatherCountryCode,
        if (customGuidance != null) 'custom_guidance': customGuidance,
        if (customGuidancePresetId != null)
          'custom_guidance_preset_id': customGuidancePresetId,
      }));

  // -------------------------------------------------------------------------
  // Schedule
  // -------------------------------------------------------------------------

  Future<ScheduleEnvelope> fetchSchedule(String token) async =>
      ScheduleEnvelope.fromJson(
          await _send('/v1/me/schedule', method: 'GET', token: token));

  Future<ScheduleEnvelope> updateSchedule(
    String token, {
    required String timezone,
    required List<String> weekdays,
    String? localTime,
  }) async =>
      ScheduleEnvelope.fromJson(
          await _send('/v1/me/schedule', method: 'PATCH', token: token, body: {
        'timezone': timezone,
        'weekdays': weekdays,
        if (localTime != null) 'local_time': localTime,
      }));

  // -------------------------------------------------------------------------
  // Feed / episodes / runs
  // -------------------------------------------------------------------------

  Future<FeedEnvelope> fetchFeed(String token) async =>
      FeedEnvelope.fromJson(
          await _send('/v1/me/feed', method: 'GET', token: token));

  Future<InboundItemsEnvelope> fetchInboundItems(String token) async =>
      InboundItemsEnvelope.fromJson(
          await _send('/v1/me/inbound-items', method: 'GET', token: token));

  Future<EpisodesEnvelope> fetchEpisodes(String token) async =>
      EpisodesEnvelope.fromJson(
          await _send('/v1/me/episodes', method: 'GET', token: token));

  Future<RunStartEnvelope> generateNow(String token) async =>
      RunStartEnvelope.fromJson(
          await _send('/v1/me/generate', method: 'POST', token: token));

  Future<RunStatusEnvelope> fetchRun(String token, String runId) async =>
      RunStatusEnvelope.fromJson(
          await _send('/v1/me/runs/$runId', method: 'GET', token: token));

  // -------------------------------------------------------------------------
  // Feedback
  // -------------------------------------------------------------------------

  Future<void> submitFeedback(
    String token, {
    required String text,
    String? localeHint,
    required String source,
  }) async {
    await _send('/v1/me/feedback', method: 'POST', token: token, body: {
      'text': text,
      if (localeHint != null) 'locale_hint': localeHint,
      'source': source,
    });
  }

  // -------------------------------------------------------------------------
  // Swipe deck
  // -------------------------------------------------------------------------

  Future<SwipeDeckEnvelope> fetchRecentSwipeDeck(String token) async =>
      SwipeDeckEnvelope.fromJson(
          await _send('/v1/me/swipe-deck/recent', method: 'GET', token: token));

  /// The onboarding deck. [topics] (catalog topic names) seed it server-side so
  /// the first stories match the categories the user just picked.
  Future<SwipeDeckEnvelope> fetchColdStartSwipeDeck(
    String token, {
    List<String>? topics,
  }) async =>
      SwipeDeckEnvelope.fromJson(await _send('/v1/me/swipe-deck/cold-start',
          method: 'GET',
          token: token,
          query: (topics != null && topics.isNotEmpty)
              ? {'topics': topics.join(',')}
              : null));

  Future<void> submitSwipe(
    String token, {
    required String dedupeKey,
    required int direction,
  }) async {
    await _send('/v1/me/swipes', method: 'POST', token: token, body: {
      'source_item_dedupe_key': dedupeKey,
      'direction': direction,
    });
  }

  // -------------------------------------------------------------------------
  // Next-episode queue
  // -------------------------------------------------------------------------

  Future<NextEpisodeQueueEnvelope> fetchNextEpisodeQueue(String token) async =>
      NextEpisodeQueueEnvelope.fromJson(await _send(
          '/v1/me/next-episode/candidates',
          method: 'GET',
          token: token));

  Future<void> pinNextEpisodeItem(String token, String dedupeKey) async {
    await _send('/v1/me/next-episode/pin', method: 'POST', token: token, body: {
      'source_item_dedupe_key': dedupeKey,
    });
  }

  Future<void> excludeNextEpisodeItem(String token, String dedupeKey) async {
    await _send('/v1/me/next-episode/exclude',
        method: 'POST', token: token, body: {
      'source_item_dedupe_key': dedupeKey,
    });
  }

  Future<void> clearNextEpisodeOverride(String token, String dedupeKey) async {
    await _send('/v1/me/next-episode/override',
        method: 'DELETE',
        token: token,
        query: {'source_item_dedupe_key': dedupeKey});
  }

  // -------------------------------------------------------------------------
  // Voice intake / corpus
  // -------------------------------------------------------------------------

  Future<VoiceIntakeAck> submitVoiceIntake(
    String token,
    String transcript,
  ) async =>
      VoiceIntakeAck.fromJson(await _send('/v1/me/voice-intake',
          method: 'POST', token: token, body: {'transcript': transcript}));

  Future<CorpusRefreshAck> refreshCorpus(String token) async =>
      CorpusRefreshAck.fromJson(
          await _send('/v1/me/corpus/refresh', method: 'POST', token: token));

  // -------------------------------------------------------------------------
  // Substack
  // -------------------------------------------------------------------------

  Future<SubstackDiscoveryEnvelope> discoverSubstacks(
    String token,
    String query,
  ) async =>
      SubstackDiscoveryEnvelope.fromJson(await _send('/v1/substack/discover',
          method: 'POST', token: token, body: {'query': query}));

  Future<SubstackProbeDto> probeSubstack(String url) async =>
      SubstackProbeDto.fromJson(await _send('/v1/substack/probe',
          method: 'GET', query: {'url': url}));

  Future<SubstackIntentsEnvelope> fetchSubstackIntents(String token) async =>
      SubstackIntentsEnvelope.fromJson(await _send('/v1/me/substack/intents',
          method: 'GET', token: token));

  Future<SubstackIntentEnvelope> createSubstackIntent(
    String token,
    String pubUrl,
  ) async =>
      SubstackIntentEnvelope.fromJson(await _send('/v1/me/substack/intents',
          method: 'POST', token: token, body: {'pub_url': pubUrl}));

  Future<void> deleteSubstackIntent(String token, String intentId) async {
    await _send('/v1/me/substack/intents/$intentId',
        method: 'DELETE', token: token);
  }

  // -------------------------------------------------------------------------
  // Push / billing
  // -------------------------------------------------------------------------

  Future<DeviceTokenAck> registerDeviceToken(
    String token, {
    required String deviceToken,
    required String environment,
    required String bundleId,
    String platform = 'ios',
    String transport = 'fcm',
  }) async =>
      DeviceTokenAck.fromJson(
          await _send('/v1/me/device-tokens', method: 'POST', token: token, body: {
        'token': deviceToken,
        'environment': environment,
        'bundle_id': bundleId,
        'platform': platform,
        'transport': transport,
      }));

  Future<VerifySubscriptionEnvelope> verifySubscription(
    String token,
    String signedTransactionInfo,
  ) async =>
      VerifySubscriptionEnvelope.fromJson(await _send(
          '/v1/me/subscription/verify',
          method: 'POST',
          token: token,
          body: {'signed_transaction_info': signedTransactionInfo}));

  // -------------------------------------------------------------------------
  // Shared items (share-to-ClawCast)
  // -------------------------------------------------------------------------

  /// Pin a shared link/text/document to the user's next pod
  /// (`POST /v1/items/shared`, multipart). Mirrors the iOS Share Extension:
  /// [kind] is one of `url|text|pdf|epub|docx`; a `url` kind sends the link as a
  /// form field, every other kind uploads [fileBytes] as the `file` part. The
  /// backend routes extraction by [kind], so the part's content-type is left as
  /// the default. Surfaces 401 (sign in) / 413 (too large) / `detail` via
  /// [ApiException].
  Future<SharedItemResult> submitSharedItem(
    String token, {
    required String kind,
    String? url,
    List<int>? fileBytes,
    String? filename,
    String? title,
  }) async {
    final uri = Uri.parse(_baseUrl).replace(path: '/v1/items/shared');
    final request = http.MultipartRequest('POST', uri)
      ..headers['Authorization'] = 'Bearer $token'
      ..fields['kind'] = kind;
    if (title != null && title.isNotEmpty) request.fields['title'] = title;
    if (kind == 'url') {
      if (url != null) request.fields['url'] = url;
    } else {
      request.files.add(http.MultipartFile.fromBytes(
        'file',
        fileBytes ?? const <int>[],
        filename: filename ?? 'shared',
      ));
    }

    final streamed = await _client.send(request);
    final resp = await http.Response.fromStream(streamed);
    if (resp.statusCode < 200 || resp.statusCode >= 300) {
      throw ApiException(_errorMessage(resp), statusCode: resp.statusCode);
    }
    final decoded = resp.body.isEmpty ? <String, dynamic>{} : jsonDecode(resp.body);
    if (decoded is Map<String, dynamic>) {
      return SharedItemResult.fromJson(decoded);
    }
    throw ApiException('Unexpected response shape from /v1/items/shared');
  }

  // -------------------------------------------------------------------------
  // Transport
  // -------------------------------------------------------------------------

  Future<Map<String, dynamic>> _send(
    String path, {
    required String method,
    Map<String, dynamic>? body,
    Map<String, String>? query,
    String? token,
  }) async {
    final uri = Uri.parse(_baseUrl).replace(path: path, queryParameters: query);
    final headers = <String, String>{'Content-Type': 'application/json'};
    if (token != null) headers['Authorization'] = 'Bearer $token';
    if (_clientPlatform != null) headers['X-Client-Platform'] = _clientPlatform!;
    final encoded = body == null ? null : jsonEncode(body);

    final Future<http.Response> pending;
    switch (method) {
      case 'GET':
        pending = _client.get(uri, headers: headers);
      case 'POST':
        pending = _client.post(uri, headers: headers, body: encoded);
      case 'PUT':
        pending = _client.put(uri, headers: headers, body: encoded);
      case 'PATCH':
        pending = _client.patch(uri, headers: headers, body: encoded);
      case 'DELETE':
        pending = _client.delete(uri, headers: headers, body: encoded);
      default:
        throw ApiException('Unsupported method: $method');
    }

    // Bound every request so a stuck backend surfaces an error the UI can show
    // (retry / empty state) instead of spinning forever — the onboarding swipe
    // deck previously appeared to hang on a slow response.
    final http.Response resp;
    try {
      resp = await pending.timeout(_requestTimeout);
    } on TimeoutException {
      throw ApiException(
        'The request timed out. Check your connection and try again.',
      );
    }

    if (resp.statusCode < 200 || resp.statusCode >= 300) {
      throw ApiException(_errorMessage(resp), statusCode: resp.statusCode);
    }

    if (resp.body.isEmpty) return <String, dynamic>{};
    final decoded = jsonDecode(resp.body);
    if (decoded is Map<String, dynamic>) return decoded;
    throw ApiException('Unexpected response shape from $path');
  }

  String _errorMessage(http.Response resp) {
    try {
      final decoded = jsonDecode(resp.body);
      if (decoded is Map && decoded['detail'] != null) {
        return decoded['detail'].toString();
      }
    } catch (_) {
      // fall through to the generic message
    }
    return 'Request failed with status ${resp.statusCode}';
  }
}
