"""Pull podcast generation telemetry for Vince Martin.

Looks up the user by email, then reports:
  - Configured delivery schedule (timezone, local_time, cutoff_time, weekdays).
  - Recent runs with wall-clock generation duration (completed_at - started_at).
  - Audio duration of the most recent published episodes.

Usage:
    GOOGLE_CLOUD_PROJECT=newsletter-pod python scripts/vince_generation_telemetry.py
    # optional flags:
    #   --email vincemartin1991@gmail.com
    #   --runs 20
    #   --prefix newsletter_pod
    #   --project newsletter-pod
"""
from __future__ import annotations

import argparse
import statistics
from datetime import datetime, timezone

from google.cloud import firestore


def _fmt_dt(value) -> str:
    if value is None:
        return "-"
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat(timespec="seconds")
    return str(value)


def _duration_seconds(started, completed) -> float | None:
    if not isinstance(started, datetime) or not isinstance(completed, datetime):
        return None
    return (completed - started).total_seconds()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--email", default="vincemartin1991@gmail.com")
    parser.add_argument("--runs", type=int, default=20)
    parser.add_argument("--prefix", default="newsletter_pod")
    parser.add_argument("--project", default="newsletter-pod")
    args = parser.parse_args()

    db = firestore.Client(project=args.project)
    users = db.collection(f"{args.prefix}_users")
    schedules = db.collection(f"{args.prefix}_delivery_schedules")
    runs = db.collection(f"{args.prefix}_user_runs")
    episodes = db.collection(f"{args.prefix}_user_episodes")

    user_docs = list(users.where("email", "==", args.email).limit(1).stream())
    if not user_docs:
        print(f"No user found with email {args.email!r}.")
        return
    user = user_docs[0].to_dict()
    user_id = user.get("id") or user_docs[0].id
    print(f"User: {user.get('display_name') or '-'} <{user.get('email')}>  id={user_id}")
    print()

    sched_doc = schedules.document(user_id).get()
    if sched_doc.exists:
        s = sched_doc.to_dict()
        print("Configured schedule:")
        print(f"  timezone     : {s.get('timezone')}")
        print(f"  local_time   : {s.get('local_time')}   (target generate-by time)")
        print(f"  cutoff_time  : {s.get('cutoff_time')}   (deadline)")
        print(f"  weekdays     : {s.get('weekdays')}")
        print(f"  enabled      : {s.get('enabled')}")
    else:
        print("No delivery schedule record (would fall back to global defaults: 07:00 / 11:00).")
    print()

    run_docs = list(runs.where("user_id", "==", user_id).stream())
    runs_list = [d.to_dict() for d in run_docs]
    runs_list.sort(key=lambda r: r.get("started_at") or datetime.min.replace(tzinfo=timezone.utc), reverse=True)
    runs_list = runs_list[: args.runs]

    print(f"Last {len(runs_list)} runs:")
    print(f"  {'started_at (UTC)':25s}  {'status':12s}  {'wall_secs':>9s}  {'audio_secs':>10s}  message")
    durations: list[float] = []
    for r in runs_list:
        wall = _duration_seconds(r.get("started_at"), r.get("completed_at"))
        if wall is not None:
            durations.append(wall)
        ep_id = r.get("published_episode_id")
        audio_secs = "-"
        if ep_id:
            ep_doc = episodes.document(ep_id).get()
            if ep_doc.exists:
                audio_secs = str(ep_doc.to_dict().get("duration_seconds") or "-")
        print(
            f"  {_fmt_dt(r.get('started_at')):25s}  "
            f"{(r.get('status') or '-'):12s}  "
            f"{(f'{wall:.1f}' if wall is not None else '-'):>9s}  "
            f"{audio_secs:>10s}  "
            f"{(r.get('message') or '')[:60]}"
        )

    print()
    if durations:
        print("Wall-clock generation duration (seconds):")
        print(f"  count  : {len(durations)}")
        print(f"  min    : {min(durations):.1f}")
        print(f"  median : {statistics.median(durations):.1f}")
        print(f"  mean   : {statistics.mean(durations):.1f}")
        print(f"  max    : {max(durations):.1f}")
    else:
        print("No completed runs with both started_at and completed_at to summarize.")


if __name__ == "__main__":
    main()
