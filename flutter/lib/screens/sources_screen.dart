import 'package:flutter/material.dart';

import '../api/api_client.dart' show SourcePayload;
import '../api/models.dart';
import '../design_tokens.dart';
import '../state/app_state.dart';
import '../widgets/editorial.dart';
import '../widgets/inbound_address_card.dart';
import '../widgets/topic_icon.dart';
import 'dashboard_scaffold.dart';
import 'substack_add_screen.dart';

/// Sources tab. Editorial rebuild of the iOS `SourcesView`: the private
/// newsletter-email card, the catalog grouped by topic with live toggles, a
/// custom-RSS section, and recently-forwarded newsletters. Toggles persist
/// through `replaceSources` (PUT /v1/me/sources).
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

  List<CatalogSourceDto> _catalog = const [];
  final Set<String> _enabledIds = {};
  final List<String> _customUrls = [];
  List<InboundItemDto> _inbound = const [];

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
      final sources = await _app.repository.fetchSources();
      final catalog = await _app.repository.fetchCatalog();
      final inbound = await _app.repository.fetchInboundItems();
      if (!mounted) return;
      setState(() {
        _catalog = catalog.sources;
        _enabledIds
          ..clear()
          ..addAll(sources.sources
              .where((s) => !s.isCustom && s.enabled)
              .map((s) => s.sourceId));
        _customUrls
          ..clear()
          ..addAll(sources.sources
              .where((s) => s.isCustom && s.enabled)
              .map((s) => s.rssUrl));
        _inbound = inbound.items;
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

  Future<void> _persist() async {
    final payload = [
      for (final id in _enabledIds) SourcePayload(sourceId: id, isCustom: false),
      for (final url in _customUrls)
        if (url.trim().isNotEmpty)
          SourcePayload(rssUrl: url.trim(), isCustom: true),
    ];
    try {
      await _app.repository.replaceSources(payload);
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text('Couldn\'t save: $e')));
    }
  }

  void _toggleCatalog(String id, bool on) {
    setState(() {
      if (on) {
        _enabledIds.add(id);
      } else {
        _enabledIds.remove(id);
      }
    });
    _persist();
  }

  void _addCustom(String url) {
    final trimmed = url.trim();
    if (trimmed.isEmpty || _customUrls.contains(trimmed)) return;
    setState(() => _customUrls.add(trimmed));
    _persist();
  }

  void _removeCustom(String url) {
    setState(() => _customUrls.remove(url));
    _persist();
  }

  /// Catalog grouped by topic, preserving first-seen topic order.
  List<MapEntry<String, List<CatalogSourceDto>>> get _grouped {
    final order = <String>[];
    final byTopic = <String, List<CatalogSourceDto>>{};
    for (final s in _catalog) {
      final topic = (s.topic?.isNotEmpty ?? false) ? s.topic! : 'Other';
      byTopic.putIfAbsent(topic, () {
        order.add(topic);
        return [];
      }).add(s);
    }
    return [for (final t in order) MapEntry(t, byTopic[t]!)];
  }

  @override
  Widget build(BuildContext context) {
    final inbound = _app.me?.user.inboundAddress;
    return Scaffold(
      appBar: AppBar(
        leading: Padding(
          padding: const EdgeInsets.all(8),
          child: ClawcastLogo(
            size: 28,
            onTap: () => DashboardScope.goHome(context),
          ),
        ),
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
                        InboundAddressCard(
                          address: inbound,
                          title: 'Newsletter email',
                          description:
                              'Forward newsletters here, or use this address '
                              'when you subscribe. Each new arrival folds into '
                              'your next episode.',
                        ),
                        const SizedBox(height: DesignTokens.spacingL),
                      ],
                      const MetaLabel('Catalog'),
                      const SizedBox(height: DesignTokens.spacingM),
                      for (final group in _grouped) ...[
                        _CatalogGroup(
                          topic: group.key,
                          sources: group.value,
                          enabledIds: _enabledIds,
                          onToggle: _toggleCatalog,
                        ),
                        const SizedBox(height: DesignTokens.spacingM),
                      ],
                      const SizedBox(height: DesignTokens.spacingS),
                      const MetaLabel('Custom RSS'),
                      const SizedBox(height: DesignTokens.spacingM),
                      _CustomRssCard(
                        urls: _customUrls,
                        onAdd: _addCustom,
                        onRemove: _removeCustom,
                      ),
                      if (_inbound.isNotEmpty) ...[
                        const SizedBox(height: DesignTokens.spacingL),
                        const MetaLabel('Recent newsletters'),
                        const SizedBox(height: DesignTokens.spacingM),
                        for (final item in _inbound) ...[
                          _InboundItemCard(item: item),
                          const SizedBox(height: DesignTokens.spacingM),
                        ],
                      ],
                    ],
                  ),
      ),
    );
  }
}

class _CatalogGroup extends StatefulWidget {
  const _CatalogGroup({
    required this.topic,
    required this.sources,
    required this.enabledIds,
    required this.onToggle,
  });

  final String topic;
  final List<CatalogSourceDto> sources;
  final Set<String> enabledIds;
  final void Function(String id, bool on) onToggle;

  @override
  State<_CatalogGroup> createState() => _CatalogGroupState();
}

class _CatalogGroupState extends State<_CatalogGroup> {
  // Collapsed by default — the real catalog has ~90 sources across 14 topics.
  bool _expanded = false;

  @override
  Widget build(BuildContext context) {
    final selected =
        widget.sources.where((s) => widget.enabledIds.contains(s.sourceId)).length;
    return EditorialCard(
      spacing: DesignTokens.spacingS,
      children: [
        InkWell(
          onTap: () => setState(() => _expanded = !_expanded),
          child: Row(
            children: [
              Icon(topicIcon(widget.topic),
                  size: 18, color: DesignTokens.colorAmberDeep),
              const SizedBox(width: DesignTokens.spacingS),
              Expanded(
                child: Text(
                  widget.topic,
                  style: DesignTokens.typographySubtitle
                      .copyWith(color: DesignTokens.colorInk),
                ),
              ),
              Text(
                '$selected of ${widget.sources.length}',
                style: DesignTokens.typographyMeta
                    .copyWith(color: DesignTokens.colorMuted),
              ),
              const SizedBox(width: DesignTokens.spacingS),
              Icon(_expanded ? Icons.expand_less : Icons.expand_more,
                  size: 18, color: DesignTokens.colorMuted),
            ],
          ),
        ),
        if (_expanded)
          for (final s in widget.sources)
            Row(
              children: [
                Expanded(
                  child: Text(
                    s.name,
                    style: DesignTokens.typographyBody
                        .copyWith(color: DesignTokens.colorInk),
                  ),
                ),
                Switch(
                  value: widget.enabledIds.contains(s.sourceId),
                  onChanged: (on) => widget.onToggle(s.sourceId, on),
                ),
              ],
            ),
      ],
    );
  }
}

class _CustomRssCard extends StatefulWidget {
  const _CustomRssCard({
    required this.urls,
    required this.onAdd,
    required this.onRemove,
  });

  final List<String> urls;
  final ValueChanged<String> onAdd;
  final ValueChanged<String> onRemove;

  @override
  State<_CustomRssCard> createState() => _CustomRssCardState();
}

class _CustomRssCardState extends State<_CustomRssCard> {
  final _controller = TextEditingController();

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  void _add() {
    widget.onAdd(_controller.text);
    _controller.clear();
  }

  @override
  Widget build(BuildContext context) {
    return EditorialCard(
      children: [
        for (final url in widget.urls)
          Row(
            children: [
              Expanded(
                child: Text(
                  url,
                  style: DesignTokens.typographyCallout
                      .copyWith(color: DesignTokens.colorInkSoft),
                  overflow: TextOverflow.ellipsis,
                ),
              ),
              IconButton(
                tooltip: 'Remove',
                onPressed: () => widget.onRemove(url),
                icon: const Icon(Icons.close, size: 18),
              ),
            ],
          ),
        Row(
          children: [
            Expanded(
              child: TextField(
                controller: _controller,
                keyboardType: TextInputType.url,
                decoration: const InputDecoration(
                  labelText: 'https://example.com/feed.xml',
                ),
                onSubmitted: (_) => _add(),
              ),
            ),
            const SizedBox(width: DesignTokens.spacingS),
            AmberButton.filled(label: 'Add', expand: false, onPressed: _add),
          ],
        ),
      ],
    );
  }
}

class _InboundItemCard extends StatelessWidget {
  const _InboundItemCard({required this.item});

  final InboundItemDto item;

  @override
  Widget build(BuildContext context) {
    return EditorialCard(
      spacing: DesignTokens.spacingXs,
      children: [
        Text(
          item.displaySender.toUpperCase(),
          style: DesignTokens.typographyMeta
              .copyWith(color: DesignTokens.colorMuted),
        ),
        Text(
          item.subject,
          style: DesignTokens.typographyBody.copyWith(color: DesignTokens.colorInk),
        ),
      ],
    );
  }
}

