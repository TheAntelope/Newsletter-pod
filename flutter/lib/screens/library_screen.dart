import 'package:flutter/material.dart';

import '../api/models.dart';
import '../design_tokens.dart';
import '../state/app_state.dart';
import '../widgets/editorial.dart';
import 'dashboard_scaffold.dart';

const _months = [
  'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', //
  'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec',
];

String _episodeMeta(LibraryEpisodeDto e) {
  final d = e.publishedAt.toLocal();
  final date = '${_months[d.month - 1]} ${d.day}';
  final seconds = e.durationSeconds;
  if (seconds == null) return date;
  return '$date · ${(seconds / 60).round()} min';
}

/// Library tab. Editorial rebuild of the iOS `LibraryView`: each episode is an
/// editorial card with its meta eyebrow, title, description, an item-count row,
/// and an expandable "In this episode" section listing the source items that
/// fed it. (Audio preview is deferred — see the UI-parity punch-list.)
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
    return Scaffold(
      appBar: AppBar(
        leading: Padding(
          padding: const EdgeInsets.all(8),
          child: ClawcastLogo(
            size: 28,
            onTap: () => DashboardScope.goHome(context),
          ),
        ),
        title: const Text('Library'),
      ),
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
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    const ClawcastLogo(size: 56),
                    const SizedBox(height: DesignTokens.spacingM),
                    Text(
                      'No episodes yet.',
                      style: DesignTokens.typographyBody
                          .copyWith(color: DesignTokens.colorMuted),
                    ),
                  ],
                ),
              );
            }
            return ListView.separated(
              padding: const EdgeInsets.all(DesignTokens.spacingL),
              itemCount: episodes.length,
              separatorBuilder: (_, _) =>
                  const SizedBox(height: DesignTokens.spacingM),
              itemBuilder: (context, i) => _EpisodeCard(episode: episodes[i]),
            );
          },
        ),
      ),
    );
  }
}

class _EpisodeCard extends StatefulWidget {
  const _EpisodeCard({required this.episode});

  final LibraryEpisodeDto episode;

  @override
  State<_EpisodeCard> createState() => _EpisodeCardState();
}

class _EpisodeCardState extends State<_EpisodeCard> {
  bool _expanded = false;

  @override
  Widget build(BuildContext context) {
    final e = widget.episode;
    final refs = e.sourceItemRefs;
    return EditorialCard(
      spacing: DesignTokens.spacingS,
      children: [
        MetaLabel(_episodeMeta(e)),
        Text(
          e.title,
          style: DesignTokens.typographyTitle.copyWith(color: DesignTokens.colorInk),
        ),
        Text(
          e.description,
          style: DesignTokens.typographyBody.copyWith(color: DesignTokens.colorInkSoft),
        ),
        Row(
          children: [
            _MetaChip(
              icon: Icons.article_outlined,
              label: '${e.processedItemCount} items',
            ),
            if (e.droppedItemCount > 0) ...[
              const SizedBox(width: DesignTokens.spacingM),
              _MetaChip(
                icon: Icons.filter_alt_outlined,
                label: '${e.droppedItemCount} trimmed',
              ),
            ],
          ],
        ),
        if (refs.isNotEmpty) ...[
          const EditorialDivider(),
          InkWell(
            onTap: () => setState(() => _expanded = !_expanded),
            child: Row(
              children: [
                Text(
                  'In this episode',
                  style: DesignTokens.typographyCalloutStrong
                      .copyWith(color: DesignTokens.colorAmberDeep),
                ),
                const Spacer(),
                Icon(
                  _expanded ? Icons.expand_less : Icons.expand_more,
                  size: 18,
                  color: DesignTokens.colorAmberDeep,
                ),
              ],
            ),
          ),
          if (_expanded)
            for (final ref in refs)
              Padding(
                padding: const EdgeInsets.only(top: DesignTokens.spacingS),
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    Text(
                      ref.sourceName.toUpperCase(),
                      style: DesignTokens.typographyMeta
                          .copyWith(color: DesignTokens.colorMuted),
                    ),
                    const SizedBox(height: 2),
                    Text(
                      ref.title,
                      style: DesignTokens.typographyCallout
                          .copyWith(color: DesignTokens.colorInk),
                    ),
                  ],
                ),
              ),
        ],
      ],
    );
  }
}

class _MetaChip extends StatelessWidget {
  const _MetaChip({required this.icon, required this.label});

  final IconData icon;
  final String label;

  @override
  Widget build(BuildContext context) {
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        Icon(icon, size: 14, color: DesignTokens.colorMuted),
        const SizedBox(width: 4),
        Text(
          label,
          style: DesignTokens.typographyCallout
              .copyWith(color: DesignTokens.colorMuted),
        ),
      ],
    );
  }
}
