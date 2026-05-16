"""Reset a single user's onboarding state so the iOS wizard re-runs fresh.

Targets ONE user (looked up by email, apple_subject, user_id, or inbound_alias)
and wipes:

  - {prefix}_user_sources         (where user_id == uid)
  - {prefix}_podcast_profiles/{uid}
  - {prefix}_delivery_schedules/{uid}
  - {prefix}_swipes               (where user_id == uid — includes synthetic
                                    voice_intake / substack_paste /
                                    forwarded_mail seeds)
  - {prefix}_user_substack_intents (where user_id == uid)
  - {prefix}_user_cursors         (where user_id == uid — so re-attached
                                    sources fetch from scratch)
  - {prefix}_users/{uid}.last_weekly_update_iso_week → None

Keeps: user record itself, inbound_alias, feed tokens, subscription, episodes,
runs, cost records, billing events, inbound_items, source_items corpus.

iOS-side reminder: the wizard's "hasCompletedOnboarding" flag is local
UserDefaults. This script cannot clear it. After running this, delete and
reinstall the app on the device for the wizard to re-appear, OR clear app data
under iOS Settings -> ClawCast -> Reset.

Usage (PowerShell):
    $env:GOOGLE_CLOUD_PROJECT = "newsletter-pod"
    # dry-run (default): shows exactly what would be deleted
    python scripts/reset_user.py --email vincemartin1991@gmail.com
    # commit
    python scripts/reset_user.py --email vincemartin1991@gmail.com --apply
"""
from __future__ import annotations

import argparse
import sys
from typing import Optional

from google.cloud import firestore


def _find_user_id(
    db: firestore.Client,
    prefix: str,
    *,
    user_id: Optional[str],
    email: Optional[str],
    apple_subject: Optional[str],
    inbound_alias: Optional[str],
) -> Optional[str]:
    users_col = db.collection(f"{prefix}_users")
    if user_id:
        doc = users_col.document(user_id).get()
        return doc.id if doc.exists else None
    if email:
        # email is case-sensitive in the user record; try common variants.
        for candidate in {email, email.strip(), email.strip().lower()}:
            docs = list(users_col.where("email", "==", candidate).limit(1).stream())
            if docs:
                return docs[0].id
        return None
    if apple_subject:
        docs = list(users_col.where("apple_subject", "==", apple_subject).limit(1).stream())
        return docs[0].id if docs else None
    if inbound_alias:
        docs = list(users_col.where("inbound_alias", "==", inbound_alias).limit(1).stream())
        return docs[0].id if docs else None
    return None


def _delete_where(db: firestore.Client, collection_name: str, field: str, value: str) -> int:
    docs = list(db.collection(collection_name).where(field, "==", value).stream())
    if not docs:
        return 0
    # Firestore caps batches at 500 ops; chunk defensively.
    deleted = 0
    for chunk_start in range(0, len(docs), 400):
        batch = db.batch()
        for doc in docs[chunk_start : chunk_start + 400]:
            batch.delete(doc.reference)
        batch.commit()
        deleted += min(400, len(docs) - chunk_start)
    return deleted


def main() -> None:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--user-id", dest="user_id")
    group.add_argument("--email")
    group.add_argument("--apple-subject", dest="apple_subject")
    group.add_argument("--inbound-alias", dest="inbound_alias")
    parser.add_argument("--apply", action="store_true",
                        help="Commit deletions. Without this flag, the script only prints what it would do.")
    parser.add_argument("--prefix", default="newsletter_pod")
    parser.add_argument("--project", default="newsletter-pod")
    args = parser.parse_args()

    db = firestore.Client(project=args.project)
    uid = _find_user_id(
        db,
        args.prefix,
        user_id=args.user_id,
        email=args.email,
        apple_subject=args.apple_subject,
        inbound_alias=args.inbound_alias,
    )
    if uid is None:
        print("No matching user found.", file=sys.stderr)
        sys.exit(1)

    users_col = db.collection(f"{args.prefix}_users")
    user_doc = users_col.document(uid).get()
    if not user_doc.exists:
        print(f"User {uid} record disappeared between lookup and read.", file=sys.stderr)
        sys.exit(1)
    user_payload = user_doc.to_dict()
    display_email = user_payload.get("email") or "(no email on record)"
    display_alias = user_payload.get("inbound_alias") or "(no alias)"
    last_weekly = user_payload.get("last_weekly_update_iso_week")
    print(f"Resolved user_id={uid}")
    print(f"  email={display_email}")
    print(f"  inbound_alias={display_alias}")
    print(f"  last_weekly_update_iso_week={last_weekly}")
    print()

    sources_col = f"{args.prefix}_user_sources"
    profiles_col = f"{args.prefix}_podcast_profiles"
    schedules_col = f"{args.prefix}_delivery_schedules"
    swipes_col = f"{args.prefix}_swipes"
    intents_col = f"{args.prefix}_user_substack_intents"
    cursors_col = f"{args.prefix}_user_cursors"

    # Pre-count what we'd delete (dry-run friendly).
    source_count = len(list(db.collection(sources_col).where("user_id", "==", uid).stream()))
    profile_exists = db.collection(profiles_col).document(uid).get().exists
    schedule_exists = db.collection(schedules_col).document(uid).get().exists
    swipe_count = len(list(db.collection(swipes_col).where("user_id", "==", uid).stream()))
    intent_count = len(list(db.collection(intents_col).where("user_id", "==", uid).stream()))
    cursor_count = len(list(db.collection(cursors_col).where("user_id", "==", uid).stream()))

    print("Will delete:")
    print(f"  user_sources:           {source_count}")
    print(f"  podcast_profile doc:    {'1' if profile_exists else '0'}")
    print(f"  delivery_schedule doc:  {'1' if schedule_exists else '0'}")
    print(f"  swipes (incl. seeds):   {swipe_count}")
    print(f"  substack_intents:       {intent_count}")
    print(f"  user_cursors:           {cursor_count}")
    print(f"  + reset users/{uid}.last_weekly_update_iso_week -> None")
    print()
    print("Will keep: user record, inbound_alias, feed_tokens, subscription, "
          "episodes, runs, cost_records, billing_events, inbound_items, "
          "source_items corpus.")
    print()

    if not args.apply:
        print("(dry run - re-run with --apply to commit)")
        return

    deleted_sources = _delete_where(db, sources_col, "user_id", uid)
    if profile_exists:
        db.collection(profiles_col).document(uid).delete()
    if schedule_exists:
        db.collection(schedules_col).document(uid).delete()
    deleted_swipes = _delete_where(db, swipes_col, "user_id", uid)
    deleted_intents = _delete_where(db, intents_col, "user_id", uid)
    deleted_cursors = _delete_where(db, cursors_col, "user_id", uid)
    users_col.document(uid).update({"last_weekly_update_iso_week": None})

    print("Committed:")
    print(f"  user_sources deleted:      {deleted_sources}")
    print(f"  podcast_profile deleted:   {1 if profile_exists else 0}")
    print(f"  delivery_schedule deleted: {1 if schedule_exists else 0}")
    print(f"  swipes deleted:            {deleted_swipes}")
    print(f"  substack_intents deleted:  {deleted_intents}")
    print(f"  user_cursors deleted:      {deleted_cursors}")
    print()
    print("Reset complete.")
    print()
    print("On the iOS device:")
    print("  1. Delete the ClawCast app (clears the UserDefaults onboarding flag).")
    print("  2. Reinstall via TestFlight.")
    print("  3. Sign in with the same Apple ID — the wizard will appear fresh.")


if __name__ == "__main__":
    main()
