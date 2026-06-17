import 'package:flutter/material.dart';

import '../api/models.dart';
import '../design_tokens.dart';
import '../services/audio_controller.dart';
import 'editorial.dart';

/// Selectable voice card used in the onboarding voice step and podcast setup.
///
/// The Flutter client picks a single voice (`profile.voiceId`) rather than the
/// iOS anchor/commentator role assignment, so this is a single-select tile: tap
/// to choose, amber 2pt ring when selected. When [previewSource] is non-null a
/// "Hear a sample" affordance plays it through the shared [AudioController]
/// (network URL or bundled asset path).
class VoiceChoiceCard extends StatelessWidget {
  const VoiceChoiceCard({
    super.key,
    required this.voice,
    required this.selected,
    required this.onSelect,
    this.previewSource,
  });

  final CatalogVoiceDto voice;
  final bool selected;
  final VoidCallback onSelect;
  final String? previewSource;

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
                  if (previewSource != null) ...[
                    const SizedBox(height: DesignTokens.spacingS),
                    VoiceSampleButton(id: voice.id, source: previewSource!),
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

class VoiceSampleButton extends StatelessWidget {
  const VoiceSampleButton({super.key, required this.id, required this.source});

  final String id;
  final String source;

  @override
  Widget build(BuildContext context) {
    final controller = AudioController.instance;
    return ListenableBuilder(
      listenable: controller,
      builder: (context, _) {
        final playing = controller.isPlaying(id);
        return InkWell(
          onTap: () => controller.toggle(id, source),
          child: Row(
            mainAxisSize: MainAxisSize.min,
            children: [
              Icon(
                playing ? Icons.stop_circle : Icons.play_circle_fill,
                size: 16,
                color: DesignTokens.colorAmberDeep,
              ),
              const SizedBox(width: 4),
              Text(
                playing ? 'Playing…' : 'Hear a sample',
                style: DesignTokens.typographyCalloutStrong
                    .copyWith(color: DesignTokens.colorAmberDeep),
              ),
            ],
          ),
        );
      },
    );
  }
}
