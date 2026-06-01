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
  Future<EpisodesEnvelope> fetchEpisodes();
  Future<NextEpisodeQueueEnvelope> fetchNextEpisodeQueue();
  Future<void> pinNextEpisodeItem(String dedupeKey);
  Future<void> excludeNextEpisodeItem(String dedupeKey);
}
