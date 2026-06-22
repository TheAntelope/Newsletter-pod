import 'dart:convert';

import 'package:geolocator/geolocator.dart';
import 'package:http/http.dart' as http;

/// A geocoded place the user can pick for the optional weather feature.
///
/// Carries the coordinates resolved at pick-time so the backend forecasts the
/// exact city the user chose, rather than re-geocoding the ambiguous display
/// string server-side (where e.g. "Springfield" resolves to the most-populous
/// match — Missouri — instead of the picked New Jersey one). [countryCode]
/// drives the backend's °F/°C choice.
class PlaceSuggestion {
  const PlaceSuggestion({
    required this.name,
    required this.latitude,
    required this.longitude,
    this.admin1,
    this.country,
    this.countryCode,
  });

  /// City/town name, e.g. "Springfield".
  final String name;
  final double latitude;
  final double longitude;

  /// First-level admin region, e.g. "New Jersey" (when the geocoder supplies it).
  final String? admin1;

  /// Country name, e.g. "United States".
  final String? country;

  /// ISO country code, e.g. "US".
  final String? countryCode;

  /// The region line shown under the city name in the picker
  /// ("New Jersey, United States"). Empty when neither is known.
  String get region => [admin1, country]
      .whereType<String>()
      .where((s) => s.isNotEmpty)
      .join(', ');

  /// The concise label saved as `weatherLocation` and shown back in the field.
  /// US city names repeat across states, so qualify those with the state;
  /// elsewhere the country reads more naturally ("Copenhagen, Denmark").
  String get label {
    final qualifier = (countryCode == 'US' && (admin1?.isNotEmpty ?? false))
        ? admin1
        : country;
    return (qualifier != null && qualifier.isNotEmpty)
        ? '$name, $qualifier'
        : name;
  }
}

/// Why the "use my current location" attempt ended: a usable place, the user
/// declining the permission, or a failure (services off, no fix, geocode failed).
enum LocationOutcomeKind { resolved, denied, error }

class LocationOutcome {
  const LocationOutcome.resolved(PlaceSuggestion this.place)
      : kind = LocationOutcomeKind.resolved,
        message = null;
  const LocationOutcome.denied()
      : kind = LocationOutcomeKind.denied,
        place = null,
        message = null;
  const LocationOutcome.error(String this.message)
      : kind = LocationOutcomeKind.error,
        place = null;

  final LocationOutcomeKind kind;

  /// The resolved place (with coordinates) when [kind] is resolved.
  final PlaceSuggestion? place;

  /// Human-readable failure reason when [kind] is error.
  final String? message;
}

/// Resolves places for the optional weather feature: a type-ahead [searchPlaces]
/// against the same Open-Meteo geocoder the backend uses (so any pick is
/// guaranteed to resolve server-side), plus [resolveCurrentPlace] for the
/// "use my location" affordance. Mirrors the iOS LocationResolver.
class LocationService {
  static const _geocodeHost = 'geocoding-api.open-meteo.com';

  /// Forward-geocode a partial [query] to a ranked list of [PlaceSuggestion]s
  /// for the autocomplete dropdown. Returns an empty list for short queries and
  /// on any error — never throws.
  static Future<List<PlaceSuggestion>> searchPlaces(
    String query, {
    http.Client? client,
    int count = 6,
  }) async {
    final trimmed = query.trim();
    // Open-Meteo needs ≥2 chars to return anything useful, and querying on a
    // single keystroke just wastes requests.
    if (trimmed.length < 2) return const [];

    final c = client ?? http.Client();
    try {
      final uri = Uri.https(_geocodeHost, '/v1/search', {
        'name': trimmed,
        'count': '$count',
        'language': 'en',
        'format': 'json',
      });
      final resp =
          await c.get(uri).timeout(const Duration(seconds: 6));
      if (resp.statusCode != 200) return const [];
      final body = jsonDecode(resp.body) as Map<String, dynamic>;
      final results = (body['results'] as List?) ?? const [];
      return results
          .whereType<Map<String, dynamic>>()
          .map(_suggestionFromJson)
          .whereType<PlaceSuggestion>()
          .toList();
    } catch (_) {
      return const [];
    } finally {
      if (client == null) c.close();
    }
  }

  static PlaceSuggestion? _suggestionFromJson(Map<String, dynamic> j) {
    final name = j['name'] as String?;
    final lat = (j['latitude'] as num?)?.toDouble();
    final lon = (j['longitude'] as num?)?.toDouble();
    if (name == null || name.isEmpty || lat == null || lon == null) return null;
    return PlaceSuggestion(
      name: name,
      latitude: lat,
      longitude: lon,
      admin1: j['admin1'] as String?,
      country: j['country'] as String?,
      countryCode: (j['country_code'] as String?)?.toUpperCase(),
    );
  }

  /// Request permission (prompting on first use), read a coarse fix, and reverse
  /// geocode it to a [PlaceSuggestion] (the GPS coordinates plus a place name).
  /// Never throws — failures come back as a [LocationOutcome].
  static Future<LocationOutcome> resolveCurrentPlace({http.Client? client}) async {
    try {
      if (!await Geolocator.isLocationServiceEnabled()) {
        return const LocationOutcome.error('Location services are turned off');
      }
      var permission = await Geolocator.checkPermission();
      if (permission == LocationPermission.denied) {
        permission = await Geolocator.requestPermission();
      }
      if (permission == LocationPermission.denied ||
          permission == LocationPermission.deniedForever) {
        return const LocationOutcome.denied();
      }
      // City-level accuracy is plenty for weather and faster/less invasive.
      final position = await Geolocator.getCurrentPosition(
        locationSettings: const LocationSettings(accuracy: LocationAccuracy.low),
      );
      final place = await _reverseGeocode(
        position.latitude,
        position.longitude,
        client,
      );
      if (place == null) {
        return const LocationOutcome.error("Couldn't read place name");
      }
      return LocationOutcome.resolved(place);
    } catch (e) {
      return LocationOutcome.error(e.toString());
    }
  }

  /// Reverse geocode via OpenStreetMap Nominatim (the platform `geocoding`
  /// plugin has no web support, and the live preview runs on web). The returned
  /// [PlaceSuggestion] keeps the GPS [lat]/[lon] — those, not Nominatim's
  /// centroid, are what we forecast from.
  static Future<PlaceSuggestion?> _reverseGeocode(
    double lat,
    double lon,
    http.Client? client,
  ) async {
    final c = client ?? http.Client();
    try {
      final uri = Uri.https('nominatim.openstreetmap.org', '/reverse', {
        'format': 'jsonv2',
        'lat': lat.toString(),
        'lon': lon.toString(),
        'zoom': '10', // city-level
        'addressdetails': '1',
      });
      final resp = await c.get(uri, headers: {
        // Nominatim's usage policy requires an identifying User-Agent.
        'User-Agent': 'ClawCast/1.0 (https://theclawcast.com)',
        'Accept': 'application/json',
      });
      if (resp.statusCode != 200) return null;
      final body = jsonDecode(resp.body) as Map<String, dynamic>;
      final address = body['address'] as Map<String, dynamic>?;
      if (address == null) return null;
      // Prefer the most specific populated place, falling back outward for
      // rural areas where there's no city/town.
      final locality = (address['city'] ??
          address['town'] ??
          address['village'] ??
          address['municipality'] ??
          address['county'] ??
          address['state']) as String?;
      if (locality == null || locality.isEmpty) return null;
      final cc = (address['country_code'] as String?)?.toUpperCase();
      return PlaceSuggestion(
        name: locality,
        latitude: lat,
        longitude: lon,
        admin1: address['state'] as String?,
        country: address['country'] as String?,
        countryCode: cc,
      );
    } catch (_) {
      return null;
    } finally {
      if (client == null) c.close();
    }
  }
}
