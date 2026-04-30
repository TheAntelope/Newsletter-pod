"""One-shot: trim every user's saved schedule + profile to fit the
new free-tier caps. The user explicitly asked us to reset the field of
play (no real paid users yet), so we apply free caps universally.

Caps applied (matching newsletter_pod/config.py defaults):
  - weekdays: keep at most FREE_MAX_DELIVERY_DAYS = 5 (drops weekend
    days first, preserving Mon-Fri).
  - desired_duration_minutes: clamped into [3, 5].

Idempotent. Safe to re-run.

Usage (PowerShell):
    $env:GOOGLE_CLOUD_PROJECT = "newsletter-pod"
    python scripts/reset_tier_caps.py            # dry-run
    python scripts/reset_tier_caps.py --apply    # write
"""
from __future__ import annotations

import argparse

from google.cloud import firestore

WEEKDAY_ORDER = [
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
]
MAX_DELIVERY_DAYS = 5
MIN_DURATION_MINUTES = 3
MAX_DURATION_MINUTES = 5


def trim_weekdays(weekdays: list[str]) -> list[str]:
    if not weekdays:
        return ["monday"]
    keep = set(weekdays)
    # Drop in reverse order until we fit the cap.
    for day in reversed(WEEKDAY_ORDER):
        if len(keep) <= MAX_DELIVERY_DAYS:
            break
        if day in keep:
            keep.discard(day)
    # Re-sort canonically.
    return [d for d in WEEKDAY_ORDER if d in keep]


def clamp_duration(value: int) -> int:
    return max(MIN_DURATION_MINUTES, min(MAX_DURATION_MINUTES, value))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--prefix", default="newsletter_pod")
    parser.add_argument("--project", default="newsletter-pod")
    args = parser.parse_args()

    db = firestore.Client(project=args.project)
    schedules_col = db.collection(f"{args.prefix}_delivery_schedules")
    profiles_col = db.collection(f"{args.prefix}_podcast_profiles")

    schedule_writes = 0
    profile_writes = 0

    for doc in schedules_col.stream():
        data = doc.to_dict()
        old = list(data.get("weekdays") or [])
        new = trim_weekdays(old)
        if new == old:
            continue
        print(f"schedule {doc.id}: weekdays {old} -> {new}")
        if args.apply:
            schedules_col.document(doc.id).update({"weekdays": new})
            schedule_writes += 1

    for doc in profiles_col.stream():
        data = doc.to_dict()
        old = data.get("desired_duration_minutes")
        if not isinstance(old, int):
            continue
        new = clamp_duration(old)
        if new == old:
            continue
        print(f"profile  {doc.id}: duration {old} -> {new}")
        if args.apply:
            profiles_col.document(doc.id).update({"desired_duration_minutes": new})
            profile_writes += 1

    print()
    print(f"Schedule changes: {schedule_writes}")
    print(f"Profile changes:  {profile_writes}")
    if not args.apply:
        print("(dry run — re-run with --apply to write)")


if __name__ == "__main__":
    main()
