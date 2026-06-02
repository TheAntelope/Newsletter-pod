import 'package:flutter/material.dart';

import '../api/models.dart';
import '../design_tokens.dart';
import '../state/app_state.dart';

/// Add a Substack: discover candidates by topic, add one (which creates an
/// intent), and review existing subscriptions — surfacing the 6-digit
/// verification code when Substack sends one.
class SubstackAddScreen extends StatefulWidget {
  const SubstackAddScreen({super.key});

  @override
  State<SubstackAddScreen> createState() => _SubstackAddScreenState();
}

class _SubstackAddScreenState extends State<SubstackAddScreen> {
  late final AppState _app;
  bool _initialized = false;

  final _searchController = TextEditingController();
  bool _searching = false;
  List<SubstackCandidateDto> _candidates = [];

  bool _loadingIntents = true;
  List<SubstackIntentDto> _intents = [];
  final Set<String> _adding = {};

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (!_initialized) {
      _initialized = true;
      _app = AppScope.of(context);
      _loadIntents();
    }
  }

  @override
  void dispose() {
    _searchController.dispose();
    super.dispose();
  }

  Future<void> _loadIntents() async {
    try {
      final env = await _app.repository.fetchSubstackIntents();
      if (!mounted) return;
      setState(() {
        _intents = env.intents;
        _loadingIntents = false;
      });
    } catch (_) {
      if (!mounted) return;
      setState(() => _loadingIntents = false);
    }
  }

  Future<void> _search() async {
    final q = _searchController.text.trim();
    if (q.isEmpty) return;
    setState(() => _searching = true);
    try {
      final env = await _app.repository.discoverSubstacks(q);
      if (!mounted) return;
      setState(() {
        _candidates = env.candidates;
        _searching = false;
      });
    } catch (e) {
      if (!mounted) return;
      setState(() => _searching = false);
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text('$e')));
    }
  }

  Future<void> _add(String pubUrl) async {
    setState(() => _adding.add(pubUrl));
    try {
      await _app.repository.createSubstackIntent(pubUrl);
      await _loadIntents();
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        const SnackBar(content: Text('Added — check for a confirmation email')),
      );
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context)
          .showSnackBar(SnackBar(content: Text('$e')));
    } finally {
      if (mounted) setState(() => _adding.remove(pubUrl));
    }
  }

  bool _alreadyAdded(String pubHost) =>
      _intents.any((i) => i.pubHost == pubHost);

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    return Scaffold(
      appBar: AppBar(title: const Text('Add Substack')),
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.all(DesignTokens.spacingL),
          children: [
            _label('FIND', text),
            Row(
              children: [
                Expanded(
                  child: TextField(
                    controller: _searchController,
                    decoration:
                        const InputDecoration(labelText: 'Topic or publication'),
                    onSubmitted: (_) => _search(),
                  ),
                ),
                const SizedBox(width: DesignTokens.spacingS),
                ElevatedButton(
                  onPressed: _searching ? null : _search,
                  child: const Text('Find'),
                ),
              ],
            ),
            const SizedBox(height: DesignTokens.spacingM),
            if (_searching)
              const Center(
                child: Padding(
                  padding: EdgeInsets.all(DesignTokens.spacingL),
                  child: CircularProgressIndicator(),
                ),
              ),
            ..._candidates.map((c) => _candidateCard(c, text)),
            const SizedBox(height: DesignTokens.spacingL),
            _label('YOUR SUBSCRIPTIONS', text),
            if (_loadingIntents)
              const Center(
                child: Padding(
                  padding: EdgeInsets.all(DesignTokens.spacingL),
                  child: CircularProgressIndicator(),
                ),
              )
            else
              ..._intents.map((i) => _intentCard(i, text)),
          ],
        ),
      ),
    );
  }

  Widget _label(String s, TextTheme text) => Padding(
        padding: const EdgeInsets.only(bottom: DesignTokens.spacingS),
        child: Text(s,
            style: text.labelSmall?.copyWith(color: DesignTokens.colorMuted)),
      );

  Widget _candidateCard(SubstackCandidateDto c, TextTheme text) {
    final added = _alreadyAdded(c.pubHost);
    final adding = _adding.contains(c.pubUrl);
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(DesignTokens.spacingM),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(c.title ?? c.pubHost, style: text.titleMedium),
            if (c.why != null) ...[
              const SizedBox(height: DesignTokens.spacingXs),
              Text(c.why!,
                  style: text.bodyMedium
                      ?.copyWith(color: DesignTokens.colorMuted)),
            ],
            const SizedBox(height: DesignTokens.spacingS),
            Align(
              alignment: Alignment.centerLeft,
              child: added
                  ? Text('Added',
                      style: text.labelMedium
                          ?.copyWith(color: DesignTokens.colorAmberDeep))
                  : ElevatedButton(
                      onPressed: adding ? null : () => _add(c.pubUrl),
                      child: adding
                          ? const SizedBox(
                              height: 16,
                              width: 16,
                              child:
                                  CircularProgressIndicator(strokeWidth: 2),
                            )
                          : const Text('Add'),
                    ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _intentCard(SubstackIntentDto i, TextTheme text) {
    final pending = i.displayStatus == SubstackIntentStatus.pending;
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(DesignTokens.spacingM),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text(i.displayTitle, style: text.titleMedium),
            const SizedBox(height: DesignTokens.spacingXs),
            Text(
              pending ? 'Pending confirmation' : 'Active',
              style: text.labelMedium?.copyWith(
                color:
                    pending ? DesignTokens.colorMuted : DesignTokens.colorAmberDeep,
              ),
            ),
            if (i.hasLiveVerificationCode) ...[
              const SizedBox(height: DesignTokens.spacingS),
              Container(
                padding: const EdgeInsets.all(DesignTokens.spacingS),
                decoration: BoxDecoration(
                  color: DesignTokens.colorCream,
                  borderRadius:
                      BorderRadius.circular(DesignTokens.radiusCard),
                ),
                child: Row(
                  children: [
                    const Icon(Icons.vpn_key, size: 18),
                    const SizedBox(width: DesignTokens.spacingS),
                    Text('Code: ${i.pendingVerificationCode}',
                        style: text.bodyLarge),
                  ],
                ),
              ),
            ],
          ],
        ),
      ),
    );
  }
}
