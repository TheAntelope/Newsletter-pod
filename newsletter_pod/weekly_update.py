from __future__ import annotations

import json
import logging
import subprocess
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# How far back to scan for commits when assembling the weekly recap.
DEFAULT_WINDOW_DAYS = 14

# Cap so a noisy week can't bloat the prompt.
MAX_COMMITS = 30

SNAPSHOT_FILENAME = "weekly_changes.json"


def iso_week_key(value: date) -> str:
    """Return the ISO year-week label for `value`, e.g. ``"2026-W19"``.

    Used to gate the once-per-week update so we deliver it on the first
    generation in each ISO week and skip on subsequent runs in that week.
    """
    iso = value.isocalendar()
    return f"{iso.year:04d}-W{iso.week:02d}"


def load_recent_commits(
    *,
    project_root: Path,
    now: Optional[datetime] = None,
    window_days: int = DEFAULT_WINDOW_DAYS,
) -> list[str]:
    """Return commit subjects from the last `window_days`, newest first.

    Tries the local git history first (works in dev and tests). If `.git` is
    not present — the deployed Cloud Run image ships without it — falls back
    to a JSON snapshot at ``<project_root>/weekly_changes.json`` produced at
    build/deploy time by ``scripts/snapshot_weekly_changes.py``.
    """
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(days=window_days)

    git_dir = project_root / ".git"
    if git_dir.exists():
        commits = _load_from_git(project_root, cutoff)
        if commits:
            return commits[:MAX_COMMITS]

    snapshot = project_root / SNAPSHOT_FILENAME
    if snapshot.exists():
        return _load_from_snapshot(snapshot, cutoff)[:MAX_COMMITS]

    return []


def _load_from_git(project_root: Path, cutoff: datetime) -> list[str]:
    try:
        result = subprocess.run(
            [
                "git",
                "log",
                f"--since={cutoff.isoformat()}",
                "--pretty=format:%s",
            ],
            cwd=str(project_root),
            capture_output=True,
            text=True,
            check=True,
            timeout=10,
        )
    except (subprocess.SubprocessError, FileNotFoundError) as exc:
        logger.warning("git log failed for weekly update: %s", exc)
        return []
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _load_from_snapshot(path: Path, cutoff: datetime) -> list[str]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        logger.warning("Failed to read %s: %s", path, exc)
        return []

    entries = payload.get("commits") if isinstance(payload, dict) else payload
    if not isinstance(entries, list):
        return []

    cutoff_naive = cutoff.replace(tzinfo=None) if cutoff.tzinfo else cutoff
    keep: list[tuple[datetime, str]] = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        subject = (entry.get("subject") or "").strip()
        if not subject:
            continue
        when = _parse_iso_datetime(entry.get("date"))
        if when is None:
            continue
        when_naive = when.replace(tzinfo=None) if when.tzinfo else when
        if when_naive < cutoff_naive:
            continue
        keep.append((when_naive, subject))

    keep.sort(key=lambda pair: pair[0], reverse=True)
    return [subject for _, subject in keep]


def _parse_iso_datetime(value: object) -> Optional[datetime]:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        try:
            return datetime.combine(date.fromisoformat(text), datetime.min.time())
        except ValueError:
            return None
