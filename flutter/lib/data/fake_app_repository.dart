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
      profile: PodcastProfileDto(
        title: 'ClawCast',
        formatPreset: 'two_hosts',
        hostPrimaryName: 'Vinnie',
        hostSecondaryName: 'Demi',
        guestNames: const [],
        desiredDurationMinutes: 5,
      ),
      schedule: DeliveryScheduleDto(
        timezone: 'Europe/Copenhagen',
        weekdays: const ['mon', 'tue', 'wed', 'thu', 'fri'],
        localTime: '07:00',
        cutoffTime: '23:00',
      ),
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
