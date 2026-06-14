"""One-shot: gift a fresh 7-day full-access trial to the FIRST N users by
signup order, and stamp the trial-gift marker so the app/push can announce it.

Framing ("a gift from theclawcast for being one of the first 100 users"):
we order every user ascending by `created_at` and take the first N (default
100) — the earliest signups. Those are the people we want to thank with a reset
7-day full-access window plus an in-app gift card and an announcement push.

This is the back-grant half of the trial-gift feature. The gift markers it
writes are what the rest of the stack keys off:
  - `trial_gift_granted_at`      -> drives `UserEntitlements.trial_gift_pending`
                                    (granted AND not yet acknowledged) so the
                                    iOS/Flutter gift card shows.
  - `trial_gift_acknowledged_at` -> cleared here; set when the user taps
                                    "Got it" via POST /v1/me/trial-gift/ack.
  - `trial_gift_pushed_at`       -> cleared here; set by
                                    POST /admin/trial-gift/notify once the
                                    announcement push has fired.

Paid users are SKIPPED. A trial reset is a no-op for an active pro/max/paid
subscriber (their tier already sits at/above the trial), and showing them a
"your free trial has been reset" gift card would just confuse a paying
customer. "Paid" mirrors `ControlPlane._resolve_tier` (and grant_time_trial.py):
PAID only when tier is pro/max/paid AND status is not expired/revoked; free,
expired, revoked, or no subscription doc all count as unpaid. Skipped paid
users STILL occupy a slot in the first-N cohort — we gift the first N signups,
not "the first N unpaid signups".

Per gifted (unpaid, in-cohort) user we set:
  - trial_ends_at               -> now + --days (default 7)
  - trial_gift_granted_at       -> now
  - trial_gift_acknowledged_at  -> None    (re-arm the gift card)
  - trial_gift_pushed_at        -> None    (re-arm the announcement push)
  - trial_premium_pods_remaining-> 0       (legacy pod trial is superseded)
  - trial_exhausted_at          -> None
  - first_month_ends_at         -> None
  - premium_pods_this_week      -> 0       (fresh full-access week)
  - default_pods_this_week      -> 0
  - current_week_iso            -> None
  - updated_at                  -> now

This is a one-shot. Re-running RESETS the 7-day clock for every unpaid user in
the cohort AND clears `trial_gift_acknowledged_at` / `trial_gift_pushed_at`,
so the gift card re-appears and /admin/trial-gift/notify will re-notify them.

Usage (PowerShell):
    $env:GOOGLE_CLOUD_PROJECT = "newsletter-pod"
    # dry-run (default): prints exactly what WOULD be written, writes nothing
    python scripts/grant_trial_gift_first_n.py
    # commit (first 100 signups, 7-day window)
    python scripts/grant_trial_gift_first_n.py --apply
    # commit a different cohort size / window
    python scripts/grant_trial_gift_first_n.py --apply --first-n 50 --days 7
"""
from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone

from google.cloud import firestore

# Tiers that count as an active paid subscription. Mirrors
# ControlPlane._resolve_tier (legacy "paid" rows map to pro).
_PAID_TIERS = {"pro", "max", "paid"}
_REVOKED_STATUSES = {"expired", "revoked"}


def _is_paid(sub: dict | None) -> bool:
    """True only for an active pro/max/paid subscription, matching the
    server's tier resolution. None / free / expired / revoked -> unpaid."""
    if not sub:
        return False
    if (sub.get("status") or "").strip().lower() in _REVOKED_STATUSES:
        return False
    return (sub.get("tier") or "").strip().lower() in _PAID_TIERS


# A datetime so far in the future that users with a missing/None created_at sort
# LAST (after every real signup), and so naive/aware datetimes never collide.
_SORT_LAST = datetime.max.replace(tzinfo=timezone.utc)


def _created_sort_key(created_at: object) -> datetime:
    """Sort key for ascending signup order. Missing/None created_at sorts last.
    Naive datetimes are treated as UTC so they compare cleanly against
    tz-aware ones (Firestore timestamps come back tz-aware, but legacy rows may
    carry naive values)."""
    if not isinstance(created_at, datetime):
        return _SORT_LAST
    if created_at.tzinfo is None:
        return created_at.replace(tzinfo=timezone.utc)
    return created_at.astimezone(timezone.utc)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Commit writes. Without this flag the script only counts and prints.",
    )
    parser.add_argument(
        "--first-n",
        type=int,
        default=100,
        help="How many of the earliest signups to gift (the first-N cohort).",
    )
    parser.add_argument("--days", type=int, default=7, help="Trial window length in days.")
    parser.add_argument("--prefix", default="newsletter_pod")
    parser.add_argument("--project", default="newsletter-pod")
    args = parser.parse_args()

    db = firestore.Client(project=args.project)
    users_col = db.collection(f"{args.prefix}_users")
    subs_col = db.collection(f"{args.prefix}_subscriptions")

    now = datetime.now(timezone.utc)
    trial_ends_at = now + timedelta(days=args.days)

    # Stream every user, then sort ascending by created_at (missing/None last).
    users = [(doc.id, doc.to_dict() or {}) for doc in users_col.stream()]
    users.sort(key=lambda item: _created_sort_key(item[1].get("created_at")))
    scanned = len(users)

    cohort = users[: args.first_n]
    print(f"Scanned {scanned} users; taking the first {len(cohort)} by signup "
          f"order (--first-n {args.first_n}).")
    print(f"Trial window = {args.days} days (ends {trial_ends_at.isoformat()}).")
    print()

    paid_skipped = 0
    granted = 0
    batch = db.batch()
    pending = 0

    for uid, _user in cohort:
        sub_doc = subs_col.document(uid).get()
        sub = sub_doc.to_dict() if sub_doc.exists else None
        if _is_paid(sub):
            # Paid users still occupy a cohort slot — skip the gift for them.
            paid_skipped += 1
            print(f"  skip (paid):  {uid}")
            continue

        granted += 1
        fields = {
            "trial_ends_at": trial_ends_at,
            "trial_gift_granted_at": now,
            "trial_gift_acknowledged_at": None,
            "trial_gift_pushed_at": None,
            "trial_premium_pods_remaining": 0,
            "trial_exhausted_at": None,
            "first_month_ends_at": None,
            "premium_pods_this_week": 0,
            "default_pods_this_week": 0,
            "current_week_iso": None,
            "updated_at": now,
        }

        if not args.apply:
            print(f"  WOULD grant:  {uid} -> {fields}")
            continue

        print(f"  grant:        {uid}")
        batch.update(users_col.document(uid), fields)
        pending += 1
        # Firestore caps batches at 500 ops; flush defensively at 400.
        if pending >= 400:
            batch.commit()
            batch = db.batch()
            pending = 0

    if args.apply and pending:
        batch.commit()

    print()
    print(f"  users scanned:            {scanned}")
    print(f"  cohort size (first N):    {len(cohort)}")
    print(f"  paid (skipped in cohort): {paid_skipped}")
    print(f"  gifted (granted):         {granted}")
    print()
    if args.apply:
        print(f"Committed gifted 7-day full-access trials to {granted} users.")
    else:
        print("(dry run — re-run with --apply to write)")


if __name__ == "__main__":
    main()
