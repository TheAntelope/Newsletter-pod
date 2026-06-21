import 'package:firebase_core/firebase_core.dart';
import 'package:firebase_messaging/firebase_messaging.dart';
import 'package:flutter/material.dart';

import 'api/api_client.dart';
import 'config.dart';
import 'data/fake_app_repository.dart';
import 'screens/root_view.dart';
import 'services/messaging_controller.dart';
import 'services/share_intake_controller.dart';
import 'services/share_tip_store.dart';
import 'state/app_state.dart';
import 'theme.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();

  final AppState appState;
  ShareIntakeController? shareController;
  if (FeatureFlags.googleSignIn) {
    // Real-auth build. Firebase.initializeApp() reads the config baked in by the
    // google-services Gradle plugin (google-services.json) on Android — no
    // firebase_options.dart / flutterfire configure required. The app still boots
    // on the demo repo; sign-in swaps it for ApiAppRepository (see AppState).
    await Firebase.initializeApp();
    // Register the FCM background/terminated handler before runApp so a push
    // that wakes the app from terminated has a handler. Foreground display +
    // tap routing are wired later by AppState after sign-in.
    FirebaseMessaging.onBackgroundMessage(firebaseMessagingBackgroundHandler);
    appState = AppState(
      FakeAppRepository(),
      apiClient: ApiClient(),
      // Persists the dashboard share-tip dismissal across launches. Real build
      // only — getInstance() touches a platform channel the demo/tests avoid.
      shareTipStore: await PrefsShareTipStore.load(),
    );
    // "Share to ClawCast": start listening to the OS share sheet. Real build
    // only — start() touches a platform channel, so the demo build + widget
    // tests never construct this.
    shareController = ShareIntakeController()..start();
  } else {
    // Demo build (default): in-memory data, no Firebase, no network.
    appState = AppState(FakeAppRepository());
  }

  runApp(AppScope(
    notifier: appState,
    child: ClawcastApp(shareController: shareController),
  ));
}

class ClawcastApp extends StatelessWidget {
  const ClawcastApp({super.key, this.shareController});

  /// Present only on the real-auth build; drives the share-intake screen. Null
  /// in the demo build / tests, where [ShareScope] is simply absent.
  final ShareIntakeController? shareController;

  @override
  Widget build(BuildContext context) {
    final app = MaterialApp(
      title: 'ClawCast',
      debugShowCheckedModeBanner: false,
      theme: ClawcastTheme.light(),
      home: const RootView(),
    );
    final controller = shareController;
    if (controller == null) return app;
    return ShareScope(notifier: controller, child: app);
  }
}
