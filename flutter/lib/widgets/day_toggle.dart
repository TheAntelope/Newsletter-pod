import 'package:flutter/material.dart';

import '../design_tokens.dart';

/// A single circular weekday toggle (M/T/W/…) used by the schedule editors.
/// Filled amber when selected, hairline ring when not — mirrors the iOS
/// `ScheduleSection` day buttons.
class DayToggle extends StatelessWidget {
  const DayToggle({
    super.key,
    required this.initial,
    required this.selected,
    required this.onTap,
  });

  final String initial;
  final bool selected;
  final VoidCallback onTap;

  @override
  Widget build(BuildContext context) {
    return GestureDetector(
      onTap: onTap,
      child: Container(
        width: 36,
        height: 36,
        alignment: Alignment.center,
        decoration: BoxDecoration(
          shape: BoxShape.circle,
          color: selected ? DesignTokens.colorAmber : Colors.transparent,
          border: Border.all(
            color: selected ? DesignTokens.colorAmber : DesignTokens.colorRule,
            width: 1.5,
          ),
        ),
        child: Text(
          initial,
          style: DesignTokens.typographySubtitle.copyWith(
            color: selected ? Colors.white : DesignTokens.colorInk,
          ),
        ),
      ),
    );
  }
}
