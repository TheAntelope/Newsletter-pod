import 'dart:io' show Platform;

import 'package:flutter/material.dart';

import '../api/models.dart';
import '../design_tokens.dart';
import '../services/dictation_controller.dart';
import '../state/app_state.dart';
import '../widgets/editorial.dart';
import '../widgets/generation_progress_bar.dart';
import 'account_screen.dart';
import 'dashboard_scaffold.dart';
import 'feed_access_screen.dart';
import 'next_episode_queue_screen.dart';
import 'paywall_screen.dart';
import 'podcast_setup_screen.dart';
import 'sources_screen.dart';

/// The Today / "Your Briefing" dashboard. Editorial rebuild mirroring the iOS
/// `HomeView`: greeting, a generation banner with progress while a run is
/// active, the hero latest-episode card, plan + schedule cards, the next-pod
/// queue entry, a setup checklist (hidden once setup is complete), and the
/// primary Generate action.
class HomeScreen extends StatefulWidget {
  const HomeScreen({super.key});

  @override
  State<HomeScreen> createState() => _HomeScreenState();
}

class _HomeScreenState extends State<HomeScreen> {
  late final AppState _app;
  bool _initialized = false;

  LibraryEpisodeDto? _latestEpisode;
  bool _queueEnabled = true;
  int _pinnedCount = 0;
  int _enabledSourceCount = 0;
  bool _loadedSources = false;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (!_initialized) {
      _initialized = true;
      _app = AppScope.of(context);
      _loadExtras();
    }
  }

  Future<void> _loadExtras() async {
    try {
      final episodes = await _app.repository.fetchEpisodes();
      if (mounted && episodes.episodes.isNotEmpty) {
        setState(() => _latestEpisode = episodes.episodes.first);
      }
    } catch (_) {/* hero falls back to the coming-soon state */}
    try {
      final queue = await _app.repository.fetchNextEpisodeQueue();
      if (mounted) {
        setState(() {
          _queueEnabled = queue.enabled;
          _pinnedCount = queue.pinnedCount;
        });
      }
    } catch (_) {/* queue card hidden on failure */}
    try {
      final sources = await _app.repository.fetchSources();
      if (mounted) {
        setState(() {
          _enabledSourceCount =
              sources.sources.where((s) => s.enabled).length;
          _loadedSources = true;
        });
      }
    } catch (_) {/* checklist treats sources as unknown */}
  }

  @override
  Widget build(BuildContext context) {
    final app = AppScope.of(context);
    final me = app.me;

    return Scaffold(
      appBar: AppBar(
        leading: Padding(
          padding: const EdgeInsets.all(8),
          child: ClawcastLogo(
            size: 28,
            onTap: () => DashboardScope.goHome(context),
          ),
        ),
        title: const Text('Your Briefing'),
        actions: [
          IconButton(
            tooltip: 'Podcast & schedule',
            onPressed: () => Navigator.of(context).push(
              MaterialPageRoute(builder: (_) => const PodcastSetupScreen()),
            ),
            icon: const Icon(Icons.tune),
          ),
          IconButton(
            tooltip: 'Account',
            onPressed: () => Navigator.of(context).push(
              MaterialPageRoute(builder: (_) => const AccountScreen()),
            ),
            icon: const Icon(Icons.settings_outlined),
          ),
        ],
      ),
      body: SafeArea(
        child: switch ((app.loading, me)) {
          (true, null) => const Center(child: CircularProgressIndicator()),
          (_, null) => Center(
              child: Padding(
                padding: const EdgeInsets.symmetric(
                  horizontal: DesignTokens.spacingXl,
                ),
                child: Text(
                  app.error ?? 'Something went wrong',
                  textAlign: TextAlign.center,
                ),
              ),
            ),
          (_, final MeEnvelope loaded) => _Dashboard(
              me: loaded,
              app: app,
              latestEpisode: _latestEpisode,
              queueEnabled: _queueEnabled,
              pinnedCount: _pinnedCount,
              enabledSourceCount: _enabledSourceCount,
              sourcesKnown: _loadedSources,
            ),
        },
      ),
    );
  }
}

class _Dashboard extends StatelessWidget {
  const _Dashboard({
    required this.me,
    required this.app,
    required this.latestEpisode,
    required this.queueEnabled,
    required this.pinnedCount,
    required this.enabledSourceCount,
    required this.sourcesKnown,
  });

  final MeEnvelope me;
  final AppState app;
  final LibraryEpisodeDto? latestEpisode;
  final bool queueEnabled;
  final int pinnedCount;
  final int enabledSourceCount;
  final bool sourcesKnown;

  @override
  Widget build(BuildContext context) {
    return ListView(
      padding: const EdgeInsets.fromLTRB(
        DesignTokens.spacingL,
        DesignTokens.spacingS,
        DesignTokens.spacingL,
        DesignTokens.spacingXl,
      ),
      children: [
        _GreetingHeader(name: me.user.firstName),
        const SizedBox(height: DesignTokens.spacingL),
        if (app.isGenerating) ...[
          _GenerationBanner(
            hasEpisode: latestEpisode != null,
            message: app.lastRunMessage,
          ),
          const SizedBox(height: DesignTokens.spacingL),
        ],
        _HeroEpisodeCard(
          episode: latestEpisode,
          isGenerating: app.isGenerating,
          app: app,
          entitlements: me.entitlements,
        ),
        if (queueEnabled) ...[
          const SizedBox(height: DesignTokens.spacingL),
          _NextEpisodeQueueCard(pinnedCount: pinnedCount),
        ],
        const SizedBox(height: DesignTokens.spacingL),
        _PlanCard(
          subscription: me.subscription,
          entitlements: me.entitlements,
        ),
        const SizedBox(height: DesignTokens.spacingL),
        _ScheduleCard(schedule: me.schedule),
        const SizedBox(height: DesignTokens.spacingL),
        _AboutPodcastCard(profile: me.profile),
        const SizedBox(height: DesignTokens.spacingL),
        _SourcesSummaryCard(
          enabledCount: enabledSourceCount,
          known: sourcesKnown,
        ),
        const SizedBox(height: DesignTokens.spacingL),
        _SetupChecklistCard(
          hasSources: !sourcesKnown || enabledSourceCount > 0,
          hasShow: me.profile.title.isNotEmpty,
          hasSchedule: me.schedule.weekdays.isNotEmpty,
          hasEpisode: latestEpisode != null,
        ),
        if (app.error != null) ...[
          const SizedBox(height: DesignTokens.spacingM),
          Text(
            app.error!,
            style: DesignTokens.typographyBody
                .copyWith(color: DesignTokens.colorAmberDeep),
          ),
        ],
        const SizedBox(height: DesignTokens.spacingL),
        const _FeedbackComposer(),
      ],
    );
  }
}

class _GreetingHeader extends StatelessWidget {
  const _GreetingHeader({required this.name});

  final String name;

  @override
  Widget build(BuildContext context) {
    final hour = DateTime.now().hour;
    final partOfDay = switch (hour) {
      >= 5 && < 12 => 'morning',
      >= 12 && < 17 => 'afternoon',
      >= 17 && < 22 => 'evening',
      _ => 'night',
    };
    final greeting =
        name.isEmpty ? 'Good $partOfDay.' : 'Good $partOfDay, $name.';
    return Text(
      greeting,
      style: DesignTokens.typographyDisplay.copyWith(color: DesignTokens.colorInk),
    );
  }
}

class _GenerationBanner extends StatelessWidget {
  const _GenerationBanner({required this.hasEpisode, required this.message});

  final bool hasEpisode;
  final String? message;

  @override
  Widget build(BuildContext context) {
    final headline = hasEpisode
        ? "We're putting together your next episode."
        : 'Your first episode is being made.';
    return EditorialCard(
      spacing: DesignTokens.spacingS,
      children: [
        Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            const Icon(Icons.auto_awesome,
                size: 22, color: DesignTokens.colorAmberDeep),
            const SizedBox(width: DesignTokens.spacingM),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    headline,
                    style: DesignTokens.typographySubtitle
                        .copyWith(color: DesignTokens.colorInk),
                  ),
                  const SizedBox(height: 2),
                  Text(
                    message ??
                        'About 3–5 minutes. You can close the app — the episode '
                            'lands in your feed and on this screen when ready.',
                    style: DesignTokens.typographyCallout
                        .copyWith(color: DesignTokens.colorInkSoft),
                  ),
                ],
              ),
            ),
          ],
        ),
        const GenerationProgressBar(isGenerating: true),
      ],
    );
  }
}

class _HeroEpisodeCard extends StatefulWidget {
  const _HeroEpisodeCard({
    required this.episode,
    required this.isGenerating,
    required this.app,
    required this.entitlements,
  });

  final LibraryEpisodeDto? episode;
  final bool isGenerating;
  final AppState app;
  final EntitlementsDto entitlements;

  @override
  State<_HeroEpisodeCard> createState() => _HeroEpisodeCardState();
}

class _HeroEpisodeCardState extends State<_HeroEpisodeCard> {
  bool _descExpanded = false;
  bool _transcriptExpanded = false;

  @override
  Widget build(BuildContext context) {
    final ep = widget.episode;
    final badge = ep != null
        ? 'Latest episode'
        : (widget.isGenerating ? 'Generating now' : 'Coming soon');
    final title = ep?.title ??
        (widget.isGenerating
            ? 'Cooking up your first briefing…'
            : 'No episode yet');
    final transcript = ep?.transcriptText;

    return EditorialCard(
      children: [
        MetaLabel(badge),
        Text(
          title,
          style: DesignTokens.typographyTitle.copyWith(color: DesignTokens.colorInk),
        ),
        if (ep != null) ...[
          Text(
            ep.description,
            maxLines: _descExpanded ? null : 3,
            overflow: _descExpanded ? null : TextOverflow.ellipsis,
            style: DesignTokens.typographyBody
                .copyWith(color: DesignTokens.colorInkSoft),
          ),
          if (ep.description.length > 140)
            _Disclosure(
              expanded: _descExpanded,
              labelCollapsed: 'Show more',
              labelExpanded: 'Show less',
              onTap: () => setState(() => _descExpanded = !_descExpanded),
            ),
          Wrap(
            spacing: DesignTokens.spacingM,
            runSpacing: DesignTokens.spacingXs,
            children: [
              if (ep.durationSeconds != null)
                _MetaChip(
                  icon: Icons.schedule,
                  label: '${(ep.durationSeconds! / 60).round()} min',
                ),
              _MetaChip(
                icon: Icons.article_outlined,
                label: '${ep.processedItemCount} items',
              ),
              _MetaChip(
                icon: Icons.calendar_today_outlined,
                label: _relativeDate(ep.publishedAt),
              ),
            ],
          ),
          if (transcript != null && transcript.isNotEmpty) ...[
            const EditorialDivider(),
            _Disclosure(
              expanded: _transcriptExpanded,
              labelCollapsed: 'Show transcript',
              labelExpanded: 'Hide transcript',
              onTap: () =>
                  setState(() => _transcriptExpanded = !_transcriptExpanded),
            ),
            if (_transcriptExpanded)
              Text(
                transcript,
                style: DesignTokens.typographyCallout
                    .copyWith(color: DesignTokens.colorInkSoft, height: 1.5),
              ),
          ],
        ] else
          Text(
            widget.isGenerating
                ? 'Your episode is on its way — it will appear here and in your '
                    'feed when ready.'
                : 'Tap Generate below to make your first episode now, or wait '
                    'for your scheduled delivery.',
            style: DesignTokens.typographyBody
                .copyWith(color: DesignTokens.colorInkSoft),
          ),
        const EditorialDivider(),
        AmberButton.filled(
          label: _openInPodcastAppLabel(),
          icon: Icons.play_arrow,
          onPressed: ep == null
              ? null
              : () => Navigator.of(context).push(
                    MaterialPageRoute(builder: (_) => const FeedAccessScreen()),
                  ),
        ),
        const SizedBox(height: DesignTokens.spacingM),
        AmberButton.filled(
          label: 'Generate now',
          icon: Icons.auto_awesome,
          loading: widget.isGenerating,
          onPressed: widget.isGenerating ? null : widget.app.generateNow,
        ),
        const SizedBox(height: DesignTokens.spacingXs),
        Text(
          _premiumRemainingLabel(widget.entitlements),
          textAlign: TextAlign.center,
          style: DesignTokens.typographyCallout
              .copyWith(color: DesignTokens.colorInkSoft),
        ),
      ],
    );
  }
}

/// The "open in podcast app" button names the platform's actual delivery
/// target: Apple Podcasts on iOS, Podcast Addict on Android (our chosen Android
/// player — see [PodcastAddict]). Other platforms get a neutral fallback.
String _openInPodcastAppLabel() {
  if (Platform.isIOS) return 'Open in Apple Podcasts';
  if (Platform.isAndroid) return 'Open in Podcast Addict';
  return 'Open in your podcast app';
}

/// "2 of 3 premium voice pods left this week" — the weekly premium-voice quota
/// shown under the Generate action. Trial users see their trial allowance.
String _premiumRemainingLabel(EntitlementsDto ent) {
  if (ent.isInTrial) {
    final n = ent.trialPremiumPodsRemaining;
    return 'Trial: $n premium voice pod${n == 1 ? '' : 's'} left';
  }
  return '${ent.premiumPodsRemainingThisWeek} of ${ent.premiumPodsPerWeek} '
      'premium voice pods left this week';
}

class _Disclosure extends StatelessWidget {
  const _Disclosure({
    required this.expanded,
    required this.labelCollapsed,
    required this.labelExpanded,
    required this.onTap,
  });

  final bool expanded;
  final String labelCollapsed;
  final String labelExpanded;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return InkWell(
      onTap: onTap,
      child: Row(
        mainAxisSize: MainAxisSize.min,
        children: [
          Text(
            expanded ? labelExpanded : labelCollapsed,
            style: DesignTokens.typographyCalloutStrong
                .copyWith(color: DesignTokens.colorAmberDeep),
          ),
          Icon(expanded ? Icons.expand_less : Icons.expand_more,
              size: 18, color: DesignTokens.colorAmberDeep),
        ],
      ),
    );
  }
}

class _AboutPodcastCard extends StatelessWidget {
  const _AboutPodcastCard({required this.profile});

  final PodcastProfileDto profile;

  String get _format => switch (profile.formatPreset) {
        'solo_host' => 'Solo host',
        'rotating_guest' => 'Rotating guest',
        _ => 'Two hosts',
      };

  @override
  Widget build(BuildContext context) {
    final hosts = [
      profile.hostPrimaryName,
      if ((profile.hostSecondaryName ?? '').isNotEmpty) profile.hostSecondaryName!,
    ].join(' & ');
    return EditorialCard(
      spacing: DesignTokens.spacingS,
      onTap: () => Navigator.of(context).push(
        MaterialPageRoute(builder: (_) => const PodcastSetupScreen()),
      ),
      children: [
        Row(
          children: [
            const Expanded(child: MetaLabel('Your show')),
            const Icon(Icons.chevron_right,
                size: 18, color: DesignTokens.colorMuted),
          ],
        ),
        Text(
          profile.title,
          style: DesignTokens.typographyTitle.copyWith(color: DesignTokens.colorInk),
        ),
        Text(
          '$_format · ${profile.desiredDurationMinutes} min'
          '${hosts.isEmpty ? '' : ' · $hosts'}',
          style: DesignTokens.typographyBody.copyWith(color: DesignTokens.colorInkSoft),
        ),
      ],
    );
  }
}

class _SourcesSummaryCard extends StatelessWidget {
  const _SourcesSummaryCard({required this.enabledCount, required this.known});

  final int enabledCount;
  final bool known;

  @override
  Widget build(BuildContext context) {
    return EditorialCard(
      spacing: DesignTokens.spacingS,
      onTap: () => Navigator.of(context).push(
        MaterialPageRoute(builder: (_) => const SourcesScreen()),
      ),
      children: [
        Row(
          children: [
            const Expanded(child: MetaLabel('Sources')),
            const Icon(Icons.chevron_right,
                size: 18, color: DesignTokens.colorMuted),
          ],
        ),
        Text(
          known ? '$enabledCount active' : 'Manage your sources',
          style: DesignTokens.typographySubtitle.copyWith(color: DesignTokens.colorInk),
        ),
        Text(
          'Pick the newsletters and feeds your briefing is built from.',
          style: DesignTokens.typographyCallout
              .copyWith(color: DesignTokens.colorInkSoft),
        ),
      ],
    );
  }
}

class _FeedbackComposer extends StatefulWidget {
  const _FeedbackComposer();

  @override
  State<_FeedbackComposer> createState() => _FeedbackComposerState();
}

class _FeedbackComposerState extends State<_FeedbackComposer> {
  final _controller = TextEditingController();
  final _dictation = DictationController();
  bool _submitting = false;
  bool _sent = false;
  String _source = 'text';
  String _dictationBase = '';

  @override
  void initState() {
    super.initState();
    _dictation.addListener(_onDictation);
  }

  @override
  void dispose() {
    _dictation.removeListener(_onDictation);
    _dictation.dispose();
    _controller.dispose();
    super.dispose();
  }

  void _onDictation() {
    if (_dictation.listening || _dictation.transcript.isNotEmpty) {
      final sep = (_dictationBase.isEmpty || _dictationBase.endsWith(' '))
          ? ''
          : ' ';
      _controller.text = '$_dictationBase$sep${_dictation.transcript}';
    }
    setState(() {});
  }

  Future<void> _toggleDictation() async {
    if (_dictation.listening) {
      await _dictation.stop();
      return;
    }
    final messenger = ScaffoldMessenger.of(context);
    _dictationBase = _controller.text;
    _source = 'voice';
    final ok = await _dictation.start();
    if (!ok) {
      messenger.showSnackBar(
        const SnackBar(content: Text("Dictation isn't available here.")),
      );
    }
  }

  Future<void> _submit() async {
    final text = _controller.text.trim();
    if (text.isEmpty) return;
    final repo = AppScope.of(context).repository;
    final messenger = ScaffoldMessenger.of(context);
    if (_dictation.listening) await _dictation.stop();
    setState(() => _submitting = true);
    try {
      await repo.submitFeedback(text: text, source: _source);
      if (!mounted) return;
      setState(() {
        _sent = true;
        _controller.clear();
        _source = 'text';
      });
    } catch (e) {
      messenger.showSnackBar(SnackBar(content: Text('$e')));
    } finally {
      if (mounted) setState(() => _submitting = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final listening = _dictation.listening;
    return EditorialCard(
      children: [
        const MetaLabel('Send feedback'),
        if (_sent)
          Text(
            'Thanks — we read every note.',
            style: DesignTokens.typographyBody
                .copyWith(color: DesignTokens.colorInkSoft),
          )
        else ...[
          TextField(
            controller: _controller,
            maxLines: 3,
            decoration: const InputDecoration(
              hintText: "What's working, what's not, what would you change?",
            ),
          ),
          Row(
            children: [
              AmberButton.outlined(
                label: listening ? 'Stop' : 'Dictate',
                icon: listening ? Icons.stop : Icons.mic,
                expand: false,
                onPressed: _submitting ? null : _toggleDictation,
              ),
              const Spacer(),
              AmberButton.filled(
                label: 'Submit',
                expand: false,
                loading: _submitting,
                onPressed: _submitting || listening ? null : _submit,
              ),
            ],
          ),
        ],
      ],
    );
  }
}

class _MetaChip extends StatelessWidget {
  const _MetaChip({required this.icon, required this.label});

  final IconData icon;
  final String label;

  @override
  Widget build(BuildContext context) {
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Icon(icon, size: 14, color: DesignTokens.colorMuted),
        const SizedBox(width: 4),
        Text(
          label,
          style: DesignTokens.typographyCallout
              .copyWith(color: DesignTokens.colorMuted),
        ),
      ],
    );
  }
}

class _PlanCard extends StatelessWidget {
  const _PlanCard({required this.subscription, required this.entitlements});

  final SubscriptionDto subscription;
  final EntitlementsDto entitlements;

  @override
  Widget build(BuildContext context) {
    final tier = subscription.tier.toUpperCase();
    return EditorialCard(
      spacing: DesignTokens.spacingS,
      onTap: () => Navigator.of(context).push(
        MaterialPageRoute(builder: (_) => const PaywallScreen()),
      ),
      children: [
        const MetaLabel('Plan'),
        Text(
          '$tier · ${subscription.status}',
          style: DesignTokens.typographyTitle.copyWith(color: DesignTokens.colorInk),
        ),
        Text(
          entitlements.isInTrial
              ? 'Trial: ${entitlements.trialPremiumPodsRemaining} premium pods left'
              : '${entitlements.premiumPodsRemainingThisWeek} of '
                  '${entitlements.premiumPodsPerWeek} premium pods left this week',
          style: DesignTokens.typographyBody.copyWith(color: DesignTokens.colorInkSoft),
        ),
        Row(
          children: [
            Text(
              'See plans',
              style: DesignTokens.typographyCalloutStrong
                  .copyWith(color: DesignTokens.colorAmberDeep),
            ),
            const Icon(Icons.chevron_right,
                size: 18, color: DesignTokens.colorAmberDeep),
          ],
        ),
      ],
    );
  }
}

class _ScheduleCard extends StatelessWidget {
  const _ScheduleCard({required this.schedule});

  final DeliveryScheduleDto schedule;

  @override
  Widget build(BuildContext context) {
    final days = schedule.weekdays
        .map((d) => d.isEmpty ? d : '${d[0].toUpperCase()}${d.substring(1)}')
        .join(' · ');
    return EditorialCard(
      spacing: DesignTokens.spacingS,
      onTap: () => Navigator.of(context).push(
        MaterialPageRoute(
          builder: (_) => const PodcastSetupScreen(
            initialSection: PodcastSetupSection.schedule,
          ),
        ),
      ),
      children: [
        Row(
          children: [
            const Expanded(child: MetaLabel('Schedule')),
            const Icon(Icons.chevron_right,
                size: 18, color: DesignTokens.colorMuted),
          ],
        ),
        Text(
          'Delivered at ${schedule.localTime}',
          style: DesignTokens.typographyTitle.copyWith(color: DesignTokens.colorInk),
        ),
        Text(
          days,
          style: DesignTokens.typographyBody.copyWith(color: DesignTokens.colorInkSoft),
        ),
      ],
    );
  }
}

class _NextEpisodeQueueCard extends StatelessWidget {
  const _NextEpisodeQueueCard({required this.pinnedCount});

  final int pinnedCount;

  @override
  Widget build(BuildContext context) {
    return EditorialCard(
      spacing: DesignTokens.spacingS,
      onTap: () => Navigator.of(context).push(
        MaterialPageRoute(builder: (_) => const NextEpisodeQueueScreen()),
      ),
      children: [
        Row(
          children: [
            const Expanded(child: MetaLabel('Coming in your next pod')),
            if (pinnedCount > 0)
              Text(
                '$pinnedCount pinned',
                style: DesignTokens.typographyCallout
                    .copyWith(color: DesignTokens.colorAmberDeep),
              ),
            const SizedBox(width: 4),
            const Icon(Icons.chevron_right,
                size: 18, color: DesignTokens.colorMuted),
          ],
        ),
        Text(
          "Peek at what's queued",
          style: DesignTokens.typographySubtitle.copyWith(color: DesignTokens.colorInk),
        ),
        Text(
          'Preview & pin the stories',
          style: DesignTokens.typographyCallout
              .copyWith(color: DesignTokens.colorInkSoft),
        ),
      ],
    );
  }
}

class _SetupChecklistCard extends StatelessWidget {
  const _SetupChecklistCard({
    required this.hasSources,
    required this.hasShow,
    required this.hasSchedule,
    required this.hasEpisode,
  });

  final bool hasSources;
  final bool hasShow;
  final bool hasSchedule;
  final bool hasEpisode;

  @override
  Widget build(BuildContext context) {
    if (hasSources && hasShow && hasSchedule && hasEpisode) {
      return const SizedBox.shrink();
    }
    return EditorialCard(
      children: [
        const MetaLabel('Setup checklist'),
        Column(
          children: [
            ChecklistRow(label: 'Pick at least one source', isComplete: hasSources),
            const SizedBox(height: DesignTokens.spacingS),
            ChecklistRow(label: 'Configure your show', isComplete: hasShow),
            const SizedBox(height: DesignTokens.spacingS),
            ChecklistRow(label: 'Set a delivery schedule', isComplete: hasSchedule),
            const SizedBox(height: DesignTokens.spacingS),
            ChecklistRow(label: 'First episode ready', isComplete: hasEpisode),
          ],
        ),
      ],
    );
  }
}

/// "5 hours ago", "yesterday", "3 days ago" — the casual meta-row date.
String _relativeDate(DateTime when) {
  final diff = DateTime.now().difference(when.toLocal());
  if (diff.inMinutes < 1) return 'just now';
  if (diff.inMinutes < 60) return '${diff.inMinutes} min ago';
  if (diff.inHours < 24) {
    return '${diff.inHours} hour${diff.inHours == 1 ? '' : 's'} ago';
  }
  if (diff.inDays == 1) return 'yesterday';
  return '${diff.inDays} days ago';
}
