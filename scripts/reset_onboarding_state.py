"""One-shot: wipe per-user onboarding-wizard state for every user so the
iOS wizard re-runs on next launch.

Deletes (per user):
  - {prefix}_user_sources    (where user_id == uid)
  - {prefix}_delivery_schedules/{uid}
  - {prefix}_podcast_profiles/{uid}

Keeps: users, feed tokens, subscriptions, episodes (welcome + history),
runs, cursors, costs, billing events, inbound items.

NOTE: the iOS "hasCompletedOnboarding" flag is local UserDefaults; this
script cannot clear it. Testers must delete & reinstall the app for the
wizard to actually appear.

Usage (PowerShell):
    $env:GOOGLE_CLOUD_PROJECT = "newsletter-pod"
    python scripts/reset_onboarding_state.py            # dry-run
    python scripts/reset_onboarding_state.py --apply    # write
"""
from __future__ import annotations

import argparse

from google.cloud import firestore


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--prefix", default="newsletter_pod")
    parser.add_argument("--project", default="newsletter-pod")
    args = parser.parse_args()

    db = firestore.Client(project=args.project)
    users_col = db.collection(f"{args.prefix}_users")
    profiles_col = db.collection(f"{args.prefix}_podcast_profiles")
    sources_col = db.collection(f"{args.prefix}_user_sources")
    schedules_col = db.collection(f"{args.prefix}_delivery_schedules")

    user_ids = [doc.id for doc in users_col.stream()]
    print(f"Found {len(user_ids)} users")

    sources_deleted = 0
    profiles_deleted = 0
    schedules_deleted = 0

    for uid in user_ids:
        src_docs = list(sources_col.where("user_id", "==", uid).stream())
        prof_doc = profiles_col.document(uid).get()
        sched_doc = schedules_col.document(uid).get()

        n_src = len(src_docs)
        has_prof = prof_doc.exists
        has_sched = sched_doc.exists

        print(
            f"user {uid}: sources={n_src} profile={'Y' if has_prof else '-'} schedule={'Y' if has_sched else '-'}"
        )

        if not args.apply:
            continue

        if src_docs:
            batch = db.batch()
            for d in src_docs:
                batch.delete(d.reference)
            batch.commit()
            sources_deleted += n_src
        if has_prof:
            profiles_col.document(uid).delete()
            profiles_deleted += 1
        if has_sched:
            schedules_col.document(uid).delete()
            schedules_deleted += 1

    print()
    print(f"Sources deleted:   {sources_deleted}")
    print(f"Profiles deleted:  {profiles_deleted}")
    print(f"Schedules deleted: {schedules_deleted}")
    if not args.apply:
        print("(dry run — re-run with --apply to write)")


if __name__ == "__main__":
    main()
