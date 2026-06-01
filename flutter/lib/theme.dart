import 'package:flutter/material.dart';

import 'design_tokens.dart';

/// ClawCast editorial theme.
///
/// Palette, type, spacing and radii come from the shared design-tokens single
/// source of truth ([DesignTokens], generated from the clawcast-tokens repo —
/// the same tokens that drive iOS `Theme.swift`). Intent: a warm, light,
/// editorial look with an amber accent and a serif display face.
class ClawcastTheme {
  ClawcastTheme._();

  static ThemeData light() {
    final colorScheme = ColorScheme.light(
      primary: DesignTokens.colorAmber,
      onPrimary: DesignTokens.colorCream,
      secondary: DesignTokens.colorAmberDeep,
      onSecondary: DesignTokens.colorCream,
      surface: DesignTokens.colorCream,
      onSurface: DesignTokens.colorInk,
    );

    final textTheme = const TextTheme(
      displayLarge: DesignTokens.typographyDisplay,
      titleLarge: DesignTokens.typographyTitle,
      titleMedium: DesignTokens.typographySubtitle,
      bodyMedium: DesignTokens.typographyBody,
      bodyLarge: DesignTokens.typographyBodyStrong,
      labelLarge: DesignTokens.typographyCalloutStrong,
      labelMedium: DesignTokens.typographyCallout,
      labelSmall: DesignTokens.typographyMeta,
    ).apply(
      bodyColor: DesignTokens.colorInk,
      displayColor: DesignTokens.colorInk,
    );

    return ThemeData(
      useMaterial3: true,
      colorScheme: colorScheme,
      scaffoldBackgroundColor: DesignTokens.colorCream,
      textTheme: textTheme,
      dividerColor: DesignTokens.colorRule,
      cardTheme: CardThemeData(
        color: DesignTokens.colorCreamDeep,
        elevation: 0,
        margin: EdgeInsets.zero,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(DesignTokens.radiusCard),
        ),
      ),
      elevatedButtonTheme: ElevatedButtonThemeData(
        style: ElevatedButton.styleFrom(
          backgroundColor: DesignTokens.colorAmber,
          foregroundColor: DesignTokens.colorCream,
          textStyle: DesignTokens.typographyCalloutStrong,
          padding: const EdgeInsets.symmetric(
            horizontal: DesignTokens.spacingL,
            vertical: DesignTokens.spacingM,
          ),
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(DesignTokens.radiusCard),
          ),
        ),
      ),
    );
  }
}
