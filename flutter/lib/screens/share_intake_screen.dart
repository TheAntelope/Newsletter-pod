import 'dart:convert';
import 'dart:io';

import 'package:flutter/material.dart';

import '../api/api_client.dart' show ApiException, SharedItemResult;
import '../data/app_repository.dart';
import '../design_tokens.dart';
import '../services/share_intake_controller.dart';
import '../state/app_state.dart';
import '../widgets/editorial.dart';

/// The "Send to ClawCast" confirmation screen — the Flutter analogue of the iOS
/// Share Extension's UI. Shown full-screen by [RootView] whenever the share
/// controller has queued items and the user is signed in. It uploads each
/// [PendingShare] to `POST /v1/items/shared` (via the live repository, which
/// carries the session token), reports per-item results, then calls [onDone]
/// (which clears the queue and returns the user to the dashboard).
class ShareIntakeScreen extends StatefulWidget {
  const ShareIntakeScreen({
    super.key,
    required this.shares,
    required this.onDone,
  });

  final List<PendingShare> shares;
  final VoidCallback onDone;

  @override
  State<ShareIntakeScreen> createState() => _ShareIntakeScreenState();
}

enum _Status { uploading, pinned, duplicate, failed }

class _ShareResult {
  _ShareResult(this.share) : status = _Status.uploading;
  final PendingShare share;
  _Status status;
  String? error;
}

class _ShareIntakeScreenState extends State<ShareIntakeScreen> {
  late final List<_ShareResult> _results =
      widget.shares.map(_ShareResult.new).toList();
  bool _done = false;

  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addPostFrameCallback((_) => _process());
  }

  Future<void> _process() async {
    final repository = AppScope.of(context).repository;
    for (final result in _results) {
      try {
        if (!result.share.supported) {
          throw const _UnsupportedShare();
        }
        final ack = await _upload(repository, result.share);
        if (!mounted) return;
        result.status = ack.duplicate ? _Status.duplicate : _Status.pinned;
      } on _UnsupportedShare {
        result
          ..status = _Status.failed
          ..error = "That kind of item can't be sent to ClawCast yet.";
      } on ApiException catch (e) {
        result
          ..status = _Status.failed
          ..error = _friendlyError(e);
      } catch (_) {
        result
          ..status = _Status.failed
          ..error = "Couldn't send this item. Try again.";
      }
      if (mounted) setState(() {});
    }
    if (mounted) setState(() => _done = true);
  }

  Future<SharedItemResult> _upload(AppRepository repository, PendingShare share) {
    switch (share.kind) {
      case 'url':
        return repository.submitSharedItem(kind: 'url', url: share.url);
      case 'text':
        return repository.submitSharedItem(
          kind: 'text',
          fileBytes: utf8.encode(share.text ?? ''),
          filename: 'shared.txt',
        );
      default: // pdf | epub | docx
        return _uploadFile(repository, share);
    }
  }

  Future<SharedItemResult> _uploadFile(
      AppRepository repository, PendingShare share) async {
    final bytes = await File(share.filePath!).readAsBytes();
    return repository.submitSharedItem(
      kind: share.kind,
      fileBytes: bytes,
      filename: share.fileName ?? 'shared',
    );
  }

  String _friendlyError(ApiException e) {
    switch (e.statusCode) {
      case 401:
        return 'Sign in to ClawCast first.';
      case 413:
        return 'File too large to share.';
      default:
        return e.message;
    }
  }

  @override
  Widget build(BuildContext context) {
    final anyPinned = _results.any(
      (r) => r.status == _Status.pinned || r.status == _Status.duplicate,
    );
    return Scaffold(
      backgroundColor: DesignTokens.colorCream,
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(DesignTokens.spacingL),
            child: ConstrainedBox(
              constraints: const BoxConstraints(maxWidth: 460),
              child: EditorialCard(
                children: [
                  Row(
                    children: [
                      const ClawcastLogo(size: 40),
                      const SizedBox(width: DesignTokens.spacingM),
                      Expanded(
                        child: Column(
                          crossAxisAlignment: CrossAxisAlignment.start,
                          children: [
                            const MetaLabel('Send to ClawCast'),
                            const SizedBox(height: 2),
                            Text(
                              _done
                                  ? (anyPinned
                                      ? 'Pinned to your next pod.'
                                      : "Couldn't send this.")
                                  : 'Sending…',
                              style: DesignTokens.typographyTitle.copyWith(
                                color: DesignTokens.colorInk,
                              ),
                            ),
                          ],
                        ),
                      ),
                    ],
                  ),
                  const EditorialDivider(),
                  for (final r in _results) _ResultRow(result: r),
                  if (_done)
                    AmberButton.filled(
                      label: 'Done',
                      onPressed: () {
                        if (!mounted) return;
                        setState(() {});
                        widget.onDone();
                      },
                    ),
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}

class _ResultRow extends StatelessWidget {
  const _ResultRow({required this.result});

  final _ShareResult result;

  @override
  Widget build(BuildContext context) {
    final (icon, color, note) = switch (result.status) {
      _Status.uploading => (
          null,
          DesignTokens.colorMuted,
          'Sending…',
        ),
      _Status.pinned => (
          Icons.check_circle,
          DesignTokens.colorAmber,
          'Pinned to your next pod',
        ),
      _Status.duplicate => (
          Icons.check_circle,
          DesignTokens.colorMuted,
          'Already in your next pod',
        ),
      _Status.failed => (
          Icons.error_outline,
          DesignTokens.colorAmberDeep,
          result.error ?? 'Failed',
        ),
    };

    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        SizedBox(
          width: 18,
          height: 18,
          child: icon == null
              ? const CircularProgressIndicator(
                  strokeWidth: 2,
                  valueColor:
                      AlwaysStoppedAnimation<Color>(DesignTokens.colorMuted),
                )
              : Icon(icon, size: 18, color: color),
        ),
        const SizedBox(width: DesignTokens.spacingS),
        Expanded(
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text(
                result.share.label,
                maxLines: 2,
                overflow: TextOverflow.ellipsis,
                style: DesignTokens.typographyBodyStrong
                    .copyWith(color: DesignTokens.colorInk),
              ),
              const SizedBox(height: 2),
              Text(
                note,
                style: DesignTokens.typographyCallout.copyWith(color: color),
              ),
            ],
          ),
        ),
      ],
    );
  }
}

/// Marker for an item the share sheet handed us that we can't forward (e.g. an
/// image), surfaced as a per-row failure rather than crashing the batch.
class _UnsupportedShare implements Exception {
  const _UnsupportedShare();
}
