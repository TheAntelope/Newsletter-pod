import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../api/models.dart';
import '../design_tokens.dart';
import '../services/link_launcher.dart';
import '../state/app_state.dart';
import '../widgets/editorial.dart';

/// Add a Substack: discover candidates by topic, add one (which creates an
/// intent), and review existing subscriptions — surfacing the 6-digit
/// verification code when Substack sends one. Editorial rebuild.
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
      ScaffoldMessenger.of(context).showSnackBar(SnackBar(content: Text('$e')));
    }
  }

  Future<void> _add(String pubUrl) async {
    final messenger = ScaffoldMessenger.of(context);
    setState(() => _adding.add(pubUrl));
    try {
      final env = await _app.repository.createSubstackIntent(pubUrl);
      await _loadIntents();
      final intent = env.intent;
      // Creating the intent alone never subscribes the alias — Substack only
      // emails the alias once the user completes the publication's own
      // subscribe form with it. Mirror the iOS flow: copy the alias to the
      // clipboard, then deep-link to the subscribe page so the user can paste
      // it and subscribe (which triggers the confirmation email → verification
      // code → push).
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
      final subscribeUrl = intent.subscribeUrl;
      if (subscribeUrl != null && mounted) {
        await openExternal(context, subscribeUrl.toString());
      }
    } catch (e) {
      if (!mounted) return;
      messenger.showSnackBar(SnackBar(content: Text('$e')));
    } finally {
      if (mounted) setState(() => _adding.remove(pubUrl));
    }
  }

  bool _alreadyAdded(String pubHost) =>
      _intents.any((i) => i.pubHost == pubHost);

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Add Substack')),
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.all(DesignTokens.spacingL),
          children: [
            const MetaLabel('Find a publication'),
            const SizedBox(height: DesignTokens.spacingM),
            Row(
              children: [
                Expanded(
                  child: TextField(
                    controller: _searchController,
                    decoration: const InputDecoration(
                      labelText: 'Topic or publication',
                    ),
                    onSubmitted: (_) => _search(),
                  ),
                ),
                const SizedBox(width: DesignTokens.spacingS),
                AmberButton.filled(
                  label: 'Find',
                  expand: false,
                  loading: _searching,
                  onPressed: _searching ? null : _search,
                ),
              ],
            ),
            const SizedBox(height: DesignTokens.spacingM),
            for (final c in _candidates) ...[
              _CandidateCard(
                candidate: c,
                added: _alreadyAdded(c.pubHost),
                adding: _adding.contains(c.pubUrl),
                onAdd: () => _add(c.pubUrl),
              ),
              const SizedBox(height: DesignTokens.spacingM),
            ],
            const SizedBox(height: DesignTokens.spacingS),
            const MetaLabel('Your subscriptions'),
            const SizedBox(height: DesignTokens.spacingM),
            if (_loadingIntents)
              const Center(
                child: Padding(
                  padding: EdgeInsets.all(DesignTokens.spacingL),
                  child: CircularProgressIndicator(),
                ),
              )
            else
              for (final i in _intents) ...[
                _IntentCard(intent: i),
                const SizedBox(height: DesignTokens.spacingM),
              ],
          ],
        ),
      ),
    );
  }
}

class _CandidateCard extends StatelessWidget {
  const _CandidateCard({
    required this.candidate,
    required this.added,
    required this.adding,
    required this.onAdd,
  });

  final SubstackCandidateDto candidate;
  final bool added;
  final bool adding;
  final VoidCallback onAdd;

  @override
  Widget build(BuildContext context) {
    final c = candidate;
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
        if (c.why != null)
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
                  onPressed: adding ? null : onAdd,
                ),
        ),
      ],
    );
  }
}

class _IntentCard extends StatelessWidget {
  const _IntentCard({required this.intent});

  final SubstackIntentDto intent;

  @override
  Widget build(BuildContext context) {
    final i = intent;
    final pending = i.displayStatus == SubstackIntentStatus.pending;
    return EditorialCard(
      spacing: DesignTokens.spacingS,
      children: [
        Row(
          children: [
            Expanded(
              child: Text(
                i.displayTitle,
                style: DesignTokens.typographySubtitle
                    .copyWith(color: DesignTokens.colorInk),
              ),
            ),
            if (i.hasPaidTier) const _PaidTag(),
          ],
        ),
        Text(
          pending ? 'Pending confirmation' : 'Active',
          style: DesignTokens.typographyMeta.copyWith(
            color: pending
                ? DesignTokens.colorMuted
                : DesignTokens.colorAmberDeep,
          ),
        ),
        if (i.hasLiveVerificationCode)
          Container(
            padding: const EdgeInsets.all(DesignTokens.spacingS),
            decoration: BoxDecoration(
              color: DesignTokens.colorCream,
              borderRadius: BorderRadius.circular(12),
              border: Border.all(color: DesignTokens.colorAmber),
            ),
            child: Row(
              children: [
                const Icon(Icons.vpn_key,
                    size: 18, color: DesignTokens.colorAmberDeep),
                const SizedBox(width: DesignTokens.spacingS),
                Text(
                  'Code: ${i.pendingVerificationCode}',
                  style: DesignTokens.typographyBodyStrong
                      .copyWith(color: DesignTokens.colorInk),
                ),
              ],
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
