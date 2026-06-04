import 'package:firebase_auth/firebase_auth.dart';
import 'package:flutter/material.dart';

import '../api/api_client.dart' show ApiException;
import '../config.dart';
import '../design_tokens.dart';
import '../services/auth_controller.dart';
import '../state/app_state.dart';
import '../widgets/editorial.dart';

/// Editorial sign-in hero.
///
/// Two paths, chosen by [FeatureFlags.googleSignIn]:
/// - **off (default / demo / tests):** "Get started" calls the stubbed
///   `AppState.signIn()` and runs on the in-memory FakeAppRepository.
/// - **on:** "Continue with Google" runs the real Google→Firebase flow, exchanges
///   the Firebase ID token at `/v1/auth/firebase`, and swaps in `ApiAppRepository`.
class SignInScreen extends StatefulWidget {
  const SignInScreen({super.key});

  @override
  State<SignInScreen> createState() => _SignInScreenState();
}

class _SignInScreenState extends State<SignInScreen> {
  static const _valueProps = [
    ('newspaper', 'From the sources you choose', Icons.newspaper_outlined),
    ('voice', 'Read in a voice you pick', Icons.graphic_eq),
    ('clock', 'Ready every morning', Icons.schedule_outlined),
  ];

  bool _busy = false;

  Future<void> _onGetStarted(AppState app) async {
    if (!FeatureFlags.googleSignIn) {
      await app.signIn(); // demo stub path
      return;
    }
    setState(() => _busy = true);
    final messenger = ScaffoldMessenger.of(context);
    try {
      final result = await AuthController().signInWithGoogle();
      await app.signInWithFirebaseToken(
        result.idToken,
        displayName: result.displayName,
      );
      // Routing reacts to app.signedIn via AppScope — no navigation here.
    } on SignInCancelled {
      // User dismissed the Google picker — quietly stand down.
    } catch (e) {
      messenger.showSnackBar(SnackBar(content: Text(_signInError(e))));
    } finally {
      if (mounted) setState(() => _busy = false);
    }
  }

  /// A safe, user-facing message. Never interpolates a raw exception (a
  /// third-party plugin's toString() could carry sensitive data); maps known
  /// types to controlled strings and falls back to a generic message.
  String _signInError(Object e) {
    if (e is FirebaseAuthException) return 'Sign-in failed (${e.code}).';
    if (e is ApiException) return 'Sign-in failed: ${e.message}';
    return 'Sign-in failed. Please try again.';
  }

  @override
  Widget build(BuildContext context) {
    final app = AppScope.of(context);
    final realAuth = FeatureFlags.googleSignIn;

    return Scaffold(
      body: SafeArea(
        child: LayoutBuilder(
          builder: (context, constraints) => SingleChildScrollView(
            padding: const EdgeInsets.all(DesignTokens.spacingL),
            child: ConstrainedBox(
              constraints: BoxConstraints(
                minHeight: constraints.maxHeight - DesignTokens.spacingL * 2,
              ),
              child: IntrinsicHeight(
                child: Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const SizedBox(height: DesignTokens.spacingXl),
                    const MetaLabel('Your daily briefing'),
                    const SizedBox(height: DesignTokens.spacingS),
                    Text(
                      'ClawCast',
                      style: DesignTokens.typographyDisplay
                          .copyWith(fontSize: 44, color: DesignTokens.colorInk),
                    ),
                    const SizedBox(height: DesignTokens.spacingS),
                    Text(
                      'A customised podcast, generated each morning from the '
                      'newsletters and sources you care about.',
                      style: DesignTokens.typographySubtitle
                          .copyWith(color: DesignTokens.colorInkSoft),
                    ),
                    const SizedBox(height: DesignTokens.spacingL),
                    EditorialCard(
                      spacing: DesignTokens.spacingM,
                      children: [
                        for (final prop in _valueProps)
                          Row(
                            children: [
                              Icon(prop.$3,
                                  size: 20,
                                  color: DesignTokens.colorAmberDeep),
                              const SizedBox(width: DesignTokens.spacingM),
                              Expanded(
                                child: Text(
                                  prop.$2,
                                  style: DesignTokens.typographyBody
                                      .copyWith(color: DesignTokens.colorInk),
                                ),
                              ),
                            ],
                          ),
                      ],
                    ),
                    const Spacer(),
                    const SizedBox(height: DesignTokens.spacingL),
                    AmberButton.filled(
                      label: _busy
                          ? 'Signing in…'
                          : (realAuth ? 'Continue with Google' : 'Get started'),
                      onPressed: () {
                        if (_busy) return;
                        _onGetStarted(app);
                      },
                    ),
                    const SizedBox(height: DesignTokens.spacingM),
                    if (!realAuth)
                      Text(
                        'Sign-in is stubbed in this build — Google / Apple via '
                        'Firebase wires in once the project is set up.',
                        style: DesignTokens.typographyMeta
                            .copyWith(color: DesignTokens.colorMuted),
                      ),
                    const SizedBox(height: DesignTokens.spacingL),
                    const Center(child: ElevenLabsBadge()),
                  ],
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }
}
