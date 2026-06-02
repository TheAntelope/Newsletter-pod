import 'package:flutter/material.dart';

import '../design_tokens.dart';

/// The small dot row tracking progress through the onboarding wizard. Dots up
/// to and including [current] are amber; the rest are rule-coloured. Port of
/// iOS `OnboardingProgressDots`.
class OnboardingProgressDots extends StatelessWidget {
  const OnboardingProgressDots({
    super.key,
    required this.current,
    required this.total,
  });

  final int current;
  final int total;

  @override
  Widget build(BuildContext context) {
    return Row(
      mainAxisSize: MainAxisSize.min,
      children: [
        for (var i = 0; i < total; i++)
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 3),
            child: Container(
              width: 6,
              height: 6,
              decoration: BoxDecoration(
                shape: BoxShape.circle,
                color: i <= current
                    ? DesignTokens.colorAmber
                    : DesignTokens.colorRule,
              ),
            ),
          ),
      ],
    );
  }
}
