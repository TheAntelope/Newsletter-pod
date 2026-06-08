import 'package:flutter/material.dart';

import '../api/models.dart';
import '../design_tokens.dart';
import '../services/link_launcher.dart';
import '../state/app_state.dart';
import '../widgets/editorial.dart';

const _months = [
  'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', //
  'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec',
];

/// "Jun 5, 2026, 2:30 PM" — abbreviated date + short 12-hour time, mirroring
/// the iOS candidate row's `.abbreviated`/`.shortened` formatting.
String _formatDateTime(DateTime when) {
  final d = when.toLocal();
  final hour12 = d.hour % 12 == 0 ? 12 : d.hour % 12;
  final minute = d.minute.toString().padLeft(2, '0');
  final period = d.hour < 12 ? 'AM' : 'PM';
  return '${_months[d.month - 1]} ${d.day}, ${d.year}, $hour12:$minute $period';
}

/// Preview of what's likely to land in the next pod, with pin/exclude. Items you
/// shared via the share sheet are highlighted and floated to the top. Pinning is
/// optimistic (local set) over the repository's pin/exclude calls. Editorial
/// rebuild of the iOS `NextEpisodeQueueView`.
class NextEpisodeQueueScreen extends StatefulWidget {
  const NextEpisodeQueueScreen({super.key});

  @override
  State<NextEpisodeQueueScreen> createState() => _NextEpisodeQueueScreenState();
}

class _NextEpisodeQueueScreenState extends State<NextEpisodeQueueScreen> {
  late final AppState _app;
  Future<NextEpisodeQueueEnvelope>? _future;
  final Set<String> _pinned = {};
  int _maxPins = 0;
  bool _seeded = false;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    if (_future == null) {
      _app = AppScope.of(context);
      _future = _app.repository.fetchNextEpisodeQueue();
    }
  }

  void _seed(NextEpisodeQueueEnvelope env) {
    if (_seeded) return;
    _seeded = true;
    _maxPins = env.maxPins;
    for (final c in env.candidates) {
      if (c.pinned) _pinned.add(c.dedupeKey);
    }
  }

  /// Shared items float to the top, otherwise original order is preserved.
  List<NextEpisodeCandidateDto> _ordered(NextEpisodeQueueEnvelope env) {
    final shared = env.candidates.where((c) => c.shared).toList();
    final rest = env.candidates.where((c) => !c.shared).toList();
    return [...shared, ...rest];
  }

  Future<void> _toggle(NextEpisodeCandidateDto c) async {
    if (_pinned.contains(c.dedupeKey)) {
      setState(() => _pinned.remove(c.dedupeKey));
      await _app.repository.excludeNextEpisodeItem(c.dedupeKey);
      return;
    }
    if (_maxPins > 0 && _pinned.length >= _maxPins) {
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(content: Text('You can pin up to $_maxPins items.')),
      );
      return;
    }
    setState(() => _pinned.add(c.dedupeKey));
    await _app.repository.pinNextEpisodeItem(c.dedupeKey);
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Next pod')),
      body: SafeArea(
        child: FutureBuilder<NextEpisodeQueueEnvelope>(
          future: _future,
          builder: (context, snapshot) {
            if (snapshot.connectionState != ConnectionState.done) {
              return const Center(child: CircularProgressIndicator());
            }
            if (snapshot.hasError) {
              return Center(child: Text('${snapshot.error}'));
            }
            final env = snapshot.data!;
            if (!env.enabled) {
              return Center(
                child: Padding(
                  padding: const EdgeInsets.all(DesignTokens.spacingL),
                  child: Text(
                    "The next-pod preview isn't available yet.",
                    style: DesignTokens.typographyBody
                        .copyWith(color: DesignTokens.colorMuted),
                    textAlign: TextAlign.center,
                  ),
                ),
              );
            }
            _seed(env);
            final candidates = _ordered(env);
            return ListView.separated(
              padding: const EdgeInsets.all(DesignTokens.spacingL),
              itemCount: candidates.length + 1,
              separatorBuilder: (_, _) =>
                  const SizedBox(height: DesignTokens.spacingM),
              itemBuilder: (context, i) {
                if (i == 0) {
                  return Text(
                    'Pin the stories you want to make sure land in your next '
                    'pod. Remove anything you’d rather skip. Want to guarantee a '
                    'story makes it in? Share it to ClawCast from any app — '
                    'browser, Mail, or Substack — and it shows up here.',
                    style: DesignTokens.typographyBody
                        .copyWith(color: DesignTokens.colorMuted),
                  );
                }
                final c = candidates[i - 1];
                return _CandidateCard(
                  candidate: c,
                  pinned: _pinned.contains(c.dedupeKey),
                  onToggle: () => _toggle(c),
                );
              },
            );
          },
        ),
      ),
    );
  }
}

class _CandidateCard extends StatelessWidget {
  const _CandidateCard({
    required this.candidate,
    required this.pinned,
    required this.onToggle,
  });

  final NextEpisodeCandidateDto candidate;
  final bool pinned;
  final VoidCallback onToggle;

  @override
  Widget build(BuildContext context) {
    final c = candidate;
    return EditorialCard(
      spacing: DesignTokens.spacingS,
      borderColor: c.shared ? DesignTokens.colorAmber : DesignTokens.colorRule,
      borderWidth: c.shared ? 1.5 : 0.5,
      children: [
        Row(
          children: [
            Expanded(child: MetaLabel(c.sourceName)),
            if (c.shared)
              const _Tag(label: 'Shared', emphasize: true)
            else if (c.likelyIncluded)
              const _Tag(label: 'Likely', emphasize: false),
          ],
        ),
        Text(
          c.title,
          style: DesignTokens.typographySubtitle.copyWith(color: DesignTokens.colorInk),
        ),
        Text(
          c.summary,
          style: DesignTokens.typographyBody.copyWith(color: DesignTokens.colorInkSoft),
        ),
        Align(
          alignment: Alignment.centerLeft,
          child: TextButton.icon(
            onPressed: onToggle,
            style: TextButton.styleFrom(
              foregroundColor:
                  pinned ? DesignTokens.colorAmberDeep : DesignTokens.colorMuted,
              padding: EdgeInsets.zero,
            ),
            icon: Icon(pinned ? Icons.push_pin : Icons.push_pin_outlined,
                size: 18),
            label: Text(pinned ? 'Pinned' : 'Pin'),
          ),
        ),
        Row(
          children: [
            const Icon(Icons.calendar_today_outlined,
                size: 12, color: DesignTokens.colorMuted),
            const SizedBox(width: 6),
            Expanded(
              child: Text(
                _formatDateTime(c.publishedAt),
                style: DesignTokens.typographyCallout
                    .copyWith(color: DesignTokens.colorMuted),
              ),
            ),
            if (c.link.isNotEmpty)
              InkWell(
                onTap: () => openExternal(context, c.link),
                child: Row(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    Text(
                      'Read',
                      style: DesignTokens.typographyCalloutStrong
                          .copyWith(color: DesignTokens.colorAmberDeep),
                    ),
                    const SizedBox(width: 4),
                    const Icon(Icons.north_east,
                        size: 14, color: DesignTokens.colorAmberDeep),
                  ],
                ),
              ),
          ],
        ),
      ],
    );
  }
}

class _Tag extends StatelessWidget {
  const _Tag({required this.label, required this.emphasize});

  final String label;
  final bool emphasize;

  @override
  Widget build(BuildContext context) {
    return Container(
      padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
      decoration: BoxDecoration(
        color: emphasize ? DesignTokens.colorAmber : Colors.transparent,
        borderRadius: BorderRadius.circular(999),
        border: Border.all(color: DesignTokens.colorAmber, width: 1),
      ),
      child: Text(
        label,
        style: DesignTokens.typographyMeta.copyWith(
          color: emphasize ? Colors.white : DesignTokens.colorAmberDeep,
        ),
      ),
    );
  }
}
