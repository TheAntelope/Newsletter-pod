"""One-shot: grant every CURRENTLY-UNPAID user a fresh 7-day full-access
(Max) trial starting now.

Background (2026-06-13): the launch model used a pod-count trial
(`trial_premium_pods_remaining`). We replaced it with a time-based 7-day trial:
while `trial_ends_at` is in the future, a free user is computed as Max in
`ControlPlane._compute_entitlements`. New signups get the window at creation;
this script back-grants it to existing unpaid users so the new trial "starts
today" for everyone already on the free plan.

"Unpaid" mirrors `ControlPlane._resolve_tier`: a user is treated as PAID only
when their subscription tier is pro/max/paid AND status is not expired/revoked.
Everyone else (free, expired, revoked, or no subscription doc) is granted.

Per granted user we set:
  - trial_ends_at               -> now + TRIAL_WINDOW_DAYS (default 7)
  - trial_premium_pods_remaining-> 0     (legacy pod trial is superseded)
  - trial_exhausted_at          -> None
  - first_month_ends_at         -> None
  - premium_pods_this_week      -> 0     (fresh full-access week)
  - default_pods_this_week      -> 0
  - current_week_iso            -> None
  - updated_at                  -> now

Paid users are skipped entirely (their tier already sits at/above Max, and the
trial field is ignored for them anyway).

This is a one-shot: re-running RESETS the 7-day clock for every unpaid user.

Usage (PowerShell):
    $env:GOOGLE_CLOUD_PROJECT = "newsletter-pod"
    # dry-run (default): counts paid vs unpaid, writes nothing
    python scripts/grant_time_trial.py
    # commit
    python scripts/grant_time_trial.py --apply
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


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Commit writes. Without this flag the script only counts and prints.",
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

    user_ids = [doc.id for doc in users_col.stream()]
    print(f"Scanned {len(user_ids)} users. Trial window = {args.days} days "
          f"(ends {trial_ends_at.isoformat()}).")
    print()

    paid = 0
    granted = 0
    batch = db.batch()
    pending = 0

    for uid in user_ids:
        sub_doc = subs_col.document(uid).get()
        sub = sub_doc.to_dict() if sub_doc.exists else None
        if _is_paid(sub):
            paid += 1
            continue

        granted += 1
        if not args.apply:
            continue

        batch.update(
            users_col.document(uid),
            {
                "trial_ends_at": trial_ends_at,
                "trial_premium_pods_remaining": 0,
                "trial_exhausted_at": None,
                "first_month_ends_at": None,
                "premium_pods_this_week": 0,
                "default_pods_this_week": 0,
                "current_week_iso": None,
                "updated_at": now,
            },
        )
        pending += 1
        # Firestore caps batches at 500 ops; flush defensively at 400.
        if pending >= 400:
            batch.commit()
            batch = db.batch()
            pending = 0

    if args.apply and pending:
        batch.commit()

    print(f"  paid (skipped):   {paid}")
    print(f"  unpaid (granted): {granted}")
    print()
    if args.apply:
        print(f"Committed 7-day full-access trials to {granted} unpaid users.")
    else:
        print("(dry run — re-run with --apply to write)")


if __name__ == "__main__":
    main()
