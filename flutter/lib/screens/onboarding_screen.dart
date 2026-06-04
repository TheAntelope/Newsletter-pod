import 'package:flutter/material.dart';

import '../api/api_client.dart' show SourcePayload;
import '../api/models.dart';
import '../design_tokens.dart';
import '../state/app_state.dart';
import '../widgets/day_toggle.dart';
import '../widgets/editorial.dart';
import '../widgets/onboarding_progress_dots.dart';
import '../widgets/voice_choice_card.dart';
import 'swipe_deck_screen.dart';

/// Onboarding wizard (welcome → name → sources → Substack → show format → voices
/// → schedule → weather → done). Editorial rebuild on the shared step-shell
/// pattern from iOS: serif display title, body subtitle, a scrollable content
/// well, and a bottom amber primary / outlined-back button pair, with the
/// progress dots up top. Collected values are local in this build; finishing
/// calls completeOnboarding so RootView shows the dashboard.
class OnboardingScreen extends StatefulWidget {
  const OnboardingScreen({super.key});

  @override
  State<OnboardingScreen> createState() => _OnboardingScreenState();
}

class _OnboardingScreenState extends State<OnboardingScreen> {
  static const _stepCount = 10;
  static const _weekdays = [
    ('mon', 'M'),
    ('tue', 'T'),
    ('wed', 'W'),
    ('thu', 'T'),
    ('fri', 'F'),
    ('sat', 'S'),
    ('sun', 'S'),
  ];

  static const _showPresets = [
    ('solo_host', 'Solo host', 'One voice walks through the day.'),
    ('two_hosts', 'Two hosts', 'An anchor and a co-host trade off. Recommended.'),
    ('rotating_guest', 'Rotating guest',
        'An anchor plus a different guest voice each day.'),
  ];

  /// Curated icon + display order for the catalog's topic categories. The chips
  /// shown are the intersection of this map with the topics actually present in
  /// the catalog, so new catalog topics fall back to a default glyph rather than
  /// disappearing.
  static const _topicIcons = <String, IconData>{
    'News': Icons.public,
    'Politics': Icons.account_balance_outlined,
    'Business': Icons.trending_up,
    'Tech': Icons.memory,
    'Strategy': Icons.lightbulb_outline,
    'Personal Finance': Icons.savings_outlined,
    'Science': Icons.science_outlined,
    'Sports': Icons.sports_basketball_outlined,
    'Culture': Icons.theater_comedy_outlined,
    'Health & Wellness': Icons.spa_outlined,
    'Fitness': Icons.fitness_center,
    'Family Life': Icons.family_restroom_outlined,
    'Food & Travel': Icons.restaurant_outlined,
    'Romantasy': Icons.auto_stories_outlined,
  };

  int _step = 0;
  final _nameController = TextEditingController();
  final _weatherController = TextEditingController();
  String _showPreset = 'two_hosts';
  // Topic categories the user picks on the sources step. These both enable the
  // matching catalog sources (pod tuning) on finish and seed the swipe deck.
  final Set<String> _selectedTopics = {'Tech', 'Business'};
  Future<CatalogEnvelope>? _catalog;
  String? _anchorVoiceId;
  String? _commentatorVoiceId;
  bool _includeWeather = false;
  final Set<String> _selectedDays = {'mon', 'tue', 'wed', 'thu', 'fri'};
  TimeOfDay _deliveryTime = const TimeOfDay(hour: 7, minute: 0);

  Future<VoiceCatalogEnvelope>? _voices;

  bool get _isTwoHost => _showPreset == 'two_hosts';
  bool get _isRotating => _showPreset == 'rotating_guest';

  @override
  void dispose() {
    _nameController.dispose();
    _weatherController.dispose();
    super.dispose();
  }

  void _next() {
    if (_step < _stepCount - 1) {
      setState(() => _step++);
    } else {
      _finish();
    }
  }

  /// Persist the picked topics as enabled sources (pod tuning), then drop into
  /// the dashboard. The source write is best-effort — onboarding completes even
  /// if it fails, since the user can still tune from the Sources tab.
  Future<void> _finish() async {
    final app = AppScope.of(context);
    await _persistTopicSources(app);
    if (!mounted) return;
    app.completeOnboarding();
  }

  Future<void> _persistTopicSources(AppState app) async {
    try {
      final catalog = await (_catalog ??= app.repository.fetchCatalog());
      final payloads = catalog.sources
          .where((s) => s.topic != null && _selectedTopics.contains(s.topic))
          .map((s) => SourcePayload(sourceId: s.sourceId, isCustom: false))
          .toList();
      if (payloads.isEmpty) return;
      await app.repository.replaceSources(payloads);
    } catch (_) {
      // Best-effort; never block finishing onboarding.
    }
  }

  void _back() {
    if (_step > 0) setState(() => _step--);
  }

  @override
  Widget build(BuildContext context) {
    final isLast = _step == _stepCount - 1;
    return Scaffold(
      body: SafeArea(
        child: Column(
          children: [
            Padding(
              padding: const EdgeInsets.fromLTRB(
                DesignTokens.spacingL,
                DesignTokens.spacingM,
                DesignTokens.spacingL,
                0,
              ),
              child: Row(
                children: [
                  OnboardingProgressDots(current: _step, total: _stepCount),
                  const Spacer(),
                  if (!isLast)
                    TextButton(
                      onPressed: AppScope.of(context).completeOnboarding,
                      style: TextButton.styleFrom(
                        foregroundColor: DesignTokens.colorMuted,
                      ),
                      child: const Text('Skip'),
                    ),
                ],
              ),
            ),
            Expanded(child: _stepContent()),
            Padding(
              padding: const EdgeInsets.all(DesignTokens.spacingL),
              child: Column(
                children: [
                  AmberButton.filled(
                    label: isLast ? 'Finish' : 'Next',
                    onPressed: _next,
                  ),
                  if (_step > 0) ...[
                    const SizedBox(height: DesignTokens.spacingS),
                    AmberButton.outlined(label: 'Back', onPressed: _back),
                  ],
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _stepContent() {
    switch (_step) {
      case 0:
        return _shell(
          title: 'Welcome to ClawCast',
          subtitle:
              'A daily briefing podcast, built from the sources you choose. '
              "Here's what we'll set up — it takes about a minute.",
          children: const [_WelcomeSteps()],
        );
      case 1:
        return _shell(
          title: 'What should we call you?',
          subtitle: "We'll greet you by name at the top of each episode.",
          children: [
            TextField(
              controller: _nameController,
              textCapitalization: TextCapitalization.words,
              decoration: const InputDecoration(labelText: 'Your name'),
            ),
          ],
        );
      case 2:
        return _shell(
          title: 'Pick your topics',
          subtitle:
              'Choose what you want in your briefing. We pull sources from these '
              "categories and build your first stories to swipe — you can fine-"
              'tune any time from the Sources tab.',
          children: [_topicsStep()],
        );
      case 3:
        return _shell(
          title: 'Tune your pod',
          subtitle:
              "Swipe right on stories you'd want to hear more about, left to "
              'skip. Optional — your picker learns from every card.',
          children: [
            SizedBox(
              height: 460,
              child: SwipeDeck(topics: _selectedTopics.toList()),
            ),
          ],
        );
      case 4:
        return _shell(
          title: 'Add your Substacks',
          subtitle:
              'Forward Substack subscriptions to your private ClawCast address '
              'and they fold into your pod automatically.',
          children: const [_InboundAddressCard()],
        );
      case 5:
        return _shell(
          title: 'Choose a format',
          subtitle: 'How should your briefing be hosted?',
          children: [_showStep()],
        );
      case 6:
        return _shell(
          title: _isTwoHost ? 'Choose your voices' : 'Choose a voice',
          subtitle: _isTwoHost
              ? 'Pick an anchor and a co-host. You can change these later.'
              : 'Pick who reads your briefing. You can change this later.',
          children: [_voiceStep()],
        );
      case 7:
        return _shell(
          title: 'Set your schedule',
          subtitle:
              'Choose which mornings your pod is ready. We default to weekdays '
              'at 07:00.',
          children: [_scheduleEditor()],
        );
      case 8:
        return _shell(
          title: 'Add a weather note?',
          subtitle:
              'Open each episode with a quick local weather line, if you like.',
          children: [_weatherEditor()],
        );
      default:
        return _shell(
          title: "You're all set",
          subtitle:
              "We'll generate your first pod shortly. You can change everything "
              'later from the app.',
          children: const [_WelcomePoints(allChecked: true)],
        );
    }
  }

  Widget _shell({
    required String title,
    required String subtitle,
    required List<Widget> children,
  }) {
    return SingleChildScrollView(
      padding: const EdgeInsets.fromLTRB(
        DesignTokens.spacingL,
        DesignTokens.spacingM,
        DesignTokens.spacingL,
        DesignTokens.spacingL,
      ),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Text(
            title,
            style: DesignTokens.typographyDisplay
                .copyWith(color: DesignTokens.colorInk),
          ),
          const SizedBox(height: DesignTokens.spacingS),
          Text(
            subtitle,
            style: DesignTokens.typographyBody
                .copyWith(color: DesignTokens.colorInkSoft),
          ),
          const SizedBox(height: DesignTokens.spacingL),
          ...children,
        ],
      ),
    );
  }

  Widget _topicsStep() {
    _catalog ??= AppScope.of(context).repository.fetchCatalog();
    return FutureBuilder<CatalogEnvelope>(
      future: _catalog,
      builder: (context, snapshot) {
        if (snapshot.connectionState != ConnectionState.done) {
          return const Padding(
            padding: EdgeInsets.all(DesignTokens.spacingL),
            child: Center(child: CircularProgressIndicator()),
          );
        }
        final topics = _topicsFrom(snapshot.data);
        return EditorialCard(
          children: [
            const MetaLabel('Topics'),
            Text(
              'Tap to add or remove. Your first swipe deck is built from these.',
              style: DesignTokens.typographyCallout
                  .copyWith(color: DesignTokens.colorMuted),
            ),
            Wrap(
              spacing: DesignTokens.spacingS,
              runSpacing: DesignTokens.spacingS,
              children: [
                for (final t in topics)
                  _TopicChip(
                    label: t,
                    icon: _topicIcons[t] ?? Icons.label_outline,
                    selected: _selectedTopics.contains(t),
                    onTap: () => setState(() {
                      if (!_selectedTopics.remove(t)) _selectedTopics.add(t);
                    }),
                  ),
              ],
            ),
          ],
        );
      },
    );
  }

  /// Distinct topic names in catalog order (first appearance wins).
  List<String> _topicsFrom(CatalogEnvelope? catalog) {
    final seen = <String>{};
    final ordered = <String>[];
    for (final s in catalog?.sources ?? const []) {
      final t = s.topic;
      if (t != null && t.isNotEmpty && seen.add(t)) ordered.add(t);
    }
    return ordered;
  }

  Widget _showStep() {
    return EditorialCard(
      spacing: 0,
      children: [
        for (var i = 0; i < _showPresets.length; i++) ...[
          if (i > 0) const EditorialDivider(),
          _ShowPresetRow(
            title: _showPresets[i].$2,
            subtitle: _showPresets[i].$3,
            selected: _showPreset == _showPresets[i].$1,
            onTap: () => setState(() => _showPreset = _showPresets[i].$1),
          ),
        ],
      ],
    );
  }

  Widget _voiceStep() {
    _voices ??= AppScope.of(context).repository.fetchVoiceCatalog();
    return FutureBuilder<VoiceCatalogEnvelope>(
      future: _voices,
      builder: (context, snapshot) {
        if (snapshot.connectionState != ConnectionState.done) {
          return const Padding(
            padding: EdgeInsets.all(DesignTokens.spacingL),
            child: Center(child: CircularProgressIndicator()),
          );
        }
        final voices = snapshot.data?.voices ?? const [];
        return Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            _FieldLabel(_isTwoHost ? 'Anchor' : 'Voice'),
            const SizedBox(height: DesignTokens.spacingS),
            for (final v in voices) ...[
              VoiceChoiceCard(
                voice: v,
                selected: _anchorVoiceId == v.id,
                onSelect: () => setState(() => _anchorVoiceId = v.id),
                previewSource: v.previewUrl,
              ),
              const SizedBox(height: DesignTokens.spacingM),
            ],
            if (_isTwoHost) ...[
              const SizedBox(height: DesignTokens.spacingS),
              const _FieldLabel('Co-host'),
              const SizedBox(height: DesignTokens.spacingS),
              for (final v in voices) ...[
                VoiceChoiceCard(
                  voice: v,
                  selected: _commentatorVoiceId == v.id,
                  onSelect: () => setState(() => _commentatorVoiceId = v.id),
                  previewSource: v.previewUrl,
                ),
                const SizedBox(height: DesignTokens.spacingM),
              ],
            ] else if (_isRotating)
              Text(
                'A different guest voice joins your anchor each day, drawn from '
                'the full catalog.',
                style: DesignTokens.typographyCallout
                    .copyWith(color: DesignTokens.colorMuted),
              ),
          ],
        );
      },
    );
  }

  Widget _scheduleEditor() {
    return EditorialCard(
      children: [
        const MetaLabel('Delivery days'),
        Row(
          mainAxisAlignment: MainAxisAlignment.spaceBetween,
          children: [
            for (final day in _weekdays)
              DayToggle(
                initial: day.$2,
                selected: _selectedDays.contains(day.$1),
                onTap: () => setState(() {
                  if (!_selectedDays.remove(day.$1)) _selectedDays.add(day.$1);
                }),
              ),
          ],
        ),
        const EditorialDivider(),
        Row(
          children: [
            Text(
              'Delivered at',
              style: DesignTokens.typographyBody
                  .copyWith(color: DesignTokens.colorInk),
            ),
            const Spacer(),
            OutlinedButton(
              onPressed: () async {
                final picked = await showTimePicker(
                  context: context,
                  initialTime: _deliveryTime,
                );
                if (picked != null) setState(() => _deliveryTime = picked);
              },
              child: Text(_formatTime(_deliveryTime)),
            ),
          ],
        ),
      ],
    );
  }

  Widget _weatherEditor() {
    return EditorialCard(
      children: [
        Row(
          children: [
            Expanded(
              child: Text(
                'Include local weather in each pod',
                style: DesignTokens.typographyBody
                    .copyWith(color: DesignTokens.colorInk),
              ),
            ),
            Switch(
              value: _includeWeather,
              onChanged: (v) => setState(() => _includeWeather = v),
            ),
          ],
        ),
        if (_includeWeather) ...[
          const EditorialDivider(),
          TextField(
            controller: _weatherController,
            decoration: const InputDecoration(
              labelText: 'City',
              hintText: 'e.g. Copenhagen',
            ),
          ),
        ],
      ],
    );
  }

  String _formatTime(TimeOfDay t) =>
      '${t.hour.toString().padLeft(2, '0')}:${t.minute.toString().padLeft(2, '0')}';
}

class _FieldLabel extends StatelessWidget {
  const _FieldLabel(this.label);

  final String label;

  @override
  Widget build(BuildContext context) {
    return Text(
      label,
      style: DesignTokens.typographyCalloutStrong
          .copyWith(color: DesignTokens.colorMuted),
    );
  }
}

class _ShowPresetRow extends StatelessWidget {
  const _ShowPresetRow({
    required this.title,
    required this.subtitle,
    required this.selected,
    required this.onTap,
  });

  final String title;
  final String subtitle;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return InkWell(
      onTap: onTap,
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: DesignTokens.spacingM),
        child: Row(
          children: [
            Icon(
              selected
                  ? Icons.radio_button_checked
                  : Icons.radio_button_unchecked,
              color: selected
                  ? DesignTokens.colorAmber
                  : DesignTokens.colorMuted,
            ),
            const SizedBox(width: DesignTokens.spacingM),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    title,
                    style: DesignTokens.typographyBodyStrong
                        .copyWith(color: DesignTokens.colorInk),
                  ),
                  Text(
                    subtitle,
                    style: DesignTokens.typographyCallout
                        .copyWith(color: DesignTokens.colorMuted),
                  ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }
}

/// The welcome preview: a numbered "here's what we'll do" list. Numbered badges
/// (not check circles) so it reads as an agenda rather than a tappable form.
class _WelcomeSteps extends StatelessWidget {
  const _WelcomeSteps();

  static const _steps = [
    'Pick the topics and sources you trust',
    'Choose a format, voice, and length',
    'Get a fresh briefing on your schedule',
  ];

  @override
  Widget build(BuildContext context) {
    return EditorialCard(
      spacing: DesignTokens.spacingM,
      children: [
        for (var i = 0; i < _steps.length; i++)
          Row(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Container(
                width: 26,
                height: 26,
                alignment: Alignment.center,
                decoration: const BoxDecoration(
                  color: DesignTokens.colorAmber,
                  shape: BoxShape.circle,
                ),
                child: Text(
                  '${i + 1}',
                  style: DesignTokens.typographyCalloutStrong
                      .copyWith(color: Colors.white),
                ),
              ),
              const SizedBox(width: DesignTokens.spacingM),
              Expanded(
                child: Text(
                  _steps[i],
                  style: DesignTokens.typographyBody
                      .copyWith(color: DesignTokens.colorInk),
                ),
              ),
            ],
          ),
      ],
    );
  }
}

/// The "you're all set" recap — the same agenda shown as completed checks.
class _WelcomePoints extends StatelessWidget {
  const _WelcomePoints({this.allChecked = false});

  final bool allChecked;

  static const _points = [
    'Pick the topics and sources you trust',
    'Choose a format, voice, and length',
    'Get a fresh briefing on your schedule',
  ];

  @override
  Widget build(BuildContext context) {
    return EditorialCard(
      spacing: DesignTokens.spacingS,
      children: [
        for (final p in _points)
          ChecklistRow(label: p, isComplete: allChecked),
      ],
    );
  }
}

/// A selectable topic pill. Amber fill when selected; cream/outline when not.
class _TopicChip extends StatelessWidget {
  const _TopicChip({
    required this.label,
    required this.icon,
    required this.selected,
    required this.onTap,
  });

  final String label;
  final IconData icon;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    final fg = selected ? Colors.white : DesignTokens.colorInk;
    return Semantics(
      button: true,
      selected: selected,
      label: label,
      child: InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(999),
        child: Container(
          padding: const EdgeInsets.symmetric(
            horizontal: DesignTokens.spacingM,
            vertical: DesignTokens.spacingS,
          ),
          decoration: BoxDecoration(
            color: selected ? DesignTokens.colorAmber : DesignTokens.colorCream,
            borderRadius: BorderRadius.circular(999),
            border: Border.all(
              color: selected ? DesignTokens.colorAmber : DesignTokens.colorRule,
            ),
          ),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(
                selected ? Icons.check : icon,
                size: 16,
                color: selected ? Colors.white : DesignTokens.colorAmberDeep,
              ),
              const SizedBox(width: 6),
              Text(
                label,
                style: DesignTokens.typographyCalloutStrong.copyWith(color: fg),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

class _InboundAddressCard extends StatelessWidget {
  const _InboundAddressCard();

  @override
  Widget build(BuildContext context) {
    final address =
        AppScope.of(context).me?.user.inboundAddress ?? 'you@theclawcast.com';
    return EditorialCard(
      spacing: DesignTokens.spacingS,
      children: [
        const MetaLabel('Your private inbound address'),
        Text(
          address,
          style: DesignTokens.typographyTitle
              .copyWith(color: DesignTokens.colorAmberDeep),
        ),
        Text(
          'Forward newsletters here, or use this address when you subscribe to '
          'new ones. The next episode picks them up automatically.',
          style: DesignTokens.typographyCallout
              .copyWith(color: DesignTokens.colorInkSoft),
        ),
      ],
    );
  }
}
