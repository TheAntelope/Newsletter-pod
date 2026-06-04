import 'dart:convert';

import 'package:geolocator/geolocator.dart';
import 'package:http/http.dart' as http;

/// Why the resolve attempt ended: a usable place name, the user declining the
/// permission, or a failure (services off, no fix, geocode failed).
enum LocationOutcomeKind { resolved, denied, error }

class LocationOutcome {
  const LocationOutcome.resolved(String this.placeName)
      : kind = LocationOutcomeKind.resolved,
        message = null;
  const LocationOutcome.denied()
      : kind = LocationOutcomeKind.denied,
        placeName = null,
        message = null;
  const LocationOutcome.error(String this.message)
      : kind = LocationOutcomeKind.error,
        placeName = null;

  final LocationOutcomeKind kind;

  /// "City, Country" when [kind] is resolved.
  final String? placeName;

  /// Human-readable failure reason when [kind] is error.
  final String? message;
}

/// Resolves the device's current location to a "City, Country" label for the
/// optional weather feature. GPS is read via geolocator (web + Android + iOS);
/// reverse geocoding is an HTTP call to OpenStreetMap Nominatim so it behaves
/// the same on every platform — the platform `geocoding` plugin has no web
/// support, and the live preview runs on web. Mirrors the iOS LocationResolver.
class LocationService {
  /// Request permission (prompting on first use), read a coarse fix, and reverse
  /// geocode it. Never throws — failures come back as a [LocationOutcome].
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
      final name = await _reverseGeocode(
        position.latitude,
        position.longitude,
        client,
      );
      if (name == null || name.isEmpty) {
        return const LocationOutcome.error("Couldn't read place name");
      }
      return LocationOutcome.resolved(name);
    } catch (e) {
      return LocationOutcome.error(e.toString());
    }
  }

  static Future<String?> _reverseGeocode(
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
      final country = address['country'] as String?;
      final parts = [locality, country]
          .whereType<String>()
          .where((s) => s.isNotEmpty)
          .toList();
      return parts.join(', ');
    } finally {
      if (client == null) c.close();
    }
  }
}
