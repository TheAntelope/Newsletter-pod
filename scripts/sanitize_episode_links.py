"""One-shot: sanitize per-subscriber auth tokens out of existing
UserEpisodeRecord documents in Firestore.

Walks every newsletter_pod_user_episodes doc, strips known auth query
params from source_item_refs[*].link, and rewrites the description to
swap old URLs for clean ones. Idempotent.

Usage (Windows PowerShell):
    $env:GOOGLE_CLOUD_PROJECT = "newsletter-pod"
    python scripts/sanitize_episode_links.py            # dry-run
    python scripts/sanitize_episode_links.py --apply    # write
"""
from __future__ import annotations

import argparse
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from google.cloud import firestore

AUTH_QUERY_PARAMS = {
    "access_token",
    "auth_token",
    "passthrough_token",
    "session_token",
    "session",
    "sessionid",
    "sid",
    "secret",
    "key",
    "apikey",
    "api_key",
    "token",
    "auth",
    "password",
    "pwd",
}


def sanitize_link(url: str) -> str:
    if not url:
        return url
    try:
        parts = urlsplit(url)
    except Exception:
        return url
    if not parts.query:
        return url
    kept = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if k.lower() not in AUTH_QUERY_PARAMS
        and not k.lower().endswith("_token")
        and not k.lower().endswith("_key")
    ]
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(kept), parts.fragment))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="write changes (omit for dry run)")
    parser.add_argument("--prefix", default="newsletter_pod", help="firestore collection prefix")
    parser.add_argument("--project", default="newsletter-pod", help="GCP project id")
    args = parser.parse_args()

    db = firestore.Client(project=args.project)
    episodes_col = db.collection(f"{args.prefix}_user_episodes")
    episodes = list(episodes_col.stream())
    print(f"Total episodes: {len(episodes)}")

    affected = 0
    writes = 0

    for doc in episodes:
        data = doc.to_dict()
        refs = data.get("source_item_refs") or []
        replacements: dict[str, str] = {}
        new_refs = []
        for ref in refs:
            old = ref.get("link") or ""
            new = sanitize_link(old)
            if new != old:
                replacements[old] = new
            new_refs.append({**ref, "link": new})

        if not replacements:
            continue

        affected += 1
        title = (data.get("title") or "")[:60]
        print(
            f"\nEpisode {doc.id} (user {(data.get('user_id') or '?')[:8]}) — {title}"
        )
        for old, new in replacements.items():
            print(f"  old: {old}")
            print(f"  new: {new}")

        new_desc = data.get("description") or ""
        desc_changed = False
        for old, new in replacements.items():
            if old in new_desc:
                new_desc = new_desc.replace(old, new)
                desc_changed = True
        if desc_changed:
            print("  description rewritten")

        update: dict[str, object] = {"source_item_refs": new_refs}
        if desc_changed:
            update["description"] = new_desc

        if args.apply:
            episodes_col.document(doc.id).update(update)
            writes += 1
            print("  written")

    print(f"\nAffected: {affected}")
    if args.apply:
        print(f"Wrote: {writes}")
    else:
        print("Dry run — re-run with --apply to write")


if __name__ == "__main__":
    main()
