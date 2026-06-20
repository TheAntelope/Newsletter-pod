import 'dart:io' show Platform;

import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../api/models.dart';
import '../design_tokens.dart';
import '../services/apple_podcasts.dart';
import '../services/podcast_addict.dart';
import '../state/app_state.dart';
import '../widgets/editorial.dart';

/// Private RSS feed access. Editorial rebuild of the iOS `FeedAccessView`: a
/// one-tap "open in Podcast Addict" step (our chosen Android player — it's
/// installed automatically if missing, then the feed is added on return), with
/// the copyable feed URL below as a fallback for any other podcast app.
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
            final isIOS = !kIsWeb && Platform.isIOS;
            return ListView(
              padding: const EdgeInsets.all(DesignTokens.spacingL),
              children: [
                EditorialCard(
                  children: [
                    const MetaLabel('Step 1'),
                    Text(
                      isIOS
                          ? 'Open in Apple Podcasts'
                          : 'Open in Podcast Addict',
                      style: DesignTokens.typographyTitle
                          .copyWith(color: DesignTokens.colorInk),
                    ),
                    Text(
                      isIOS
                          ? 'Your briefings are delivered as a private podcast '
                              'feed. Tap below to add it to Apple Podcasts.'
                          : 'Your briefings are delivered as a private podcast '
                              'feed. Tap below to add it to Podcast Addict — '
                              'we’ll install the app for you if you don’t have '
                              'it yet.',
                      style: DesignTokens.typographyBody
                          .copyWith(color: DesignTokens.colorInkSoft),
                    ),
                    AmberButton.filled(
                      label: isIOS
                          ? 'Open in Apple Podcasts'
                          : 'Open in Podcast Addict',
                      icon: isIOS ? Icons.play_arrow : Icons.podcasts,
                      onPressed: () => isIOS
                          ? ApplePodcasts.open(context, feed.feedUrl)
                          : PodcastAddict.subscribe(context, feed.feedUrl),
                    ),
                  ],
                ),
                const SizedBox(height: DesignTokens.spacingL),
                EditorialCard(
                  children: [
                    const MetaLabel('Or · Use another podcast app'),
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
