"""Read-only: verify a user's registered device tokens + recent episodes.

Confirms the pod-ready push chain end-to-end on the data side:
  - which collection prefix prod actually uses
  - the user's active device tokens (platform / transport / env / last_seen)
  - the most recent published episode + run (so we know generation works)

Usage (PowerShell):
    $env:GOOGLE_CLOUD_PROJECT = "newsletter-pod"
    python scripts/check_push_tokens.py --email vincemartin1991@gmail.com
    python scripts/check_push_tokens.py --alias 6hk6266a
"""
from __future__ import annotations

import argparse
import sys

from google.cloud import firestore

CANDIDATE_PREFIXES = ["newsletter_pod", "control_plane"]


def _find(db, prefix, *, email=None, alias=None, user_id=None):
    users = db.collection(f"{prefix}_users")
    if user_id:
        doc = users.document(user_id).get()
        return doc.id if doc.exists else None
    if email:
        for cand in {email, email.strip(), email.strip().lower()}:
            docs = list(users.where("email", "==", cand).limit(1).stream())
            if docs:
                return docs[0].id
    if alias:
        for cand in {alias, f"{alias}@theclawcast.com"}:
            docs = list(users.where("inbound_alias", "==", cand).limit(1).stream())
            if docs:
                return docs[0].id
    return None


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--email")
    ap.add_argument("--alias")
    ap.add_argument("--user-id", dest="user_id")
    ap.add_argument("--project", default="newsletter-pod")
    args = ap.parse_args()

    db = firestore.Client(project=args.project)

    prefix = uid = None
    for p in CANDIDATE_PREFIXES:
        found = _find(db, p, email=args.email, alias=args.alias, user_id=args.user_id)
        if found:
            prefix, uid = p, found
            break

    if not uid:
        print("No matching user found in any candidate prefix.", file=sys.stderr)
        sys.exit(1)

    user = db.collection(f"{prefix}_users").document(uid).get().to_dict() or {}
    print(f"prefix={prefix}")
    print(f"user_id={uid}")
    print(f"  email={user.get('email')!r}")
    print(f"  inbound_alias={user.get('inbound_alias')!r}")
    print(f"  apple_subject={user.get('apple_subject')!r}")
    print(f"  google_subject={user.get('google_subject')!r}")
    print()

    # --- device tokens ---
    toks = list(
        db.collection(f"{prefix}_device_tokens").where("user_id", "==", uid).stream()
    )
    print(f"device_tokens: {len(toks)} total")
    active = 0
    for t in toks:
        d = t.to_dict()
        inval = d.get("invalidated_at")
        if inval is None:
            active += 1
        print(
            f"  - platform={d.get('platform')} transport={d.get('transport')} "
            f"env={d.get('environment')} bundle={d.get('bundle_id')} "
            f"last_seen={d.get('last_seen_at')} "
            f"invalidated={inval} token=…{str(d.get('token'))[-8:]}"
        )
    print(f"  -> {active} ACTIVE (non-invalidated)")
    print()

    # --- recent episodes / runs ---
    # Equality-only filter (no composite index needed); sort client-side.
    eps = [
        e.to_dict()
        for e in db.collection(f"{prefix}_user_episodes")
        .where("user_id", "==", uid)
        .stream()
    ]
    eps.sort(key=lambda d: str(d.get("created_at")), reverse=True)
    print(f"recent episodes: {len(eps)} total")
    for d in eps[:3]:
        print(
            f"  - id={d.get('id')} created_at={d.get('created_at')} "
            f"title={str(d.get('title'))[:50]!r}"
        )


if __name__ == "__main__":
    main()
