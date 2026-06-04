import 'package:flutter/material.dart';

import '../api/api_client.dart' show SourcePayload;
import '../api/models.dart';
import '../design_tokens.dart';
import '../services/location_service.dart';
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
  static const _stepCount = 11;
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

  // Style options, mirrored from the podcast-settings editor so the two stay in
  // step. The onboarding defaults lean playful + dad jokes (see _tone/_humor).
  static const _toneOptions = [
    ('calm_analyst', 'Calm analyst'),
    ('warm_friendly', 'Warm & friendly'),
    ('snappy_news', 'Snappy news'),
    ('playful', 'Playful'),
  ];

  static const _humorOptions = [
    ('none', 'None'),
    ('dry_wit', 'Dry wit'),
    ('dad_jokes', 'Dad jokes'),
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
  // Style step (right after voice). Defaults to a playful show with dad jokes.
  String _tone = 'playful';
  String _humor = 'dad_jokes';
  int _keyFindings = 3;
  bool _greeting = true;
  bool _topTakeaways = true;
  bool _includeWeather = false;
  // "Use my current location" flow for the weather city. Mirrors the iOS
  // LocationResolver states (idle / requesting / denied / error / resolved).
  bool _locating = false;
  bool _locationDenied = false;
  String? _locationError;
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

  /// Persist the picked topics as enabled sources (pod tuning) and the onboarding
  /// picks onto the profile, then drop into the dashboard. Neither write blocks
  /// finishing — the user can still tune in-app — but a failure is surfaced (not
  /// silently swallowed) so they know which picks didn't save.
  Future<void> _finish() async {
    final app = AppScope.of(context);
    final messenger = ScaffoldMessenger.of(context);
    final failed = <String>[
      if (!await _persistTopicSources(app)) 'topics',
      if (!await _persistProfile(app)) 'show settings',
    ];
    if (mounted && failed.isNotEmpty) {
      messenger.showSnackBar(
        SnackBar(
          content: Text(
            "Couldn't save your ${failed.join(' and ')} during setup — "
            'open the app to set them.',
          ),
        ),
      );
    }
    if (!mounted) return;
    app.completeOnboarding();
  }

  /// Returns true on success (including the no-op empty case), false if the
  /// source write failed — the caller surfaces that.
  Future<bool> _persistTopicSources(AppState app) async {
    try {
      final catalog = await (_catalog ??= app.repository.fetchCatalog());
      final payloads = catalog.sources
          .where((s) => s.topic != null && _selectedTopics.contains(s.topic))
          .map((s) => SourcePayload(sourceId: s.sourceId, isCustom: false))
          .toList();
      if (payloads.isEmpty) return true;
      await app.repository.replaceSources(payloads);
      return true;
    } catch (_) {
      return false;
    }
  }

  /// Persist the onboarding picks onto the podcast profile + schedule. We patch
  /// the loaded profile rather than build one from scratch so server-managed
  /// fields (title, host names, guidance, duration) survive untouched. Like the
  /// source write, this never blocks finishing onboarding; returns true on
  /// success, false on failure so the caller can surface it.
  Future<bool> _persistProfile(AppState app) async {
    try {
      final config = await app.repository.fetchPodcastConfig();
      final loaded = config.profile;
      final weather = _weatherController.text.trim();
      final updated = PodcastProfileDto(
        title: loaded.title,
        formatPreset: _showPreset,
        hostPrimaryName: loaded.hostPrimaryName,
        hostSecondaryName: loaded.hostSecondaryName,
        guestNames: loaded.guestNames,
        desiredDurationMinutes: loaded.desiredDurationMinutes,
        voiceId: _anchorVoiceId ?? loaded.voiceId,
        secondaryVoiceId: _isTwoHost
            ? (_commentatorVoiceId ?? loaded.secondaryVoiceId)
            : loaded.secondaryVoiceId,
        tone: _tone,
        keyFindingsCount: _keyFindings,
        humorStyle: _humor,
        personalizedGreeting: _greeting,
        includeTopTakeaways: _topTakeaways,
        includeWeather: _includeWeather,
        weatherLocation: weather.isEmpty ? null : weather,
        customGuidance: loaded.customGuidance,
        customGuidancePresetId: loaded.customGuidancePresetId,
      );
      await app.repository.updatePodcastConfig(updated);

      // Preserve the server's timezone; only override the days + delivery time.
      final schedule = await app.repository.fetchSchedule();
      await app.repository.updateSchedule(
        timezone: schedule.schedule.timezone,
        weekdays: _selectedDays.toList(),
        localTime: _formatTime(_deliveryTime),
      );
      return true;
    } catch (_) {
      return false;
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
            // ElevenLabs Startup Grant attribution — pinned to the bottom of the
            // welcome screen only, just above the primary action.
            if (_step == 0) ...[
              const ElevenLabsBadge(),
              const SizedBox(height: DesignTokens.spacingS),
            ],
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
          leading: const ClawcastLogo(size: 64),
          title: 'Welcome to ClawCast',
          subtitle:
              'A daily briefing podcast, built from the sources you choose. '
              "Here's what we'll set up — it takes about a minute.",
          children: const [_WelcomeSteps()],
        );
      case 1:
        return _shell(
          title: 'Pick your voice',
          subtitle:
              'First, the fun part — choose the voice that reads your briefing '
              'every morning. Tap a card to hear a sample.',
          children: [_hostVoiceStep()],
        );
      case 2:
        return _shell(
          title: 'Style your show',
          subtitle:
              'Set the feel of your briefing — tone, humor, how many takeaways, '
              'and whether to open with the local weather. You can change any of '
              'this later from Podcast settings.',
          children: [_styleStep()],
        );
      case 3:
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
      case 4:
        return _shell(
          title: 'Pick your topics',
          subtitle:
              'Choose what you want in your briefing. We pull sources from these '
              "categories and build your first stories to swipe — you can fine-"
              'tune any time from the Sources tab.',
          children: [_topicsStep()],
        );
      case 5:
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
      case 6:
        return _shell(
          title: 'Add your Substacks',
          subtitle:
              'Forward Substack subscriptions to your private ClawCast address '
              'and they fold into your pod automatically.',
          children: const [_InboundAddressCard()],
        );
      case 7:
        return _shell(
          title: 'Choose a format',
          subtitle: 'How should your briefing be hosted?',
          children: [_showStep()],
        );
      case 8:
        return _shell(
          title: _isTwoHost ? 'Add a co-host' : 'Your host',
          subtitle: _isTwoHost
              ? 'Your show pairs two voices — pick a co-host to trade off with '
                  'the host you chose. You can change these later.'
              : 'This is the voice you picked to read your briefing. Change it '
                  'here if you like.',
          children: [_coHostStep()],
        );
      case 9:
        return _shell(
          title: 'Set your schedule',
          subtitle:
              'Choose which mornings your pod is ready. We default to weekdays '
              'at 07:00.',
          children: [_scheduleEditor()],
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
    Widget? leading,
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
          if (leading != null) ...[
            leading,
            const SizedBox(height: DesignTokens.spacingL),
          ],
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

  /// The fun opener: pick the primary host voice. Single-select, with audio
  /// samples. Format-independent so it can be the very first onboarding step.
  Widget _hostVoiceStep() {
    return _voiceCatalogBuilder((voices) {
      return Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          for (final v in voices) ...[
            VoiceChoiceCard(
              voice: v,
              selected: _anchorVoiceId == v.id,
              onSelect: () => setState(() => _anchorVoiceId = v.id),
              previewSource: v.previewUrl,
            ),
            const SizedBox(height: DesignTokens.spacingM),
          ],
        ],
      );
    });
  }

  /// Shown after the format is chosen. For two-host it picks the co-host (the
  /// host was chosen up front, on step 0); otherwise it re-shows the host picker
  /// so it can still be changed, plus the rotating-guest note.
  Widget _coHostStep() {
    return _voiceCatalogBuilder((voices) {
      final hostName = _voiceName(voices, _anchorVoiceId);
      if (_isTwoHost) {
        return Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            if (hostName != null) ...[
              const _FieldLabel('Your host'),
              const SizedBox(height: DesignTokens.spacingS),
              Text(
                hostName,
                style: DesignTokens.typographyBodyStrong
                    .copyWith(color: DesignTokens.colorInk),
              ),
              const SizedBox(height: DesignTokens.spacingL),
            ],
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
          ],
        );
      }
      return Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          for (final v in voices) ...[
            VoiceChoiceCard(
              voice: v,
              selected: _anchorVoiceId == v.id,
              onSelect: () => setState(() => _anchorVoiceId = v.id),
              previewSource: v.previewUrl,
            ),
            const SizedBox(height: DesignTokens.spacingM),
          ],
          if (_isRotating)
            Text(
              'A different guest voice joins ${hostName ?? 'your host'} each day, '
              'drawn from the full catalog.',
              style: DesignTokens.typographyCallout
                  .copyWith(color: DesignTokens.colorMuted),
            ),
        ],
      );
    });
  }

  /// Resolves the voice-catalog future once and hands the list to [builder],
  /// showing a spinner while it loads. Shared by the host and co-host steps.
  Widget _voiceCatalogBuilder(
      Widget Function(List<CatalogVoiceDto> voices) builder) {
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
        return builder(snapshot.data?.voices ?? const []);
      },
    );
  }

  String? _voiceName(List<CatalogVoiceDto> voices, String? id) {
    if (id == null) return null;
    for (final v in voices) {
      if (v.id == id) return v.name;
    }
    return null;
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

  /// The Style step, shown right after the voice pick. Mirrors the Style + Weather
  /// sections of the podcast-settings editor: tone, humor, key-takeaway count,
  /// greeting + top-takeaways toggles, then the weather note (folded in here
  /// rather than a separate late step).
  Widget _styleStep() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        EditorialCard(
          children: [
            const _FieldLabel('Tone'),
            _PillGroup(
              options: _toneOptions,
              selectedId: _tone,
              onSelect: (id) => setState(() => _tone = id),
            ),
            const _FieldLabel('Humor'),
            _PillGroup(
              options: _humorOptions,
              selectedId: _humor,
              onSelect: (id) => setState(() => _humor = id),
            ),
            const _FieldLabel('Key takeaways'),
            Row(
              children: [
                for (var n = 3; n <= 7; n++)
                  Padding(
                    padding: const EdgeInsets.only(right: DesignTokens.spacingS),
                    child: _NumberPill(
                      value: n,
                      selected: _keyFindings == n,
                      onTap: () => setState(() => _keyFindings = n),
                    ),
                  ),
              ],
            ),
            const EditorialDivider(),
            _SwitchRow(
              label: 'Greet me by name',
              value: _greeting,
              onChanged: (v) => setState(() => _greeting = v),
            ),
            _SwitchRow(
              label: 'Include top takeaways',
              value: _topTakeaways,
              onChanged: (v) => setState(() => _topTakeaways = v),
            ),
          ],
        ),
        const SizedBox(height: DesignTokens.spacingL),
        const MetaLabel('Weather'),
        const SizedBox(height: DesignTokens.spacingM),
        _weatherEditor(),
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
          const SizedBox(height: DesignTokens.spacingS),
          _locationRow(),
        ],
      ],
    );
  }

  /// "Use my current location" affordance under the city field. Detects the
  /// user's city (with permission) and fills the field, or surfaces a denial /
  /// error inline. Typing stays available for anyone who declines.
  Widget _locationRow() {
    if (_locating) {
      return Row(
        children: const [
          SizedBox(
            width: 16,
            height: 16,
            child: CircularProgressIndicator(strokeWidth: 2),
          ),
          SizedBox(width: DesignTokens.spacingS),
          Text('Detecting your location…'),
        ],
      );
    }
    final hasCity = _weatherController.text.trim().isNotEmpty;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Align(
          alignment: Alignment.centerLeft,
          child: TextButton.icon(
            onPressed: _resolveLocation,
            style: TextButton.styleFrom(
              foregroundColor: DesignTokens.colorAmberDeep,
              padding: EdgeInsets.zero,
            ),
            icon: const Icon(Icons.my_location, size: 18),
            label: Text(hasCity ? 'Update from my location' : 'Use my current location'),
          ),
        ),
        if (_locationDenied)
          Text(
            'Location access denied. Enable it in your settings, or type your '
            'city above.',
            style: DesignTokens.typographyCallout
                .copyWith(color: DesignTokens.colorMuted),
          )
        else if (_locationError != null)
          Text(
            "Couldn't fetch location: $_locationError",
            style: DesignTokens.typographyCallout
                .copyWith(color: DesignTokens.colorMuted),
          ),
      ],
    );
  }

  Future<void> _resolveLocation() async {
    setState(() {
      _locating = true;
      _locationDenied = false;
      _locationError = null;
    });
    final outcome = await LocationService.resolveCurrentPlace();
    if (!mounted) return;
    setState(() {
      _locating = false;
      switch (outcome.kind) {
        case LocationOutcomeKind.resolved:
          _weatherController.text = outcome.placeName!;
        case LocationOutcomeKind.denied:
          _locationDenied = true;
        case LocationOutcomeKind.error:
          _locationError = outcome.message;
      }
    });
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

/// The setup agenda, shown two ways: as numbered steps on the welcome screen
/// and as completed checks on the "you're all set" recap. Kept in one place so
/// the two never drift — and so it stays an accurate summary of the actual
/// onboarding steps (voice + format, topics + sources, schedule). Note there is
/// no length/duration step in onboarding — that lives in the podcast settings.
const _setupAgenda = [
  'Pick your voice and show format',
  'Choose the topics and sources you trust',
  'Get a fresh briefing on your schedule',
];

/// The welcome preview: a numbered "here's what we'll do" list. Numbered badges
/// (not check circles) so it reads as an agenda rather than a tappable form.
class _WelcomeSteps extends StatelessWidget {
  const _WelcomeSteps();

  @override
  Widget build(BuildContext context) {
    return EditorialCard(
      spacing: DesignTokens.spacingM,
      children: [
        for (var i = 0; i < _setupAgenda.length; i++)
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
                  _setupAgenda[i],
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

  @override
  Widget build(BuildContext context) {
    return EditorialCard(
      spacing: DesignTokens.spacingS,
      children: [
        for (final p in _setupAgenda)
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

/// A wrapped row of single-select choice pills (tone / humor). Mirrors the
/// podcast-settings `_PillGroup` so the two surfaces match.
class _PillGroup extends StatelessWidget {
  const _PillGroup({
    required this.options,
    required this.selectedId,
    required this.onSelect,
  });

  final List<(String, String)> options;
  final String selectedId;
  final ValueChanged<String> onSelect;

  @override
  Widget build(BuildContext context) {
    return Wrap(
      spacing: DesignTokens.spacingS,
      runSpacing: DesignTokens.spacingS,
      children: [
        for (final opt in options)
          _ChoicePill(
            label: opt.$2,
            selected: selectedId == opt.$1,
            onTap: () => onSelect(opt.$1),
          ),
      ],
    );
  }
}

class _ChoicePill extends StatelessWidget {
  const _ChoicePill({
    required this.label,
    required this.selected,
    required this.onTap,
  });

  final String label;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: onTap,
      child: Container(
        padding: const EdgeInsets.symmetric(
          horizontal: DesignTokens.spacingM,
          vertical: DesignTokens.spacingS,
        ),
        decoration: BoxDecoration(
          color: selected ? DesignTokens.colorAmber : Colors.transparent,
          borderRadius: BorderRadius.circular(999),
          border: Border.all(
            color: selected ? DesignTokens.colorAmber : DesignTokens.colorRule,
            width: 1.5,
          ),
        ),
        child: Text(
          label,
          style: DesignTokens.typographyCalloutStrong.copyWith(
            color: selected ? Colors.white : DesignTokens.colorInk,
          ),
        ),
      ),
    );
  }
}

class _NumberPill extends StatelessWidget {
  const _NumberPill({
    required this.value,
    required this.selected,
    required this.onTap,
  });

  final int value;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: onTap,
      child: Container(
        width: 40,
        height: 40,
        alignment: Alignment.center,
        decoration: BoxDecoration(
          shape: BoxShape.circle,
          color: selected ? DesignTokens.colorAmber : Colors.transparent,
          border: Border.all(
            color: selected ? DesignTokens.colorAmber : DesignTokens.colorRule,
            width: 1.5,
          ),
        ),
        child: Text(
          '$value',
          style: DesignTokens.typographySubtitle.copyWith(
            color: selected ? Colors.white : DesignTokens.colorInk,
          ),
        ),
      ),
    );
  }
}

class _SwitchRow extends StatelessWidget {
  const _SwitchRow({
    required this.label,
    required this.value,
    required this.onChanged,
  });

  final String label;
  final bool value;
  final ValueChanged<bool> onChanged;

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        Expanded(
          child: Text(
            label,
            style: DesignTokens.typographyBody
                .copyWith(color: DesignTokens.colorInk),
          ),
        ),
        Switch(value: value, onChanged: onChanged),
      ],
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
