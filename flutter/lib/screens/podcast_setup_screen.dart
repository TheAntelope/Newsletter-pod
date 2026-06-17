import 'package:flutter/material.dart';

import '../api/models.dart';
import '../design_tokens.dart';
import '../state/app_state.dart';
import '../widgets/day_toggle.dart';
import '../widgets/editorial.dart';
import '../widgets/voice_choice_card.dart';
import '../widgets/weather_location_field.dart';

const _weekdayOptions = [
  ('mon', 'M'), ('tue', 'T'), ('wed', 'W'), ('thu', 'T'), //
  ('fri', 'F'), ('sat', 'S'), ('sun', 'S'),
];

const _formatOptions = [
  ('solo_host', 'Solo host', 'One voice walks through the day.'),
  ('two_hosts', 'Two hosts', 'An anchor and a co-host trade off.'),
  ('rotating_guest', 'Rotating guest', 'An anchor plus a different guest each day.'),
];

const _toneOptions = [
  ('calm_analyst', 'Calm analyst'),
  ('warm_friendly', 'Warm & friendly'),
  ('snappy_news', 'Snappy news'),
  ('playful', 'Playful'),
];

const _humorOptions = [
  ('none', 'None'),
  ('dry_wit', 'Dry wit'),
  ('dad_jokes', 'Dad jokes'),
  ('witty', 'Witty & clever'),
  ('sarcastic', 'Sarcastic'),
  ('punny', 'Punny'),
  ('silly', 'Playful & silly'),
];

const _guidanceMaxLength = 500;

class _Preset {
  const _Preset({
    required this.id,
    required this.label,
    required this.tone,
    required this.humor,
    required this.keyFindings,
    required this.greeting,
    required this.guidance,
  });

  final String id;
  final String label;
  final String tone;
  final String humor;
  final int keyFindings;
  final bool greeting;
  final String guidance;
}

const _guidancePresets = [
  _Preset(
    id: 'quick_calm',
    label: 'Quick & Calm',
    tone: 'calm_analyst',
    humor: 'none',
    keyFindings: 3,
    greeting: true,
    guidance: 'Prioritize clarity over color.',
  ),
  _Preset(
    id: 'morning_energy',
    label: 'Morning Energy',
    tone: 'warm_friendly',
    humor: 'dad_jokes',
    keyFindings: 5,
    greeting: true,
    guidance: 'Open with a warm greeting and one upbeat sentence about the day.',
  ),
  _Preset(
    id: 'newsroom_brief',
    label: 'Newsroom Brief',
    tone: 'snappy_news',
    humor: 'none',
    keyFindings: 5,
    greeting: false,
    guidance: 'Tight transitions, lead with the lede, no filler.',
  ),
  _Preset(
    id: 'friend_catching_up',
    label: 'Friend Catching You Up',
    tone: 'warm_friendly',
    humor: 'dry_wit',
    keyFindings: 3,
    greeting: true,
    guidance: "Sound like a smart friend explaining over coffee. Use 'you' often.",
  ),
];

/// Which section the screen should scroll to once its form has loaded.
/// `show` (the default) lands at the top; `schedule` jumps to the day-circle
/// schedule editor near the bottom.
enum PodcastSetupSection { show, schedule }

/// Podcast setup + schedule editor. Editorial rebuild of the iOS `PodcastSetupView`
/// + `ScheduleSection` with the full config surface: show fields, format, voice
/// cards, length, style (tone / humor / key-takeaways / greeting / takeaways),
/// custom-guidance presets + free text, weather, and the day-circle schedule.
class PodcastSetupScreen extends StatefulWidget {
  const PodcastSetupScreen({super.key, this.initialSection});

  /// When `schedule`, the form auto-scrolls to the Schedule section after load.
  final PodcastSetupSection? initialSection;

  @override
  State<PodcastSetupScreen> createState() => _PodcastSetupScreenState();
}

class _PodcastSetupScreenState extends State<PodcastSetupScreen> {
  late final AppState _app;
  bool _initialized = false;
  bool _loading = true;
  bool _saving = false;
  String? _error;

  final _titleController = TextEditingController();
  final _hostPrimaryController = TextEditingController();
  final _hostSecondaryController = TextEditingController();
  final _weatherController = TextEditingController();
  final _guidanceController = TextEditingController();
  // The listener's name, used only when "Greet me by name" is on (account-level
  // displayName, not a profile field).
  final _nameController = TextEditingController();

  String _formatPreset = 'two_hosts';
  int _durationMinutes = 5;
  String? _voiceId;
  // Co-host voice, only used (and editable) when the format is 'two_hosts'.
  String? _secondaryVoiceId;
  String _tone = 'playful';
  String _humor = 'dad_jokes';
  int _keyFindings = 3;
  bool _greeting = true;
  bool _topTakeaways = true;
  bool _includeWeather = false;
  String? _presetId;

  final Set<String> _weekdays = {};
  String _localTime = '07:00';
  String _cutoffTime = '23:00';
  String _timezone = 'UTC';

  PodcastProfileDto? _loadedProfile;
  EntitlementsDto? _entitlements;
  List<CatalogVoiceDto> _voices = const [];

  /// Anchor for the Schedule section so a deep-link can scroll it into view.
  final _scheduleKey = GlobalKey();

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (!_initialized) {
      _initialized = true;
      _app = AppScope.of(context);
      _load();
    }
  }

  Future<void> _load() async {
    try {
      final config = await _app.repository.fetchPodcastConfig();
      final schedule = await _app.repository.fetchSchedule();
      final voices = await _app.repository.fetchVoiceCatalog();
      if (!mounted) return;
      final p = config.profile;
      final s = schedule.schedule;
      setState(() {
        _loadedProfile = p;
        _entitlements = config.entitlements;
        _voices = voices.voices;
        _titleController.text = p.title;
        _nameController.text = _app.me?.user.displayName ?? '';
        _hostPrimaryController.text = p.hostPrimaryName;
        _hostSecondaryController.text = p.hostSecondaryName ?? '';
        _weatherController.text = p.weatherLocation ?? '';
        _guidanceController.text = p.customGuidance ?? '';
        _formatPreset = p.formatPreset;
        _durationMinutes = p.desiredDurationMinutes;
        _voiceId = p.voiceId;
        _secondaryVoiceId = p.secondaryVoiceId;
        _tone = p.tone ?? 'playful';
        _humor = p.humorStyle ?? 'dad_jokes';
        _keyFindings = p.keyFindingsCount ?? 3;
        _greeting = p.personalizedGreeting ?? true;
        _topTakeaways = p.includeTopTakeaways ?? true;
        _includeWeather = p.includeWeather ?? false;
        _presetId = p.customGuidancePresetId;
        _weekdays
          ..clear()
          ..addAll(s.weekdays);
        _localTime = s.localTime;
        _cutoffTime = s.cutoffTime;
        _timezone = s.timezone;
        _loading = false;
      });
      if (widget.initialSection == PodcastSetupSection.schedule) {
        WidgetsBinding.instance.addPostFrameCallback((_) {
          final ctx = _scheduleKey.currentContext;
          if (ctx != null) {
            Scrollable.ensureVisible(
              ctx,
              duration: const Duration(milliseconds: 350),
              alignment: 0.05,
            );
          }
        });
      }
    } catch (e) {
      if (!mounted) return;
      setState(() {
        _error = e.toString();
        _loading = false;
      });
    }
  }

  @override
  void dispose() {
    _titleController.dispose();
    _hostPrimaryController.dispose();
    _hostSecondaryController.dispose();
    _weatherController.dispose();
    _guidanceController.dispose();
    _nameController.dispose();
    super.dispose();
  }

  void _applyPreset(_Preset preset) {
    setState(() {
      _tone = preset.tone;
      _humor = preset.humor;
      _keyFindings = preset.keyFindings;
      _greeting = preset.greeting;
      _presetId = preset.id;
      _guidanceController.text = preset.guidance;
    });
  }

  Future<void> _pickTime() async {
    final parts = _localTime.split(':');
    final initial = TimeOfDay(
      hour: int.tryParse(parts.first) ?? 7,
      minute: parts.length > 1 ? (int.tryParse(parts[1]) ?? 0) : 0,
    );
    final picked = await showTimePicker(context: context, initialTime: initial);
    if (picked == null) return;
    setState(() {
      _localTime = '${picked.hour.toString().padLeft(2, '0')}:'
          '${picked.minute.toString().padLeft(2, '0')}';
    });
  }

  Future<void> _save() async {
    final loaded = _loadedProfile;
    if (loaded == null) return;
    setState(() => _saving = true);

    final title = _titleController.text.trim();
    final hostPrimary = _hostPrimaryController.text.trim();
    final hostSecondary = _hostSecondaryController.text.trim();
    final weather = _weatherController.text.trim();
    final guidance = _guidanceController.text.trim();
    final updated = PodcastProfileDto(
      title: title.isEmpty ? loaded.title : title,
      formatPreset: _formatPreset,
      hostPrimaryName: hostPrimary.isEmpty ? loaded.hostPrimaryName : hostPrimary,
      hostSecondaryName: hostSecondary.isEmpty ? null : hostSecondary,
      guestNames: loaded.guestNames,
      desiredDurationMinutes: _durationMinutes,
      voiceId: _voiceId,
      // Only persist the co-host voice for two-host shows; otherwise leave the
      // stored value untouched (solo / rotating-guest use a single voice).
      secondaryVoiceId: _formatPreset == 'two_hosts'
          ? (_secondaryVoiceId ?? loaded.secondaryVoiceId)
          : loaded.secondaryVoiceId,
      tone: _tone,
      keyFindingsCount: _keyFindings,
      humorStyle: _humor,
      personalizedGreeting: _greeting,
      includeTopTakeaways: _topTakeaways,
      includeWeather: _includeWeather,
      weatherLocation: weather.isEmpty ? null : weather,
      customGuidance: guidance.isEmpty ? null : guidance,
      customGuidancePresetId: _presetId,
    );

    try {
      await _app.repository.updatePodcastConfig(updated);
      await _app.repository.updateSchedule(
        timezone: _timezone,
        weekdays: _weekdays.toList(),
        localTime: _localTime,
      );
      // Persist the greeting name to the account display name (only when the
      // greeting is on and a name was entered), then refresh `me`.
      final name = _nameController.text.trim();
      if (_greeting && name.isNotEmpty && name != _app.me?.user.displayName) {
        await _app.repository.updateProfile(
          displayName: name,
          timezone: _app.me?.user.timezone ?? _timezone,
        );
        await _app.loadMe();
      }
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(const SnackBar(content: Text('Saved')));
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('$e')));
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Podcast & schedule')),
      body: SafeArea(
        child: _loading
            ? const Center(child: CircularProgressIndicator())
            : _error != null
                ? Center(child: Text(_error!))
                : _buildForm(),
      ),
    );
  }

  Widget _buildForm() {
    final ent = _entitlements;
    final minM = ent?.minDurationMinutes ?? 3;
    final maxM = ent?.maxDurationMinutes ?? 7;

    return ListView(
      padding: const EdgeInsets.all(DesignTokens.spacingL),
      children: [
        _section('Show'),
        EditorialCard(
          children: [
            TextField(
              controller: _titleController,
              decoration: const InputDecoration(labelText: 'Title'),
            ),
            TextField(
              controller: _hostPrimaryController,
              decoration: const InputDecoration(labelText: 'Primary host'),
            ),
            TextField(
              controller: _hostSecondaryController,
              decoration:
                  const InputDecoration(labelText: 'Secondary host (optional)'),
            ),
          ],
        ),
        _section('Format'),
        EditorialCard(
          spacing: 0,
          children: [
            for (var i = 0; i < _formatOptions.length; i++) ...[
              if (i > 0) const EditorialDivider(),
              _RadioRow(
                title: _formatOptions[i].$2,
                subtitle: _formatOptions[i].$3,
                selected: _formatPreset == _formatOptions[i].$1,
                onTap: () => setState(() => _formatPreset = _formatOptions[i].$1),
              ),
            ],
          ],
        ),
        _section('Voice'),
        EditorialCard(
          children: [
            if (_formatPreset == 'two_hosts') ...[
              _voicePicker(
                label: 'Host 1 (anchor)',
                selectedId: _voiceId,
                onChanged: (id) => setState(() => _voiceId = id),
              ),
              const EditorialDivider(),
              _voicePicker(
                label: 'Host 2 (co-host)',
                selectedId: _secondaryVoiceId,
                onChanged: (id) => setState(() => _secondaryVoiceId = id),
              ),
            ] else
              _voicePicker(
                label: _formatPreset == 'rotating_guest'
                    ? 'Anchor voice'
                    : 'Host voice',
                selectedId: _voiceId,
                onChanged: (id) => setState(() => _voiceId = id),
              ),
          ],
        ),
        _section('Length'),
        EditorialCard(
          children: [
            Row(
              children: [
                IconButton.filledTonal(
                  onPressed: _durationMinutes > minM
                      ? () => setState(() => _durationMinutes--)
                      : null,
                  icon: const Icon(Icons.remove),
                ),
                Expanded(
                  child: Center(
                    child: Text(
                      '$_durationMinutes min',
                      style: DesignTokens.typographyTitle
                          .copyWith(color: DesignTokens.colorInk),
                    ),
                  ),
                ),
                IconButton.filledTonal(
                  onPressed: _durationMinutes < maxM
                      ? () => setState(() => _durationMinutes++)
                      : null,
                  icon: const Icon(Icons.add),
                ),
              ],
            ),
            Text(
              'Your plan allows $minM–$maxM minute episodes.',
              style: DesignTokens.typographyCallout
                  .copyWith(color: DesignTokens.colorMuted),
            ),
          ],
        ),
        _section('Style'),
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
            if (_greeting)
              TextField(
                controller: _nameController,
                textCapitalization: TextCapitalization.words,
                decoration: const InputDecoration(labelText: 'Your name'),
              ),
            _SwitchRow(
              label: 'Include top takeaways',
              value: _topTakeaways,
              onChanged: (v) => setState(() => _topTakeaways = v),
            ),
          ],
        ),
        _section('Custom guidance'),
        EditorialCard(
          children: [
            Wrap(
              spacing: DesignTokens.spacingS,
              runSpacing: DesignTokens.spacingS,
              children: [
                for (final p in _guidancePresets)
                  _ChoicePill(
                    label: p.label,
                    selected: _presetId == p.id,
                    onTap: () => _applyPreset(p),
                  ),
              ],
            ),
            TextField(
              controller: _guidanceController,
              maxLines: 3,
              maxLength: _guidanceMaxLength,
              decoration: const InputDecoration(
                hintText:
                    'Tell the hosts how the show should feel — e.g. “Lean '
                    'technical, skip background.”',
              ),
              onChanged: (_) => setState(() => _presetId = null),
            ),
          ],
        ),
        _section('Weather'),
        EditorialCard(
          children: [
            _SwitchRow(
              label: 'Open with a local weather note',
              value: _includeWeather,
              onChanged: (v) => setState(() => _includeWeather = v),
            ),
            if (_includeWeather)
              WeatherLocationField(controller: _weatherController),
          ],
        ),
        _section('Schedule', key: _scheduleKey),
        EditorialCard(
          children: [
            Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                for (final opt in _weekdayOptions)
                  DayToggle(
                    initial: opt.$2,
                    selected: _weekdays.contains(opt.$1),
                    onTap: () => setState(() {
                      if (!_weekdays.remove(opt.$1)) _weekdays.add(opt.$1);
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
                OutlinedButton(onPressed: _pickTime, child: Text(_localTime)),
              ],
            ),
            Text(
              'Stories must arrive before $_cutoffTime to make that day’s pod.',
              style: DesignTokens.typographyCallout
                  .copyWith(color: DesignTokens.colorMuted),
            ),
            const EditorialDivider(),
            _NoScheduleOptOut(
              optedOut: _weekdays.isEmpty,
              onOptOut: () => setState(_weekdays.clear),
            ),
          ],
        ),
        const SizedBox(height: DesignTokens.spacingXl),
        AmberButton.filled(
          label: 'Save',
          loading: _saving,
          onPressed: _saving ? null : _save,
        ),
      ],
    );
  }

  /// A labelled voice dropdown + "Hear a sample" affordance. Used once per host
  /// (two for a two-host show, one otherwise) so each speaker gets its own voice.
  Widget _voicePicker({
    required String label,
    required String? selectedId,
    required ValueChanged<String?> onChanged,
  }) {
    // DropdownButtonFormField asserts its value is either null or matches exactly
    // one item, so resolve the currently-selected voice (null if it's not in the
    // catalog) rather than passing a dangling id.
    CatalogVoiceDto? selected;
    for (final v in _voices) {
      if (v.id == selectedId) {
        selected = v;
        break;
      }
    }
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        _FieldLabel(label),
        DropdownButtonFormField<String>(
          initialValue: selected?.id,
          isExpanded: true,
          decoration: const InputDecoration(
            hintText: 'Choose a voice',
            border: OutlineInputBorder(),
          ),
          items: [
            for (final v in _voices)
              DropdownMenuItem(
                value: v.id,
                child: Text(
                  v.gender.isEmpty ? v.name : '${v.name} · ${v.gender}',
                  overflow: TextOverflow.ellipsis,
                ),
              ),
          ],
          onChanged: onChanged,
        ),
        if (selected?.previewUrl != null) ...[
          const SizedBox(height: DesignTokens.spacingS),
          VoiceSampleButton(id: selected!.id, source: selected.previewUrl!),
        ],
      ],
    );
  }

  Widget _section(String label, {Key? key}) => Padding(
        key: key,
        padding: const EdgeInsets.fromLTRB(
          0,
          DesignTokens.spacingL,
          0,
          DesignTokens.spacingM,
        ),
        child: MetaLabel(label),
      );
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

class _RadioRow extends StatelessWidget {
  const _RadioRow({
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
              selected ? Icons.radio_button_checked : Icons.radio_button_unchecked,
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
