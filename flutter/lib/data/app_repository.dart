import '../api/api_client.dart' show SourcePayload;
import '../api/models.dart';

/// The data layer the screens talk to.
///
/// Backed by [ApiAppRepository] in production (wraps the HTTP [ApiClient]) and
/// [FakeAppRepository] for local stubbing + widget tests, so the UI can be built
/// and exercised before Firebase auth and the external accounts exist.
abstract interface class AppRepository {
  Future<MeEnvelope> fetchMe();
  Future<RunStartEnvelope> generateNow();
  Future<SourcesEnvelope> fetchSources();

  /// Persist the full set of enabled sources (catalog ids + custom RSS urls);
  /// sources absent from [sources] are disabled server-side. Returns the new
  /// state. Mirrors `PUT /v1/me/sources`.
  Future<SourcesEnvelope> replaceSources(List<SourcePayload> sources);

  Future<EpisodesEnvelope> fetchEpisodes();
  Future<NextEpisodeQueueEnvelope> fetchNextEpisodeQueue();
  Future<void> pinNextEpisodeItem(String dedupeKey);
  Future<void> excludeNextEpisodeItem(String dedupeKey);

  Future<PodcastConfigEnvelope> fetchPodcastConfig();
  Future<PodcastConfigEnvelope> updatePodcastConfig(PodcastProfileDto profile);
  Future<ScheduleEnvelope> fetchSchedule();
  Future<ScheduleEnvelope> updateSchedule({
    required String timezone,
    required List<String> weekdays,
    String? localTime,
  });
  Future<VoiceCatalogEnvelope> fetchVoiceCatalog();
  Future<SwipeDeckEnvelope> fetchSwipeDeck();
  Future<void> submitSwipe(String dedupeKey, int direction);

  Future<SubstackIntentsEnvelope> fetchSubstackIntents();
  Future<SubstackDiscoveryEnvelope> discoverSubstacks(String query);
  Future<SubstackIntentEnvelope> createSubstackIntent(String pubUrl);
}
