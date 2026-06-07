import 'package:flutter/services.dart' show PlatformException;
import 'package:purchases_flutter/purchases_flutter.dart';

import '../config.dart';

/// Wraps the RevenueCat (Play Billing) SDK. Like the other controllers, nothing
/// here touches a platform channel until a method runs, and every method is a
/// no-op unless the real-auth purchases flag + an Android SDK key are present —
/// so the demo build and widget tests never reach it.
class PurchasesController {
  PurchasesController._();

  static bool _configured = false;

  /// TEMP (billing diagnosis): emit RevenueCat verbose logs so an on-device
  /// `adb logcat` shows the exact product query + store response while we work
  /// out why `getProducts` returns empty on the internal track. Flip back to
  /// false (or delete) once billing is verified.
  static const bool _verboseBillingLogs = true;

  static bool get _enabled =>
      FeatureFlags.purchasesRevenueCat && AppConfig.revenueCatAndroidKey.isNotEmpty;

  /// Configure the SDK once and identify the user as [appUserId] (our backend
  /// user id, so RevenueCat's `app_user_id` matches what the webhook expects).
  /// Safe to call on every sign-in: re-logs-in if already configured.
  static Future<void> configureAndLogin(String appUserId) async {
    if (!_enabled) return;
    if (!_configured) {
      if (_verboseBillingLogs) {
        await Purchases.setLogLevel(LogLevel.verbose);
      }
      await Purchases.configure(
        PurchasesConfiguration(AppConfig.revenueCatAndroidKey)
          ..appUserID = appUserId,
      );
      _configured = true;
    } else {
      await Purchases.logIn(appUserId);
    }
  }

  static Future<void> logOut() async {
    if (!_enabled || !_configured) return;
    await Purchases.logOut();
  }

  /// Maps a tier (`pro` | `max` — what RevenueCat's `entitlements.active` and
  /// our backend webhook key off) to its Play Console **subscription id** and
  /// the **base plan id** for each period.
  ///
  /// The Play subscription ids are the bare strings `pro` / `max` (NOT
  /// `clawcast_`-prefixed — the `clawcast_*` string is only the display name).
  ///
  /// Note the per-tier asymmetry in the *yearly* base plan id: Pro's is
  /// `annual`, but Max's active yearly base plan is `annualmax` (Max's `annual`
  /// base plan is Inactive in Play Console).
  static const Map<String, ({String sub, String monthly, String annual})>
      _playSubscription = {
    'pro': (sub: 'pro', monthly: 'monthly', annual: 'annual'),
    'max': (sub: 'max', monthly: 'monthly', annual: 'annualmax'),
  };

  /// Purchase [tier] ('pro' | 'max') for the chosen period — no Offering needed.
  /// Returns true if the entitlement is active afterward; false on user-cancel
  /// or a missing product. The backend reconciles the real plan from the
  /// RevenueCat webhook; the UI just calls [AppState.loadMe] after success.
  ///
  /// IMPORTANT (Android getProducts gotcha, Jun 2026): on Android `getProducts`
  /// must be called with the **bare subscription id** (`pro`), NOT the
  /// `subscriptionId:basePlanId` form. It returns one [StoreProduct] per base
  /// plan, each with `identifier` == `"<sub>:<basePlan>"`; we pick the one we
  /// want from that list. Passing the colon form makes Play look up a product
  /// literally named `pro:monthly`, which doesn't exist → empty list, no error,
  /// silent purchase failure. (This — not the `clawcast_` prefix — was the real
  /// cause of the empty-getProducts bug.)
  static Future<bool> purchase(String tier, {bool annual = false}) async {
    if (!_enabled) return false;
    final cfg = _playSubscription[tier];
    if (cfg == null) return false;
    final wantedId = '${cfg.sub}:${annual ? cfg.annual : cfg.monthly}';
    try {
      final products = await Purchases.getProducts(
        [cfg.sub],
        productCategory: ProductCategory.subscription,
      );
      if (products.isEmpty) return false;
      // Pick the base plan we want; don't silently buy the wrong period.
      final matches = products.where((p) => p.identifier == wantedId);
      if (matches.isEmpty) return false;
      // purchases_flutter 8.x returns the CustomerInfo directly.
      final customerInfo = await Purchases.purchaseStoreProduct(matches.first);
      final active = customerInfo.entitlements.active;
      return active.containsKey(tier) || active.isNotEmpty;
    } on PlatformException catch (e) {
      // A user-cancelled purchase is a normal outcome, not an error.
      if (PurchasesErrorHelper.getErrorCode(e) ==
          PurchasesErrorCode.purchaseCancelledError) {
        return false;
      }
      rethrow;
    }
  }
}
