import 'package:firebase_core/firebase_core.dart';
import 'package:flutter/material.dart';

import 'api/api_client.dart';
import 'config.dart';
import 'data/fake_app_repository.dart';
import 'screens/root_view.dart';
import 'state/app_state.dart';
import 'theme.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();

  final AppState appState;
  if (FeatureFlags.googleSignIn) {
    // Real-auth build. Firebase.initializeApp() reads the config baked in by the
    // google-services Gradle plugin (google-services.json) on Android — no
    // firebase_options.dart / flutterfire configure required. The app still boots
    // on the demo repo; sign-in swaps it for ApiAppRepository (see AppState).
    await Firebase.initializeApp();
    appState = AppState(FakeAppRepository(), apiClient: ApiClient());
  } else {
    // Demo build (default): in-memory data, no Firebase, no network.
    appState = AppState(FakeAppRepository());
  }

  runApp(AppScope(notifier: appState, child: const ClawcastApp()));
}

class ClawcastApp extends StatelessWidget {
  const ClawcastApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'ClawCast',
      debugShowCheckedModeBanner: false,
      theme: ClawcastTheme.light(),
      home: const RootView(),
    );
  }
}
