import 'package:flutter/material.dart';
import 'package:url_launcher/url_launcher.dart';

/// Open [url] in an external app/browser, surfacing a snackbar if it can't be
/// launched. Captures the messenger before the await so it's safe across the
/// async gap.
Future<void> openExternal(BuildContext context, String url) async {
  final messenger = ScaffoldMessenger.of(context);
  final uri = Uri.tryParse(url);
  if (uri == null) {
    messenger.showSnackBar(SnackBar(content: Text("Couldn't open $url")));
    return;
  }
  try {
    final ok = await launchUrl(uri, mode: LaunchMode.externalApplication);
    if (!ok) {
      messenger.showSnackBar(SnackBar(content: Text("Couldn't open $url")));
    }
  } catch (_) {
    messenger.showSnackBar(SnackBar(content: Text("Couldn't open $url")));
  }
}
