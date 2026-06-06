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

  /// Maps an entitlement id (`pro` | `max` — what RevenueCat's
  /// `entitlements.active` and our backend webhook key off) to the Play Store
  /// *subscription product id*, which is prefixed `clawcast_` in Play Console.
  /// These are NOT the same namespace: the empty-`getProducts` billing bug
  /// (Jun 2026) was caused by sending the entitlement id `max` to Play, which
  /// has no such product, so Play returned an empty list with no error.
  static const Map<String, String> _playSubscriptionId = {
    'pro': 'clawcast_pro',
    'max': 'clawcast_max',
  };

  /// Purchase [tier] ('pro' | 'max') for the chosen period. Buys the Play
  /// subscription product directly by id — the Play product id has the form
  /// `subscriptionId:basePlanId` (e.g. `clawcast_pro:monthly`,
  /// `clawcast_max:annual`), which is how the products are configured in Play
  /// Console / RevenueCat — so no Offering is needed. Returns true if the
  /// entitlement is active afterward; false on user-cancel or a missing
  /// product. The backend reconciles the real plan from the RevenueCat webhook;
  /// the UI just calls [AppState.loadMe] after success.
  static Future<bool> purchase(String tier, {bool annual = false}) async {
    if (!_enabled) return false;
    final subscriptionId = _playSubscriptionId[tier];
    if (subscriptionId == null) return false;
    final productId = '$subscriptionId:${annual ? 'annual' : 'monthly'}';
    try {
      final products = await Purchases.getProducts(
        [productId],
        productCategory: ProductCategory.subscription,
      );
      if (products.isEmpty) return false;
      // purchases_flutter 8.x returns the CustomerInfo directly.
      final customerInfo = await Purchases.purchaseStoreProduct(products.first);
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
