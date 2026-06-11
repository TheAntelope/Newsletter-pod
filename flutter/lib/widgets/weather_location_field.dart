import 'dart:async';

import 'package:flutter/material.dart';

import '../design_tokens.dart';
import '../services/location_service.dart';
import 'editorial.dart';

/// The city field for the optional weather feature: a type-ahead dropdown backed
/// by the same Open-Meteo geocoder the backend uses, plus a "use my current
/// location" affordance.
///
/// Picking a suggestion (or resolving via GPS) records the place's coordinates
/// and shows a ✓ confirmation — so the saved value is one the backend forecasts
/// exactly, instead of re-geocoding the ambiguous display string (where
/// "Springfield" resolves to the most-populous match rather than the one the
/// user picked). See [PlaceSuggestion].
///
/// The widget owns no persistence: it reports every change up through
/// [onChanged] as (label, lat, lon, countryCode); the parent saves them.
class WeatherLocationField extends StatefulWidget {
  const WeatherLocationField({
    super.key,
    this.initialLabel,
    this.initialLatitude,
    this.initialLongitude,
    required this.onChanged,
  });

  final String? initialLabel;
  final double? initialLatitude;
  final double? initialLongitude;

  /// Fired whenever the value changes. Coordinates are null when the text is
  /// free-typed or empty (not a confirmed pick); the backend then clears any
  /// stale coordinates so it never pairs a new city with old coordinates.
  final void Function(
    String? label,
    double? latitude,
    double? longitude,
    String? countryCode,
  ) onChanged;

  @override
  State<WeatherLocationField> createState() => _WeatherLocationFieldState();
}

class _WeatherLocationFieldState extends State<WeatherLocationField> {
  late final TextEditingController _controller;
  final _focusNode = FocusNode();
  Timer? _debounce;

  List<PlaceSuggestion> _suggestions = const [];
  bool _searching = false;
  String? _noResultsFor; // the exact query a search returned nothing for

  bool _locating = false;
  bool _locationDenied = false;
  String? _locationError;

  // Set once the user picks a suggestion / resolves GPS; cleared on free edit.
  // Drives the ✓ confirmation; the picked country code is reported straight
  // through [onChanged], so it needs no separate field here.
  double? _lat;
  double? _lon;

  bool get _confirmed => _lat != null && _lon != null;

  @override
  void initState() {
    super.initState();
    _controller = TextEditingController(text: widget.initialLabel ?? '');
    _lat = widget.initialLatitude;
    _lon = widget.initialLongitude;
  }

  @override
  void dispose() {
    _debounce?.cancel();
    _controller.dispose();
    _focusNode.dispose();
    super.dispose();
  }

  void _onTextChanged(String value) {
    // Any manual edit invalidates a prior confirmed pick: the text no longer
    // matches known coordinates, so drop them (the backend will too).
    _lat = null;
    _lon = null;
    final trimmed = value.trim();
    widget.onChanged(trimmed.isEmpty ? null : trimmed, null, null, null);
    _debounce?.cancel();
    _noResultsFor = null;
    _locationDenied = false;
    _locationError = null;
    if (trimmed.length < 2) {
      setState(() {
        _suggestions = const [];
        _searching = false;
      });
      return;
    }
    setState(() => _searching = true);
    _debounce =
        Timer(const Duration(milliseconds: 350), () => _runSearch(trimmed));
  }

  Future<void> _runSearch(String query) async {
    final results = await LocationService.searchPlaces(query);
    // Ignore a stale response if the user kept typing.
    if (!mounted || _controller.text.trim() != query) return;
    setState(() {
      _suggestions = results;
      _searching = false;
      _noResultsFor = results.isEmpty ? query : null;
    });
  }

  void _pick(PlaceSuggestion s) {
    _controller.text = s.label;
    _controller.selection = TextSelection.collapsed(offset: s.label.length);
    _focusNode.unfocus();
    setState(() {
      _lat = s.latitude;
      _lon = s.longitude;
      _suggestions = const [];
      _searching = false;
      _noResultsFor = null;
    });
    widget.onChanged(s.label, s.latitude, s.longitude, s.countryCode);
  }

  void _clear() {
    _controller.clear();
    _onTextChanged('');
  }

  void _dismissSuggestions() {
    if (_suggestions.isEmpty && _noResultsFor == null) return;
    setState(() {
      _suggestions = const [];
      _noResultsFor = null;
    });
  }

  Future<void> _resolveLocation() async {
    setState(() {
      _locating = true;
      _locationDenied = false;
      _locationError = null;
      _suggestions = const [];
      _noResultsFor = null;
    });
    final outcome = await LocationService.resolveCurrentPlace();
    if (!mounted) return;
    setState(() => _locating = false);
    switch (outcome.kind) {
      case LocationOutcomeKind.resolved:
        _pick(outcome.place!);
      case LocationOutcomeKind.denied:
        setState(() => _locationDenied = true);
      case LocationOutcomeKind.error:
        setState(() => _locationError = outcome.message);
    }
  }

  @override
  Widget build(BuildContext context) {
    final query = _controller.text.trim();
    // TapRegion dismisses the dropdown on an outside tap without racing the
    // suggestion taps (which live inside the region) — avoids the focus-loss
    // race that drops the list before onTap fires.
    return TapRegion(
      onTapOutside: (_) => _dismissSuggestions(),
      child: Column(
        crossAxisAlignment: CrossAxisAlignment.start,
        children: [
          TextField(
            controller: _controller,
            focusNode: _focusNode,
            textInputAction: TextInputAction.search,
            onChanged: _onTextChanged,
            decoration: InputDecoration(
              labelText: 'City',
              hintText: 'e.g. Copenhagen',
              suffixIcon: _suffixIcon(),
            ),
          ),
          if (_suggestions.isNotEmpty) _suggestionsPanel(),
          if (_suggestions.isEmpty &&
              !_searching &&
              _noResultsFor != null &&
              _noResultsFor == query)
            Padding(
              padding: const EdgeInsets.only(top: DesignTokens.spacingS),
              child: Text(
                'No matching cities — keep typing, or use your location below.',
                style: DesignTokens.typographyCallout
                    .copyWith(color: DesignTokens.colorMuted),
              ),
            ),
          const SizedBox(height: DesignTokens.spacingS),
          _statusRow(),
        ],
      ),
    );
  }

  Widget? _suffixIcon() {
    if (_searching) {
      return const Padding(
        padding: EdgeInsets.all(12),
        child: SizedBox(
          width: 16,
          height: 16,
          child: CircularProgressIndicator(strokeWidth: 2),
        ),
      );
    }
    if (_controller.text.isNotEmpty) {
      return IconButton(
        icon: const Icon(Icons.clear, size: 18),
        tooltip: 'Clear',
        onPressed: _clear,
      );
    }
    return null;
  }

  Widget _suggestionsPanel() {
    return Container(
      margin: const EdgeInsets.only(top: DesignTokens.spacingS),
      decoration: BoxDecoration(
        color: Colors.white,
        borderRadius: BorderRadius.circular(DesignTokens.radiusCard),
        border: Border.all(color: DesignTokens.colorRule, width: 0.5),
      ),
      clipBehavior: Clip.antiAlias,
      child: Material(
        color: Colors.transparent,
        child: Column(
          mainAxisSize: MainAxisSize.min,
          children: [
            for (var i = 0; i < _suggestions.length; i++) ...[
              if (i > 0) const EditorialDivider(),
              _suggestionTile(_suggestions[i]),
            ],
          ],
        ),
      ),
    );
  }

  Widget _suggestionTile(PlaceSuggestion s) {
    return InkWell(
      onTap: () => _pick(s),
      child: Padding(
        padding: const EdgeInsets.symmetric(
          horizontal: DesignTokens.spacingM,
          vertical: DesignTokens.spacingS + 2,
        ),
        child: Row(
          children: [
            const Icon(Icons.place_outlined,
                size: 18, color: DesignTokens.colorMuted),
            const SizedBox(width: DesignTokens.spacingS),
            Expanded(
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.start,
                children: [
                  Text(
                    s.name,
                    style: DesignTokens.typographyBodyStrong
                        .copyWith(color: DesignTokens.colorInk),
                  ),
                  if (s.region.isNotEmpty)
                    Text(
                      s.region,
                      style: DesignTokens.typographyCallout
                          .copyWith(color: DesignTokens.colorMuted),
                    ),
                ],
              ),
            ),
          ],
        ),
      ),
    );
  }

  Widget _statusRow() {
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
    final hasText = _controller.text.trim().isNotEmpty;
    return Column(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        if (_confirmed) ...[
          Row(
            children: [
              const Icon(Icons.check_circle,
                  size: 18, color: DesignTokens.colorAmber),
              const SizedBox(width: DesignTokens.spacingS),
              Expanded(
                child: Text(
                  'Location confirmed — your pods will use this spot’s weather.',
                  style: DesignTokens.typographyCallout
                      .copyWith(color: DesignTokens.colorInkSoft),
                ),
              ),
            ],
          ),
          const SizedBox(height: DesignTokens.spacingXs),
        ],
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
              hasText ? 'Update from my location' : 'Use my current location',
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
