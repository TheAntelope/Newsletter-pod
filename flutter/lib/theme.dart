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
      // Flat, cream chrome — the editorial look has no Material elevation on the
      // navigation bar or app bar (mirrors iOS `editorialBackground()`).
      appBarTheme: AppBarTheme(
        backgroundColor: DesignTokens.colorCream,
        foregroundColor: DesignTokens.colorInk,
        surfaceTintColor: Colors.transparent,
        elevation: 0,
        scrolledUnderElevation: 0,
        centerTitle: false,
        // Bake ink into the title style: when titleTextStyle is set but has no
        // color, the AppBar skips merging foregroundColor in, so the title
        // would otherwise fall back to a light default on the cream background.
        titleTextStyle:
            DesignTokens.typographyTitle.copyWith(color: DesignTokens.colorInk),
      ),
      navigationBarTheme: NavigationBarThemeData(
        backgroundColor: DesignTokens.colorCream,
        surfaceTintColor: Colors.transparent,
        indicatorColor: _amberWash,
        elevation: 0,
        height: 64,
        labelTextStyle: WidgetStateProperty.resolveWith((states) {
          final selected = states.contains(WidgetState.selected);
          return DesignTokens.typographyMeta.copyWith(
            color: selected
                ? DesignTokens.colorAmberDeep
                : DesignTokens.colorMuted,
          );
        }),
        iconTheme: WidgetStateProperty.resolveWith((states) {
          final selected = states.contains(WidgetState.selected);
          return IconThemeData(
            color: selected
                ? DesignTokens.colorAmberDeep
                : DesignTokens.colorMuted,
          );
        }),
      ),
      cardTheme: CardThemeData(
        color: DesignTokens.colorCreamDeep,
        elevation: 0,
        margin: EdgeInsets.zero,
        shape: RoundedRectangleBorder(
          borderRadius: BorderRadius.circular(DesignTokens.radiusCard),
        ),
      ),
      inputDecorationTheme: InputDecorationTheme(
        filled: true,
        fillColor: Colors.white,
        labelStyle: DesignTokens.typographyBody
            .copyWith(color: DesignTokens.colorMuted),
        border: _inputBorder(DesignTokens.colorRule, 1),
        enabledBorder: _inputBorder(DesignTokens.colorRule, 1),
        focusedBorder: _inputBorder(DesignTokens.colorAmber, 1.5),
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

  /// ~12% amber, used as the bottom-nav selection pill.
  static const Color _amberWash = Color(0x1FB8642A);

  static OutlineInputBorder _inputBorder(Color color, double width) =>
      OutlineInputBorder(
        borderRadius: const BorderRadius.all(Radius.circular(12)),
        borderSide: BorderSide(color: color, width: width),
      );
}
