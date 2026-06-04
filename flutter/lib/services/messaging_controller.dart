import 'dart:convert';
import 'dart:io' show Platform;

import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:flutter_local_notifications/flutter_local_notifications.dart';

/// Background / terminated-state message handler.
///
/// Must be a top-level (or static) function annotated with
/// `@pragma('vm:entry-point')` so it survives tree-shaking and can run in its
/// own isolate when FCM wakes the app. For "notification" messages (the only
/// kind we send) the OS draws the tray notification itself while the app is
/// backgrounded, so there's nothing to render here — the tap is handled by
/// [MessagingController.configure] via `onMessageOpenedApp` / the initial
/// message. Kept as a no-op hook so a future data-only push has a home.
@pragma('vm:entry-point')
Future<void> firebaseMessagingBackgroundHandler(RemoteMessage message) async {}

/// Wraps FCM permission + token retrieval, foreground display, and tap routing.
/// The app routes BOTH platforms through FCM (Android natively, iOS via FCM →
/// APNs), so [transport] is always `fcm`; the backend stores [platform] for
/// diagnostics and lowercases only APNs tokens.
///
/// Like [AuthController], nothing here touches a platform channel until a method
/// runs on the real-auth path after sign-in — the demo build and widget tests
/// never reach it.
class MessagingController {
  MessagingController({
    FirebaseMessaging? messaging,
    FlutterLocalNotificationsPlugin? localNotifications,
  })  : _messaging = messaging ?? FirebaseMessaging.instance,
        _local = localNotifications ?? FlutterLocalNotificationsPlugin();

  final FirebaseMessaging _messaging;
  final FlutterLocalNotificationsPlugin _local;

  /// Android channel for "your briefing is ready" pushes. Importance.high so it
  /// surfaces as a heads-up banner. Must match the channel a foreground
  /// notification is posted to (created in [configure]).
  static const AndroidNotificationChannel _channel = AndroidNotificationChannel(
    'pod_ready',
    'Briefing ready',
    description: 'Tells you when your latest briefing is ready to listen.',
    importance: Importance.high,
  );

  bool _listenersWired = false;

  /// The backend's push-transport value. The Flutter app always uses FCM.
  String get transport => 'fcm';

  /// 'ios' or 'android' — the platform string the backend persists.
  String get platform => Platform.isIOS ? 'ios' : 'android';

  /// Requests notification permission (Android 13+ shows the system prompt; iOS
  /// shows the alert prompt) and returns the FCM registration token, or null if
  /// it's denied/unavailable.
  Future<String?> requestPermissionAndToken() async {
    await _messaging.requestPermission();
    if (Platform.isIOS) {
      // On iOS the FCM token is only minted once Firebase has the APNs token.
      // It can lag the permission grant on a cold first launch, so wait briefly
      // rather than returning null and never registering.
      final apnsToken = await _messaging.getAPNSToken();
      if (apnsToken == null) {
        await Future<void>.delayed(const Duration(seconds: 2));
      }
    }
    return _messaging.getToken();
  }

  /// Wires foreground display + tap routing and creates the Android channel.
  /// Idempotent. [onOpened] fires with the message `data` map when the user
  /// taps a notification — whether tapped from the foreground, from the
  /// background, or as the tap that cold-started the app from terminated.
  Future<void> configure({
    required void Function(Map<String, dynamic> data) onOpened,
  }) async {
    if (_listenersWired) return;
    _listenersWired = true;

    const androidInit = AndroidInitializationSettings('@mipmap/ic_launcher');
    // FCM already requested the iOS permissions via requestPermission(); don't
    // double-prompt here.
    const darwinInit = DarwinInitializationSettings(
      requestAlertPermission: false,
      requestBadgePermission: false,
      requestSoundPermission: false,
    );
    await _local.initialize(
      const InitializationSettings(android: androidInit, iOS: darwinInit),
      onDidReceiveNotificationResponse: (response) {
        final payload = response.payload;
        if (payload != null && payload.isNotEmpty) {
          onOpened(_decodePayload(payload));
        }
      },
    );
    await _local
        .resolvePlatformSpecificImplementation<
            AndroidFlutterLocalNotificationsPlugin>()
        ?.createNotificationChannel(_channel);

    // iOS: surface the banner even while the app is foregrounded.
    await _messaging.setForegroundNotificationPresentationOptions(
      alert: true,
      badge: true,
      sound: true,
    );

    // Foreground: FCM does NOT draw a notification, so render one ourselves.
    FirebaseMessaging.onMessage.listen(_showForeground);
    // Tap while the app was backgrounded.
    FirebaseMessaging.onMessageOpenedApp.listen((m) => onOpened(_dataOf(m)));
    // Tap that launched the app from a terminated state.
    final initial = await _messaging.getInitialMessage();
    if (initial != null) onOpened(_dataOf(initial));
  }

  Future<void> _showForeground(RemoteMessage message) async {
    final notification = message.notification;
    if (notification == null) return; // data-only: nothing to display
    await _local.show(
      notification.hashCode,
      notification.title,
      notification.body,
      NotificationDetails(
        android: AndroidNotificationDetails(
          _channel.id,
          _channel.name,
          channelDescription: _channel.description,
          importance: Importance.high,
          priority: Priority.high,
          icon: '@mipmap/ic_launcher',
        ),
        iOS: const DarwinNotificationDetails(),
      ),
      payload: jsonEncode(message.data),
    );
  }

  Map<String, dynamic> _dataOf(RemoteMessage m) => Map<String, dynamic>.from(m.data);

  Map<String, dynamic> _decodePayload(String payload) {
    try {
      final decoded = jsonDecode(payload);
      return decoded is Map<String, dynamic> ? decoded : <String, dynamic>{};
    } catch (_) {
      return <String, dynamic>{};
    }
  }
}
