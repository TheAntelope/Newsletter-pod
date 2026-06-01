import '../api/models.dart';
import 'app_repository.dart';

/// In-memory demo data so the UI runs end-to-end without a backend, Firebase, or
/// accounts. Swapped for [ApiAppRepository] once sign-in returns a real session.
class FakeAppRepository implements AppRepository {
  @override
  Future<MeEnvelope> fetchMe() async {
    await Future<void>.delayed(const Duration(milliseconds: 150));
    return MeEnvelope(
      user: UserDto(
        id: 'demo-user',
        email: 'demo@theclawcast.com',
        displayName: 'Vince Martin',
        timezone: 'Europe/Copenhagen',
        inboundAddress: 'demo@theclawcast.com',
      ),
      profile: _demoProfile(),
      schedule: _demoSchedule(),
      subscription: SubscriptionDto(
        userId: 'demo-user',
        tier: 'free',
        status: 'active',
      ),
      entitlements: _demoEntitlements(),
    );
  }

  @override
  Future<RunStartEnvelope> generateNow() async {
    await Future<void>.delayed(const Duration(milliseconds: 300));
    return RunStartEnvelope(
      run: UserRunDto(
        id: 'demo-run',
        status: 'queued',
        message: 'Your next pod is being generated…',
        candidateCount: 12,
        capHit: false,
      ),
      started: true,
    );
  }

  @override
  Future<SourcesEnvelope> fetchSources() async {
    await Future<void>.delayed(const Duration(milliseconds: 150));
    return SourcesEnvelope(
      sources: [
        UserSourceDto(
          id: 's1',
          sourceId: 'stratechery',
          name: 'Stratechery',
          rssUrl: 'https://stratechery.com/feed/',
          isCustom: false,
          enabled: true,
        ),
        UserSourceDto(
          id: 's2',
          sourceId: 'platformer',
          name: 'Platformer',
          rssUrl: 'https://www.platformer.news/rss/',
          isCustom: false,
          enabled: true,
        ),
        UserSourceDto(
          id: 's3',
          sourceId: 'custom-1',
          name: 'My Substack',
          rssUrl: 'https://my.substack.com/feed',
          isCustom: true,
          enabled: false,
        ),
      ],
      entitlements: _demoEntitlements(),
    );
  }

  @override
  Future<EpisodesEnvelope> fetchEpisodes() async {
    await Future<void>.delayed(const Duration(milliseconds: 150));
    final now = DateTime.now();
    return EpisodesEnvelope(
      episodes: [
        LibraryEpisodeDto(
          id: 'e1',
          title: 'Your Tuesday Briefing',
          description: 'AI agents, the chip race, and a quiet week in fintech.',
          publishedAt: now.subtract(const Duration(days: 1)),
          durationSeconds: 312,
          processedItemCount: 11,
          droppedItemCount: 2,
          capHit: false,
          sourceItemRefs: const [],
        ),
        LibraryEpisodeDto(
          id: 'e2',
          title: 'Your Monday Briefing',
          description: 'Earnings season kicks off and two big product launches.',
          publishedAt: now.subtract(const Duration(days: 2)),
          durationSeconds: 287,
          processedItemCount: 9,
          droppedItemCount: 0,
          capHit: false,
          sourceItemRefs: const [],
        ),
      ],
    );
  }

  @override
  Future<NextEpisodeQueueEnvelope> fetchNextEpisodeQueue() async {
    await Future<void>.delayed(const Duration(milliseconds: 150));
    final now = DateTime.now();
    return NextEpisodeQueueEnvelope(
      enabled: true,
      pinnedCount: 1,
      maxPins: 3,
      pinsRemaining: 2,
      rankerUsed: true,
      candidates: [
        NextEpisodeCandidateDto(
          dedupeKey: 'c1',
          sourceId: 'stratechery',
          sourceName: 'Stratechery',
          title: 'The agentic web and the next platform shift',
          summary: 'Why agents change distribution and what it means for aggregators.',
          link: 'https://stratechery.com/x',
          publishedAt: now.subtract(const Duration(hours: 5)),
          pinned: true,
          likelyIncluded: true,
        ),
        NextEpisodeCandidateDto(
          dedupeKey: 'c2',
          sourceId: 'platformer',
          sourceName: 'Platformer',
          title: 'Inside the latest trust & safety reorg',
          summary: 'A look at how the team is restructuring after a tough quarter.',
          link: 'https://platformer.news/x',
          publishedAt: now.subtract(const Duration(hours: 8)),
          pinned: false,
          likelyIncluded: true,
        ),
        NextEpisodeCandidateDto(
          dedupeKey: 'c3',
          sourceId: 'platformer',
          sourceName: 'Platformer',
          title: 'A quieter week in fintech',
          summary: 'Few launches, but two funding rounds worth noting.',
          link: 'https://platformer.news/y',
          publishedAt: now.subtract(const Duration(hours: 20)),
          pinned: false,
          likelyIncluded: false,
        ),
      ],
    );
  }

  @override
  Future<void> pinNextEpisodeItem(String dedupeKey) async {
    await Future<void>.delayed(const Duration(milliseconds: 80));
  }

  @override
  Future<void> excludeNextEpisodeItem(String dedupeKey) async {
    await Future<void>.delayed(const Duration(milliseconds: 80));
  }

  @override
  Future<PodcastConfigEnvelope> fetchPodcastConfig() async {
    await Future<void>.delayed(const Duration(milliseconds: 150));
    return PodcastConfigEnvelope(
      profile: _demoProfile(),
      entitlements: _demoEntitlements(),
    );
  }

  @override
  Future<PodcastConfigEnvelope> updatePodcastConfig(
      PodcastProfileDto profile) async {
    await Future<void>.delayed(const Duration(milliseconds: 150));
    return PodcastConfigEnvelope(
      profile: profile,
      entitlements: _demoEntitlements(),
    );
  }

  @override
  Future<ScheduleEnvelope> fetchSchedule() async {
    await Future<void>.delayed(const Duration(milliseconds: 120));
    return ScheduleEnvelope(
      schedule: _demoSchedule(),
      entitlements: _demoEntitlements(),
    );
  }

  @override
  Future<ScheduleEnvelope> updateSchedule({
    required String timezone,
    required List<String> weekdays,
    String? localTime,
  }) async {
    await Future<void>.delayed(const Duration(milliseconds: 120));
    return ScheduleEnvelope(
      schedule: DeliveryScheduleDto(
        timezone: timezone,
        weekdays: weekdays,
        localTime: localTime ?? '07:00',
        cutoffTime: '23:00',
      ),
      entitlements: _demoEntitlements(),
    );
  }

  @override
  Future<VoiceCatalogEnvelope> fetchVoiceCatalog() async {
    await Future<void>.delayed(const Duration(milliseconds: 120));
    return VoiceCatalogEnvelope(
      voices: [
        CatalogVoiceDto(
          id: 'vinnie',
          name: 'Vinnie Chase',
          gender: 'male',
          description: 'Warm, conversational anchor.',
        ),
        CatalogVoiceDto(
          id: 'demi',
          name: 'Demi Dreams',
          gender: 'female',
          description: 'Bright, energetic co-host.',
        ),
      ],
    );
  }

  @override
  Future<SwipeDeckEnvelope> fetchSwipeDeck() async {
    await Future<void>.delayed(const Duration(milliseconds: 150));
    final now = DateTime.now();
    return SwipeDeckEnvelope(
      items: [
        SwipeDeckCardDto(
          sourceItemDedupeKey: 'sw1',
          title: 'The state of open-source LLMs',
          summary: 'A roundup of the latest open-weight releases and benchmarks.',
          cardSummary:
              'A roundup of the latest open-weight model releases and where they beat closed ones.',
          sourceId: 'stratechery',
          sourceName: 'Stratechery',
          link: 'https://stratechery.com/sw1',
          publishedAt: now.subtract(const Duration(hours: 6)),
        ),
        SwipeDeckCardDto(
          sourceItemDedupeKey: 'sw2',
          title: 'Why latency is the new moat',
          summary: 'Speed is becoming the defensible edge in consumer AI.',
          cardSummary:
              'Why response speed is becoming the defensible edge in consumer AI products.',
          sourceId: 'platformer',
          sourceName: 'Platformer',
          link: 'https://platformer.news/sw2',
          publishedAt: now.subtract(const Duration(hours: 9)),
        ),
        SwipeDeckCardDto(
          sourceItemDedupeKey: 'sw3',
          title: 'A field guide to agent frameworks',
          summary: 'Comparing the major agent orchestration libraries.',
          cardSummary:
              'A practical comparison of the major agent-orchestration libraries shipping now.',
          sourceId: 'stratechery',
          sourceName: 'Stratechery',
          link: 'https://stratechery.com/sw3',
          publishedAt: now.subtract(const Duration(hours: 14)),
        ),
      ],
    );
  }

  @override
  Future<void> submitSwipe(String dedupeKey, int direction) async {}

  PodcastProfileDto _demoProfile() => PodcastProfileDto(
        title: 'ClawCast',
        formatPreset: 'two_hosts',
        hostPrimaryName: 'Vinnie',
        hostSecondaryName: 'Demi',
        guestNames: const [],
        desiredDurationMinutes: 5,
        voiceId: 'vinnie',
      );

  DeliveryScheduleDto _demoSchedule() => DeliveryScheduleDto(
        timezone: 'Europe/Copenhagen',
        weekdays: const ['mon', 'tue', 'wed', 'thu', 'fri'],
        localTime: '07:00',
        cutoffTime: '23:00',
      );

  EntitlementsDto _demoEntitlements() => EntitlementsDto(
        tier: 'free',
        maxDeliveryDays: 7,
        minDurationMinutes: 3,
        maxDurationMinutes: 5,
        maxItemsPerEpisode: 25,
        premiumPodsPerWeek: 1,
        isInTrial: true,
        trialPremiumPodsRemaining: 5,
      );
}
