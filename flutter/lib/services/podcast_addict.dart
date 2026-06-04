import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

/// Hands the user's private RSS feed to **Podcast Addict** — our chosen Android
/// podcast player (largest install base; supports private feeds by URL).
///
/// Flow when the user taps "Open in Podcast Addict":
///   1. Try the `podcastaddict://<feed>` subscribe deep link.
///   2. If Podcast Addict isn't installed the launch fails — we remember the
///      feed and send the user to the Play Store to install it.
///   3. When the user returns to ClawCast we automatically retry the deep link
///      (see [retryPendingOnResume]), so the feed is added without a second tap.
///
/// The `podcastaddict://` scheme comes from the community podcast-platform
/// scheme registry; verify the subscribe behaviour on a real device when wiring
/// up the first Android build.
class PodcastAddict {
  PodcastAddict._();

  static const String packageName = 'com.bambuna.podcastaddict';

  // market:// opens the Play Store app directly; the https URL is the fallback
  // for devices/emulators without Play Store installed.
  static final Uri _playStoreUri =
      Uri.parse('market://details?id=$packageName');
  static final Uri _playStoreWebUri = Uri.parse(
      'https://play.google.com/store/apps/details?id=$packageName');

  /// Feed URL pending a retry once Podcast Addict is installed (set when we
  /// bounce the user to the Play Store, cleared once the deep link succeeds).
  static String? _pendingFeedUrl;

  /// Build the Podcast Addict subscribe deep link from a feed URL by dropping
  /// the `http(s)://` prefix: `podcastaddict://api.host/feeds/abc.xml`.
  static Uri deepLinkFor(String feedUrl) {
    final stripped = feedUrl.replaceFirst(RegExp(r'^https?://'), '');
    return Uri.parse('podcastaddict://$stripped');
  }

  /// Open the feed in Podcast Addict, installing it first if needed. Returns
  /// true if Podcast Addict opened, false if we redirected to the Play Store.
  static Future<bool> subscribe(BuildContext context, String feedUrl) async {
    final messenger = ScaffoldMessenger.of(context);
    if (await _launchDeepLink(feedUrl)) {
      _pendingFeedUrl = null;
      return true;
    }

    // Not installed (or no handler): remember the feed and send them to install.
    _pendingFeedUrl = feedUrl;
    final opened = await _launchExternal(_playStoreUri) ||
        await _launchExternal(_playStoreWebUri);
    messenger.showSnackBar(
      SnackBar(
        content: Text(opened
            ? 'Install Podcast Addict — your feed is added automatically when '
                'you come back.'
            : "Couldn't open the Play Store. Search for “Podcast Addict” to "
                'install it.'),
        duration: const Duration(seconds: 6),
      ),
    );
    return false;
  }

  /// Call from the app's lifecycle observer on resume. If we previously sent the
  /// user to the Play Store, retry the subscribe deep link now that they're
  /// back — by which point Podcast Addict is (hopefully) installed.
  static Future<void> retryPendingOnResume() async {
    final feedUrl = _pendingFeedUrl;
    if (feedUrl == null) return;
    if (await _launchDeepLink(feedUrl)) {
      _pendingFeedUrl = null;
    }
  }

  static Future<bool> _launchDeepLink(String feedUrl) =>
      _launchExternal(deepLinkFor(feedUrl));

  /// Launch a URI in its external app, treating both a `false` result and a
  /// "no Activity found" platform exception as "no handler installed".
  static Future<bool> _launchExternal(Uri uri) async {
    try {
      return await launchUrl(uri, mode: LaunchMode.externalApplication);
    } catch (_) {
      return false;
    }
  }
}
