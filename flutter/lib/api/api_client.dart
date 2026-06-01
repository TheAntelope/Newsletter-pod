// Dart port of ios/NewsletterPodApp/APIClient.swift.
//
// Same backend contract: Bearer-token auth, JSON bodies, a `{detail}` error
// envelope, ISO8601 dates (DateTime.parse handles both fractional and plain).
// Adds signInWithFirebase for the Android/Flutter client (Phase 1 endpoint);
// the Apple path is kept for parity.
import 'dart:convert';

import 'package:http/http.dart' as http;

import '../config.dart';
import 'models.dart';
import 'responses.dart';

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

class ApiClient {
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

  Future<SwipeDeckEnvelope> fetchColdStartSwipeDeck(String token) async =>
      SwipeDeckEnvelope.fromJson(await _send('/v1/me/swipe-deck/cold-start',
          method: 'GET', token: token));

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
  }) async =>
      DeviceTokenAck.fromJson(
          await _send('/v1/me/device-tokens', method: 'POST', token: token, body: {
        'token': deviceToken,
        'environment': environment,
        'bundle_id': bundleId,
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
    final encoded = body == null ? null : jsonEncode(body);

    final http.Response resp;
    switch (method) {
      case 'GET':
        resp = await _client.get(uri, headers: headers);
      case 'POST':
        resp = await _client.post(uri, headers: headers, body: encoded);
      case 'PUT':
        resp = await _client.put(uri, headers: headers, body: encoded);
      case 'PATCH':
        resp = await _client.patch(uri, headers: headers, body: encoded);
      case 'DELETE':
        resp = await _client.delete(uri, headers: headers, body: encoded);
      default:
        throw ApiException('Unsupported method: $method');
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
