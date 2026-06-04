import 'dart:async';

import 'package:flutter/widgets.dart';
import 'package:receive_sharing_intent/receive_sharing_intent.dart';

/// One item the user pushed into ClawCast from another app's share sheet,
/// normalized into the shape `POST /v1/items/shared` expects. [kind] is one of
/// `url | text | pdf | epub | docx | unsupported`.
@immutable
class PendingShare {
  const PendingShare({
    required this.kind,
    required this.label,
    this.url,
    this.text,
    this.filePath,
    this.fileName,
  });

  final String kind;
  final String label; // short human-readable preview for the confirm screen

  final String? url;
  final String? text;
  final String? filePath;
  final String? fileName;

  bool get supported => kind != 'unsupported';
}

/// Listens to the OS share sheet and exposes the queue of [PendingShare]s the
/// UI should confirm-and-upload. Real-auth build only — [start] subscribes to a
/// platform channel, so the demo build and widget tests must never call it (they
/// simply never construct/provide a controller). The screen routing reacts to
/// [hasPending] via [ShareScope].
class ShareIntakeController extends ChangeNotifier {
  StreamSubscription<List<SharedMediaFile>>? _sub;
  final List<PendingShare> _pending = <PendingShare>[];

  List<PendingShare> get pending => List.unmodifiable(_pending);
  bool get hasPending => _pending.isNotEmpty;

  /// Subscribe to shares that arrive while the app is already running, then
  /// drain the share that cold-launched the app (if any) and clear it so it
  /// isn't re-delivered on the next resume.
  void start() {
    _sub = ReceiveSharingIntent.instance.getMediaStream().listen(
      _ingest,
      onError: (_) {/* a malformed intent must not crash the app */},
    );
    ReceiveSharingIntent.instance.getInitialMedia().then((media) {
      _ingest(media);
      ReceiveSharingIntent.instance.reset();
    });
  }

  void _ingest(List<SharedMediaFile> files) {
    if (files.isEmpty) return;
    _pending.addAll(files.map(mapSharedFile));
    notifyListeners();
  }

  /// Empty the queue (called once the confirm screen finishes uploading).
  void clear() {
    if (_pending.isEmpty) return;
    _pending.clear();
    notifyListeners();
  }

  @override
  void dispose() {
    _sub?.cancel();
    super.dispose();
  }

  // ---------------------------------------------------------------------------
  // Mapping (pure; unit-tested)
  // ---------------------------------------------------------------------------

  /// Translate a platform [SharedMediaFile] into our normalized [PendingShare].
  @visibleForTesting
  static PendingShare mapSharedFile(SharedMediaFile file) {
    switch (file.type) {
      case SharedMediaType.url:
        return PendingShare(kind: 'url', url: file.path, label: file.path);
      case SharedMediaType.text:
        return classifyText(file.path);
      case SharedMediaType.file:
        return _mapFile(file);
      case SharedMediaType.image:
      case SharedMediaType.video:
        return PendingShare(kind: 'unsupported', label: _basename(file.path));
    }
  }

  /// Last path segment, tolerant of either separator (Android hands us POSIX
  /// paths; tests may run on Windows).
  static String _basename(String path) => path.split(RegExp(r'[/\\]')).last;

  /// Android delivers a shared link as `text/plain` (not a `url` type), so a
  /// bare URL must be promoted to `kind=url` for the backend to fetch the
  /// article; anything else stays plain text.
  @visibleForTesting
  static PendingShare classifyText(String raw) {
    final trimmed = raw.trim();
    if (_isSingleUrl(trimmed)) {
      return PendingShare(kind: 'url', url: trimmed, label: trimmed);
    }
    final preview =
        trimmed.length <= 80 ? trimmed : '${trimmed.substring(0, 77)}…';
    return PendingShare(kind: 'text', text: raw, label: preview);
  }

  static bool _isSingleUrl(String s) {
    if (s.contains(RegExp(r'\s'))) return false;
    final uri = Uri.tryParse(s);
    return uri != null &&
        (uri.scheme == 'http' || uri.scheme == 'https') &&
        uri.host.isNotEmpty;
  }

  static PendingShare _mapFile(SharedMediaFile file) {
    final name = _basename(file.path);
    final lower = name.toLowerCase();
    final mime = (file.mimeType ?? '').toLowerCase();
    String? kind;
    if (mime.contains('pdf') || lower.endsWith('.pdf')) {
      kind = 'pdf';
    } else if (mime.contains('epub') || lower.endsWith('.epub')) {
      kind = 'epub';
    } else if (mime.contains('wordprocessingml') || lower.endsWith('.docx')) {
      kind = 'docx';
    }
    if (kind == null) {
      return PendingShare(kind: 'unsupported', fileName: name, label: name);
    }
    return PendingShare(
      kind: kind,
      filePath: file.path,
      fileName: name,
      label: name,
    );
  }
}

/// Exposes the [ShareIntakeController] to the widget tree (above MaterialApp).
/// Absent in the demo build / tests — consumers use [maybeOf] and no-op when it
/// isn't there.
class ShareScope extends InheritedNotifier<ShareIntakeController> {
  const ShareScope({
    super.key,
    required ShareIntakeController super.notifier,
    required super.child,
  });

  static ShareIntakeController? maybeOf(BuildContext context) =>
      context
          .dependOnInheritedWidgetOfExactType<ShareScope>()
          ?.notifier;
}
