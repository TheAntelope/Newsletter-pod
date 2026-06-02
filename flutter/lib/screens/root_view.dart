import 'package:flutter/material.dart';

import '../state/app_state.dart';
import 'dashboard_scaffold.dart';
import 'onboarding_screen.dart';
import 'sign_in_screen.dart';

/// Top-level router: sign-in → onboarding (new sign-in) → tabbed dashboard.
/// Rebuilds automatically when [AppState] notifies (via [AppScope]).
class RootView extends StatelessWidget {
  const RootView({super.key});

  @override
  Widget build(BuildContext context) {
    final app = AppScope.of(context);
    if (!app.signedIn) return const SignInScreen();
    if (!app.onboardingComplete) return const OnboardingScreen();
    return const DashboardScaffold();
  }
}
