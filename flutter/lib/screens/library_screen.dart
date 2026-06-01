import 'package:flutter/material.dart';

import '../api/models.dart';
import '../design_tokens.dart';
import '../state/app_state.dart';

const _months = [
  'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
  'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec',
];

String _episodeMeta(LibraryEpisodeDto e) {
  final d = e.publishedAt.toLocal();
  final date = '${_months[d.month - 1]} ${d.day}';
  final seconds = e.durationSeconds;
  if (seconds == null) return date;
  return '$date · ${(seconds / 60).round()} min';
}

class LibraryScreen extends StatefulWidget {
  const LibraryScreen({super.key});

  @override
  State<LibraryScreen> createState() => _LibraryScreenState();
}

class _LibraryScreenState extends State<LibraryScreen> {
  Future<EpisodesEnvelope>? _future;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    _future ??= AppScope.of(context).repository.fetchEpisodes();
  }

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    return Scaffold(
      appBar: AppBar(title: const Text('Library')),
      body: SafeArea(
        child: FutureBuilder<EpisodesEnvelope>(
          future: _future,
          builder: (context, snapshot) {
            if (snapshot.connectionState != ConnectionState.done) {
              return const Center(child: CircularProgressIndicator());
            }
            if (snapshot.hasError) {
              return Center(child: Text('${snapshot.error}'));
            }
            final episodes = snapshot.data!.episodes;
            if (episodes.isEmpty) {
              return Center(
                child: Text('No episodes yet.', style: text.bodyMedium),
              );
            }
            return ListView.separated(
              padding: const EdgeInsets.all(DesignTokens.spacingL),
              itemCount: episodes.length,
              separatorBuilder: (_, _) =>
                  const SizedBox(height: DesignTokens.spacingS),
              itemBuilder: (context, i) {
                final e = episodes[i];
                return Card(
                  child: Padding(
                    padding: const EdgeInsets.all(DesignTokens.spacingM),
                    child: Column(
                      crossAxisAlignment: CrossAxisAlignment.start,
                      children: [
                        Text(
                          _episodeMeta(e).toUpperCase(),
                          style: text.labelSmall
                              ?.copyWith(color: DesignTokens.colorMuted),
                        ),
                        const SizedBox(height: DesignTokens.spacingXs),
                        Text(e.title, style: text.titleLarge),
                        const SizedBox(height: DesignTokens.spacingS),
                        Text(e.description, style: text.bodyMedium),
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
