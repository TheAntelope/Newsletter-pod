"""Heal pre-existing duplicate accounts (same person, two providers).

Cross-provider linking (control_plane._try_link_by_verified_email) stops NEW
duplicates from forming, but accounts created before it shipped — e.g. an Apple
(iOS) account and a Firebase/Google (Android) account for the same email — must
be merged by hand. This is that tool.

Read-only by default. Two modes:

    # 1) Audit: list every group of users sharing a normalized email.
    $env:GOOGLE_CLOUD_PROJECT = "newsletter-pod"
    python scripts/merge_accounts.py --audit

    # 2) Merge a specific pair: attach the absorbed account's identities to the
    #    canonical account, re-point the absorbed account's CONTENT to canonical,
    #    then delete the absorbed user doc. Dry-run unless --apply is passed.
    python scripts/merge_accounts.py --canonical <CANON_ID> --absorb <ABSORB_ID>
    python scripts/merge_accounts.py --canonical <CANON_ID> --absorb <ABSORB_ID> --apply

Canonical keeps its own singletons (profile, subscription, schedule, feed token,
churn snapshot). Only additive content is re-pointed. Pick the richer / primary
account (usually the Apple one) as canonical. A backup of the absorbed user doc
is written before deletion.

Caveat: a RevenueCat entitlement bought under the absorbed account's app_user_id
does not carry to the canonical id — reconcile billing separately if needed.
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any

from google.cloud import firestore

PREFIX = "newsletter_pod"

# Collections that carry a `user_id` field and hold per-user *content* that
# should follow the user into the canonical account. Singletons keyed by user_id
# as the doc id (profiles, subscriptions, delivery_schedules, churn_risks) are
# deliberately excluded — the canonical account keeps its own.
CONTENT_COLLECTIONS = [
    "user_sources",
    "user_episodes",
    "user_runs",
    "inbound_items",
    "feedback",
    "swipes",
    "swipe_decks",
    "user_substack_intents",
    "device_tokens",
    "next_episode_overrides",
    "cost_records",
    "billing_events",
]


def _normalize_email(email: Any) -> str | None:
    if not email or not isinstance(email, str):
        return None
    return email.strip().lower() or None


def _audit(db: firestore.Client) -> None:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for doc in db.collection(f"{PREFIX}_users").stream():
        data = doc.to_dict() or {}
        email = _normalize_email(data.get("email"))
        if email:
            groups[email].append({"id": doc.id, **data})
    dupes = {e: us for e, us in groups.items() if len(us) > 1}
    if not dupes:
        print("No duplicate-email account groups found.")
        return
    print(f"{len(dupes)} duplicate-email group(s):\n")
    for email, users in sorted(dupes.items()):
        print(f"  {email}  ({len(users)} accounts)")
        for u in sorted(users, key=lambda x: str(x.get("created_at"))):
            prov = u.get("identity_provider")
            apple = "apple" if u.get("apple_subject") else None
            provs = ",".join(p for p in {prov, apple} if p) or "-"
            print(f"    - {u['id']}  created={str(u.get('created_at'))[:19]}  "
                  f"providers={provs}  name={u.get('display_name')!r}")
        print()
    print("To merge a pair:\n  python scripts/merge_accounts.py "
          "--canonical <id> --absorb <id> [--apply]")


def _identities_of(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Reconstruct the identity list from a user doc, folding in legacy fields."""
    out: list[dict[str, Any]] = list(data.get("identities") or [])
    seen = {(i.get("provider"), i.get("subject")) for i in out}
    if data.get("identity_provider") and data.get("provider_subject"):
        key = (data["identity_provider"], data["provider_subject"])
        if key not in seen:
            out.append({"provider": key[0], "subject": key[1],
                        "email": _normalize_email(data.get("email")),
                        "email_verified": False, "linked_at": None})
            seen.add(key)
    if data.get("apple_subject") and ("apple", data["apple_subject"]) not in seen:
        out.append({"provider": "apple", "subject": data["apple_subject"],
                    "email": _normalize_email(data.get("email")),
                    "email_verified": False, "linked_at": None})
    return out


def _merge(db: firestore.Client, canonical_id: str, absorb_id: str, apply: bool) -> None:
    users = db.collection(f"{PREFIX}_users")
    canon_doc = users.document(canonical_id).get()
    absorb_doc = users.document(absorb_id).get()
    assert canon_doc.exists, f"canonical {canonical_id} not found"
    assert absorb_doc.exists, f"absorbed {absorb_id} not found"
    assert canonical_id != absorb_id, "canonical and absorb must differ"
    canon = canon_doc.to_dict() or {}
    absorb = absorb_doc.to_dict() or {}

    # Merge identity sets (canonical's + absorbed's), dedup by (provider, subject).
    merged: list[dict[str, Any]] = []
    seen: set[tuple] = set()
    for ident in _identities_of(canon) + _identities_of(absorb):
        key = (ident.get("provider"), ident.get("subject"))
        if key not in seen:
            seen.add(key)
            merged.append(ident)
    identity_keys = sorted({f"{i['provider']}:{i['subject']}" for i in merged})

    print(f"=== MERGE {absorb_id}  ->  {canonical_id} {'(APPLY)' if apply else '(dry-run)'} ===")
    print(f"  canonical email={canon.get('email')}  absorbed email={absorb.get('email')}")
    print(f"  merged identities: {identity_keys}")

    # Count content to re-point.
    plan: dict[str, list[str]] = {}
    for coll in CONTENT_COLLECTIONS:
        ids = [d.id for d in db.collection(f"{PREFIX}_{coll}")
               .where("user_id", "==", absorb_id).stream()]
        if ids:
            plan[coll] = ids
        print(f"  {coll}: {len(ids)} doc(s) to re-point")

    if not apply:
        print("\n(dry-run) re-run with --apply to execute.")
        return

    # Backup the absorbed user doc.
    backup_path = f"scripts/_merge_backup_{absorb_id}.json"
    with open(backup_path, "w", encoding="utf-8") as fh:
        json.dump(absorb, fh, default=str, indent=2)
    print(f"  backup: {backup_path}")

    # 1) Update canonical with the merged identity set + keys.
    users.document(canonical_id).update({
        "identities": merged,
        "identity_keys": identity_keys,
        "updated_at": datetime.now(timezone.utc),
    })
    # 2) Re-point content docs.
    repointed = 0
    for coll, ids in plan.items():
        col = db.collection(f"{PREFIX}_{coll}")
        for doc_id in ids:
            col.document(doc_id).update({"user_id": canonical_id})
            repointed += 1
    print(f"  re-pointed {repointed} content doc(s)")
    # 3) Delete the absorbed user doc (content now lives under canonical).
    users.document(absorb_id).delete()
    print(f"  deleted absorbed user {absorb_id}")
    print("  done.")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--audit", action="store_true", help="list duplicate-email groups")
    ap.add_argument("--canonical", help="account id to keep")
    ap.add_argument("--absorb", help="account id to fold in and delete")
    ap.add_argument("--apply", action="store_true", help="execute (default: dry-run)")
    args = ap.parse_args()

    db = firestore.Client()
    if args.audit or not (args.canonical and args.absorb):
        _audit(db)
        return
    _merge(db, args.canonical, args.absorb, args.apply)


if __name__ == "__main__":
    main()
