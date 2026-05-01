"""One-shot: re-point every podcast profile from the old Demi Dreams
ElevenLabs voice ID to the new one. Users who explicitly picked Demi
in the iOS picker have it stored on `PodcastProfileRecord.voice_id`,
so a code-default change alone leaves them on the retired voice.

Idempotent. Safe to re-run.

Usage (PowerShell):
    $env:GOOGLE_CLOUD_PROJECT = "newsletter-pod"
    python scripts/migrate_demi_dreams_voice_id.py            # dry-run
    python scripts/migrate_demi_dreams_voice_id.py --apply    # write
"""
from __future__ import annotations

import argparse

from google.cloud import firestore

OLD_VOICE_ID = "suMMgpGbVcnihP1CcgFS"
NEW_VOICE_ID = "RKCbSROXui75bk1SVpy8"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--prefix", default="newsletter_pod")
    parser.add_argument("--project", default="newsletter-pod")
    args = parser.parse_args()

    db = firestore.Client(project=args.project)
    profiles_col = db.collection(f"{args.prefix}_podcast_profiles")

    writes = 0
    for doc in profiles_col.where("voice_id", "==", OLD_VOICE_ID).stream():
        print(f"profile {doc.id}: voice_id {OLD_VOICE_ID} -> {NEW_VOICE_ID}")
        if args.apply:
            profiles_col.document(doc.id).update({"voice_id": NEW_VOICE_ID})
            writes += 1

    print()
    print(f"Profile changes: {writes}")
    if not args.apply:
        print("(dry run — re-run with --apply to write)")


if __name__ == "__main__":
    main()
