import 'package:flutter/material.dart';

import '../design_tokens.dart';
import '../state/app_state.dart';
import '../widgets/editorial.dart';

/// Editorial sign-in hero. Sign-in is stubbed in this build — the real flow
/// becomes Google/Apple via Firebase, exchanged at `/v1/auth/firebase` for the
/// app session JWT, then the repository swaps to `ApiAppRepository`.
class SignInScreen extends StatelessWidget {
  const SignInScreen({super.key});

  static const _valueProps = [
    ('newspaper', 'From the sources you choose', Icons.newspaper_outlined),
    ('voice', 'Read in a voice you pick', Icons.graphic_eq),
    ('clock', 'Ready every morning', Icons.schedule_outlined),
  ];

  @override
  Widget build(BuildContext context) {
    final app = AppScope.of(context);

    return Scaffold(
      body: SafeArea(
        child: LayoutBuilder(
          builder: (context, constraints) => SingleChildScrollView(
            padding: const EdgeInsets.all(DesignTokens.spacingL),
            child: ConstrainedBox(
              constraints: BoxConstraints(
                minHeight:
                    constraints.maxHeight - DesignTokens.spacingL * 2,
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
                              size: 20, color: DesignTokens.colorAmberDeep),
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
                  label: 'Get started',
                  onPressed: app.signIn,
                ),
                const SizedBox(height: DesignTokens.spacingM),
                    Text(
                      'Sign-in is stubbed in this build — Google / Apple via '
                      'Firebase wires in once the project is set up.',
                      style: DesignTokens.typographyMeta
                          .copyWith(color: DesignTokens.colorMuted),
                    ),
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
