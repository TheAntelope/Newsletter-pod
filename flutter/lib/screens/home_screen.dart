import 'package:flutter/material.dart';

import '../api/models.dart';
import '../design_tokens.dart';
import '../state/app_state.dart';

class HomeScreen extends StatelessWidget {
  const HomeScreen({super.key});

  @override
  Widget build(BuildContext context) {
    final app = AppScope.of(context);
    final me = app.me;

    return Scaffold(
      appBar: AppBar(
        title: const Text('Today'),
        actions: [
          IconButton(
            tooltip: 'Sign out',
            onPressed: app.signOut,
            icon: const Icon(Icons.logout),
          ),
        ],
      ),
      body: SafeArea(
        child: switch ((app.loading, me)) {
          (true, null) => const Center(child: CircularProgressIndicator()),
          (_, null) => Center(
              child: Text(app.error ?? 'Something went wrong'),
            ),
          (_, final MeEnvelope loaded) => _Dashboard(me: loaded, app: app),
        },
      ),
    );
  }
}

class _Dashboard extends StatelessWidget {
  const _Dashboard({required this.me, required this.app});

  final MeEnvelope me;
  final AppState app;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    final name = me.user.firstName;
    final greeting = name.isNotEmpty ? 'Good morning, $name' : 'Welcome';

    return ListView(
      padding: const EdgeInsets.all(DesignTokens.spacingL),
      children: [
        Text(greeting, style: text.displayLarge),
        const SizedBox(height: DesignTokens.spacingXs),
        Text(
          'Your ${me.profile.title} is set to ${me.profile.desiredDurationMinutes} min.',
          style: text.titleMedium?.copyWith(color: DesignTokens.colorMuted),
        ),
        const SizedBox(height: DesignTokens.spacingL),
        _PlanCard(
          subscription: me.subscription,
          entitlements: me.entitlements,
        ),
        const SizedBox(height: DesignTokens.spacingM),
        _ScheduleCard(schedule: me.schedule),
        const SizedBox(height: DesignTokens.spacingL),
        SizedBox(
          width: double.infinity,
          child: ElevatedButton(
            onPressed: app.generateNow,
            child: const Text('Generate now'),
          ),
        ),
        if (app.lastRunMessage != null) ...[
          const SizedBox(height: DesignTokens.spacingM),
          Text(
            app.lastRunMessage!,
            style: text.bodyMedium?.copyWith(color: DesignTokens.colorAmberDeep),
          ),
        ],
        if (app.error != null) ...[
          const SizedBox(height: DesignTokens.spacingM),
          Text(app.error!, style: text.bodyMedium),
        ],
      ],
    );
  }
}

class _PlanCard extends StatelessWidget {
  const _PlanCard({required this.subscription, required this.entitlements});

  final SubscriptionDto subscription;
  final EntitlementsDto entitlements;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    final tier = subscription.tier.toUpperCase();

    return Card(
      child: Padding(
        padding: const EdgeInsets.all(DesignTokens.spacingM),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('PLAN', style: text.labelSmall?.copyWith(color: DesignTokens.colorMuted)),
            const SizedBox(height: DesignTokens.spacingXs),
            Text('$tier · ${subscription.status}', style: text.titleLarge),
            const SizedBox(height: DesignTokens.spacingS),
            if (entitlements.isInTrial)
              Text(
                'Trial: ${entitlements.trialPremiumPodsRemaining} premium pods left',
                style: text.bodyMedium,
              )
            else
              Text(
                '${entitlements.premiumPodsRemainingThisWeek} of '
                '${entitlements.premiumPodsPerWeek} premium pods left this week',
                style: text.bodyMedium,
              ),
          ],
        ),
      ),
    );
  }
}

class _ScheduleCard extends StatelessWidget {
  const _ScheduleCard({required this.schedule});

  final DeliveryScheduleDto schedule;

  @override
  Widget build(BuildContext context) {
    final text = Theme.of(context).textTheme;
    final days = schedule.weekdays
        .map((d) => d.isEmpty ? d : '${d[0].toUpperCase()}${d.substring(1)}')
        .join(' · ');

    return Card(
      child: Padding(
        padding: const EdgeInsets.all(DesignTokens.spacingM),
        child: Column(
          crossAxisAlignment: CrossAxisAlignment.start,
          children: [
            Text('SCHEDULE', style: text.labelSmall?.copyWith(color: DesignTokens.colorMuted)),
            const SizedBox(height: DesignTokens.spacingXs),
            Text('Delivered at ${schedule.localTime}', style: text.titleLarge),
            const SizedBox(height: DesignTokens.spacingS),
            Text(days, style: text.bodyMedium),
          ],
        ),
      ),
    );
  }
}
