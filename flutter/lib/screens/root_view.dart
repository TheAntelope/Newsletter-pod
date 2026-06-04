import 'package:flutter/material.dart';

import '../services/podcast_addict.dart';
import '../services/share_intake_controller.dart';
import '../state/app_state.dart';
import 'dashboard_scaffold.dart';
import 'onboarding_screen.dart';
import 'share_intake_screen.dart';
import 'sign_in_screen.dart';

/// Top-level router: sign-in → onboarding (new sign-in) → tabbed dashboard.
/// Rebuilds automatically when [AppState] notifies (via [AppScope]).
///
/// Also observes app lifecycle so that, after we bounce the user to the Play
/// Store to install Podcast Addict, the pending feed is added automatically the
/// moment they return to ClawCast (see [PodcastAddict.retryPendingOnResume]).
class RootView extends StatefulWidget {
  const RootView({super.key});

  @override
  State<RootView> createState() => _RootViewState();
}

class _RootViewState extends State<RootView> with WidgetsBindingObserver {
  @override
  void initState() {
    super.initState();
    WidgetsBinding.instance.addObserver(this);
  }

  @override
  void dispose() {
    WidgetsBinding.instance.removeObserver(this);
    super.dispose();
  }

  @override
  void didChangeAppLifecycleState(AppLifecycleState state) {
    if (state == AppLifecycleState.resumed) {
      PodcastAddict.retryPendingOnResume();
    }
  }

  @override
  Widget build(BuildContext context) {
    final app = AppScope.of(context);
    if (!app.signedIn) return const SignInScreen();
    if (!app.onboardingComplete) return const OnboardingScreen();
    // A share waits behind sign-in/onboarding: once the user is in, surface the
    // "Send to ClawCast" confirmation full-screen, then drop back to the
    // dashboard. ShareScope is absent in the demo build, so [share] is null.
    final share = ShareScope.maybeOf(context);
    if (share != null && share.hasPending) {
      return ShareIntakeScreen(shares: share.pending, onDone: share.clear);
    }
    return const DashboardScaffold();
  }
}
