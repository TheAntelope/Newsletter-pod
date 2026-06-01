import 'package:flutter/material.dart';

import '../api/models.dart';
import '../design_tokens.dart';
import '../state/app_state.dart';

const _weekdayOptions = [
  ('mon', 'Mon'), ('tue', 'Tue'), ('wed', 'Wed'), ('thu', 'Thu'),
  ('fri', 'Fri'), ('sat', 'Sat'), ('sun', 'Sun'),
];

/// Podcast setup + schedule editor. Loads the current config, schedule and voice
/// catalog, lets the user edit the common fields, and saves via updatePodcastConfig
/// + updateSchedule (carrying over the untouched profile fields).
class PodcastSetupScreen extends StatefulWidget {
  const PodcastSetupScreen({super.key});

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
  int _durationMinutes = 5;
  String? _voiceId;
  final Set<String> _weekdays = {};
  String _localTime = '07:00';
  String _timezone = 'UTC';

  PodcastProfileDto? _loadedProfile;
  EntitlementsDto? _entitlements;
  List<CatalogVoiceDto> _voices = const [];

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
        _hostPrimaryController.text = p.hostPrimaryName;
        _hostSecondaryController.text = p.hostSecondaryName ?? '';
        _durationMinutes = p.desiredDurationMinutes;
        _voiceId = p.voiceId;
        _weekdays
          ..clear()
          ..addAll(s.weekdays);
        _localTime = s.localTime;
        _timezone = s.timezone;
        _loading = false;
      });
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
    super.dispose();
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
    final updated = PodcastProfileDto(
      title: title.isEmpty ? loaded.title : title,
      formatPreset: loaded.formatPreset,
      hostPrimaryName: hostPrimary.isEmpty ? loaded.hostPrimaryName : hostPrimary,
      hostSecondaryName: hostSecondary.isEmpty ? null : hostSecondary,
      guestNames: loaded.guestNames,
      desiredDurationMinutes: _durationMinutes,
      voiceId: _voiceId,
      secondaryVoiceId: loaded.secondaryVoiceId,
      tone: loaded.tone,
      keyFindingsCount: loaded.keyFindingsCount,
      humorStyle: loaded.humorStyle,
      personalizedGreeting: loaded.personalizedGreeting,
      includeTopTakeaways: loaded.includeTopTakeaways,
      includeWeather: loaded.includeWeather,
      weatherLocation: loaded.weatherLocation,
      customGuidance: loaded.customGuidance,
      customGuidancePresetId: loaded.customGuidancePresetId,
    );

    try {
      await _app.repository.updatePodcastConfig(updated);
      await _app.repository.updateSchedule(
        timezone: _timezone,
        weekdays: _weekdays.toList(),
        localTime: _localTime,
      );
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(const SnackBar(content: Text('Saved')));
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text('$e')));
    } finally {
      if (mounted) setState(() => _saving = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    return Scaffold(
      appBar: AppBar(title: const Text('Podcast & schedule')),
      body: SafeArea(
        child: _loading
            ? const Center(child: CircularProgressIndicator())
            : _error != null
                ? Center(child: Text(_error!))
                : _buildForm(text),
      ),
    );
  }

  Widget _buildForm(TextTheme text) {
    final ent = _entitlements;
    final minM = ent?.minDurationMinutes ?? 3;
    final maxM = ent?.maxDurationMinutes ?? 5;

    Widget label(String s) => Padding(
          padding: const EdgeInsets.only(bottom: DesignTokens.spacingS),
          child: Text(s,
              style: text.labelSmall?.copyWith(color: DesignTokens.colorMuted)),
        );

    return ListView(
      padding: const EdgeInsets.all(DesignTokens.spacingL),
      children: [
        label('SHOW'),
        TextField(
          controller: _titleController,
          decoration: const InputDecoration(labelText: 'Title'),
        ),
        const SizedBox(height: DesignTokens.spacingM),
        TextField(
          controller: _hostPrimaryController,
          decoration: const InputDecoration(labelText: 'Primary host'),
        ),
        const SizedBox(height: DesignTokens.spacingM),
        TextField(
          controller: _hostSecondaryController,
          decoration:
              const InputDecoration(labelText: 'Secondary host (optional)'),
        ),
        const SizedBox(height: DesignTokens.spacingL),
        label('LENGTH'),
        Row(
          children: [
            IconButton.filledTonal(
              onPressed: _durationMinutes > minM
                  ? () => setState(() => _durationMinutes--)
                  : null,
              icon: const Icon(Icons.remove),
            ),
            const SizedBox(width: DesignTokens.spacingM),
            Text('$_durationMinutes min', style: text.titleLarge),
            const SizedBox(width: DesignTokens.spacingM),
            IconButton.filledTonal(
              onPressed: _durationMinutes < maxM
                  ? () => setState(() => _durationMinutes++)
                  : null,
              icon: const Icon(Icons.add),
            ),
          ],
        ),
        const SizedBox(height: DesignTokens.spacingL),
        label('VOICE'),
        DropdownButton<String?>(
          value: _voiceId,
          isExpanded: true,
          items: [
            const DropdownMenuItem<String?>(value: null, child: Text('Default')),
            ..._voices.map(
              (v) => DropdownMenuItem<String?>(value: v.id, child: Text(v.name)),
            ),
          ],
          onChanged: (v) => setState(() => _voiceId = v),
        ),
        const SizedBox(height: DesignTokens.spacingL),
        label('SCHEDULE'),
        Wrap(
          spacing: DesignTokens.spacingS,
          children: _weekdayOptions.map((opt) {
            return FilterChip(
              label: Text(opt.$2),
              selected: _weekdays.contains(opt.$1),
              onSelected: (on) => setState(() {
                if (on) {
                  _weekdays.add(opt.$1);
                } else {
                  _weekdays.remove(opt.$1);
                }
              }),
            );
          }).toList(),
        ),
        const SizedBox(height: DesignTokens.spacingM),
        Row(
          children: [
            Text('Delivered at', style: text.bodyMedium),
            const SizedBox(width: DesignTokens.spacingS),
            OutlinedButton(onPressed: _pickTime, child: Text(_localTime)),
          ],
        ),
        const SizedBox(height: DesignTokens.spacingXl),
        SizedBox(
          width: double.infinity,
          child: ElevatedButton(
            onPressed: _saving ? null : _save,
            child: _saving
                ? const SizedBox(
                    height: 18,
                    width: 18,
                    child: CircularProgressIndicator(strokeWidth: 2),
                  )
                : const Text('Save'),
          ),
        ),
      ],
    );
  }
}
