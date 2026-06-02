import 'dart:async';

import 'package:flutter/material.dart';

import '../design_tokens.dart';

/// A self-pacing progress bar shown while an episode is generating. It has no
/// real progress signal, so it interpolates elapsed time against an expected
/// duration and caps at 95% until generation flips off, when it snaps to 100%
/// ("Episode ready"). Dart port of iOS `GenerationProgressBar` (which uses a
/// `TimelineView`); here a 0.5s timer drives the rebuilds.
class GenerationProgressBar extends StatefulWidget {
  const GenerationProgressBar({
    super.key,
    required this.isGenerating,
    this.expectedDuration = const Duration(seconds: 240),
  });

  final bool isGenerating;
  final Duration expectedDuration;

  @override
  State<GenerationProgressBar> createState() => _GenerationProgressBarState();
}

class _GenerationProgressBarState extends State<GenerationProgressBar> {
  static const double _cap = 0.95;

  DateTime? _startedAt;
  bool _didComplete = false;
  Timer? _timer;

  @override
  void initState() {
    super.initState();
    _sync(widget.isGenerating);
  }

  @override
  void didUpdateWidget(GenerationProgressBar oldWidget) {
    super.didUpdateWidget(oldWidget);
    if (oldWidget.isGenerating != widget.isGenerating) {
      _sync(widget.isGenerating);
    }
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }

  void _sync(bool active) {
    if (active) {
      if (_startedAt == null) {
        _startedAt = DateTime.now();
        _didComplete = false;
        _timer ??= Timer.periodic(const Duration(milliseconds: 500), (_) {
          if (mounted) setState(() {});
        });
      }
    } else if (_startedAt != null) {
      setState(() {
        _didComplete = true;
        _startedAt = null;
      });
      _timer?.cancel();
      _timer = null;
    }
  }

  /// Only render once a run has actually been tracked (started or completed) —
  /// avoids a misleading 0% bar before generation kicks off.
  bool get _hasTrackedRun => _startedAt != null || _didComplete;

  double get _progress {
    if (_didComplete) return 1;
    final start = _startedAt;
    if (start == null) return 0;
    final elapsed = DateTime.now().difference(start).inMilliseconds / 1000.0;
    final p = elapsed / widget.expectedDuration.inSeconds;
    return p < _cap ? p : _cap;
  }

  String get _statusText {
    if (_didComplete) return 'Episode ready';
    if (widget.isGenerating) return 'Generating…';
    return '';
  }

  @override
  Widget build(BuildContext context) {
    if (!_hasTrackedRun) return const SizedBox.shrink();
    final p = _progress;
    final metaStyle = DesignTokens.typographyMeta
        .copyWith(color: DesignTokens.colorMuted);

    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        ClipRRect(
          borderRadius: BorderRadius.circular(4),
          child: LinearProgressIndicator(
            value: p,
            minHeight: 6,
            color: DesignTokens.colorAmber,
            backgroundColor: DesignTokens.colorRule,
          ),
        ),
        const SizedBox(height: 6),
        Row(
          children: [
            Text(_statusText, style: metaStyle),
            const Spacer(),
            Text('${(p * 100).round()}%', style: metaStyle),
          ],
        ),
      ],
    );
  }
}
