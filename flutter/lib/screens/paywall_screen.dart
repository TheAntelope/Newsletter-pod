import 'package:flutter/material.dart';

import '../design_tokens.dart';
import '../state/app_state.dart';

/// Presentational paywall. Mirrors the launch tier model (see billing memo): Free
/// / Pro / Max. Purchases are stubbed until RevenueCat is wired (Phase 2 billing);
/// the "Choose" buttons explain that rather than charging.
class PaywallScreen extends StatelessWidget {
  const PaywallScreen({super.key});

  static const _plans = [
    _Plan(
      tier: 'free',
      name: 'Free',
      price: 'Free',
      features: [
        '1 default-voice pod per week',
        'Up to 25 items per episode',
      ],
    ),
    _Plan(
      tier: 'pro',
      name: 'Pro',
      price: r'$19.99/mo · $179.99/yr',
      features: [
        '3 premium-voice pods per week',
        'Up to 75 items per episode',
        'Custom voice selection',
      ],
    ),
    _Plan(
      tier: 'max',
      name: 'Max',
      price: r'$29.99/mo · $269.99/yr',
      features: [
        '7 premium-voice pods per week',
        'Everything in Pro',
        'Priority generation',
      ],
    ),
  ];

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    final currentTier = AppScope.of(context).me?.subscription.tier ?? 'free';

    return Scaffold(
      appBar: AppBar(title: const Text('Plans')),
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.all(DesignTokens.spacingL),
          children: [
            Text('Choose your plan', style: text.displayLarge),
            const SizedBox(height: DesignTokens.spacingS),
            Text(
              'Upgrade for more pods a week and premium voices.',
              style: text.titleMedium?.copyWith(color: DesignTokens.colorMuted),
            ),
            const SizedBox(height: DesignTokens.spacingL),
            for (final plan in _plans) ...[
              _PlanCard(plan: plan, current: plan.tier == currentTier),
              const SizedBox(height: DesignTokens.spacingM),
            ],
            const SizedBox(height: DesignTokens.spacingS),
            Text(
              'Subscriptions are handled by your app store via RevenueCat — '
              'wiring in once the project is set up.',
              style: text.labelMedium?.copyWith(color: DesignTokens.colorMuted),
            ),
          ],
        ),
      ),
    );
  }
}

class _Plan {
  const _Plan({
    required this.tier,
    required this.name,
    required this.price,
    required this.features,
  });

  final String tier;
  final String name;
  final String price;
  final List<String> features;
}

class _PlanCard extends StatelessWidget {
  const _PlanCard({required this.plan, required this.current});

  final _Plan plan;
  final bool current;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    return Card(
      child: Padding(
        padding: const EdgeInsets.all(DesignTokens.spacingM),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Row(
              children: [
                Expanded(child: Text(plan.name, style: text.titleLarge)),
                Text(plan.price, style: text.labelLarge),
              ],
            ),
            const SizedBox(height: DesignTokens.spacingS),
            for (final f in plan.features)
              Padding(
                padding: const EdgeInsets.only(bottom: DesignTokens.spacingXs),
                child: Row(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Icon(Icons.check, size: 16,
                        color: DesignTokens.colorAmber),
                    const SizedBox(width: DesignTokens.spacingS),
                    Expanded(child: Text(f, style: text.bodyMedium)),
                  ],
                ),
              ),
            const SizedBox(height: DesignTokens.spacingS),
            SizedBox(
              width: double.infinity,
              child: current
                  ? OutlinedButton(
                      onPressed: null,
                      child: const Text('Current plan'),
                    )
                  : ElevatedButton(
                      onPressed: () {
                        ScaffoldMessenger.of(context).showSnackBar(
                          const SnackBar(
                            content: Text(
                              'Purchases arrive with RevenueCat — coming soon.',
                            ),
                          ),
                        );
                      },
                      child: Text('Choose ${plan.name}'),
                    ),
            ),
          ],
        ),
      ),
    );
  }
}
