import 'package:flutter/material.dart';

import '../api/models.dart';
import '../config.dart';
import '../design_tokens.dart';
import '../services/purchases_controller.dart';
import '../state/app_state.dart';
import '../widgets/editorial.dart';

/// Paywall. Mirrors the launch tier model (see billing memo): Free / Pro / Max.
/// Editorial rebuild of the iOS `PaywallView` (header + trial-status + plan
/// cards). With [FeatureFlags.purchasesRevenueCat] off (default) the "Choose"
/// buttons show a "coming soon" note; with it on they run a real RevenueCat
/// (Play Billing) purchase and refresh `/v1/me`.
class PaywallScreen extends StatefulWidget {
  const PaywallScreen({super.key});

  @override
  State<PaywallScreen> createState() => _PaywallScreenState();

  static const _plans = [
    _Plan(
      tier: 'free',
      name: 'Free',
      recommended: false,
      features: [
        '1 default-voice pod per week',
        'Up to 25 items per episode',
      ],
    ),
    _Plan(
      tier: 'pro',
      name: 'Pro',
      monthlyPrice: r'$19.99/mo',
      annualPrice: r'$179.99/yr',
      recommended: true,
      features: [
        '3 premium-voice pods per week',
        'Up to 75 items per episode',
        'Custom voice selection',
      ],
    ),
    _Plan(
      tier: 'max',
      name: 'Max',
      monthlyPrice: r'$29.99/mo',
      annualPrice: r'$269.99/yr',
      recommended: false,
      features: [
        '7 premium-voice pods per week',
        'Everything in Pro',
        'Priority generation',
      ],
    ),
  ];

}

class _PaywallScreenState extends State<PaywallScreen> {
  String? _busyTier;

  /// Selected billing period for the paid plans. Drives both the price shown on
  /// each card and the `annual:` flag passed to the purchase.
  bool _annual = false;

  Future<void> _choose(AppState app, String tier) async {
    final messenger = ScaffoldMessenger.of(context);
    if (!FeatureFlags.purchasesRevenueCat) {
      messenger.showSnackBar(
        const SnackBar(
          content: Text('Purchases arrive with RevenueCat — coming soon.'),
        ),
      );
      return;
    }
    setState(() => _busyTier = tier);
    try {
      final ok = await PurchasesController.purchase(tier, annual: _annual);
      if (ok) {
        await app.loadMe(); // backend reconciles the plan from the webhook
        messenger.showSnackBar(
          SnackBar(content: Text("You're on $tier — enjoy!")),
        );
      }
      // ok == false → cancelled or no offering; stay quiet.
    } catch (_) {
      messenger.showSnackBar(
        const SnackBar(content: Text('Purchase failed. Please try again.')),
      );
    } finally {
      if (mounted) setState(() => _busyTier = null);
    }
  }

  @override
  Widget build(BuildContext context) {
    final app = AppScope.of(context);
    final currentTier = app.me?.subscription.tier ?? 'free';
    final entitlements = app.me?.entitlements;

    return Scaffold(
      appBar: AppBar(title: const Text('Plans')),
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.all(DesignTokens.spacingL),
          children: [
            EditorialCard(
              children: [
                const MetaLabel('Go further'),
                Text(
                  'Choose your plan',
                  style: DesignTokens.typographyTitle
                      .copyWith(color: DesignTokens.colorInk),
                ),
                Text(
                  'Upgrade for more pods a week and premium voices.',
                  style: DesignTokens.typographyBody
                      .copyWith(color: DesignTokens.colorInkSoft),
                ),
              ],
            ),
            const SizedBox(height: DesignTokens.spacingL),
            if (entitlements != null) ...[
              _TrialStatusCard(entitlements: entitlements),
              const SizedBox(height: DesignTokens.spacingL),
            ],
            Center(
              child: SegmentedButton<bool>(
                segments: const [
                  ButtonSegment(value: false, label: Text('Monthly')),
                  ButtonSegment(value: true, label: Text('Yearly · save ~25%')),
                ],
                selected: {_annual},
                showSelectedIcon: false,
                onSelectionChanged: (selection) =>
                    setState(() => _annual = selection.first),
              ),
            ),
            const SizedBox(height: DesignTokens.spacingL),
            for (final plan in PaywallScreen._plans) ...[
              _PlanCard(
                plan: plan,
                annual: _annual,
                current: plan.tier == currentTier,
                busy: _busyTier == plan.tier,
                onChoose: () => _choose(app, plan.tier),
              ),
              const SizedBox(height: DesignTokens.spacingM),
            ],
            const SizedBox(height: DesignTokens.spacingS),
            if (!FeatureFlags.purchasesRevenueCat)
              Text(
                'Subscriptions are handled by Google Play via RevenueCat — '
                'wiring in once the project is set up.',
                style: DesignTokens.typographyMeta
                    .copyWith(color: DesignTokens.colorMuted),
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
    required this.recommended,
    required this.features,
    this.monthlyPrice,
    this.annualPrice,
  });

  final String tier;
  final String name;
  final bool recommended;
  final List<String> features;

  /// Null for the Free plan (no purchasable period).
  final String? monthlyPrice;
  final String? annualPrice;

  bool get isPaid => monthlyPrice != null;

  /// Price label for the selected period; 'Free' for the non-paid plan.
  String priceLabel({required bool annual}) {
    if (!isPaid) return 'Free';
    return (annual ? annualPrice : monthlyPrice)!;
  }
}

class _TrialStatusCard extends StatelessWidget {
  const _TrialStatusCard({required this.entitlements});

  final EntitlementsDto entitlements;

  @override
  Widget build(BuildContext context) {
    final (label, headline, body) = _content;
    return EditorialCard(
      spacing: DesignTokens.spacingS,
      children: [
        MetaLabel(label),
        Text(
          headline,
          style: DesignTokens.typographyCalloutStrong
              .copyWith(color: DesignTokens.colorInk),
        ),
        Text(
          body,
          style: DesignTokens.typographyCallout
              .copyWith(color: DesignTokens.colorInkSoft),
        ),
      ],
    );
  }

  (String, String, String) get _content {
    if (entitlements.isInTrial && entitlements.trialPremiumPodsRemaining > 0) {
      return (
        'Free trial',
        '${entitlements.trialPremiumPodsRemaining} premium-voice pods left in your trial',
        'After your trial, free users get 1 premium-voice pod/week for the first '
            'month, then 1 default-voice pod/week.',
      );
    }
    if (entitlements.isInFirstMonth) {
      return (
        'Free · First month',
        '${entitlements.premiumPodsRemainingThisWeek} premium-voice pod left this week',
        'After your first month, free users get 1 default-voice pod/week. '
            'Upgrade to keep premium voices flowing.',
      );
    }
    return (
      'Free',
      '1 default-voice pod/week',
      'Upgrade for premium voices and more pods a week.',
    );
  }
}

class _PlanCard extends StatelessWidget {
  const _PlanCard({
    required this.plan,
    required this.annual,
    required this.current,
    required this.busy,
    required this.onChoose,
  });

  final _Plan plan;
  final bool annual;
  final bool current;
  final bool busy;
  final VoidCallback onChoose;

  @override
  Widget build(BuildContext context) {
    return EditorialCard(
      spacing: DesignTokens.spacingS,
      borderColor:
          plan.recommended ? DesignTokens.colorAmber : DesignTokens.colorRule,
      borderWidth: plan.recommended ? 1.5 : 0.5,
      children: [
        Row(
          children: [
            Text(
              plan.name,
              style: DesignTokens.typographyTitle
                  .copyWith(color: DesignTokens.colorInk),
            ),
            if (plan.recommended) ...[
              const SizedBox(width: DesignTokens.spacingS),
              Container(
                padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 2),
                decoration: BoxDecoration(
                  color: DesignTokens.colorAmber,
                  borderRadius: BorderRadius.circular(999),
                ),
                child: Text(
                  'Popular',
                  style: DesignTokens.typographyMeta.copyWith(color: Colors.white),
                ),
              ),
            ],
            const Spacer(),
            Text(
              plan.priceLabel(annual: annual),
              style: DesignTokens.typographyCallout
                  .copyWith(color: DesignTokens.colorMuted),
            ),
          ],
        ),
        for (final f in plan.features)
          Padding(
            padding: const EdgeInsets.only(top: 2),
            child: Row(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Icon(Icons.check,
                    size: 16, color: DesignTokens.colorAmber),
                const SizedBox(width: DesignTokens.spacingS),
                Expanded(
                  child: Text(
                    f,
                    style: DesignTokens.typographyBody
                        .copyWith(color: DesignTokens.colorInk),
                  ),
                ),
              ],
            ),
          ),
        const SizedBox(height: DesignTokens.spacingXs),
        current
            ? const AmberButton.outlined(label: 'Current plan')
            : AmberButton.filled(
                label: busy ? 'Purchasing…' : 'Choose ${plan.name}',
                onPressed: () {
                  if (!busy) onChoose();
                },
              ),
      ],
    );
  }
}
