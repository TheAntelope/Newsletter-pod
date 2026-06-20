import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

/// Hands the user's private RSS feed to **Apple Podcasts** — the default iOS
/// podcast player — by swapping the feed's scheme to Apple's `podcast://`
/// subscribe scheme (`https://api.host/feeds/abc.xml` ->
/// `podcast://api.host/feeds/abc.xml`). Opening that URL adds the private feed
/// in Apple Podcasts. This mirrors the original native iOS `openInApplePodcasts`
/// behaviour and is the Apple-side counterpart to [PodcastAddict] on Android.
class ApplePodcasts {
  ApplePodcasts._();

  /// Build the Apple Podcasts subscribe deep link by replacing the `http(s)://`
  /// prefix with `podcast://`, keeping host + path (+ query) intact.
  static Uri deepLinkFor(String feedUrl) {
    final stripped = feedUrl.replaceFirst(RegExp(r'^https?://'), '');
    return Uri.parse('podcast://$stripped');
  }

  /// Open the feed in Apple Podcasts. Falls back to the raw `https://` feed URL
  /// (opened in the browser) if the `podcast://` scheme has no handler, and
  /// surfaces a snackbar only if both attempts fail. Returns true if either
  /// launch succeeded.
  static Future<bool> open(BuildContext context, String feedUrl) async {
    final messenger = ScaffoldMessenger.of(context);
    if (await _launchExternal(deepLinkFor(feedUrl))) return true;
    final webUri = Uri.tryParse(feedUrl);
    if (webUri != null && await _launchExternal(webUri)) return true;
    messenger.showSnackBar(
      const SnackBar(content: Text("Couldn't open Apple Podcasts.")),
    );
    return false;
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
