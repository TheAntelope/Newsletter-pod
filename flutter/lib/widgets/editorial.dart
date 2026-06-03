import 'package:flutter/material.dart';

import '../design_tokens.dart';

/// The editorial component kit — the Dart port of the bespoke SwiftUI views in
/// `ios/NewsletterPodApp/Theme.swift`. Screens are built on these rather than
/// raw Material `Card`/`ListTile` so the Flutter app matches the iOS app's
/// look: warm cream ground, white hairline-ruled cards, amber accent, serif
/// display type, the `LABEL` eyebrow style.

const _cardShadow = BoxShadow(
  color: Color(0x0F000000), // black @ ~6%
  blurRadius: 8,
  offset: Offset(0, 2),
);

/// White surface, hairline rule border, soft shadow, generous padding. Children
/// are laid out in a leading-aligned column with [spacing] (default 16) between
/// them — mirrors the iOS `EditorialCard` VStack.
class EditorialCard extends StatelessWidget {
  const EditorialCard({
    super.key,
    required this.children,
    this.spacing = DesignTokens.spacingM,
    this.padding = const EdgeInsets.all(DesignTokens.spacingL),
    this.onTap,
    this.borderColor,
    this.borderWidth = 0.5,
    this.crossAxisAlignment = CrossAxisAlignment.start,
  });

  final List<Widget> children;
  final double spacing;
  final EdgeInsetsGeometry padding;
  final VoidCallback? onTap;
  final Color? borderColor;
  final double borderWidth;
  final CrossAxisAlignment crossAxisAlignment;

  @override
  Widget build(BuildContext context) {
    final radius = BorderRadius.circular(DesignTokens.radiusCard);

    Widget content = Padding(
      padding: padding,
      child: Column(
        crossAxisAlignment: crossAxisAlignment,
        mainAxisSize: MainAxisSize.min,
        children: _interleave(children, spacing),
      ),
    );

    if (onTap != null) {
      content = InkWell(
        onTap: onTap,
        borderRadius: radius,
        child: content,
      );
    }

    return DecoratedBox(
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: radius,
        border: Border.all(
          color: borderColor ?? DesignTokens.colorRule,
          width: borderWidth,
        ),
        boxShadow: const [_cardShadow],
      ),
      child: ClipRRect(borderRadius: radius, child: content),
    );
  }

  static List<Widget> _interleave(List<Widget> children, double spacing) {
    if (children.length <= 1) return children;
    return [
      for (var i = 0; i < children.length; i++) ...[
        children[i],
        if (i < children.length - 1) SizedBox(height: spacing),
      ],
    ];
  }
}

/// The `LABEL` eyebrow style: uppercased, wide-tracked, amber. The only place
/// the app uppercases type.
class MetaLabel extends StatelessWidget {
  const MetaLabel(this.text, {super.key});

  final String text;

  @override
  Widget build(BuildContext context) {
    return Text(
      text.toUpperCase(),
      style: DesignTokens.typographyMeta.copyWith(
        color: DesignTokens.colorAmberDeep,
        letterSpacing: 1.4,
      ),
    );
  }
}

/// A full-width hairline rule (0.5pt) in the rule colour.
class EditorialDivider extends StatelessWidget {
  const EditorialDivider({super.key});

  @override
  Widget build(BuildContext context) {
    return const SizedBox(
      width: double.infinity,
      height: 0.5,
      child: ColoredBox(color: DesignTokens.colorRule),
    );
  }
}

/// A setup-checklist line: filled amber check when complete, struck-through
/// muted label; open circle + ink label when not.
class ChecklistRow extends StatelessWidget {
  const ChecklistRow({
    super.key,
    required this.label,
    required this.isComplete,
  });

  final String label;
  final bool isComplete;

  @override
  Widget build(BuildContext context) {
    return Row(
      children: [
        Icon(
          isComplete ? Icons.check_circle : Icons.circle_outlined,
          size: 18,
          color: isComplete ? DesignTokens.colorAmber : DesignTokens.colorMuted,
        ),
        const SizedBox(width: DesignTokens.spacingS),
        Expanded(
          child: Text(
            label,
            style: DesignTokens.typographyBody.copyWith(
              color: isComplete
                  ? DesignTokens.colorMuted
                  : DesignTokens.colorInk,
              decoration: isComplete ? TextDecoration.lineThrough : null,
              decorationColor: DesignTokens.colorMuted,
            ),
          ),
        ),
      ],
    );
  }
}

/// The amber primary/secondary action button — filled (amber fill, white text)
/// or outlined (amber 1.5pt border, amber-deep text). Full-width by default and
/// 12pt-cornered, matching iOS `AmberButtonStyle`.
class AmberButton extends StatelessWidget {
  const AmberButton.filled({
    super.key,
    required this.label,
    this.onPressed,
    this.icon,
    this.expand = true,
    this.loading = false,
  }) : _filled = true;

  const AmberButton.outlined({
    super.key,
    required this.label,
    this.onPressed,
    this.icon,
    this.expand = true,
    this.loading = false,
  }) : _filled = false;

  final String label;
  final VoidCallback? onPressed;
  final IconData? icon;
  final bool expand;
  final bool loading;
  final bool _filled;

  @override
  Widget build(BuildContext context) {
    const shape = RoundedRectangleBorder(
      borderRadius: BorderRadius.all(Radius.circular(12)),
    );
    const textStyle = TextStyle(fontSize: 16, fontWeight: FontWeight.w600);
    const padding = EdgeInsets.symmetric(vertical: 14);

    final Widget child = loading
        ? SizedBox(
            height: 20,
            width: 20,
            child: CircularProgressIndicator(
              strokeWidth: 2,
              valueColor: AlwaysStoppedAnimation<Color>(
                _filled ? Colors.white : DesignTokens.colorAmberDeep,
              ),
            ),
          )
        : (icon == null
            ? Text(label)
            : Row(
                mainAxisSize: MainAxisSize.min,
                children: [
                  Icon(icon, size: 18),
                  const SizedBox(width: 8),
                  Text(label),
                ],
              ));

    final Widget button = _filled
        ? ElevatedButton(
            onPressed: loading ? null : onPressed,
            style: ElevatedButton.styleFrom(
              backgroundColor: DesignTokens.colorAmber,
              foregroundColor: Colors.white,
              disabledBackgroundColor: DesignTokens.colorRule,
              disabledForegroundColor: DesignTokens.colorMuted,
              textStyle: textStyle,
              elevation: 0,
              padding: padding,
              shape: shape,
            ),
            child: child,
          )
        : OutlinedButton(
            onPressed: loading ? null : onPressed,
            style: OutlinedButton.styleFrom(
              foregroundColor: DesignTokens.colorAmberDeep,
              disabledForegroundColor: DesignTokens.colorMuted,
              textStyle: textStyle,
              padding: padding,
              side: const BorderSide(color: DesignTokens.colorAmber, width: 1.5),
              shape: shape,
            ),
            child: child,
          );

    return expand ? SizedBox(width: double.infinity, child: button) : button;
  }
}
