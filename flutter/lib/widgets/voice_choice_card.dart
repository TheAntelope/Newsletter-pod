import 'package:flutter/material.dart';

import '../api/models.dart';
import '../design_tokens.dart';
import 'editorial.dart';

/// Selectable voice card used in the onboarding voice step and podcast setup.
///
/// The Flutter client picks a single voice (`profile.voiceId`) rather than the
/// iOS anchor/commentator role assignment, so this is a single-select tile: tap
/// to choose, amber 2pt ring when selected. The "Hear a sample" affordance only
/// appears when an [onPreview] callback is supplied (audio preview is wired
/// later — see the UI-parity punch-list).
class VoiceChoiceCard extends StatelessWidget {
  const VoiceChoiceCard({
    super.key,
    required this.voice,
    required this.selected,
    required this.onSelect,
    this.onPreview,
    this.isPlaying = false,
  });

  final CatalogVoiceDto voice;
  final bool selected;
  final VoidCallback onSelect;
  final VoidCallback? onPreview;
  final bool isPlaying;

  @override
  Widget build(BuildContext context) {
    return EditorialCard(
      onTap: onSelect,
      borderColor: selected ? DesignTokens.colorAmber : DesignTokens.colorRule,
      borderWidth: selected ? 2 : 0.5,
      children: [
        Row(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    voice.name,
                    style: DesignTokens.typographySubtitle
                        .copyWith(color: DesignTokens.colorInk),
                  ),
                  if (voice.description.isNotEmpty) ...[
                    const SizedBox(height: 4),
                    Text(
                      voice.description,
                      style: DesignTokens.typographyCallout
                          .copyWith(color: DesignTokens.colorInkSoft),
                    ),
                  ],
                  if (onPreview != null) ...[
                    const SizedBox(height: DesignTokens.spacingS),
                    InkWell(
                      onTap: onPreview,
                      child: Row(
                        mainAxisSize: MainAxisSize.min,
                        children: [
                          Icon(
                            isPlaying
                                ? Icons.volume_up
                                : Icons.play_circle_fill,
                            size: 16,
                            color: DesignTokens.colorAmberDeep,
                          ),
                          const SizedBox(width: 4),
                          Text(
                            isPlaying ? 'Playing…' : 'Hear a sample',
                            style: DesignTokens.typographyCalloutStrong
                                .copyWith(color: DesignTokens.colorAmberDeep),
                          ),
                        ],
                      ),
                    ),
                  ],
                ],
              ),
            ),
            const SizedBox(width: DesignTokens.spacingM),
            Icon(
              selected ? Icons.check_circle : Icons.radio_button_unchecked,
              color: selected
                  ? DesignTokens.colorAmber
                  : DesignTokens.colorMuted,
            ),
          ],
        ),
      ],
    );
  }
}
