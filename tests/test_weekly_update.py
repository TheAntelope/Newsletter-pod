from __future__ import annotations

import json
from datetime import date, datetime, timezone

from newsletter_pod.weekly_update import iso_week_key, load_recent_commits


def test_iso_week_key_uses_iso_year_and_week():
    # 2026-01-01 is a Thursday and falls in ISO week 1 of 2026.
    assert iso_week_key(date(2026, 1, 1)) == "2026-W01"
    # 2025-12-29 (Monday) is the start of ISO week 1 of 2026.
    assert iso_week_key(date(2025, 12, 29)) == "2026-W01"
    # 2026-05-04 → ISO week 19.
    assert iso_week_key(date(2026, 5, 4)) == "2026-W19"


def test_load_recent_commits_reads_snapshot_when_no_git(tmp_path):
    snapshot = {
        "commits": [
            {"date": "2026-05-08T12:00:00+00:00", "subject": "Recent fun feature"},
            {"date": "2026-04-01T12:00:00+00:00", "subject": "Old technical refactor"},
            {"date": "2026-05-09T12:00:00+00:00", "subject": "Another listener improvement"},
        ],
    }
    (tmp_path / "weekly_changes.json").write_text(json.dumps(snapshot), encoding="utf-8")

    commits = load_recent_commits(
        project_root=tmp_path,
        now=datetime(2026, 5, 10, tzinfo=timezone.utc),
        window_days=14,
    )

    # Old commit is dropped, recent two remain newest-first.
    assert commits == [
        "Another listener improvement",
        "Recent fun feature",
    ]


def test_load_recent_commits_returns_empty_when_no_sources(tmp_path):
    commits = load_recent_commits(
        project_root=tmp_path,
        now=datetime(2026, 5, 10, tzinfo=timezone.utc),
    )
    assert commits == []
