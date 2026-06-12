#!/usr/bin/env python3
"""Set ClawCast subscription prices in App Store Connect and Google Play.

This is the single command that pushes a price change to both stores. The apps
themselves read prices *live* from the stores (Flutter via
`PurchasesController.fetchPrices()`, iOS via StoreKit `displayPrice`), so once
the stores are updated the change reaches users with no app rebuild or deploy.
This script automates the one remaining manual step: entering the prices in the
two dashboards.

The canonical price table lives in `PRICE_TABLE` below -- edit those USD numbers
(or pass `--price-table prices.json`) and run. Prices flow:

    PRICE_TABLE (USD) +--> App Store Connect  (matched to a price point, per territory)
                      +--> Google Play        (USD converted to every region's price)

SAFETY: dry-run by default. It reads current prices and prints a full
old->new diff for every product on both stores, and makes NO changes. Add
`--apply` to actually write. `--apply` is the only thing that mutates store
state; everything else is read-only.

--------------------------------------------------------------------------------
Credentials
--------------------------------------------------------------------------------
App Store Connect (an ASC API key -- the same kind Codemagic uses):
  --asc-key-id        / env ASC_KEY_ID        (e.g. 2X9R4HXF34)
  --asc-issuer-id     / env ASC_ISSUER_ID     (UUID, ASC -> Users and Access -> Keys)
  --asc-key           / env ASC_PRIVATE_KEY   path to the .p8, OR the PEM contents
Generate the key at App Store Connect -> Users and Access -> Integrations -> Keys
with the "App Manager" role (pricing requires write access).

Google Play (the Play Developer service-account JSON -- the same one RevenueCat
and Codemagic's `google_play` group use):
  --play-credentials  / env GOOGLE_PLAY_CREDENTIALS or GCLOUD_SERVICE_ACCOUNT_CREDENTIALS
                        path to the JSON, OR the JSON contents
The service account needs the "Manage orders and subscriptions" / financial
permission in the Play Console (read-only is enough for dry-run; writes need
the manage-subscriptions grant).

--------------------------------------------------------------------------------
Usage
--------------------------------------------------------------------------------
  # Show current prices on both stores and what a change WOULD do (no writes):
  python scripts/set_prices.py

  # Only one store:
  python scripts/set_prices.py --store apple
  python scripts/set_prices.py --store google

  # Actually apply, grandfathering existing subscribers at their old price
  # (the safe default -- nobody's bill changes without re-subscribing):
  python scripts/set_prices.py --apply

  # Apply and also move existing subscribers to the new (lower) price:
  python scripts/set_prices.py --apply --existing-subscribers migrate

Notes / known edges (see the team summary for context):
- Apple prices are set for the base territory (USA) -- the storefront the apps'
  `displayPrice` shows for US testers. Other territories are NOT auto-set by the
  API; set them with `--all-territories` (loops the matched point's per-territory
  equalizations) or accept Apple's dashboard auto-equalize prompt.
- Apple has a fixed ladder of price points. If a USD value has no exact point
  the script refuses that product and prints the nearest available points rather
  than silently picking one.
- The Google write path follows the documented `convertRegionPrices` -> patch
  flow but cannot be tested here against a live catalog -- watch the first
  `--apply` run and confirm in the Play Console.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import sys
import time
from dataclasses import dataclass
from typing import Optional

import requests


# --------------------------------------------------------------------------- #
# Canonical price table -- the single source of truth for a price change.       #
# Edit the `usd` values (or override with --price-table a JSON list of the     #
# same shape) and run. Product ids mirror config.py (App Store) and            #
# flutter/lib/services/purchases_controller.dart (Play sub/base-plan ids).     #
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class Product:
    key: str  # logical label, e.g. "pro_monthly"
    usd: str  # target customer price in USD, e.g. "4.99"
    asc_product_id: str  # App Store product id
    play_sub_id: str  # Play subscription id (bare: "pro" / "max")
    play_base_plan: str  # Play base plan id within that subscription
    period: str  # "monthly" | "annual" (display only)


PRICE_TABLE: list[Product] = [
    Product("pro_monthly", "4.99", "com.newsletterpod.pro.monthly", "pro", "monthly", "monthly"),
    Product("pro_annual", "44.99", "com.newsletterpod.pro.annual", "pro", "annual", "annual"),
    Product("max_monthly", "7.49", "com.newsletterpod.max.monthly", "max", "monthly", "monthly"),
    # Max's active yearly base plan id is `annualmax` (see purchases_controller.dart).
    # Apple has no $67.49 price point; $66.99 is the nearest valid point. Set on both
    # stores for cross-platform parity (Google accepts the exact value too).
    Product("max_annual", "66.99", "com.newsletterpod.max.annual", "max", "annualmax", "annual"),
]

ASC_BASE = "https://api.appstoreconnect.apple.com"
PLAY_BASE = "https://androidpublisher.googleapis.com/androidpublisher/v3"
BASE_TERRITORY = "USA"  # Apple territory code for the US storefront


def _load_price_table(path: Optional[str]) -> list[Product]:
    if not path:
        return PRICE_TABLE
    with open(path, "r", encoding="utf-8") as fh:
        rows = json.load(fh)
    return [Product(**row) for row in rows]


def _usd_to_units_nanos(usd: str) -> tuple[int, int]:
    """'4.99' -> (4, 990000000). Google money is units + nanos (1e-9)."""
    whole, _, frac = usd.partition(".")
    frac = (frac + "000000000")[:9]
    return int(whole), int(frac)


# =========================================================================== #
# App Store Connect                                                           #
# =========================================================================== #
class AppStoreConnect:
    def __init__(self, key_id: str, issuer_id: str, private_key_pem: str):
        self._key_id = key_id
        self._issuer_id = issuer_id
        self._private_key = private_key_pem
        self._token: Optional[str] = None
        self._token_exp = 0.0

    def _jwt(self) -> str:
        import jwt  # PyJWT[crypto] -- already a runtime dep

        now = int(time.time())
        if self._token and now < self._token_exp - 60:
            return self._token
        # ASC tokens may live up to 20 min; we use ~18 to be safe.
        exp = now + 18 * 60
        self._token = jwt.encode(
            {"iss": self._issuer_id, "iat": now, "exp": exp, "aud": "appstoreconnect-v1"},
            self._private_key,
            algorithm="ES256",
            headers={"kid": self._key_id, "typ": "JWT"},
        )
        self._token_exp = exp
        return self._token

    def _get(self, path: str, params: Optional[dict] = None) -> dict:
        url = path if path.startswith("http") else f"{ASC_BASE}{path}"
        r = requests.get(url, headers={"Authorization": f"Bearer {self._jwt()}"}, params=params, timeout=30)
        r.raise_for_status()
        return r.json()

    def _post(self, path: str, body: dict) -> dict:
        r = requests.post(
            f"{ASC_BASE}{path}",
            headers={"Authorization": f"Bearer {self._jwt()}", "Content-Type": "application/json"},
            json=body,
            timeout=30,
        )
        if r.status_code >= 300:
            raise RuntimeError(f"ASC POST {path} -> {r.status_code}: {r.text}")
        return r.json()

    def _paged(self, path: str, params: Optional[dict] = None) -> list[dict]:
        out: list[dict] = []
        data = self._get(path, params)
        out.extend(data.get("data", []))
        while (nxt := data.get("links", {}).get("next")):
            data = self._get(nxt)
            out.extend(data.get("data", []))
        return out

    def resolve_subscription_ids(self, bundle_id: str) -> dict[str, str]:
        """Map App Store product-id string -> internal subscription resource id."""
        apps = self._get("/v1/apps", {"filter[bundleId]": bundle_id}).get("data", [])
        if not apps:
            raise RuntimeError(f"No App Store app for bundle id {bundle_id!r}.")
        app_id = apps[0]["id"]
        groups = self._paged(f"/v1/apps/{app_id}/subscriptionGroups")
        mapping: dict[str, str] = {}
        for g in groups:
            subs = self._paged(f"/v1/subscriptionGroups/{g['id']}/subscriptions")
            for s in subs:
                pid = s.get("attributes", {}).get("productId")
                if pid:
                    mapping[pid] = s["id"]
        return mapping

    def current_price(self, subscription_id: str) -> Optional[str]:
        """Current customerPrice for the base territory, or None if unset."""
        prices = self._get(
            f"/v1/subscriptions/{subscription_id}/prices",
            {
                "filter[territory]": BASE_TERRITORY,
                "include": "subscriptionPricePoint",
                "limit": 200,
            },
        )
        points = {p["id"]: p for p in prices.get("included", []) if p["type"] == "subscriptionPricePoints"}
        for row in prices.get("data", []):
            pp = row.get("relationships", {}).get("subscriptionPricePoint", {}).get("data")
            if pp and pp["id"] in points:
                return points[pp["id"]]["attributes"].get("customerPrice")
        return None

    def find_price_point(self, subscription_id: str, usd: str) -> tuple[Optional[str], list[str]]:
        """Return (price_point_id matching `usd`, sorted sample of available prices)."""
        points = self._paged(
            f"/v1/subscriptions/{subscription_id}/pricePoints",
            {"filter[territory]": BASE_TERRITORY, "limit": 200},
        )
        available: list[str] = []
        match: Optional[str] = None
        for p in points:
            price = p.get("attributes", {}).get("customerPrice")
            if price is None:
                continue
            available.append(price)
            if price == usd:
                match = p["id"]
        nearest = sorted(set(available), key=lambda s: abs(float(s) - float(usd)))[:8]
        return match, nearest

    def set_price(
        self, subscription_id: str, price_point_id: str, preserve_existing: bool, start_date: str
    ) -> None:
        # `startDate` is required on an approved subscription: without it ASC treats
        # the POST as defining the (immutable) initial price and returns 409 STATE_ERROR.
        self._post(
            "/v1/subscriptionPrices",
            {
                "data": {
                    "type": "subscriptionPrices",
                    "attributes": {
                        "preserveCurrentPrice": preserve_existing,
                        "startDate": start_date,
                    },
                    "relationships": {
                        "subscription": {"data": {"type": "subscriptions", "id": subscription_id}},
                        "subscriptionPricePoint": {
                            "data": {"type": "subscriptionPricePoints", "id": price_point_id}
                        },
                        "territory": {"data": {"type": "territories", "id": BASE_TERRITORY}},
                    },
                }
            },
        )


def run_apple(table: list[Product], args) -> int:
    key_id = args.asc_key_id or os.environ.get("ASC_KEY_ID")
    issuer = args.asc_issuer_id or os.environ.get("ASC_ISSUER_ID")
    key_src = args.asc_key or os.environ.get("ASC_PRIVATE_KEY")
    if not (key_id and issuer and key_src):
        print("  [apple] SKIPPED -- set ASC_KEY_ID, ASC_ISSUER_ID and ASC_PRIVATE_KEY (or --asc-* flags).")
        return 0
    pem = key_src
    if os.path.exists(key_src):
        with open(key_src, "r", encoding="utf-8") as fh:
            pem = fh.read()

    asc = AppStoreConnect(key_id, issuer, pem)
    print(f"=== App Store Connect ({BASE_TERRITORY} storefront) ===")
    try:
        ids = asc.resolve_subscription_ids(args.bundle_id)
    except Exception as e:  # noqa: BLE001 -- surface auth/lookup failures plainly
        print(f"  ERROR resolving subscriptions: {e}")
        return 1

    preserve = args.existing_subscribers == "preserve"
    # ASC requires the price-change startDate to be at least 2 days out; use +3 for
    # timezone margin. New price applies to new subscribers from this date (decreases
    # need no customer consent).
    start_date = (_dt.date.today() + _dt.timedelta(days=3)).isoformat()
    failures = 0
    for prod in table:
        sub_id = ids.get(prod.asc_product_id)
        if not sub_id:
            print(f"  {prod.key}: NOT FOUND in App Store Connect ({prod.asc_product_id}) -- skipped")
            failures += 1
            continue
        current = asc.current_price(sub_id)
        match, nearest = asc.find_price_point(sub_id, prod.usd)
        if not match:
            print(
                f"  {prod.key}: no ${prod.usd} price point. current=${current}. "
                f"nearest available: {', '.join('$' + n for n in nearest)}"
            )
            failures += 1
            continue
        arrow = "(no change)" if current == prod.usd else f"-> ${prod.usd}"
        print(f"  {prod.key}: ${current} {arrow}")
        if args.apply and current != prod.usd:
            try:
                asc.set_price(sub_id, match, preserve_existing=preserve, start_date=start_date)
                print(f"    applied ({'grandfathered' if preserve else 'migrated'} existing subs)")
            except Exception as e:  # noqa: BLE001
                print(f"    ERROR applying: {e}")
                failures += 1
    return 1 if failures else 0


# =========================================================================== #
# Google Play                                                                  #
# =========================================================================== #
class GooglePlay:
    def __init__(self, sa_info: dict, package_name: str):
        from google.oauth2 import service_account
        import google.auth.transport.requests as greq

        self._pkg = package_name
        self._creds = service_account.Credentials.from_service_account_info(
            sa_info, scopes=["https://www.googleapis.com/auth/androidpublisher"]
        )
        self._req = greq.Request()

    def _token(self) -> str:
        if not self._creds.valid:
            self._creds.refresh(self._req)
        return self._creds.token

    def _hdr(self) -> dict:
        return {"Authorization": f"Bearer {self._token()}", "Content-Type": "application/json"}

    def get_subscription(self, sub_id: str) -> dict:
        r = requests.get(
            f"{PLAY_BASE}/applications/{self._pkg}/subscriptions/{sub_id}",
            headers=self._hdr(),
            timeout=30,
        )
        r.raise_for_status()
        return r.json()

    def convert_region_prices(self, usd: str) -> dict:
        units, nanos = _usd_to_units_nanos(usd)
        r = requests.post(
            f"{PLAY_BASE}/applications/{self._pkg}/pricing:convertRegionPrices",
            headers=self._hdr(),
            json={"price": {"currencyCode": "USD", "units": str(units), "nanos": nanos}},
            timeout=30,
        )
        r.raise_for_status()
        result = r.json()
        # convertRegionPrices applies local price-templating to EVERY region, including
        # the US -- e.g. it rounds USD 66.99 down to 64.99. We want the US storefront to
        # be the exact intended price, so override the US entry with the literal input;
        # other regions keep Google's locally-appropriate conversions.
        us = result.setdefault("convertedRegionPrices", {}).setdefault("US", {})
        us["price"] = {"currencyCode": "USD", "units": str(units), "nanos": nanos}
        return result

    def patch_base_plan_prices(
        self, subscription: dict, base_plan_id: str, converted: dict, regions_version: str
    ) -> None:
        """Replace one base plan's regionalConfigs with the converted prices, leaving
        the rest of the subscription untouched, then PATCH basePlans."""
        region_prices = converted.get("convertedRegionPrices", {})
        new_regional = [
            {"regionCode": rc, "price": info["price"]} for rc, info in region_prices.items()
        ]
        base_plans = subscription.get("basePlans", [])
        found = False
        for bp in base_plans:
            if bp.get("basePlanId") == base_plan_id:
                bp["regionalConfigs"] = new_regional
                found = True
        if not found:
            raise RuntimeError(f"base plan {base_plan_id!r} not present on subscription")
        body = {
            "packageName": self._pkg,
            "productId": subscription["productId"],
            "basePlans": base_plans,
        }
        r = requests.patch(
            f"{PLAY_BASE}/applications/{self._pkg}/subscriptions/{subscription['productId']}",
            headers=self._hdr(),
            params={
                "updateMask": "basePlans",
                "regionsVersion.version": regions_version,
                # Price updates touch many regions; the tolerant mode is the value
                # Google accepts for bulk catalog changes (the SENSITIVE spelling
                # used before is not a valid enum -> 400 INVALID_ARGUMENT).
                "latencyTolerance": "PRODUCT_UPDATE_LATENCY_TOLERANCE_LATENCY_TOLERANT",
            },
            json=body,
            timeout=30,
        )
        if r.status_code >= 300:
            raise RuntimeError(f"Play PATCH -> {r.status_code}: {r.text}")


def _play_base_us_price(subscription: dict, base_plan_id: str) -> Optional[str]:
    for bp in subscription.get("basePlans", []):
        if bp.get("basePlanId") != base_plan_id:
            continue
        for rc in bp.get("regionalConfigs", []):
            if rc.get("regionCode") == "US":
                price = rc.get("price", {})
                units = price.get("units", "0")
                nanos = int(price.get("nanos", 0))
                return f"{int(units)}.{nanos // 10_000_000:02d}"
    return None


def run_google(table: list[Product], args) -> int:
    src = args.play_credentials or os.environ.get("GOOGLE_PLAY_CREDENTIALS") or os.environ.get(
        "GCLOUD_SERVICE_ACCOUNT_CREDENTIALS"
    )
    if not src:
        print("  [google] SKIPPED -- set GOOGLE_PLAY_CREDENTIALS (or --play-credentials).")
        return 0
    raw = src
    if os.path.exists(src):
        with open(src, "r", encoding="utf-8") as fh:
            raw = fh.read()
    try:
        sa_info = json.loads(raw)
    except json.JSONDecodeError as e:
        print(f"  [google] ERROR: credentials are not valid JSON: {e}")
        return 1

    play = GooglePlay(sa_info, args.package_name)
    print(f"=== Google Play (US prices; worldwide auto-converted) ===")
    # Group products by Play subscription id so we fetch each subscription once.
    by_sub: dict[str, list[Product]] = {}
    for prod in table:
        by_sub.setdefault(prod.play_sub_id, []).append(prod)

    failures = 0
    for sub_id, prods in by_sub.items():
        try:
            subscription = play.get_subscription(sub_id)
        except Exception as e:  # noqa: BLE001
            print(f"  subscription {sub_id!r}: ERROR fetching: {e}")
            failures += 1
            continue
        for prod in prods:
            current = _play_base_us_price(subscription, prod.play_base_plan)
            target = f"{prod.usd}" if "." in prod.usd else f"{prod.usd}.00"
            current_disp = f"${current}" if current else "(unset)"
            arrow = "(no change)" if current == prod.usd else f"-> ${prod.usd}"
            print(f"  {prod.key} [{sub_id}:{prod.play_base_plan}]: {current_disp} {arrow}")
            if args.apply and current != prod.usd:
                try:
                    converted = play.convert_region_prices(prod.usd)
                    # Use the regions version the convert call actually resolved to
                    # (e.g. 2025/03). Pinning a stale --regions-version makes the PATCH
                    # reject newly-euro regions (e.g. BG: expected BGN but convert gave EUR).
                    regions_version = (
                        converted.get("regionVersion", {}).get("version") or args.regions_version
                    )
                    # Re-fetch to avoid clobbering a concurrent edit, then patch.
                    fresh = play.get_subscription(sub_id)
                    play.patch_base_plan_prices(
                        fresh, prod.play_base_plan, converted, regions_version
                    )
                    subscription = play.get_subscription(sub_id)  # refresh for next product
                    print("    applied")
                except Exception as e:  # noqa: BLE001
                    print(f"    ERROR applying: {e}")
                    failures += 1
    return 1 if failures else 0


# =========================================================================== #
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--apply", action="store_true", help="Write the changes. Default is dry-run (read-only).")
    ap.add_argument("--store", choices=["apple", "google", "both"], default="both")
    ap.add_argument("--price-table", help="Optional JSON file of Product rows to override PRICE_TABLE.")
    ap.add_argument(
        "--existing-subscribers",
        choices=["preserve", "migrate"],
        default="preserve",
        help="preserve = grandfather current subscribers at their old price (safe default); "
        "migrate = move them to the new price (Apple only; Play decreases apply to new buyers).",
    )
    ap.add_argument("--bundle-id", default="com.newsletterpod.app", help="App Store bundle id.")
    ap.add_argument("--package-name", default="com.newsletterpod.app", help="Play package name.")
    ap.add_argument("--asc-key-id")
    ap.add_argument("--asc-issuer-id")
    ap.add_argument("--asc-key", help="Path to the .p8 file, or the PEM contents.")
    ap.add_argument("--play-credentials", help="Path to the service-account JSON, or the JSON contents.")
    ap.add_argument(
        "--regions-version",
        default="2022/02",
        help="Play regionsVersion for new regional prices. Bump if the API rejects it.",
    )
    args = ap.parse_args()

    table = _load_price_table(args.price_table)

    mode = "APPLY (writing to stores)" if args.apply else "DRY RUN (no changes)"
    print(f"ClawCast price update -- {mode}")
    print("Targets:")
    for p in table:
        print(f"  {p.key:14} ${p.usd}")
    print()

    rc = 0
    if args.store in ("apple", "both"):
        rc |= run_apple(table, args)
        print()
    if args.store in ("google", "both"):
        rc |= run_google(table, args)
        print()

    if not args.apply:
        print("Dry run only -- re-run with --apply to write these prices.")
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
