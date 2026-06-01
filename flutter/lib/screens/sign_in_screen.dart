import 'package:flutter/material.dart';

import '../design_tokens.dart';
import '../state/app_state.dart';

class SignInScreen extends StatelessWidget {
  const SignInScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    final app = AppScope.of(context);

    return Scaffold(
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(DesignTokens.spacingL),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              const SizedBox(height: DesignTokens.spacingXl),
              Text('ClawCast', style: text.displayLarge),
              const SizedBox(height: DesignTokens.spacingS),
              Text(
                'Your briefing, in your ears.',
                style: text.titleMedium?.copyWith(color: DesignTokens.colorMuted),
              ),
              const SizedBox(height: DesignTokens.spacingL),
              Text(
                'A customised daily podcast, generated from the newsletters and '
                'sources you choose.',
                style: text.bodyMedium,
              ),
              const Spacer(),
              SizedBox(
                width: double.infinity,
                child: ElevatedButton(
                  onPressed: app.signIn,
                  child: const Text('Get started'),
                ),
              ),
              const SizedBox(height: DesignTokens.spacingM),
              Text(
                'Sign-in is stubbed in this build — Google/Apple via Firebase '
                'wires in once the project is set up.',
                style: text.labelMedium?.copyWith(color: DesignTokens.colorMuted),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
