import 'package:flutter/material.dart';

import '../design_tokens.dart';
import '../services/link_launcher.dart';
import '../state/app_state.dart';
import '../widgets/editorial.dart';
import 'feed_access_screen.dart';
import 'paywall_screen.dart';

/// Account / settings. Editorial rebuild of the iOS `AccountSheet` (+ Reset and
/// Delete sections): identity (with an editable display name), subscription, the
/// private feed, destructive reset / delete with confirmation, sign-out, and
/// legal links.
class AccountScreen extends StatelessWidget {
  const AccountScreen({super.key});

  String _tierLabel(String tier) =>
      tier.isEmpty ? 'Free' : '${tier[0].toUpperCase()}${tier.substring(1)}';

  Future<bool> _confirm(
    BuildContext context, {
    required String title,
    required String message,
    required String confirmLabel,
  }) async {
    final result = await showDialog<bool>(
      context: context,
      builder: (context) => AlertDialog(
        backgroundColor: DesignTokens.colorCream,
        title: Text(title, style: DesignTokens.typographyTitle),
        content: Text(message, style: DesignTokens.typographyBody),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(false),
            child: const Text('Cancel'),
          ),
          TextButton(
            onPressed: () => Navigator.of(context).pop(true),
            style: TextButton.styleFrom(foregroundColor: DesignTokens.colorAmberDeep),
            child: Text(confirmLabel),
          ),
        ],
      ),
    );
    return result ?? false;
  }

  @override
  Widget build(BuildContext context) {
    final app = AppScope.of(context);
    final user = app.me?.user;
    final tier = app.me?.subscription.tier ?? 'free';
    final identity = (user?.email?.isNotEmpty ?? false)
        ? user!.email!
        : (user?.displayName ?? 'Listener');
    final displayName = (user?.displayName ?? '').trim();
    final nameLabel = (user?.hasFriendlyName ?? false) ? displayName : 'Add your name';

    return Scaffold(
      appBar: AppBar(title: const Text('Account')),
      body: SafeArea(
        child: ListView(
          padding: const EdgeInsets.all(DesignTokens.spacingL),
          children: [
            EditorialCard(
              spacing: DesignTokens.spacingS,
              children: [
                const MetaLabel('Signed in'),
                Text(
                  identity,
                  style: DesignTokens.typographySubtitle
                      .copyWith(color: DesignTokens.colorInk),
                ),
              ],
            ),
            const SizedBox(height: DesignTokens.spacingL),
            // The display name drives the home greeting and the spoken greeting
            // in every generated episode — make it changeable at any time.
            EditorialCard(
              spacing: DesignTokens.spacingS,
              onTap: () => _onEditName(context, app),
              children: [
                Row(
                  children: [
                    const Expanded(child: MetaLabel('Name')),
                    Text(
                      'Edit',
                      style: DesignTokens.typographyCallout
                          .copyWith(color: DesignTokens.colorAmberDeep),
                    ),
                    const SizedBox(width: 4),
                    const Icon(Icons.chevron_right,
                        size: 18, color: DesignTokens.colorMuted),
                  ],
                ),
                Text(
                  nameLabel,
                  style: DesignTokens.typographyBody
                      .copyWith(color: DesignTokens.colorInk),
                ),
              ],
            ),
            const SizedBox(height: DesignTokens.spacingL),
            EditorialCard(
              spacing: DesignTokens.spacingS,
              onTap: () => Navigator.of(context).push(
                MaterialPageRoute(builder: (_) => const PaywallScreen()),
              ),
              children: [
                Row(
                  children: [
                    const Expanded(child: MetaLabel('Subscription')),
                    Text(
                      _tierLabel(tier),
                      style: DesignTokens.typographyCallout
                          .copyWith(color: DesignTokens.colorMuted),
                    ),
                    const SizedBox(width: 4),
                    const Icon(Icons.chevron_right,
                        size: 18, color: DesignTokens.colorMuted),
                  ],
                ),
                Text(
                  'View plans',
                  style: DesignTokens.typographyBody
                      .copyWith(color: DesignTokens.colorInk),
                ),
              ],
            ),
            const SizedBox(height: DesignTokens.spacingL),
            EditorialCard(
              spacing: DesignTokens.spacingS,
              onTap: () => Navigator.of(context).push(
                MaterialPageRoute(builder: (_) => const FeedAccessScreen()),
              ),
              children: [
                Row(
                  children: [
                    const Expanded(child: MetaLabel('Private feed')),
                    const Icon(Icons.chevron_right,
                        size: 18, color: DesignTokens.colorMuted),
                  ],
                ),
                Text(
                  'Add your briefings to any podcast app',
                  style: DesignTokens.typographyBody
                      .copyWith(color: DesignTokens.colorInk),
                ),
              ],
            ),
            const SizedBox(height: DesignTokens.spacingL),
            const MetaLabel('Start over'),
            const SizedBox(height: DesignTokens.spacingM),
            EditorialCard(
              children: [
                Text(
                  'Reset clears your sources, schedule, format, and swipe '
                  'history, then re-runs setup. Your account, subscription, and '
                  'past episodes are kept.',
                  style: DesignTokens.typographyCallout
                      .copyWith(color: DesignTokens.colorInkSoft),
                ),
                AmberButton.outlined(
                  label: 'Reset my algorithm',
                  onPressed: () => _onReset(context, app),
                ),
              ],
            ),
            const SizedBox(height: DesignTokens.spacingL),
            EditorialCard(
              children: [
                AmberButton.outlined(
                  label: 'Sign out',
                  onPressed: () {
                    app.signOut();
                    Navigator.of(context).popUntil((r) => r.isFirst);
                  },
                ),
                _DangerButton(
                  label: 'Delete account',
                  onPressed: () => _onDelete(context, app),
                ),
              ],
            ),
            const SizedBox(height: DesignTokens.spacingL),
            const MetaLabel('Legal'),
            const SizedBox(height: DesignTokens.spacingM),
            EditorialCard(
              spacing: 0,
              children: [
                _LegalRow(label: 'Terms of Use', url: 'https://theclawcast.com/terms'),
                const EditorialDivider(),
                _LegalRow(
                    label: 'Privacy Policy',
                    url: 'https://theclawcast.com/privacy'),
              ],
            ),
          ],
        ),
      ),
    );
  }

  /// Prompts for a new display name (prefilled with the current one) and, on a
  /// non-blank Save, persists it via `PATCH /v1/me` then reloads `me` so the
  /// change flows through to the home greeting and future generated episodes
  /// (the backend greets by first name from `display_name`). Blank input is a
  /// no-op — we never wipe an existing name.
  Future<void> _onEditName(BuildContext context, AppState app) async {
    final current = (app.me?.user.displayName ?? '').trim();
    final controller = TextEditingController(text: current);
    final newName = await showDialog<String>(
      context: context,
      builder: (context) => AlertDialog(
        backgroundColor: DesignTokens.colorCream,
        title: Text('Your name', style: DesignTokens.typographyTitle),
        content: TextField(
          controller: controller,
          autofocus: true,
          textCapitalization: TextCapitalization.words,
          textInputAction: TextInputAction.done,
          decoration: const InputDecoration(hintText: 'First name'),
          style: DesignTokens.typographyBody,
          onSubmitted: (value) => Navigator.of(context).pop(value),
        ),
        actions: [
          TextButton(
            onPressed: () => Navigator.of(context).pop(),
            child: const Text('Cancel'),
          ),
          TextButton(
            onPressed: () => Navigator.of(context).pop(controller.text),
            style: TextButton.styleFrom(
                foregroundColor: DesignTokens.colorAmberDeep),
            child: const Text('Save'),
          ),
        ],
      ),
    );
    final trimmed = newName?.trim() ?? '';
    // Blank input or an unchanged name: do nothing (never wipe an existing name).
    if (trimmed.isEmpty || trimmed == current) return;
    await app.repository.updateProfile(
      displayName: trimmed,
      timezone: app.me?.user.timezone ?? 'UTC',
    );
    await app.loadMe();
  }

  Future<void> _onReset(BuildContext context, AppState app) async {
    final ok = await _confirm(
      context,
      title: 'Reset your algorithm?',
      message:
          "We'll wipe your sources, schedule, and swipe history and walk you "
          'back through setup. Past episodes stay in your feed.',
      confirmLabel: 'Reset',
    );
    if (!ok || !context.mounted) return;
    await app.repository.resetAlgorithm();
    app.restartOnboarding();
    if (context.mounted) Navigator.of(context).popUntil((r) => r.isFirst);
  }

  Future<void> _onDelete(BuildContext context, AppState app) async {
    final ok = await _confirm(
      context,
      title: 'Delete your account?',
      message:
          'This permanently deletes your account, feed, and episodes. This '
          "can't be undone.",
      confirmLabel: 'Delete',
    );
    if (!ok || !context.mounted) return;
    await app.repository.deleteAccount();
    app.signOut();
    if (context.mounted) Navigator.of(context).popUntil((r) => r.isFirst);
  }
}

class _DangerButton extends StatelessWidget {
  const _DangerButton({required this.label, required this.onPressed});

  final String label;
  final VoidCallback onPressed;

  @override
  Widget build(BuildContext context) {
    return SizedBox(
      width: double.infinity,
      child: TextButton(
        onPressed: onPressed,
        style: TextButton.styleFrom(
          foregroundColor: const Color(0xFFC62828),
          padding: const EdgeInsets.symmetric(vertical: 14),
        ),
        child: Text(label),
      ),
    );
  }
}

class _LegalRow extends StatelessWidget {
  const _LegalRow({required this.label, required this.url});

  final String label;
  final String url;

  @override
  Widget build(BuildContext context) {
    return InkWell(
      onTap: () => openExternal(context, url),
      child: Padding(
        padding: const EdgeInsets.symmetric(vertical: DesignTokens.spacingM),
        child: Row(
          children: [
            Expanded(
              child: Text(
                label,
                style: DesignTokens.typographyBody
                    .copyWith(color: DesignTokens.colorInk),
              ),
            ),
            const Icon(Icons.open_in_new,
                size: 16, color: DesignTokens.colorMuted),
          ],
        ),
      ),
    );
  }
}
