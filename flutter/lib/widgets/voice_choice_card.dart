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
                    _SampleButton(id: voice.id, source: previewSource!),
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

/// One podcaster slot in the podcast-setup "Voice cast" section: a role eyebrow
/// ("Host" / "Co-host" / "Narrator"), the podcaster's display name, a drop-down
/// of the voice catalog, and a play/pause sample of the currently-selected
/// voice. Mirrors the iOS `voiceRow`, which renders one of these per host so a
/// `two_hosts` show shows exactly two cards.
///
/// [displayName] is owned by the caller: it's the name typed into the Show
/// section's host field, falling back to the chosen voice's own name. That's how
/// renaming a host there flows through to the podcaster shown here.
class HostVoiceCard extends StatelessWidget {
  const HostVoiceCard({
    super.key,
    required this.roleLabel,
    required this.displayName,
    required this.voices,
    required this.selectedVoiceId,
    required this.onSelect,
    this.excludeVoiceId,
  });

  final String roleLabel;
  final String displayName;
  final List<CatalogVoiceDto> voices;
  final String? selectedVoiceId;
  final ValueChanged<String> onSelect;

  /// The other host's voice, hidden from this drop-down so two hosts can't share
  /// a single voice (matches the iOS "already chosen" exclusion).
  final String? excludeVoiceId;

  @override
  Widget build(BuildContext context) {
    CatalogVoiceDto? selectedVoice;
    for (final v in voices) {
      if (v.id == selectedVoiceId) {
        selectedVoice = v;
        break;
      }
    }
    final items = [
      for (final v in voices)
        if (v.id != excludeVoiceId || v.id == selectedVoiceId) v,
    ];
    // Guard against a stale/unknown voice id so DropdownButton's value always
    // matches one of its items (or null → shows the hint).
    final value = selectedVoice == null ? null : selectedVoiceId;
    final preview = selectedVoice?.previewUrl;

    return EditorialCard(
      spacing: DesignTokens.spacingS,
      children: [
        MetaLabel(roleLabel),
        Text(
          displayName,
          style: DesignTokens.typographySubtitle
              .copyWith(color: DesignTokens.colorInk),
        ),
        Container(
          padding:
              const EdgeInsets.symmetric(horizontal: DesignTokens.spacingM),
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(DesignTokens.radiusCard),
            border: Border.all(color: DesignTokens.colorRule, width: 1),
          ),
          child: DropdownButtonHideUnderline(
            child: DropdownButton<String>(
              isExpanded: true,
              value: value,
              hint: Text(
                'Choose a voice',
                style: DesignTokens.typographyBody
                    .copyWith(color: DesignTokens.colorMuted),
              ),
              icon: const Icon(Icons.expand_more,
                  color: DesignTokens.colorAmberDeep),
              style: DesignTokens.typographyBody
                  .copyWith(color: DesignTokens.colorInk),
              items: [
                for (final v in items)
                  DropdownMenuItem<String>(value: v.id, child: Text(v.name)),
              ],
              onChanged: (id) {
                if (id != null) onSelect(id);
              },
            ),
          ),
        ),
        if (selectedVoice != null && selectedVoice.description.isNotEmpty)
          Text(
            selectedVoice.description,
            style: DesignTokens.typographyCallout
                .copyWith(color: DesignTokens.colorInkSoft),
          ),
        if (selectedVoice != null && preview != null && preview.isNotEmpty)
          _SampleButton(id: selectedVoice.id, source: preview),
      ],
    );
  }
}

class _SampleButton extends StatelessWidget {
  const _SampleButton({required this.id, required this.source});

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
