import 'package:firebase_messaging/firebase_messaging.dart';

/// Wraps FCM permission + token retrieval. Like [AuthController], nothing here
/// touches a platform channel until [requestPermissionAndToken] runs, which only
/// happens on the real-auth path after sign-in — the demo build and widget tests
/// never reach it.
class MessagingController {
  MessagingController({FirebaseMessaging? messaging})
      : _messaging = messaging ?? FirebaseMessaging.instance;

  final FirebaseMessaging _messaging;

  /// Requests notification permission (Android 13+ shows the system prompt) and
  /// returns the FCM registration token, or null if it's denied/unavailable.
  Future<String?> requestPermissionAndToken() async {
    await _messaging.requestPermission();
    return _messaging.getToken();
  }
}
