// Weekday format bridging between the app and the backend.
//
// The UI (and the fake repository) represent weekdays as 3-letter codes
// ('mon', 'tue', ...). The backend stores and schedules on the canonical full
// names ('monday', 'tuesday', ...) and rejects anything else with an
// "Invalid weekday" error. Convert at the API boundary so both sides keep their
// own representation. Both helpers are tolerant: an already-correct value (or an
// unknown one) is passed through unchanged.

const Map<String, String> _fullByCode = {
  'mon': 'monday',
  'tue': 'tuesday',
  'wed': 'wednesday',
  'thu': 'thursday',
  'fri': 'friday',
  'sat': 'saturday',
  'sun': 'sunday',
};

final Map<String, String> _codeByFull = {
  for (final e in _fullByCode.entries) e.value: e.key,
};

/// App code ('tue') -> the full name the backend expects ('tuesday').
String weekdayToApi(String day) {
  final d = day.trim().toLowerCase();
  return _fullByCode[d] ?? d;
}

/// Backend name ('tuesday') -> the 3-letter code the app uses ('tue').
String weekdayFromApi(String day) {
  final d = day.trim().toLowerCase();
  return _codeByFull[d] ?? d;
}

List<String> weekdaysToApi(Iterable<String> days) =>
    days.map(weekdayToApi).toList();

List<String> weekdaysFromApi(Iterable<String> days) =>
    days.map(weekdayFromApi).toList();
