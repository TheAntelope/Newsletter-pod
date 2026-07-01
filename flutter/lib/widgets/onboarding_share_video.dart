import 'package:flutter/material.dart';
import 'package:video_player/video_player.dart';

import '../design_tokens.dart';

/// The bundled "how to share to ClawCast" clip, shown on the onboarding
/// share-teach step. It's a silent 1080x1920 screen recording with burned-in
/// STEP captions (rendered by the marketing repo's build_share_feature.sh), so
/// it plays muted and loops — nothing is lost without audio.
///
/// Robustness: the platform video plugin isn't present in widget tests (and a
/// device could fail to decode the asset), so we render [fallback] — the static
/// share-sheet mock — until the controller initialises, and stay on it forever
/// if initialisation throws. That keeps the teach step meaningful in every
/// environment and means tests never touch the video platform channel.
class OnboardingShareVideo extends StatefulWidget {
  const OnboardingShareVideo({super.key, required this.fallback});

  /// Shown while the clip loads and if it can't play at all.
  final Widget fallback;

  /// Caps how tall the (portrait 9:16) clip renders so it doesn't dominate the
  /// scrollable onboarding step; width follows from the real aspect ratio.
  static const double _maxHeight = 360;

  @override
  State<OnboardingShareVideo> createState() => _OnboardingShareVideoState();
}

class _OnboardingShareVideoState extends State<OnboardingShareVideo> {
  static const _assetPath = 'assets/onboarding/clawcast-share-onboarding.mp4';

  late final VideoPlayerController _controller;
  bool _ready = false;

  @override
  void initState() {
    super.initState();
    _controller = VideoPlayerController.asset(_assetPath);
    _init();
  }

  Future<void> _init() async {
    try {
      await _controller.initialize();
      if (!mounted) return;
      await _controller.setLooping(true);
      await _controller.setVolume(0);
      await _controller.play();
      if (!mounted) return;
      setState(() => _ready = true);
    } catch (_) {
      // Plugin missing (tests) or decode failure — stay on the fallback mock.
    }
  }

  @override
  void dispose() {
    _controller.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    if (!_ready) return widget.fallback;
    return Center(
      child: ConstrainedBox(
        constraints: const BoxConstraints(
          maxHeight: OnboardingShareVideo._maxHeight,
        ),
        child: AspectRatio(
          aspectRatio: _controller.value.aspectRatio,
          child: ClipRRect(
            borderRadius: BorderRadius.circular(DesignTokens.radiusCard),
            child: Stack(
              fit: StackFit.expand,
              children: [
                VideoPlayer(_controller),
                // A thin rule border, matching the static mock's framing.
                DecoratedBox(
                  decoration: BoxDecoration(
                    borderRadius:
                        BorderRadius.circular(DesignTokens.radiusCard),
                    border: Border.all(color: DesignTokens.colorRule),
                  ),
                ),
              ],
            ),
          ),
        ),
      ),
    );
  }
}
