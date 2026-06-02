import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../api/models.dart';
import '../design_tokens.dart';
import '../state/app_state.dart';
import '../widgets/editorial.dart';

/// Private RSS feed access. Editorial rebuild of the iOS `FeedAccessView`: a
/// "add to your podcast app" step, the copyable feed URL, and the latest-run
/// status. (The Apple-Podcasts deep link is iOS-only; on Android we surface the
/// URL to paste into any podcast app.)
class FeedAccessScreen extends StatefulWidget {
  const FeedAccessScreen({super.key});

  @override
  State<FeedAccessScreen> createState() => _FeedAccessScreenState();
}

class _FeedAccessScreenState extends State<FeedAccessScreen> {
  Future<FeedEnvelope>? _future;
  bool _copied = false;

  @override
  void didChangeDependencies() {
    super.didChangeDependencies();
    _future ??= AppScope.of(context).repository.fetchFeed();
  }

  Future<void> _copy(String url) async {
    await Clipboard.setData(ClipboardData(text: url));
    if (!mounted) return;
    setState(() => _copied = true);
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      appBar: AppBar(title: const Text('Feed access')),
      body: SafeArea(
        child: FutureBuilder<FeedEnvelope>(
          future: _future,
          builder: (context, snapshot) {
            if (snapshot.connectionState != ConnectionState.done) {
              return const Center(child: CircularProgressIndicator());
            }
            if (snapshot.hasError) {
              return Center(child: Text('${snapshot.error}'));
            }
            final feed = snapshot.data!;
            return ListView(
              padding: const EdgeInsets.all(DesignTokens.spacingL),
              children: [
                EditorialCard(
                  children: [
                    const MetaLabel('Step 1'),
                    Text(
                      'Add to your podcast app',
                      style: DesignTokens.typographyTitle
                          .copyWith(color: DesignTokens.colorInk),
                    ),
                    Text(
                      'Your briefings are delivered as a private podcast feed. '
                      'Add it to the player you already use.',
                      style: DesignTokens.typographyBody
                          .copyWith(color: DesignTokens.colorInkSoft),
                    ),
                  ],
                ),
                const SizedBox(height: DesignTokens.spacingL),
                EditorialCard(
                  children: [
                    const MetaLabel('Step 2 · Add by URL'),
                    Container(
                      width: double.infinity,
                      padding: const EdgeInsets.all(DesignTokens.spacingS),
                      decoration: BoxDecoration(
                        color: DesignTokens.colorCreamDeep,
                        borderRadius: BorderRadius.circular(10),
                      ),
                      child: SelectableText(
                        feed.feedUrl,
                        style: const TextStyle(
                          fontFamily: 'monospace',
                          fontSize: 13,
                          color: DesignTokens.colorInkSoft,
                        ),
                      ),
                    ),
                    AmberButton.outlined(
                      label: _copied ? 'Copied' : 'Copy feed link',
                      icon: _copied ? Icons.check : Icons.copy,
                      onPressed: () => _copy(feed.feedUrl),
                    ),
                    Text(
                      'In your podcast app: add a show by URL and paste this link.',
                      style: DesignTokens.typographyCallout
                          .copyWith(color: DesignTokens.colorMuted),
                    ),
                  ],
                ),
                if (feed.latestRun != null) ...[
                  const SizedBox(height: DesignTokens.spacingL),
                  _LatestRunCard(run: feed.latestRun!),
                ],
              ],
            );
          },
        ),
      ),
    );
  }
}

class _LatestRunCard extends StatelessWidget {
  const _LatestRunCard({required this.run});

  final UserRunDto run;

  @override
  Widget build(BuildContext context) {
    final status =
        run.status.isEmpty ? run.status : '${run.status[0].toUpperCase()}${run.status.substring(1)}';
    return EditorialCard(
      spacing: DesignTokens.spacingS,
      children: [
        const MetaLabel('Latest run'),
        Row(
          children: [
            Expanded(
              child: Text(
                status,
                style: DesignTokens.typographySubtitle
                    .copyWith(color: DesignTokens.colorInk),
              ),
            ),
            if (run.capHit)
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                decoration: BoxDecoration(
                  color: DesignTokens.colorCreamDeep,
                  borderRadius: BorderRadius.circular(999),
                ),
                child: Text(
                  'Cap hit',
                  style: DesignTokens.typographyMeta
                      .copyWith(color: DesignTokens.colorAmberDeep),
                ),
              ),
          ],
        ),
        Text(
          run.message,
          style: DesignTokens.typographyCallout
              .copyWith(color: DesignTokens.colorInkSoft),
        ),
      ],
    );
  }
}
