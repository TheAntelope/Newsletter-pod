"""Inspect a single user's Substack <-> podcast plumbing.

Pulls everything you'd want to look at to answer the question:
"Why isn't this user's Substack content showing up in their podcasts?"

Reads (never writes) the following Firestore collections for one user:
  - {prefix}_users                (record + inbound_alias)
  - {prefix}_user_substack_intents
  - {prefix}_user_sources         (to see whether any Substack feeds are
                                   actually attached as RSS sources)
  - {prefix}_inbound_items        (recent inbound mail / prefetched posts)
  - {prefix}_user_episodes        (last N, with their source_item_refs)
  - {prefix}_user_runs            (last N, including skipped / no_content)

For each recent episode it also computes the time window since the previous
episode and counts how many inbound items fell into that window, plus whether
any of them showed up in the episode's source_item_refs. That's the smoking
gun for "Substack content arrived but never made it into the script".

Usage (PowerShell):
    $env:GOOGLE_CLOUD_PROJECT = "newsletter-pod"
    python scripts/inspect_user_substack.py --email vincemartin1991@gmail.com
    # bigger windows:
    python scripts/inspect_user_substack.py --email vince... --episodes 10 --inbound 50
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone
from typing import Any, Optional

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
        for candidate in {email, email.strip(), email.strip().lower()}:
            docs = list(users_col.where("email", "==", candidate).limit(1).stream())
            if docs:
                return docs[0].id
        return None
    if apple_subject:
        docs = list(users_col.where("apple_subject", "==", apple_subject).limit(1).stream())
        return docs[0].id if docs else None
    if inbound_alias:
        docs = list(users_col.where("inbound_alias", "==", inbound_alias.lower()).limit(1).stream())
        return docs[0].id if docs else None
    return None


def _fmt_dt(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat(timespec="seconds")
    return str(value)


def _short(value: Any, length: int = 80) -> str:
    if value is None:
        return ""
    text = str(value).replace("\n", " ").strip()
    return text if len(text) <= length else text[: length - 1] + "..."


def _parse_dt(raw: Any) -> Optional[datetime]:
    if raw is None:
        return None
    if isinstance(raw, datetime):
        return raw if raw.tzinfo else raw.replace(tzinfo=timezone.utc)
    try:
        parsed = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def main() -> None:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--user-id", dest="user_id")
    group.add_argument("--email")
    group.add_argument("--apple-subject", dest="apple_subject")
    group.add_argument("--inbound-alias", dest="inbound_alias")
    parser.add_argument("--episodes", type=int, default=5, help="How many recent episodes to inspect.")
    parser.add_argument("--runs", type=int, default=10, help="How many recent runs to list.")
    parser.add_argument("--inbound", type=int, default=20, help="How many recent inbound items to list.")
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

    user_doc = db.collection(f"{args.prefix}_users").document(uid).get()
    if not user_doc.exists:
        print(f"User {uid} disappeared between lookup and read.", file=sys.stderr)
        sys.exit(1)
    user = user_doc.to_dict() or {}

    print("=" * 78)
    print(f"USER {uid}")
    print(f"  email                = {user.get('email')}")
    print(f"  display_name         = {user.get('display_name')}")
    print(f"  inbound_alias        = {user.get('inbound_alias')}  (full: "
          f"{user.get('inbound_alias')}@theclawcast.com)")
    print(f"  created_at           = {_fmt_dt(user.get('created_at'))}")
    print(f"  trial_remaining      = {user.get('trial_premium_pods_remaining')}")
    print(f"  premium_this_week    = {user.get('premium_pods_this_week')}")
    print(f"  default_this_week    = {user.get('default_pods_this_week')}")
    print()

    # --- Substack intents ----------------------------------------------------
    intent_docs = list(
        db.collection(f"{args.prefix}_user_substack_intents")
        .where("user_id", "==", uid)
        .stream()
    )
    print("=" * 78)
    print(f"SUBSTACK INTENTS ({len(intent_docs)})")
    intent_hosts: set[str] = set()
    intent_pub_titles: dict[str, str] = {}
    for doc in intent_docs:
        i = doc.to_dict() or {}
        host = (i.get("pub_host") or "").lower()
        intent_hosts.add(host)
        if i.get("pub_title"):
            intent_pub_titles[host] = i["pub_title"]
        print(f"  - {host}")
        print(f"      title           : {i.get('pub_title')}")
        print(f"      author          : {i.get('pub_author')}")
        print(f"      has_paid_tier   : {i.get('has_paid_tier')}")
        print(f"      created_at      : {_fmt_dt(i.get('created_at'))}")
        print(f"      auto_confirmed  : {_fmt_dt(i.get('auto_confirmed_at'))}")
        print(f"      confirmed_at    : {_fmt_dt(i.get('confirmed_at'))}")
        print(f"      alias_email     : {i.get('alias_email')}")
    if not intent_docs:
        print("  (none)")
    print()

    # --- User RSS sources -----------------------------------------------------
    source_docs = list(
        db.collection(f"{args.prefix}_user_sources")
        .where("user_id", "==", uid)
        .stream()
    )
    print("=" * 78)
    print(f"USER RSS SOURCES ({len(source_docs)})")
    substack_in_sources: list[str] = []
    for doc in source_docs:
        s = doc.to_dict() or {}
        rss = s.get("rss_url") or ""
        is_substack = "substack.com" in rss.lower() or any(h in rss.lower() for h in intent_hosts)
        marker = "  [SUBSTACK]" if is_substack else ""
        print(f"  - {s.get('name')}  ({'on' if s.get('enabled') else 'OFF'}){marker}")
        print(f"      source_id : {s.get('source_id')}")
        print(f"      rss_url   : {rss}")
        if is_substack:
            substack_in_sources.append(rss)
    if not source_docs:
        print("  (none)")
    print()
    if intent_hosts and not substack_in_sources:
        print(f"  ! {len(intent_hosts)} Substack intent(s) exist but NO Substack RSS feed")
        print(f"    appears in user_sources. The ingestion pipeline reads from")
        print(f"    user_sources only — Substack content won't be ingested via RSS.")
        print()

    # --- Inbound items --------------------------------------------------------
    inbound_docs = list(
        db.collection(f"{args.prefix}_inbound_items")
        .where("user_id", "==", uid)
        .order_by("received_at", direction=firestore.Query.DESCENDING)
        .limit(args.inbound)
        .stream()
    )
    print("=" * 78)
    print(f"RECENT INBOUND ITEMS ({len(inbound_docs)} of last {args.inbound})")
    inbound: list[dict[str, Any]] = []
    for doc in inbound_docs:
        item = doc.to_dict() or {}
        item["_received_dt"] = _parse_dt(item.get("received_at"))
        inbound.append(item)
        host = (item.get("sender_domain") or "").lower()
        intent_match = "[Substack-intent match]" if host in intent_hosts else ""
        sub_marker = "[substack.com sender]" if "substack.com" in host else ""
        consumed = "[CONSUMED]" if item.get("consumed_at") else "[unused]"
        print(
            f"  {_fmt_dt(item.get('received_at'))}  "
            f"{consumed} {sub_marker} {intent_match}"
        )
        print(f"      from   : {item.get('from_email')}  ({item.get('from_name')})")
        print(f"      domain : {host}")
        print(f"      subject: {_short(item.get('subject'), 100)}")
        print(f"      article: {item.get('article_url')}")
    if not inbound_docs:
        print("  (none)")
    print()

    # --- Recent episodes ------------------------------------------------------
    episode_docs = list(
        db.collection(f"{args.prefix}_user_episodes")
        .where("user_id", "==", uid)
        .stream()
    )
    episodes = [doc.to_dict() or {} for doc in episode_docs]
    for ep in episodes:
        ep["_published_dt"] = _parse_dt(ep.get("published_at"))
    episodes = [ep for ep in episodes if ep["_published_dt"] is not None]
    episodes.sort(key=lambda ep: ep["_published_dt"], reverse=True)
    episodes = episodes[: args.episodes]

    print("=" * 78)
    print(f"LAST {len(episodes)} EPISODES (newest first)")
    print()
    for idx, ep in enumerate(episodes):
        published = ep["_published_dt"]
        prev_published = (
            episodes[idx + 1]["_published_dt"] if idx + 1 < len(episodes) else None
        )
        refs = ep.get("source_item_refs") or []
        ref_sources = sorted({r.get("source_name", "") for r in refs})

        # Did any source_item_ref match a Substack intent / known substack host?
        substack_refs = []
        for r in refs:
            blob = " ".join(
                str(v or "").lower() for v in (r.get("source_name"), r.get("link"), r.get("title"))
            )
            if "substack.com" in blob or any(h and h in blob for h in intent_hosts):
                substack_refs.append(r)

        # Inbound items that arrived in this episode's window
        if prev_published is not None:
            window = [it for it in inbound if prev_published < it["_received_dt"] <= published]
            window_label = f"({_fmt_dt(prev_published)} -> {_fmt_dt(published)}]"
        else:
            window = [it for it in inbound if it["_received_dt"] <= published]
            window_label = f"(<= {_fmt_dt(published)})"
        window_substack = [
            it for it in window
            if "substack.com" in (it.get("sender_domain") or "").lower()
            or (it.get("sender_domain") or "").lower() in intent_hosts
        ]

        print(f"  [{idx}] {ep.get('title')}")
        print(f"      id           : {ep.get('id')}")
        print(f"      published_at : {_fmt_dt(published)}")
        print(f"      duration_s   : {ep.get('duration_seconds')}")
        print(f"      processed    : {ep.get('processed_item_count')}  "
              f"dropped={ep.get('dropped_item_count')}  cap_hit={ep.get('cap_hit')}")
        print(f"      ref sources  : {', '.join(ref_sources) if ref_sources else '(none)'}")
        print(f"      substack refs in episode : {len(substack_refs)}")
        for r in substack_refs:
            print(f"        - {r.get('source_name')}  |  {_short(r.get('title'), 70)}")
        print(f"      inbound window {window_label}")
        print(f"      inbound items in window  : {len(window)}  "
              f"(substack-shaped: {len(window_substack)})")
        for it in window_substack:
            print(f"        - {_fmt_dt(it['_received_dt'])}  "
                  f"{it.get('sender_domain')}  |  {_short(it.get('subject'), 70)}")
        if window_substack and not substack_refs:
            print(f"      !! {len(window_substack)} Substack inbound item(s) arrived in window")
            print(f"         but none appear in this episode's source_item_refs.")
        print()

    # --- Recent runs (catches skips / no_content) ----------------------------
    run_docs = list(
        db.collection(f"{args.prefix}_user_runs")
        .where("user_id", "==", uid)
        .stream()
    )
    runs = [doc.to_dict() or {} for doc in run_docs]
    for r in runs:
        r["_started_dt"] = _parse_dt(r.get("started_at"))
    runs = [r for r in runs if r["_started_dt"] is not None]
    runs.sort(key=lambda r: r["_started_dt"], reverse=True)
    runs = runs[: args.runs]

    print("=" * 78)
    print(f"LAST {len(runs)} RUNS")
    for r in runs:
        print(
            f"  {_fmt_dt(r['_started_dt'])}  "
            f"{r.get('status'):<12}  "
            f"candidates={r.get('candidate_count')}  "
            f"processed={r.get('processed_item_count')}  "
            f"ep={r.get('published_episode_id') or '-'}"
        )
        if r.get("message"):
            print(f"      msg: {_short(r.get('message'), 100)}")
    if not runs:
        print("  (none)")
    print()

    # --- Summary -------------------------------------------------------------
    print("=" * 78)
    print("SUMMARY")
    print(f"  Substack intents      : {len(intent_docs)}")
    print(f"  Substack-shaped feeds in user_sources : {len(substack_in_sources)}")
    print(f"  Inbound items (window)                : {len(inbound)}")
    sub_inbound = [
        it for it in inbound
        if "substack.com" in (it.get("sender_domain") or "").lower()
        or (it.get("sender_domain") or "").lower() in intent_hosts
    ]
    print(f"    of which substack-shaped            : {len(sub_inbound)}")
    consumed = [it for it in sub_inbound if it.get("consumed_at")]
    print(f"    of which marked consumed_at         : {len(consumed)}")
    print()
    if intent_hosts and not substack_in_sources and sub_inbound and not consumed:
        print("  Diagnosis: Substack intents are saving inbound items, but those items")
        print("  are never being attached to an episode (consumed_at is unset on all of")
        print("  them) and no Substack feed shows up in user_sources. That matches the")
        print("  expected behavior of process_user_generation, which only pulls items")
        print("  from RSSIngestionService over user_sources. See control_plane.py:1480.")


if __name__ == "__main__":
    main()
