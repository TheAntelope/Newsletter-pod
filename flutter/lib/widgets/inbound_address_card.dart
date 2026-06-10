import 'package:flutter/material.dart';
import 'package:flutter/services.dart';

import '../design_tokens.dart';
import 'editorial.dart';

/// Displays the user's private inbound email address and makes it effortless to
/// copy. There are three overlapping affordances so copying never feels fiddly:
/// the whole address chip is a tap target, there's an explicit full-width copy
/// button, and the raw text stays selectable for a manual long-press copy. Both
/// the chip and the button confirm with an inline check and a snackbar.
///
/// Shared by onboarding and the source-setup screens so the affordance is
/// identical everywhere we hand the user their address.
class InboundAddressCard extends StatefulWidget {
  const InboundAddressCard({
    super.key,
    required this.address,
    this.title = 'Your private inbound address',
    this.description =
        'Forward newsletters here, or use this address when you subscribe to '
        'new ones. The next episode picks them up automatically.',
  });

  final String address;
  final String title;
  final String description;

  @override
  State<InboundAddressCard> createState() => _InboundAddressCardState();
}

class _InboundAddressCardState extends State<InboundAddressCard> {
  bool _copied = false;

  Future<void> _copy() async {
    final messenger = ScaffoldMessenger.of(context);
    await Clipboard.setData(ClipboardData(text: widget.address));
    if (!mounted) return;
    setState(() => _copied = true);
    messenger
      ..hideCurrentSnackBar()
      ..showSnackBar(
        const SnackBar(content: Text('Email address copied')),
      );
  }

  @override
  Widget build(BuildContext context) {
    return EditorialCard(
      spacing: DesignTokens.spacingS,
      children: [
        MetaLabel(widget.title),
        // The whole chip is tappable to copy — the easiest possible target —
        // while the text inside stays selectable for a manual long-press copy.
        InkWell(
          onTap: _copy,
          borderRadius: BorderRadius.circular(12),
          child: Container(
            width: double.infinity,
            padding: const EdgeInsets.all(DesignTokens.spacingM),
            decoration: BoxDecoration(
              color: DesignTokens.colorCream,
              borderRadius: BorderRadius.circular(12),
              border: Border.all(color: DesignTokens.colorAmber),
            ),
            child: Row(
              children: [
                Expanded(
                  child: SelectableText(
                    widget.address,
                    style: DesignTokens.typographyTitle
                        .copyWith(color: DesignTokens.colorAmberDeep),
                  ),
                ),
                const SizedBox(width: DesignTokens.spacingS),
                Icon(
                  _copied ? Icons.check : Icons.copy,
                  size: 20,
                  color: DesignTokens.colorAmberDeep,
                ),
              ],
            ),
          ),
        ),
        Align(
          alignment: Alignment.centerLeft,
          child: AmberButton.filled(
            label: _copied ? 'Copied' : 'Copy email address',
            icon: _copied ? Icons.check : Icons.copy,
            expand: false,
            onPressed: _copy,
          ),
        ),
        Text(
          widget.description,
          style: DesignTokens.typographyCallout
              .copyWith(color: DesignTokens.colorInkSoft),
        ),
      ],
    );
  }
}
