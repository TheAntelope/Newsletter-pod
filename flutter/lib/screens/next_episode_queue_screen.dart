import 'package:flutter/material.dart';

import '../api/models.dart';
import '../design_tokens.dart';
import '../state/app_state.dart';

/// Preview of what's likely to land in the next pod, with pin/exclude. Pinning
/// is optimistic (local set) over the repository's pin/exclude calls.
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
    final text = Theme.of(context).textTheme;
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
                    'The next-pod preview isn’t available yet.',
                    style: text.bodyMedium,
                    textAlign: TextAlign.center,
                  ),
                ),
              );
            }
            _seed(env);
            return ListView.separated(
              padding: const EdgeInsets.all(DesignTokens.spacingL),
              itemCount: env.candidates.length + 1,
              separatorBuilder: (_, _) =>
                  const SizedBox(height: DesignTokens.spacingS),
              itemBuilder: (context, i) {
                if (i == 0) {
                  return Padding(
                    padding:
                        const EdgeInsets.only(bottom: DesignTokens.spacingS),
                    child: Text(
                      'Pin the stories you want to make sure land in your next pod.',
                      style: text.bodyMedium
                          ?.copyWith(color: DesignTokens.colorMuted),
                    ),
                  );
                }
                final c = env.candidates[i - 1];
                final pinned = _pinned.contains(c.dedupeKey);
                return Card(
                  child: Padding(
                    padding: const EdgeInsets.all(DesignTokens.spacingM),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Row(
                          children: [
                            Expanded(
                              child: Text(
                                c.sourceName.toUpperCase(),
                                style: text.labelSmall
                                    ?.copyWith(color: DesignTokens.colorMuted),
                              ),
                            ),
                            if (c.likelyIncluded)
                              Text(
                                'Likely',
                                style: text.labelSmall?.copyWith(
                                    color: DesignTokens.colorAmberDeep),
                              ),
                          ],
                        ),
                        const SizedBox(height: DesignTokens.spacingXs),
                        Text(c.title, style: text.titleMedium),
                        const SizedBox(height: DesignTokens.spacingXs),
                        Text(c.summary, style: text.bodyMedium),
                        const SizedBox(height: DesignTokens.spacingS),
                        Align(
                          alignment: Alignment.centerLeft,
                          child: TextButton.icon(
                            onPressed: () => _toggle(c),
                            icon: Icon(pinned
                                ? Icons.push_pin
                                : Icons.push_pin_outlined),
                            label: Text(pinned ? 'Pinned' : 'Pin'),
                          ),
                        ),
                      ],
                    ),
                  ),
                );
              },
            );
          },
        ),
      ),
    );
  }
}
