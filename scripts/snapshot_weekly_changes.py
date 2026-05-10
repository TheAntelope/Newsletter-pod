"""Snapshot recent git commits into weekly_changes.json.

Run before building the deployed Cloud Run image so the runtime can read a
recent commit history without needing the .git directory inside the image.

The runtime (newsletter_pod.weekly_update.load_recent_commits) prefers the
local git history when .git is present and only falls back to this snapshot
in deployed environments.

Usage::

    python scripts/snapshot_weekly_changes.py            # default 21-day window
    python scripts/snapshot_weekly_changes.py --days 30
"""
from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_PATH = PROJECT_ROOT / "weekly_changes.json"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=21)
    args = parser.parse_args()

    cutoff = datetime.now(timezone.utc) - timedelta(days=args.days)
    result = subprocess.run(
        [
            "git",
            "log",
            f"--since={cutoff.isoformat()}",
            "--pretty=format:%cI%x09%s",
        ],
        cwd=str(PROJECT_ROOT),
        capture_output=True,
        text=True,
        check=True,
    )

    commits = []
    for line in result.stdout.splitlines():
        if "\t" not in line:
            continue
        iso, subject = line.split("\t", 1)
        subject = subject.strip()
        if subject:
            commits.append({"date": iso.strip(), "subject": subject})

    payload = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window_days": args.days,
        "commits": commits,
    }
    OUTPUT_PATH.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {len(commits)} commits to {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
