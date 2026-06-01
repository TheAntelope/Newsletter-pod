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
