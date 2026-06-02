import 'package:flutter/foundation.dart';
import 'package:speech_to_text/speech_to_text.dart';

/// Thin wrapper over `speech_to_text` for the dictate-to-text affordances.
///
/// Initialization (which touches the platform/permission channel) is deferred to
/// the first [start] call, so simply building a widget that holds a controller
/// is safe in headless tests. Where speech recognition isn't available (e.g. a
/// browser without the Web Speech API, or denied permission) [available] stays
/// false and callers degrade to plain text entry.
class DictationController extends ChangeNotifier {
  final SpeechToText _speech = SpeechToText();

  bool _initialized = false;
  bool _available = false;
  bool _listening = false;
  String _transcript = '';
  String? _error;

  bool get available => _available;
  bool get listening => _listening;
  String get transcript => _transcript;
  String? get error => _error;

  Future<bool> _ensureInit() async {
    if (_initialized) return _available;
    _initialized = true;
    try {
      _available = await _speech.initialize(
        onStatus: (status) {
          final stopped = status == 'done' || status == 'notListening';
          if (stopped && _listening) {
            _listening = false;
            notifyListeners();
          }
        },
        onError: (err) {
          _error = err.errorMsg;
          _listening = false;
          notifyListeners();
        },
      );
    } catch (_) {
      _available = false;
    }
    notifyListeners();
    return _available;
  }

  /// Begin a fresh dictation. Returns false if recognition isn't available.
  Future<bool> start() async {
    if (!await _ensureInit()) return false;
    _error = null;
    _transcript = '';
    _listening = true;
    notifyListeners();
    await _speech.listen(
      onResult: (result) {
        _transcript = result.recognizedWords;
        notifyListeners();
      },
    );
    return true;
  }

  Future<void> stop() async {
    if (!_listening) return;
    await _speech.stop();
    _listening = false;
    notifyListeners();
  }

  @override
  void dispose() {
    if (_listening) _speech.stop();
    super.dispose();
  }
}
