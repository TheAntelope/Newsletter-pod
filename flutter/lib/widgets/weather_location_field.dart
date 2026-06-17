import 'package:flutter/material.dart';

import '../design_tokens.dart';
import '../services/location_service.dart';

/// City text field plus a "Use my current location" affordance.
///
/// Detects the user's city with permission (coarse / city-level accuracy —
/// faster and less invasive than precise GPS) and fills the field, or surfaces
/// a denial / error inline. Typing always stays available for anyone who
/// declines. Shared by the onboarding weather step and the podcast-setup
/// weather section so both behave identically. The chosen city is written back
/// through [controller]; the parent reads `controller.text` when it saves.
class WeatherLocationField extends StatefulWidget {
  const WeatherLocationField({super.key, required this.controller});

  final TextEditingController controller;

  @override
  State<WeatherLocationField> createState() => _WeatherLocationFieldState();
}

class _WeatherLocationFieldState extends State<WeatherLocationField> {
  bool _locating = false;
  bool _locationDenied = false;
  String? _locationError;

  @override
  void initState() {
    super.initState();
    // Rebuild so the button label tracks whether a city is set as the user types.
    widget.controller.addListener(_onControllerChanged);
  }

  @override
  void dispose() {
    widget.controller.removeListener(_onControllerChanged);
    super.dispose();
  }

  void _onControllerChanged() {
    if (mounted) setState(() {});
  }

  Future<void> _resolveLocation() async {
    setState(() {
      _locating = true;
      _locationDenied = false;
      _locationError = null;
    });
    final outcome = await LocationService.resolveCurrentPlace();
    if (!mounted) return;
    setState(() {
      _locating = false;
      switch (outcome.kind) {
        case LocationOutcomeKind.resolved:
          widget.controller.text = outcome.placeName!;
        case LocationOutcomeKind.denied:
          _locationDenied = true;
        case LocationOutcomeKind.error:
          _locationError = outcome.message;
      }
    });
  }

  @override
  Widget build(BuildContext context) {
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        TextField(
          controller: widget.controller,
          decoration: const InputDecoration(
            labelText: 'City',
            hintText: 'e.g. Copenhagen',
          ),
        ),
        const SizedBox(height: DesignTokens.spacingS),
        _locationRow(),
      ],
    );
  }

  Widget _locationRow() {
    if (_locating) {
      return Row(
        children: const [
          SizedBox(
            width: 16,
            height: 16,
            child: CircularProgressIndicator(strokeWidth: 2),
          ),
          SizedBox(width: DesignTokens.spacingS),
          Text('Detecting your location…'),
        ],
      );
    }
    final hasCity = widget.controller.text.trim().isNotEmpty;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Align(
          alignment: Alignment.centerLeft,
          child: TextButton.icon(
            onPressed: _resolveLocation,
            style: TextButton.styleFrom(
              foregroundColor: DesignTokens.colorAmberDeep,
              padding: EdgeInsets.zero,
            ),
            icon: const Icon(Icons.my_location, size: 18),
            label: Text(
              hasCity ? 'Update from my location' : 'Use my current location',
            ),
          ),
        ),
        if (_locationDenied)
          Text(
            'Location access denied. Enable it in your settings, or type your '
            'city above.',
            style: DesignTokens.typographyCallout
                .copyWith(color: DesignTokens.colorMuted),
          )
        else if (_locationError != null)
          Text(
            "Couldn't fetch location: $_locationError",
            style: DesignTokens.typographyCallout
                .copyWith(color: DesignTokens.colorMuted),
          ),
      ],
    );
  }
}
