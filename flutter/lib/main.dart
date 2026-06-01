import 'package:flutter/material.dart';

import 'data/fake_app_repository.dart';
import 'screens/root_view.dart';
import 'state/app_state.dart';
import 'theme.dart';

void main() {
  // Stub data layer until Firebase auth + the external accounts exist. Swap
  // FakeAppRepository for ApiAppRepository(ApiClient(), token) once sign-in
  // returns a real session.
  final appState = AppState(FakeAppRepository());
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
