import 'dart:io' show Platform;

import 'package:flutter/foundation.dart' show kIsWeb;
import 'package:flutter/services.dart' show PlatformException;
import 'package:purchases_flutter/purchases_flutter.dart';

import '../config.dart';

/// Wraps the RevenueCat SDK across **both** stores (Play Billing on Android,
/// StoreKit on iOS). Like the other controllers, nothing here touches a platform
/// channel until a method runs, and every method is a no-op unless the real-auth
/// purchases flag + the current platform's SDK key are present — so the demo
/// build, widget tests, and web never reach it.
class PurchasesController {
  PurchasesController._();

  static bool _configured = false;

  /// TEMP (billing diagnosis): emit RevenueCat verbose logs so an on-device
  /// `adb logcat` / Console shows the exact product query + store response while
  /// we work out store wiring. Flip back to false (or delete) once verified.
  static const bool _verboseBillingLogs = true;

  /// The RevenueCat public SDK key for the running platform. Empty on web (and
  /// when the relevant `--dart-define` key wasn't provided), which keeps the
  /// controller inert. `kIsWeb` is checked first so `Platform` is never touched
  /// on web (where `dart:io` is unavailable).
  static String get _platformKey {
    if (kIsWeb) return '';
    return Platform.isIOS
        ? AppConfig.revenueCatIosKey
        : AppConfig.revenueCatAndroidKey;
  }

  static bool get _enabled =>
      FeatureFlags.purchasesRevenueCat && _platformKey.isNotEmpty;

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
        PurchasesConfiguration(_platformKey)..appUserID = appUserId,
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

  /// Play Console **subscription id** + per-period **base plan id** for each
  /// tier (Android only). The subscription ids are the bare strings `pro` / `max`
  /// (NOT `clawcast_`-prefixed — that's only the display name).
  ///
  /// Note the per-tier asymmetry in the *yearly* base plan id: Pro's is `annual`,
  /// but Max's active yearly base plan is `annualmax` (Max's `annual` base plan
  /// is Inactive in Play Console).
  static const Map<String, ({String sub, String monthly, String annual})>
      _playSubscription = {
    'pro': (sub: 'pro', monthly: 'monthly', annual: 'annual'),
    'max': (sub: 'max', monthly: 'monthly', annual: 'annualmax'),
  };

  /// App Store **product ids** per tier/period (iOS only). These match the SKUs
  /// the native app shipped (`ios/NewsletterPodApp/AppConfiguration.swift`), so
  /// an existing Apple subscriber's purchase resolves to the same products.
  static const Map<String, ({String monthly, String annual})> _appStoreProducts = {
    'pro': (
      monthly: 'com.newsletterpod.pro.monthly',
      annual: 'com.newsletterpod.pro.annual',
    ),
    'max': (
      monthly: 'com.newsletterpod.max.monthly',
      annual: 'com.newsletterpod.max.annual',
    ),
  };

  static const List<String> _tiers = ['pro', 'max'];

  /// The store identifiers for [tier] on the current platform: the ids to pass
  /// to `getProducts`, plus the `StoreProduct.identifier` we expect back for the
  /// monthly and annual periods.
  ///
  /// IMPORTANT (Android getProducts gotcha, Jun 2026): on Android `getProducts`
  /// must be called with the **bare subscription id** (`pro`), NOT the
  /// `subscriptionId:basePlanId` form. It returns one [StoreProduct] per base
  /// plan, each with `identifier` == `"<sub>:<basePlan>"`; we pick the one we
  /// want from that list. Passing the colon form makes Play look up a product
  /// literally named `pro:monthly`, which doesn't exist → empty list, no error,
  /// silent purchase failure. On iOS, products are queried by their full App
  /// Store product id and `StoreProduct.identifier` echoes it verbatim.
  static ({List<String> query, String monthly, String annual})? _storeIdsFor(
      String tier) {
    if (kIsWeb) return null;
    if (Platform.isIOS) {
      final cfg = _appStoreProducts[tier];
      if (cfg == null) return null;
      return (query: [cfg.monthly, cfg.annual], monthly: cfg.monthly, annual: cfg.annual);
    }
    final cfg = _playSubscription[tier];
    if (cfg == null) return null;
    return (
      query: [cfg.sub],
      monthly: '${cfg.sub}:${cfg.monthly}',
      annual: '${cfg.sub}:${cfg.annual}',
    );
  }

  /// Live, store-localized price strings for the paid tiers, keyed by tier and
  /// period — e.g. `{'pro': (monthly: r'$4.99', annual: r'$44.99'), ...}`.
  ///
  /// This is the source of truth for paywall prices: RevenueCat reads them
  /// straight from the store, so a price change there propagates to the app with
  /// no code change or redeploy. The returned strings are the store's own
  /// `priceString` (already localized + currency-formatted, no period suffix —
  /// the caller appends `/mo` or `/yr`).
  ///
  /// Returns an empty map when purchases are disabled (demo build / widget tests
  /// / web, where [_enabled] is false) or every store query fails; callers fall
  /// back to their static labels. A per-tier query failure just omits that tier.
  static Future<Map<String, ({String? monthly, String? annual})>>
      fetchPrices() async {
    if (!_enabled) return {};
    final prices = <String, ({String? monthly, String? annual})>{};
    for (final tier in _tiers) {
      final ids = _storeIdsFor(tier);
      if (ids == null) continue;
      try {
        final products = await Purchases.getProducts(
          ids.query,
          productCategory: ProductCategory.subscription,
        );
        String? priceFor(String identifier) {
          for (final p in products) {
            if (p.identifier == identifier) return p.priceString;
          }
          return null;
        }

        prices[tier] = (
          monthly: priceFor(ids.monthly),
          annual: priceFor(ids.annual),
        );
      } on PlatformException {
        // Skip this tier; the caller falls back to its static label.
      }
    }
    return prices;
  }

  /// Purchase [tier] ('pro' | 'max') for the chosen period — no Offering needed.
  /// Returns true if the entitlement is active afterward; false on user-cancel
  /// or a missing product. The backend reconciles the real plan from the store
  /// webhook (RevenueCat → `pro`/`max` entitlement); the UI just calls
  /// [AppState.loadMe] after success.
  static Future<bool> purchase(String tier, {bool annual = false}) async {
    if (!_enabled) return false;
    final ids = _storeIdsFor(tier);
    if (ids == null) return false;
    final wantedId = annual ? ids.annual : ids.monthly;
    try {
      final products = await Purchases.getProducts(
        ids.query,
        productCategory: ProductCategory.subscription,
      );
      if (products.isEmpty) return false;
      // Pick the base plan / product we want; don't silently buy the wrong period.
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

  /// Restore an existing store subscription. Essential on iOS so an App Store
  /// subscriber who reinstalls — or upgrades from the native app to this Flutter
  /// build — regains their entitlement without re-paying. Returns true if any
  /// entitlement is active afterward. The backend tier is reconciled from the
  /// store webhook; the caller refreshes via [AppState.loadMe].
  static Future<bool> restorePurchases() async {
    if (!_enabled) return false;
    try {
      final info = await Purchases.restorePurchases();
      return info.entitlements.active.isNotEmpty;
    } on PlatformException {
      return false;
    }
  }
}
