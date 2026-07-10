import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:url_launcher/url_launcher.dart';

/// How an Apple Podcasts open was fulfilled: the app alone (feed previously
/// handed over), the follow deep link (first handoff), or not at all.
enum _OpenPath { appOnly, followLink, failed }

/// Hands the user's private RSS feed to **Apple Podcasts** — the default iOS
/// podcast player — and opens the app on later visits.
///
/// The first open swaps the feed's scheme to Apple's `podcast://` subscribe
/// scheme (`https://api.host/feeds/abc.xml` ->
/// `podcast://api.host/feeds/abc.xml`), which walks the user through Apple's
/// follow sheet. Apple Podcasts shows that sheet on EVERY `podcast://` launch —
/// even for a feed the user already follows — so once the handoff has happened
/// we remember the feed (keyed on its URL, so a regenerated feed token re-runs
/// the follow flow) and from then on just open the app. This is the Apple-side
/// counterpart to [PodcastAddict] on Android.
class ApplePodcasts {
  ApplePodcasts._();

  /// The feed URL we last handed to Apple Podcasts via the follow flow. A URL
  /// (not a bool) so a reset that regenerates the user's feed token naturally
  /// re-triggers the follow flow for the new feed.
  static const String _addedFeedKey = 'apple_podcasts_added_feed_url';

  /// Schemes that open the Apple Podcasts app itself (no feed, so no follow
  /// sheet), tried in order. Both are registered by Apple Podcasts; the second
  /// is the legacy alias kept as a fallback.
  static final List<Uri> _appOnlyUris = [
    Uri.parse('podcasts://'),
    Uri.parse('pcast://'),
  ];

  /// Seam for tests: performs the actual external launch. Defaults to
  /// url_launcher; tests replace it to observe which URIs we try and to
  /// simulate a missing handler.
  @visibleForTesting
  static Future<bool> Function(Uri uri) launcher = _launchExternal;

  /// Build the Apple Podcasts subscribe deep link by replacing the `http(s)://`
  /// prefix with `podcast://`, keeping host + path (+ query) intact.
  static Uri deepLinkFor(String feedUrl) {
    final stripped = feedUrl.replaceFirst(RegExp(r'^https?://'), '');
    return Uri.parse('podcast://$stripped');
  }

  /// Whether [feedUrl] has already been handed to Apple Podcasts on this
  /// device. Best-effort: a reinstall forgets the flag and the user simply
  /// sees the follow sheet once more.
  static Future<bool> hasAddedFeed(String feedUrl) async {
    final prefs = await SharedPreferences.getInstance();
    return prefs.getString(_addedFeedKey) == feedUrl;
  }

  /// Open the user's briefings in Apple Podcasts: the follow flow the first
  /// time, just the app once the feed has been added. On an app-only open,
  /// surfaces a transient "Re-add feed" recovery action — the remembered flag
  /// only proves we LAUNCHED the follow sheet once, not that the user tapped
  /// Follow (Apple gives no signal either way), so a user who cancelled the
  /// sheet needs a way back into the follow flow from this button. Falls back
  /// to the raw `https://` feed URL (opened in the browser) if Apple Podcasts
  /// can't be opened at all, and surfaces a snackbar only if everything fails.
  /// Returns true if any launch succeeded.
  static Future<bool> open(BuildContext context, String feedUrl) async {
    final messenger = ScaffoldMessenger.of(context);
    switch (await _openSmart(feedUrl)) {
      case _OpenPath.appOnly:
        messenger.showSnackBar(SnackBar(
          content: const Text('Not seeing your briefings in Apple Podcasts?'),
          duration: const Duration(seconds: 8),
          action: SnackBarAction(
            label: 'Re-add feed',
            onPressed: () => _addViaFollowLink(feedUrl),
          ),
        ));
        return true;
      case _OpenPath.followLink:
        return true;
      case _OpenPath.failed:
        if (await _openWebFallback(feedUrl)) return true;
        messenger.showSnackBar(
          const SnackBar(content: Text("Couldn't open Apple Podcasts.")),
        );
        return false;
    }
  }

  /// Always run the follow flow (the Feed-access screen's explicit "add this
  /// feed" action), even if we think the feed was already added — this is the
  /// escape hatch when the remembered state is wrong (e.g. the user cancelled
  /// the follow sheet once). Same fallback chain as [open].
  static Future<bool> addFeed(BuildContext context, String feedUrl) async {
    final messenger = ScaffoldMessenger.of(context);
    if (await _addViaFollowLink(feedUrl)) return true;
    if (await _openWebFallback(feedUrl)) return true;
    messenger.showSnackBar(
      const SnackBar(content: Text("Couldn't open Apple Podcasts.")),
    );
    return false;
  }

  /// Context-free open for the notification-tap path: no snackbars, same
  /// added-feed logic as [open]. Returns true if Apple Podcasts opened.
  static Future<bool> openPlayer(String feedUrl) async =>
      await _openSmart(feedUrl) != _OpenPath.failed;

  /// The shared decision: app-only when the feed was already handed over,
  /// otherwise (or when the app-only schemes have no handler, e.g. Apple
  /// Podcasts was deleted) the follow deep link.
  static Future<_OpenPath> _openSmart(String feedUrl) async {
    if (await hasAddedFeed(feedUrl)) {
      for (final uri in _appOnlyUris) {
        if (await launcher(uri)) return _OpenPath.appOnly;
      }
    }
    return await _addViaFollowLink(feedUrl)
        ? _OpenPath.followLink
        : _OpenPath.failed;
  }

  static Future<bool> _addViaFollowLink(String feedUrl) async {
    if (!await launcher(deepLinkFor(feedUrl))) return false;
    final prefs = await SharedPreferences.getInstance();
    await prefs.setString(_addedFeedKey, feedUrl);
    return true;
  }

  static Future<bool> _openWebFallback(String feedUrl) async {
    final webUri = Uri.tryParse(feedUrl);
    return webUri != null && await launcher(webUri);
  }

  /// Launch a URI in its external app, treating both a `false` result and a
  /// "no handler" platform exception as "couldn't open".
  static Future<bool> _launchExternal(Uri uri) async {
    try {
      return await launchUrl(uri, mode: LaunchMode.externalApplication);
    } catch (_) {
      return false;
    }
  }
}
