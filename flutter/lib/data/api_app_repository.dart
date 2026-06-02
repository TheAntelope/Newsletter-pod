import '../api/api_client.dart';
import '../api/models.dart';
import 'app_repository.dart';

/// Production repository: wraps [ApiClient] with the signed-in session token.
class ApiAppRepository implements AppRepository {
  ApiAppRepository(this._client, this._token);

  final ApiClient _client;
  final String _token;

  @override
  Future<MeEnvelope> fetchMe() => _client.fetchMe(_token);

  @override
  Future<RunStartEnvelope> generateNow() => _client.generateNow(_token);

  @override
  Future<SourcesEnvelope> fetchSources() => _client.fetchSources(_token);

  @override
  Future<SourcesEnvelope> replaceSources(List<SourcePayload> sources) =>
      _client.replaceSources(_token, sources);

  @override
  Future<EpisodesEnvelope> fetchEpisodes() => _client.fetchEpisodes(_token);

  @override
  Future<NextEpisodeQueueEnvelope> fetchNextEpisodeQueue() =>
      _client.fetchNextEpisodeQueue(_token);

  @override
  Future<void> pinNextEpisodeItem(String dedupeKey) =>
      _client.pinNextEpisodeItem(_token, dedupeKey);

  @override
  Future<void> excludeNextEpisodeItem(String dedupeKey) =>
      _client.excludeNextEpisodeItem(_token, dedupeKey);

  @override
  Future<PodcastConfigEnvelope> fetchPodcastConfig() =>
      _client.fetchPodcastConfig(_token);

  @override
  Future<PodcastConfigEnvelope> updatePodcastConfig(PodcastProfileDto p) =>
      _client.updatePodcastConfig(
        _token,
        title: p.title,
        formatPreset: p.formatPreset,
        hostPrimaryName: p.hostPrimaryName,
        hostSecondaryName: p.hostSecondaryName,
        guestNames: p.guestNames,
        desiredDurationMinutes: p.desiredDurationMinutes,
        voiceId: p.voiceId,
        secondaryVoiceId: p.secondaryVoiceId,
        tone: p.tone,
        keyFindingsCount: p.keyFindingsCount,
        humorStyle: p.humorStyle,
        personalizedGreeting: p.personalizedGreeting,
        includeTopTakeaways: p.includeTopTakeaways,
        includeWeather: p.includeWeather,
        weatherLocation: p.weatherLocation,
        customGuidance: p.customGuidance,
        customGuidancePresetId: p.customGuidancePresetId,
      );

  @override
  Future<ScheduleEnvelope> fetchSchedule() => _client.fetchSchedule(_token);

  @override
  Future<ScheduleEnvelope> updateSchedule({
    required String timezone,
    required List<String> weekdays,
    String? localTime,
  }) =>
      _client.updateSchedule(
        _token,
        timezone: timezone,
        weekdays: weekdays,
        localTime: localTime,
      );

  @override
  Future<VoiceCatalogEnvelope> fetchVoiceCatalog() =>
      _client.fetchVoiceCatalog();

  @override
  Future<SwipeDeckEnvelope> fetchSwipeDeck() =>
      _client.fetchRecentSwipeDeck(_token);

  @override
  Future<void> submitSwipe(String dedupeKey, int direction) =>
      _client.submitSwipe(_token, dedupeKey: dedupeKey, direction: direction);

  @override
  Future<SubstackIntentsEnvelope> fetchSubstackIntents() =>
      _client.fetchSubstackIntents(_token);

  @override
  Future<SubstackDiscoveryEnvelope> discoverSubstacks(String query) =>
      _client.discoverSubstacks(_token, query);

  @override
  Future<SubstackIntentEnvelope> createSubstackIntent(String pubUrl) =>
      _client.createSubstackIntent(_token, pubUrl);
}
