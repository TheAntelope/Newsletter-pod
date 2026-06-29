"""Create, list, and deactivate promo codes.

A promo code grants free full-access (Max) time when a user enters it in the
app (POST /v1/me/redeem). The grant reuses the trial lever: redeeming sets the
user's `trial_ends_at` to now + `grant_days`, so a free user is computed as Max
until it lapses (see ControlPlane._compute_entitlements). One shared code can be
handed out broadly and still bounded by `max_redemptions` (enforced atomically
at redemption time) and, optionally, an `expires_at` redemption window.

Storage matches the app: the FirestoreControlPlaneRepository writes the
`{prefix}_promo_codes` collection with the doc id == the normalized code, so the
backend reads exactly what this script writes.

Usage (PowerShell):
    $env:GOOGLE_CLOUD_PROJECT = "newsletter-pod"

    # Create a single shared code: 1 year free, capped at 500 redemptions.
    python scripts/manage_promo_codes.py create --code CLAWCAST1YR --days 365 \
        --max 500 --label "Launch promo" --apply
    # Optional redemption window (code stops working after this date):
    #   --expires 2026-12-31

    # List every code with its usage.
    python scripts/manage_promo_codes.py list

    # Turn a code off (existing redemptions keep their granted time).
    python scripts/manage_promo_codes.py deactivate --code CLAWCAST1YR --apply

Mutating actions (create / deactivate) are dry-run by default; pass --apply to
write. `list` always reads.
"""
from __future__ import annotations

import argparse
import os
from datetime import datetime, timezone

from newsletter_pod.user_models import PromoCodeRecord
from newsletter_pod.user_repository import FirestoreControlPlaneRepository
from newsletter_pod.utils import utc_now


def _normalize(code: str) -> str:
    # Must match ControlPlane.normalize_promo_code so the doc id the app looks
    # up equals what we write here.
    return (code or "").strip().upper()


def _parse_expires(value: str | None) -> datetime | None:
    if not value:
        return None
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _repo(args: argparse.Namespace) -> FirestoreControlPlaneRepository:
    # FirestoreControlPlaneRepository() builds firestore.Client() off the
    # ambient project; set it explicitly so --project works like the other
    # scripts (e.g. grant_time_trial.py).
    os.environ.setdefault("GOOGLE_CLOUD_PROJECT", args.project)
    return FirestoreControlPlaneRepository(args.prefix)


def _fmt(record: PromoCodeRecord) -> str:
    cap = "∞" if record.max_redemptions is None else str(record.max_redemptions)
    expires = record.expires_at.date().isoformat() if record.expires_at else "—"
    state = "active" if record.active else "OFF"
    label = f"  “{record.label}”" if record.label else ""
    return (
        f"  {record.code:<20} {state:<7} "
        f"{record.redemptions_used}/{cap} used  "
        f"grant={record.grant_days}d  expires={expires}{label}"
    )


def _create(args: argparse.Namespace) -> None:
    code = _normalize(args.code)
    if not code:
        raise SystemExit("--code is required and cannot be empty.")
    max_redemptions = None if args.max is not None and args.max <= 0 else args.max
    expires_at = _parse_expires(args.expires)

    repo = _repo(args)
    existing = repo.get_promo_code(code)
    if existing is not None and not args.force:
        raise SystemExit(
            f"Code {code!r} already exists ({existing.redemptions_used} redemptions). "
            f"Pass --force to overwrite (this RESETS the redemption counter)."
        )

    now = utc_now()
    record = PromoCodeRecord(
        code=code,
        grant_days=args.days,
        max_redemptions=max_redemptions,
        redemptions_used=0,
        active=True,
        expires_at=expires_at,
        label=args.label,
        created_at=now if existing is None else existing.created_at,
        updated_at=now,
    )

    cap = "unlimited" if max_redemptions is None else str(max_redemptions)
    print(
        f"{'Creating' if existing is None else 'OVERWRITING'} code {code}: "
        f"grant={args.days}d, cap={cap}, "
        f"expires={expires_at.isoformat() if expires_at else 'never'}, "
        f"label={args.label!r}"
    )
    if not args.apply:
        print("(dry run — re-run with --apply to write)")
        return
    repo.save_promo_code(record)
    print("Saved.")


def _list(args: argparse.Namespace) -> None:
    repo = _repo(args)
    records = repo.list_promo_codes()
    if not records:
        print("No promo codes.")
        return
    print(f"{len(records)} promo code(s):")
    for record in records:
        print(_fmt(record))


def _deactivate(args: argparse.Namespace) -> None:
    code = _normalize(args.code)
    repo = _repo(args)
    record = repo.get_promo_code(code)
    if record is None:
        raise SystemExit(f"No such code: {code!r}")
    if not record.active:
        print(f"Code {code} is already inactive — nothing to do.")
        return
    print(f"Deactivating {code} ({record.redemptions_used} redemptions so far).")
    if not args.apply:
        print("(dry run — re-run with --apply to write)")
        return
    record.active = False
    record.updated_at = utc_now()
    repo.save_promo_code(record)
    print("Deactivated. Existing redemptions keep their granted time.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--prefix", default="newsletter_pod")
    parser.add_argument("--project", default="newsletter-pod")
    sub = parser.add_subparsers(dest="command", required=True)

    p_create = sub.add_parser("create", help="Create (or --force overwrite) a code.")
    p_create.add_argument("--code", required=True)
    p_create.add_argument("--days", type=int, default=365, help="Days of access granted per redemption.")
    p_create.add_argument(
        "--max",
        type=int,
        default=500,
        help="Total redemption cap across all users (<= 0 means unlimited).",
    )
    p_create.add_argument("--expires", help="Redemption window end (ISO date, e.g. 2026-12-31). Optional.")
    p_create.add_argument("--label", help="Human note shown in `list`.")
    p_create.add_argument("--force", action="store_true", help="Overwrite an existing code (RESETS its counter).")
    p_create.add_argument("--apply", action="store_true", help="Commit the write.")
    p_create.set_defaults(func=_create)

    p_list = sub.add_parser("list", help="List all codes with usage.")
    p_list.set_defaults(func=_list)

    p_deact = sub.add_parser("deactivate", help="Turn a code off.")
    p_deact.add_argument("--code", required=True)
    p_deact.add_argument("--apply", action="store_true", help="Commit the write.")
    p_deact.set_defaults(func=_deactivate)

    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
