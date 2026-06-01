import 'package:flutter/material.dart';

import '../state/app_state.dart';
import 'home_screen.dart';
import 'sign_in_screen.dart';

/// Top-level router: signed-in → dashboard, otherwise the sign-in screen.
/// Rebuilds automatically when [AppState] notifies (via [AppScope]).
class RootView extends StatelessWidget {
  const RootView({super.key});

  @override
  Widget build(BuildContext context) {
    final app = AppScope.of(context);
    return app.signedIn ? const HomeScreen() : const SignInScreen();
  }
}
