import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../api/api_client.dart' show SourcePayload;
import '../api/models.dart';
import '../design_tokens.dart';
import '../state/app_state.dart';
import '../widgets/editorial.dart';
import 'substack_add_screen.dart';

/// Sources tab. Editorial rebuild of the iOS `SourcesView`: the private
/// newsletter-email card up top, then each source as an editorial card with a
/// live toggle that persists through `replaceSources` (PUT /v1/me/sources).
class SourcesScreen extends StatefulWidget {
  const SourcesScreen({super.key});

  @override
  State<SourcesScreen> createState() => _SourcesScreenState();
}

class _SourcesScreenState extends State<SourcesScreen> {
  late final AppState _app;
  bool _initialized = false;
  bool _loading = true;
  String? _error;
  List<UserSourceDto> _sources = const [];

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
      final env = await _app.repository.fetchSources();
      if (!mounted) return;
      setState(() {
        _sources = env.sources;
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

  Future<void> _toggle(UserSourceDto source, bool enabled) async {
    final previous = _sources;
    setState(() {
      _sources = [
        for (final s in _sources)
          if (s.id == source.id)
            UserSourceDto(
              id: s.id,
              sourceId: s.sourceId,
              name: s.name,
              rssUrl: s.rssUrl,
              isCustom: s.isCustom,
              enabled: enabled,
            )
          else
            s,
      ];
    });
    try {
      final payload = [
        for (final s in _sources)
          if (s.enabled)
            s.isCustom
                ? SourcePayload(rssUrl: s.rssUrl, isCustom: true)
                : SourcePayload(sourceId: s.sourceId, isCustom: false),
      ];
      await _app.repository.replaceSources(payload);
    } catch (e) {
      if (!mounted) return;
      setState(() => _sources = previous); // revert on failure
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text('Couldn\'t save: $e')));
    }
  }

  @override
  Widget build(BuildContext context) {
    final inbound = _app.me?.user.inboundAddress;
    return Scaffold(
      appBar: AppBar(
        title: const Text('Sources'),
        actions: [
          IconButton(
            tooltip: 'Add Substack',
            onPressed: () => Navigator.of(context).push(
              MaterialPageRoute(builder: (_) => const SubstackAddScreen()),
            ),
            icon: const Icon(Icons.add),
          ),
        ],
      ),
      body: SafeArea(
        child: _loading
            ? const Center(child: CircularProgressIndicator())
            : _error != null
                ? Center(child: Text(_error!))
                : ListView(
                    padding: const EdgeInsets.all(DesignTokens.spacingL),
                    children: [
                      if (inbound != null && inbound.isNotEmpty) ...[
                        _NewsletterEmailCard(address: inbound),
                        const SizedBox(height: DesignTokens.spacingL),
                      ],
                      const MetaLabel('Your sources'),
                      const SizedBox(height: DesignTokens.spacingM),
                      for (final s in _sources) ...[
                        _SourceCard(source: s, onToggle: (v) => _toggle(s, v)),
                        const SizedBox(height: DesignTokens.spacingM),
                      ],
                    ],
                  ),
      ),
    );
  }
}

class _SourceCard extends StatelessWidget {
  const _SourceCard({required this.source, required this.onToggle});

  final UserSourceDto source;
  final ValueChanged<bool> onToggle;

  @override
  Widget build(BuildContext context) {
    return EditorialCard(
      padding: const EdgeInsets.fromLTRB(
        DesignTokens.spacingL,
        DesignTokens.spacingM,
        DesignTokens.spacingM,
        DesignTokens.spacingM,
      ),
      children: [
        Row(
          children: [
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    source.name,
                    style: DesignTokens.typographySubtitle
                        .copyWith(color: DesignTokens.colorInk),
                  ),
                  const SizedBox(height: 2),
                  Text(
                    source.isCustom ? 'Custom feed' : 'Curated',
                    style: DesignTokens.typographyMeta
                        .copyWith(color: DesignTokens.colorMuted),
                  ),
                ],
              ),
            ),
            Switch(value: source.enabled, onChanged: onToggle),
          ],
        ),
      ],
    );
  }
}

class _NewsletterEmailCard extends StatefulWidget {
  const _NewsletterEmailCard({required this.address});

  final String address;

  @override
  State<_NewsletterEmailCard> createState() => _NewsletterEmailCardState();
}

class _NewsletterEmailCardState extends State<_NewsletterEmailCard> {
  bool _copied = false;

  Future<void> _copy() async {
    await Clipboard.setData(ClipboardData(text: widget.address));
    if (!mounted) return;
    setState(() => _copied = true);
  }

  @override
  Widget build(BuildContext context) {
    return EditorialCard(
      spacing: DesignTokens.spacingS,
      children: [
        Row(
          children: [
            const Expanded(child: MetaLabel('Newsletter email')),
            if (_copied)
              Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  const Icon(Icons.check_circle,
                      size: 14, color: DesignTokens.colorAmberDeep),
                  const SizedBox(width: 4),
                  Text(
                    'Copied',
                    style: DesignTokens.typographyMeta
                        .copyWith(color: DesignTokens.colorAmberDeep),
                  ),
                ],
              )
            else
              InkWell(
                onTap: _copy,
                child: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    const Icon(Icons.copy,
                        size: 14, color: DesignTokens.colorAmberDeep),
                    const SizedBox(width: 4),
                    Text(
                      'Copy',
                      style: DesignTokens.typographyMeta
                          .copyWith(color: DesignTokens.colorAmberDeep),
                    ),
                  ],
                ),
              ),
          ],
        ),
        SelectableText(
          widget.address,
          style: DesignTokens.typographyTitle
              .copyWith(color: DesignTokens.colorAmberDeep),
        ),
        Text(
          'Forward newsletters here, or use this address when you subscribe. '
          'Each new arrival folds into your next episode.',
          style: DesignTokens.typographyCallout
              .copyWith(color: DesignTokens.colorInkSoft),
        ),
      ],
    );
  }
}
