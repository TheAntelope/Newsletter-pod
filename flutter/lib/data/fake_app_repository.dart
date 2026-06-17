import 'dart:convert';

import '../api/api_client.dart' show SourcePayload, SharedItemResult;
import '../api/models.dart';
import 'app_repository.dart';
import 'demo_catalog_data.dart';

/// In-memory demo data so the UI runs end-to-end without a backend, Firebase, or
/// accounts. Swapped for [ApiAppRepository] once sign-in returns a real session.
class FakeAppRepository implements AppRepository {
  // Mutable profile bits so updateProfile / reset reflect in-session.
  String _displayName = 'Vince Martin';
  String _timezone = 'Europe/Copenhagen';

  UserDto _user() => UserDto(
        id: 'demo-user',
        email: 'demo@theclawcast.com',
        displayName: _displayName,
        timezone: _timezone,
        inboundAddress: 'demo@theclawcast.com',
      );

  @override
  Future<MeEnvelope> fetchMe() async {
    await Future<void>.delayed(const Duration(milliseconds: 150));
    return MeEnvelope(
      user: _user(),
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
  Future<MeEnvelope> updateProfile({
    required String displayName,
    required String timezone,
  }) async {
    await Future<void>.delayed(const Duration(milliseconds: 120));
    _displayName = displayName;
    _timezone = timezone;
    return fetchMe();
  }

  @override
  Future<void> resetAlgorithm() async {
    await Future<void>.delayed(const Duration(milliseconds: 150));
  }

  @override
  Future<void> deleteAccount() async {
    await Future<void>.delayed(const Duration(milliseconds: 150));
  }

  @override
  Future<FeedEnvelope> fetchFeed() async {
    await Future<void>.delayed(const Duration(milliseconds: 150));
    final now = DateTime.now();
    return FeedEnvelope(
      feedUrl: 'https://theclawcast.com/feeds/6hk6266a.xml',
      token: '6hk6266a',
      latestEpisode: UserEpisodeDto(
        id: 'e1',
        title: 'Your Tuesday Briefing',
        description: 'AI agents, the chip race, and a quiet week in fintech.',
        publishedAt: now.subtract(const Duration(days: 1)),
        durationSeconds: 312,
        processedItemCount: 11,
        droppedItemCount: 2,
        capHit: false,
      ),
      latestRun: UserRunDto(
        id: 'run-1',
        status: 'completed',
        message: 'Published “Your Tuesday Briefing” (11 items).',
        candidateCount: 13,
        capHit: false,
        publishedEpisodeId: 'e1',
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
  Future<CatalogEnvelope> fetchCatalog() async {
    // The real production catalog (~90 sources across 14 topics), embedded as a
    // Dart constant (see demo_catalog_data.dart for why not rootBundle). The
    // live ApiAppRepository fetches the same public endpoint once auth lands.
    return CatalogEnvelope.fromJson(
        jsonDecode(kDemoSourcesCatalogJson) as Map<String, dynamic>);
  }

  @override
  Future<InboundItemsEnvelope> fetchInboundItems() async {
    await Future<void>.delayed(const Duration(milliseconds: 150));
    final now = DateTime.now();
    return InboundItemsEnvelope(
      inboundAddress: 'demo@theclawcast.com',
      items: [
        InboundItemDto(
          id: 'in1',
          fromEmail: 'casey@platformer.news',
          fromName: 'Platformer',
          senderDomain: 'platformer.news',
          subject: 'The trust & safety reorg, explained',
          articleUrl: 'https://platformer.news/x',
          receivedAt: now.subtract(const Duration(hours: 3)),
        ),
        InboundItemDto(
          id: 'in2',
          fromEmail: 'lenny@substack.com',
          fromName: "Lenny's Newsletter",
          senderDomain: 'substack.com',
          subject: 'How the best PMs run discovery',
          receivedAt: now.subtract(const Duration(hours: 20)),
        ),
      ],
    );
  }

  @override
  Future<void> submitFeedback({
    required String text,
    required String source,
  }) async {
    await Future<void>.delayed(const Duration(milliseconds: 150));
  }

  final Set<String> _deletedIntentIds = {};

  @override
  Future<void> deleteSubstackIntent(String intentId) async {
    await Future<void>.delayed(const Duration(milliseconds: 80));
    _deletedIntentIds.add(intentId);
    _createdIntents.removeWhere((i) => i.id == intentId);
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

  /// Mutable so [replaceSources] toggles survive within a session (the demo has
  /// no backend to round-trip through).
  final List<UserSourceDto> _sources = [
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
  ];

  @override
  Future<SourcesEnvelope> fetchSources() async {
    await Future<void>.delayed(const Duration(milliseconds: 150));
    return SourcesEnvelope(
      sources: List.unmodifiable(_sources),
      entitlements: _demoEntitlements(),
    );
  }

  @override
  Future<SourcesEnvelope> replaceSources(List<SourcePayload> sources) async {
    await Future<void>.delayed(const Duration(milliseconds: 120));
    final enabledCatalog =
        sources.map((s) => s.sourceId).whereType<String>().toSet();
    final enabledCustom =
        sources.map((s) => s.rssUrl).whereType<String>().toSet();
    for (var i = 0; i < _sources.length; i++) {
      final s = _sources[i];
      final enabled = s.isCustom
          ? enabledCustom.contains(s.rssUrl)
          : enabledCatalog.contains(s.sourceId);
      _sources[i] = UserSourceDto(
        id: s.id,
        sourceId: s.sourceId,
        name: s.name,
        rssUrl: s.rssUrl,
        isCustom: s.isCustom,
        enabled: enabled,
      );
    }
    return SourcesEnvelope(
      sources: List.unmodifiable(_sources),
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
          sourceItemRefs: [
            SourceItemRefDto(
              sourceId: 'stratechery',
              sourceName: 'Stratechery',
              title: 'The agentic web and the next platform shift',
              link: 'https://stratechery.com/x',
            ),
            SourceItemRefDto(
              sourceId: 'platformer',
              sourceName: 'Platformer',
              title: 'Inside the latest trust & safety reorg',
              link: 'https://platformer.news/x',
            ),
          ],
          transcriptText: 'Good morning. Today: AI agents are quietly rewiring '
              'how software gets distributed, the chip race adds another '
              'contender, and fintech takes a breather.\n\n'
              'First up — the agentic web. The argument is that once agents '
              'mediate what we read and buy, the aggregators that won the last '
              'era have to fight for a very different kind of attention.\n\n'
              'Over in trust & safety, a major platform reorganized its team '
              'after a rough quarter. We unpack what changed and why it matters '
              'for everyone shipping moderation at scale.',
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
          dedupeKey: 'shared1',
          sourceId: 'shared',
          sourceName: 'Shared by you',
          title: 'A long read you sent from Safari',
          summary: 'Saved via the share sheet — pinned to the top so it always '
              'makes the cut.',
          link: 'https://example.com/shared',
          publishedAt: now.subtract(const Duration(hours: 2)),
          pinned: false,
          likelyIncluded: true,
          shared: true,
        ),
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
    // Real voice catalog with public GCS preview MP3s, so "Hear a sample" plays
    // the actual ElevenLabs voices (Vinnie Chase, Demi Dreams, …). Embedded as a
    // Dart constant (see demo_catalog_data.dart) rather than a bundled asset.
    return VoiceCatalogEnvelope.fromJson(
        jsonDecode(kDemoVoicesCatalogJson) as Map<String, dynamic>);
  }

  @override
  Future<SwipeDeckEnvelope> fetchSwipeDeck({List<String>? topics}) async {
    await Future<void>.delayed(const Duration(milliseconds: 150));
    if (topics != null && topics.isNotEmpty) return _coldStartDeck(topics);
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

  /// A cold-start onboarding deck synthesized from the catalog: one card per
  /// source in the picked [topics] (capped), so the stack visibly reflects the
  /// categories the user just selected. The live backend builds the real deck
  /// from freshly-ingested items for the same topics.
  SwipeDeckEnvelope _coldStartDeck(List<String> topics) {
    final selected = topics.toSet();
    final catalog = CatalogEnvelope.fromJson(
        jsonDecode(kDemoSourcesCatalogJson) as Map<String, dynamic>);
    final matches = catalog.sources
        .where((s) => s.topic != null && selected.contains(s.topic))
        .take(12)
        .toList();
    final now = DateTime.now();
    final items = <SwipeDeckCardDto>[];
    for (var i = 0; i < matches.length; i++) {
      final s = matches[i];
      final topic = s.topic!;
      items.add(SwipeDeckCardDto(
        sourceItemDedupeKey: 'cold-${s.sourceId}',
        title: 'What ${s.name} is covering in $topic',
        summary: 'A representative $topic story from ${s.name}.',
        cardSummary:
            'A representative $topic story from ${s.name} — swipe to teach your '
            'pod what to pull more of.',
        sourceId: s.sourceId,
        sourceName: s.name,
        link: s.rssUrl,
        publishedAt: now.subtract(Duration(hours: i + 1)),
      ));
    }
    return SwipeDeckEnvelope(items: items);
  }

  final List<SubstackIntentDto> _createdIntents = [];

  @override
  Future<SubstackIntentsEnvelope> fetchSubstackIntents() async {
    await Future<void>.delayed(const Duration(milliseconds: 150));
    return SubstackIntentsEnvelope(
      inboundAddress: 'demo@theclawcast.com',
      intents: [..._baseIntents(), ..._createdIntents]
          .where((i) => !_deletedIntentIds.contains(i.id))
          .toList(),
    );
  }

  @override
  Future<SubstackDiscoveryEnvelope> discoverSubstacks(String query) async {
    await Future<void>.delayed(const Duration(milliseconds: 250));
    return SubstackDiscoveryEnvelope(
      candidates: [
        SubstackCandidateDto(
          pubUrl: 'https://www.platformer.news',
          pubHost: 'www.platformer.news',
          title: 'Platformer',
          author: 'Casey Newton',
          hasPaidTier: true,
          feedUrl: 'https://www.platformer.news/rss',
          why: 'Tech & policy reporting that matches your interests.',
        ),
        SubstackCandidateDto(
          pubUrl: 'https://importai.substack.com',
          pubHost: 'importai.substack.com',
          title: 'Import AI',
          author: 'Jack Clark',
          hasPaidTier: false,
          feedUrl: 'https://importai.substack.com/feed',
          why: 'A weekly AI research roundup.',
        ),
      ],
    );
  }

  @override
  Future<SubstackIntentEnvelope> createSubstackIntent(String pubUrl) async {
    await Future<void>.delayed(const Duration(milliseconds: 150));
    final host = Uri.tryParse(pubUrl)?.host ?? pubUrl;
    final intent = SubstackIntentDto(
      id: 'new-${_createdIntents.length + 1}',
      userId: 'demo-user',
      pubUrl: pubUrl,
      pubHost: host,
      pubTitle: host,
      hasPaidTier: false,
      aliasEmail: 'demo@theclawcast.com',
      createdAt: DateTime.now(),
      status: SubstackIntentStatus.pending,
    );
    _createdIntents.add(intent);
    return SubstackIntentEnvelope(intent: intent);
  }

  /// Tracks shares submitted this session so the demo flags the second identical
  /// share as a duplicate, mirroring the backend's deterministic de-dupe.
  final Set<String> _sharedKeys = {};

  @override
  Future<SharedItemResult> submitSharedItem({
    required String kind,
    String? url,
    List<int>? fileBytes,
    String? filename,
    String? title,
  }) async {
    await Future<void>.delayed(const Duration(milliseconds: 200));
    final key = '$kind:${url ?? filename ?? title ?? ''}';
    final duplicate = !_sharedKeys.add(key);
    return SharedItemResult(
      itemId: 'demo-share-${_sharedKeys.length}',
      title: title ?? url ?? filename ?? 'Shared item',
      shareKind: kind,
      duplicate: duplicate,
    );
  }

  List<SubstackIntentDto> _baseIntents() {
    final now = DateTime.now();
    return [
      SubstackIntentDto(
        id: 'int1',
        userId: 'demo-user',
        pubUrl: 'https://newsletter.pragmaticengineer.com',
        pubHost: 'newsletter.pragmaticengineer.com',
        pubTitle: 'The Pragmatic Engineer',
        hasPaidTier: true,
        aliasEmail: 'demo@theclawcast.com',
        createdAt: now.subtract(const Duration(days: 2)),
        confirmedAt: now.subtract(const Duration(days: 1)),
        status: SubstackIntentStatus.confirmed,
      ),
      SubstackIntentDto(
        id: 'int2',
        userId: 'demo-user',
        pubUrl: 'https://www.lennysnewsletter.com',
        pubHost: 'www.lennysnewsletter.com',
        pubTitle: "Lenny's Newsletter",
        hasPaidTier: true,
        aliasEmail: 'demo@theclawcast.com',
        createdAt: now.subtract(const Duration(minutes: 10)),
        status: SubstackIntentStatus.pending,
        pendingVerificationCode: '481920',
        pendingVerificationExpiresAt: now.add(const Duration(minutes: 12)),
      ),
    ];
  }

  PodcastProfileDto _demoProfile() => PodcastProfileDto(
        title: 'ClawCast',
        formatPreset: 'two_hosts',
        hostPrimaryName: 'Vinnie',
        hostSecondaryName: 'Demi',
        guestNames: const [],
        desiredDurationMinutes: 5,
        voiceId: 'suMMgpGbVcnihP1CcgFS', // Vinnie Chase (real catalog id)
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
        maxDurationMinutes: 7,
        maxItemsPerEpisode: 25,
        premiumPodsPerWeek: 1,
        isInTrial: true,
        trialPremiumPodsRemaining: 5,
      );
}
