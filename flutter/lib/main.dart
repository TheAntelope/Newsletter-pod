import 'package:flutter/material.dart';

import 'design_tokens.dart';
import 'theme.dart';

void main() {
  runApp(const ClawcastApp());
}

class ClawcastApp extends StatelessWidget {
  const ClawcastApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'ClawCast',
      debugShowCheckedModeBanner: false,
      theme: ClawcastTheme.light(),
      home: const HomePlaceholder(),
    );
  }
}

/// Temporary Phase 2 shell so the editorial theme renders and the local run loop
/// (flutter run -d chrome / widget tests) is exercised. Real screens (dashboard,
/// sources, onboarding, paywall, swipe deck, …) replace this as the port proceeds.
class HomePlaceholder extends StatelessWidget {
  const HomePlaceholder({super.key});

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    return Scaffold(
      body: SafeArea(
        child: Padding(
          padding: const EdgeInsets.all(DesignTokens.spacingL),
          child: Column(
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text('ClawCast', style: text.displayLarge),
              const SizedBox(height: DesignTokens.spacingS),
              Text(
                'Your briefing, in your ears.',
                style: text.titleMedium?.copyWith(color: DesignTokens.colorMuted),
              ),
              const SizedBox(height: DesignTokens.spacingXl),
              Card(
                child: Padding(
                  padding: const EdgeInsets.all(DesignTokens.spacingM),
                  child: Text(
                    'Flutter Android shell — Phase 2 scaffold.',
                    style: text.bodyMedium,
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}
