import 'dart:async';
import 'dart:io' show Platform;

import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../api/api_client.dart' show SourcePayload;
import '../api/models.dart';
import '../design_tokens.dart';
import '../services/link_launcher.dart';
import '../services/location_service.dart';
import '../state/app_state.dart';
import '../widgets/day_toggle.dart';
import '../widgets/editorial.dart';
import '../widgets/inbound_address_card.dart';
import '../widgets/onboarding_progress_dots.dart';
import '../widgets/topic_icon.dart';
import '../widgets/voice_choice_card.dart';
import 'swipe_deck_screen.dart';

/// Onboarding wizard (welcome → voice → style+weather → format → co-host → name
/// → topics → swipe → Substack → share → schedule → done). Editorial rebuild on
/// the shared step-shell pattern from iOS: serif display title, body subtitle, a
/// scrollable content well, and a bottom amber primary / outlined-back button
/// pair, with the progress dots up top. On finish the picks are written through
/// to the podcast profile + schedule (best-effort) before completeOnboarding
/// hands off to RootView's dashboard.
class OnboardingScreen extends StatefulWidget {
  const OnboardingScreen({super.key});

  @override
  State<OnboardingScreen> createState() => _OnboardingScreenState();
}

class _OnboardingScreenState extends State<OnboardingScreen> {
  /// The visible steps, in display order. This is an explicit sequence (not the
  /// numeric id order), so the switch in [_stepContent] keys off ids, not
  /// position. Two steps are conditional:
  ///   - the name step (3) only when the user opted into a personalised greeting
  ///     on the style step;
  ///   - the second-voice / co-host step (8) only for a two-host show — solo and
  ///     rotating-guest shows use the single host voice picked up front.
  /// The format step (7) is placed right after the style step (2), and the
  /// co-host step (8) directly follows the format step when two hosts is picked.
  List<int> get _activeSteps => [
        0, // welcome
        1, // pick your voice (host)
        2, // style your show
        7, // choose a format
        if (_isTwoHost) 8, // add a co-host (second voice)
        if (_greeting) 3, // what should we call you?
        4, // pick your topics
        5, // tune your pod (swipe deck)
        6, // add your Substacks
        11, // add from anywhere (OS share sheet)
        9, // set your schedule
        10, // you're all set
      ];

  /// The step id currently shown, resolved from the position [_step] within
  /// [_activeSteps]. `_step` indexes the visible list, not the raw id space.
  int get _currentStepId =>
      _activeSteps[_step.clamp(0, _activeSteps.length - 1)];
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
    ('witty', 'Witty & clever'),
    ('sarcastic', 'Sarcastic'),
    ('punny', 'Punny'),
    ('silly', 'Playful & silly'),
  ];

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

  @override
  void dispose() {
    _nameController.dispose();
    _weatherController.dispose();
    super.dispose();
  }

  void _next() {
    if (_step < _activeSteps.length - 1) {
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
    // Auto-kick the user's first episode as they leave onboarding — parity with
    // iOS, which fires generateNow() on the final onboarding step. Not awaited:
    // generateNow() flips isGenerating synchronously and drives its own polling,
    // so the dashboard greets the user with the generation banner the moment we
    // hand off. Runs after the profile/source/schedule writes above so the
    // backend generates against the picks just saved.
    unawaited(app.generateNow());
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
    final isLast = _step == _activeSteps.length - 1;
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
                  OnboardingProgressDots(
                      current: _step, total: _activeSteps.length),
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
            if (_currentStepId == 0) ...[
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
    switch (_currentStepId) {
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
              child: SwipeDeck(
                topics: _selectedTopics.toList(),
                onboarding: true,
              ),
            ),
          ],
        );
      case 6:
        return _shell(
          title: 'Add your newsletters',
          subtitle:
              'Describe what you read and we\'ll find matching Substacks — or '
              'paste a handle directly. Add the ones you want, then subscribe '
              'with your private ClawCast address. Optional; you can do this any '
              'time from Sources.',
          children: const [_OnboardingSubstackStep()],
        );
      case 7:
        return _shell(
          title: 'Choose a format',
          subtitle: 'How should your briefing be hosted?',
          children: [_showStep()],
        );
      case 8:
        // Only reached for a two-host show (see _activeSteps) — solo and
        // rotating-guest shows skip the second-voice pick entirely.
        return _shell(
          title: 'Add a co-host',
          subtitle:
              'Your show pairs two voices — pick a co-host to trade off with '
              'the host you chose. You can change these later.',
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
      case 11:
        return _shell(
          title: 'Add from anywhere',
          subtitle:
              'One more thing worth knowing: outside the app — reading in your '
              'browser, Mail, or Substack — you can send anything straight to '
              'ClawCast and we’ll work it into your next pod. No copy-paste.',
          children: const [_ShareFromAnywhereStep()],
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
                    icon: topicIcon(t),
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

  /// The second-voice pick, shown only for a two-host show (the host was chosen
  /// up front, on step 1). Solo and rotating-guest shows skip this step, so it
  /// always renders the co-host picker.
  Widget _coHostStep() {
    return _voiceCatalogBuilder((voices) {
      final hostName = _voiceName(voices, _anchorVoiceId);
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
        const EditorialDivider(),
        _NoScheduleOptOut(
          optedOut: _selectedDays.isEmpty,
          onOptOut: () => setState(_selectedDays.clear),
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

/// Lets the user decline a recurring schedule and generate pods on demand
/// instead. "Opted out" is simply an empty weekday set — when it's empty we show
/// a confirming note rather than the opt-out button.
class _NoScheduleOptOut extends StatelessWidget {
  const _NoScheduleOptOut({required this.optedOut, required this.onOptOut});

  final bool optedOut;
  final VoidCallback onOptOut;

  @override
  Widget build(BuildContext context) {
    if (optedOut) {
      return Row(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          Icon(
            Icons.bolt_outlined,
            size: 20,
            color: DesignTokens.colorMuted,
          ),
          const SizedBox(width: DesignTokens.spacingS),
          Expanded(
            child: Text(
              'No schedule — pick days above any time, or just generate a pod '
              'yourself whenever you want one.',
              style: DesignTokens.typographyCallout
                  .copyWith(color: DesignTokens.colorMuted),
            ),
          ),
        ],
      );
    }
    return Align(
      alignment: Alignment.centerLeft,
      child: TextButton(
        onPressed: onOptOut,
        child: const Text(
          "No thanks — I'll generate pods on my own when I want to",
          textAlign: TextAlign.left,
        ),
      ),
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

/// Onboarding teach step for the OS share sheet. ClawCast ingests whatever the
/// user reads elsewhere, but that flow lives entirely in the system share sheet
/// (there's no in-app button), so onboarding surfaces it once — a mock of the
/// share sheet plus a three-step how-to. The dashboard's `_ShareTipCard` is the
/// recurring reminder; this is the first introduction.
class _ShareFromAnywhereStep extends StatelessWidget {
  const _ShareFromAnywhereStep();

  @override
  Widget build(BuildContext context) {
    // Match the platform's name for the affordance: "Share" on Android, "the
    // Share button" on iOS — so the instruction matches what the user sees.
    final shareVerb =
        (!kIsWeb && Platform.isIOS) ? 'the Share button' : 'Share';
    final steps = [
      'Reading something good? Tap $shareVerb in your browser, Mail, or Substack.',
      'Pick ClawCast from the share sheet.',
      'We work it into your next pod — automatically.',
    ];
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const _ShareSheetMock(),
        const SizedBox(height: DesignTokens.spacingL),
        EditorialCard(
          spacing: DesignTokens.spacingM,
          children: [
            for (var i = 0; i < steps.length; i++)
              _NumberedRow(index: i, text: steps[i]),
          ],
        ),
      ],
    );
  }
}

/// A numbered "agenda" row: amber badge with the 1-based index, then the label.
class _NumberedRow extends StatelessWidget {
  const _NumberedRow({required this.index, required this.text});

  final int index;
  final String text;

  @override
  Widget build(BuildContext context) {
    return Row(
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
            '${index + 1}',
            style: DesignTokens.typographyCalloutStrong
                .copyWith(color: Colors.white),
          ),
        ),
        const SizedBox(width: DesignTokens.spacingM),
        Expanded(
          child: Text(
            text,
            style:
                DesignTokens.typographyBody.copyWith(color: DesignTokens.colorInk),
          ),
        ),
      ],
    );
  }
}

/// A stylised mock of the OS share sheet with the ClawCast row highlighted, so
/// users recognise the target when they open the real sheet. Purely decorative.
class _ShareSheetMock extends StatelessWidget {
  const _ShareSheetMock();

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.all(DesignTokens.spacingM),
      decoration: BoxDecoration(
        color: DesignTokens.colorCream,
        borderRadius: BorderRadius.circular(DesignTokens.radiusCard),
        border: Border.all(color: DesignTokens.colorRule),
      ),
      child: Column(
        children: [
          // Grabber handle, like a bottom sheet.
          Container(
            width: 36,
            height: 4,
            decoration: BoxDecoration(
              color: DesignTokens.colorRule,
              borderRadius: BorderRadius.circular(999),
            ),
          ),
          const SizedBox(height: DesignTokens.spacingM),
          Row(
            children: [
              const Icon(Icons.ios_share,
                  size: 16, color: DesignTokens.colorMuted),
              const SizedBox(width: 6),
              Text(
                'Share',
                style: DesignTokens.typographyCalloutStrong
                    .copyWith(color: DesignTokens.colorMuted),
              ),
            ],
          ),
          const SizedBox(height: DesignTokens.spacingM),
          // The highlighted ClawCast destination.
          Container(
            padding: const EdgeInsets.all(DesignTokens.spacingS),
            decoration: BoxDecoration(
              color: Colors.white,
              borderRadius: BorderRadius.circular(DesignTokens.radiusCard),
              border: Border.all(color: DesignTokens.colorAmber, width: 1.5),
            ),
            child: Row(
              children: [
                const ClawcastLogo(size: 36),
                const SizedBox(width: DesignTokens.spacingM),
                Expanded(
                  child: Text(
                    'ClawCast',
                    style: DesignTokens.typographyBodyStrong
                        .copyWith(color: DesignTokens.colorInk),
                  ),
                ),
                const Icon(Icons.check_circle,
                    size: 20, color: DesignTokens.colorAmberDeep),
              ],
            ),
          ),
          const SizedBox(height: DesignTokens.spacingS),
          // Dimmed sibling rows so it reads as one option among many.
          for (final sib in const ['Messages', 'Mail', 'Notes'])
            Padding(
              padding: const EdgeInsets.symmetric(vertical: 6),
              child: Row(
                children: [
                  Container(
                    width: 36,
                    height: 36,
                    decoration: BoxDecoration(
                      color: DesignTokens.colorRule,
                      borderRadius: BorderRadius.circular(8),
                    ),
                  ),
                  const SizedBox(width: DesignTokens.spacingM),
                  Text(
                    sib,
                    style: DesignTokens.typographyBody
                        .copyWith(color: DesignTokens.colorMuted),
                  ),
                ],
              ),
            ),
        ],
      ),
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

/// Onboarding newsletters step: a natural-language / handle search over
/// Substack ([AppRepository.discoverSubstacks]), add candidates as intents
/// in-flow, then subscribe each added publication per-item. Mirrors the iOS
/// `OnboardingNewslettersStep` search engine — with the per-item Subscribe
/// affordance added: creating an intent alone never starts mail flowing
/// (Substack's double opt-in needs the alias pasted into its own form), so each
/// added row gets a Subscribe button that copies the alias and opens the
/// publication. The inbound alias card stays at the bottom for forwarding
/// existing subscriptions.
class _OnboardingSubstackStep extends StatefulWidget {
  const _OnboardingSubstackStep();

  @override
  State<_OnboardingSubstackStep> createState() =>
      _OnboardingSubstackStepState();
}

class _OnboardingSubstackStepState extends State<_OnboardingSubstackStep> {
  static const _maxEntries = 5;

  final _searchController = TextEditingController();
  bool _searching = false;
  bool _hasSearched = false;
  String? _error;
  List<SubstackCandidateDto> _candidates = [];
  final List<SubstackIntentDto> _registered = [];
  final Set<String> _adding = {};
  final Set<String> _subscribing = {};

  @override
  void dispose() {
    _searchController.dispose();
    super.dispose();
  }

  bool get _reachedMax => _registered.length >= _maxEntries;

  String get _trimmed => _searchController.text.trim();

  /// A short, URL-ish or @handle input is a direct paste — skip the search
  /// (LLM round-trip) and create the intent straight away.
  bool get _looksLikeHandle =>
      _trimmed.startsWith('@') ||
      (_trimmed.contains('.') && !_trimmed.contains(' '));

  void _onSubmit() {
    final q = _trimmed;
    if (q.isEmpty || _searching || _reachedMax) return;
    if (_looksLikeHandle) {
      _addByUrl(q);
    } else {
      _search(q);
    }
  }

  Future<void> _search(String query) async {
    final repo = AppScope.of(context).repository;
    setState(() {
      _searching = true;
      _hasSearched = true;
      _error = null;
      _candidates = [];
    });
    try {
      final env = await repo.discoverSubstacks(query);
      if (!mounted) return;
      setState(() {
        _candidates = env.candidates;
        _searching = false;
      });
    } catch (_) {
      if (!mounted) return;
      setState(() {
        _searching = false;
        _error = "Couldn't search right now — try again, or paste a handle.";
      });
    }
  }

  Future<void> _addByUrl(String raw) async {
    setState(() {
      _searching = true;
      _error = null;
    });
    final intent = await _createIntent(raw);
    if (!mounted) return;
    setState(() {
      _searching = false;
      if (intent != null) {
        _searchController.clear();
        _candidates = [];
        _hasSearched = false;
      }
    });
  }

  Future<void> _addCandidate(SubstackCandidateDto c) async {
    if (_reachedMax) return;
    setState(() => _adding.add(c.pubUrl));
    await _createIntent(c.pubUrl);
    if (!mounted) return;
    setState(() => _adding.remove(c.pubUrl));
  }

  /// Creates the intent and appends it to the registered list (dedup by id).
  /// Returns the intent on success; sets [_error] and returns null on failure.
  Future<SubstackIntentDto?> _createIntent(String pubUrl) async {
    try {
      final env =
          await AppScope.of(context).repository.createSubstackIntent(pubUrl);
      final intent = env.intent;
      if (mounted && !_registered.any((i) => i.id == intent.id)) {
        setState(() => _registered.add(intent));
      }
      return intent;
    } catch (_) {
      if (mounted) {
        setState(() => _error = "Couldn't add that publication.");
      }
      return null;
    }
  }

  /// Per-item subscribe: copy the ClawCast alias and open Substack's subscribe
  /// form so the user can paste it and complete the double opt-in. This is the
  /// step that actually starts mail flowing — creating the intent alone doesn't.
  Future<void> _subscribe(SubstackIntentDto intent) async {
    final messenger = ScaffoldMessenger.of(context);
    setState(() => _subscribing.add(intent.id));
    try {
      await Clipboard.setData(ClipboardData(text: intent.aliasEmail));
      if (!mounted) return;
      messenger.showSnackBar(
        const SnackBar(
          content: Text(
            'ClawCast email copied — paste it into Substack and subscribe. '
            "We'll auto-confirm the rest.",
          ),
        ),
      );
      final url = intent.subscribeUrl;
      if (url != null && mounted) {
        await openExternal(context, url.toString());
      }
    } finally {
      if (mounted) setState(() => _subscribing.remove(intent.id));
    }
  }

  bool _alreadyAdded(String pubHost) =>
      _registered.any((i) => i.pubHost == pubHost);

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        _searchRow(),
        if (_error != null) ...[
          const SizedBox(height: DesignTokens.spacingS),
          Text(
            _error!,
            style: DesignTokens.typographyCallout.copyWith(color: Colors.red),
          ),
        ],
        if (_searching) ...[
          const SizedBox(height: DesignTokens.spacingM),
          Row(
            children: [
              const SizedBox(
                width: 16,
                height: 16,
                child: CircularProgressIndicator(strokeWidth: 2),
              ),
              const SizedBox(width: DesignTokens.spacingS),
              Text(
                'Searching…',
                style: DesignTokens.typographyCallout
                    .copyWith(color: DesignTokens.colorMuted),
              ),
            ],
          ),
        ],
        if (!_searching) ...[
          const SizedBox(height: DesignTokens.spacingM),
          if (_candidates.isNotEmpty)
            _suggestions()
          else
            _hintOrEmpty(),
        ],
        if (_registered.isNotEmpty) ...[
          const SizedBox(height: DesignTokens.spacingL),
          const EditorialDivider(),
          const SizedBox(height: DesignTokens.spacingS),
          const MetaLabel('Added to your pod'),
          const SizedBox(height: DesignTokens.spacingM),
          for (final i in _registered) ...[
            _registeredRow(i),
            const SizedBox(height: DesignTokens.spacingM),
          ],
        ],
        const SizedBox(height: DesignTokens.spacingL),
        const MetaLabel('Already subscribe to newsletters?'),
        const SizedBox(height: DesignTokens.spacingM),
        InboundAddressCard(
          address: AppScope.of(context).me?.user.inboundAddress ??
              'you@theclawcast.com',
        ),
      ],
    );
  }

  Widget _searchRow() {
    return Row(
      children: [
        Expanded(
          child: TextField(
            controller: _searchController,
            textCapitalization: TextCapitalization.sentences,
            decoration: const InputDecoration(
              labelText: 'Describe what you read, or paste a handle',
              hintText: 'e.g. "AI strategy", or lenny.substack.com',
            ),
            onChanged: (_) => setState(() {}),
            onSubmitted: (_) => _onSubmit(),
          ),
        ),
        const SizedBox(width: DesignTokens.spacingS),
        AmberButton.filled(
          label: _looksLikeHandle ? 'Add' : 'Find',
          expand: false,
          loading: _searching,
          onPressed: (_searching || _reachedMax) ? null : _onSubmit,
        ),
      ],
    );
  }

  Widget _hintOrEmpty() {
    final text = _hasSearched
        ? 'No clear matches — try describing it differently, or paste a handle '
            'like lenny.substack.com or @lenny.'
        : 'Try: "AI strategy and regulation", "longevity research and habits", '
            'or just @stratechery.';
    return Text(
      text,
      style: DesignTokens.typographyCallout
          .copyWith(color: DesignTokens.colorMuted),
    );
  }

  Widget _suggestions() {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const MetaLabel('Suggestions'),
        const SizedBox(height: DesignTokens.spacingM),
        for (final c in _candidates) ...[
          _candidateCard(c),
          const SizedBox(height: DesignTokens.spacingM),
        ],
        if (_reachedMax)
          Text(
            'Max $_maxEntries reached — continue to keep setting up.',
            style: DesignTokens.typographyMeta
                .copyWith(color: DesignTokens.colorMuted),
          ),
      ],
    );
  }

  Widget _candidateCard(SubstackCandidateDto c) {
    final added = _alreadyAdded(c.pubHost);
    final adding = _adding.contains(c.pubUrl);
    return EditorialCard(
      spacing: DesignTokens.spacingS,
      children: [
        Row(
          children: [
            Expanded(
              child: Text(
                c.title ?? c.pubHost,
                style: DesignTokens.typographySubtitle
                    .copyWith(color: DesignTokens.colorInk),
              ),
            ),
            if (c.hasPaidTier) const _PaidTag(),
          ],
        ),
        if (c.author != null && c.author!.isNotEmpty)
          Text(
            c.author!,
            style: DesignTokens.typographyMeta
                .copyWith(color: DesignTokens.colorMuted),
          ),
        if (c.why != null && c.why!.isNotEmpty)
          Text(
            c.why!,
            style: DesignTokens.typographyCallout
                .copyWith(color: DesignTokens.colorInkSoft),
          ),
        Align(
          alignment: Alignment.centerLeft,
          child: added
              ? Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    const Icon(Icons.check_circle,
                        size: 16, color: DesignTokens.colorAmberDeep),
                    const SizedBox(width: 4),
                    Text(
                      'Added',
                      style: DesignTokens.typographyCalloutStrong
                          .copyWith(color: DesignTokens.colorAmberDeep),
                    ),
                  ],
                )
              : AmberButton.filled(
                  label: 'Add',
                  expand: false,
                  loading: adding,
                  onPressed:
                      (adding || _reachedMax) ? null : () => _addCandidate(c),
                ),
        ),
      ],
    );
  }

  Widget _registeredRow(SubstackIntentDto i) {
    final subscribing = _subscribing.contains(i.id);
    return EditorialCard(
      spacing: DesignTokens.spacingS,
      children: [
        Row(
          children: [
            const Icon(Icons.check_circle,
                size: 18, color: DesignTokens.colorAmberDeep),
            const SizedBox(width: DesignTokens.spacingS),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    i.displayTitle,
                    style: DesignTokens.typographySubtitle
                        .copyWith(color: DesignTokens.colorInk),
                  ),
                  if (i.pubAuthor != null && i.pubAuthor!.isNotEmpty)
                    Text(
                      i.pubAuthor!,
                      style: DesignTokens.typographyMeta
                          .copyWith(color: DesignTokens.colorMuted),
                    ),
                ],
              ),
            ),
            if (i.hasPaidTier) const _PaidTag(),
          ],
        ),
        Text(
          'Subscribe with your ClawCast address to start receiving it.',
          style: DesignTokens.typographyCallout
              .copyWith(color: DesignTokens.colorInkSoft),
        ),
        Align(
          alignment: Alignment.centerLeft,
          child: AmberButton.outlined(
            label: 'Subscribe',
            icon: Icons.open_in_new,
            expand: false,
            loading: subscribing,
            onPressed: subscribing ? null : () => _subscribe(i),
          ),
        ),
      ],
    );
  }
}

class _PaidTag extends StatelessWidget {
  const _PaidTag();

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
      decoration: BoxDecoration(
        borderRadius: BorderRadius.circular(999),
        border: Border.all(color: DesignTokens.colorAmber, width: 1),
      ),
      child: Text(
        'Paid',
        style: DesignTokens.typographyMeta
            .copyWith(color: DesignTokens.colorAmberDeep),
      ),
    );
  }
}

