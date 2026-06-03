import '../api/api_client.dart' show SourcePayload;
import '../api/models.dart';

/// The data layer the screens talk to.
///
/// Backed by [ApiAppRepository] in production (wraps the HTTP [ApiClient]) and
/// [FakeAppRepository] for local stubbing + widget tests, so the UI can be built
/// and exercised before Firebase auth and the external accounts exist.
abstract interface class AppRepository {
  Future<MeEnvelope> fetchMe();

  /// Update the display name / timezone (`PATCH /v1/me`). Returns the fresh `me`.
  Future<MeEnvelope> updateProfile({
    required String displayName,
    required String timezone,
  });

  /// Wipe sources/schedule/profile/swipes and re-run onboarding server-side
  /// (`POST /v1/me/reset`). Account, feed token, subscription, episodes are kept.
  Future<void> resetAlgorithm();

  /// Delete the account (`DELETE /v1/me`).
  Future<void> deleteAccount();

  Future<RunStartEnvelope> generateNow();

  /// The private RSS feed URL/token + latest episode/run (`GET /v1/me/feed`).
  Future<FeedEnvelope> fetchFeed();

  /// The full topic-tagged source catalog (`GET /v1/sources/catalog`).
  Future<CatalogEnvelope> fetchCatalog();

  /// Recently-ingested forwarded newsletters (`GET /v1/me/inbound-items`).
  Future<InboundItemsEnvelope> fetchInboundItems();

  /// Submit free-text/voice feedback (`POST /v1/me/feedback`).
  Future<void> submitFeedback({required String text, required String source});

  /// Remove a Substack subscription intent (`DELETE /v1/me/substack/intents/{id}`).
  Future<void> deleteSubstackIntent(String intentId);
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
