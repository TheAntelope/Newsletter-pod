"""Admin metrics endpoint backing /admin/metrics.

Phase 2 deliverable. Two responsibilities:

1. Decide who's an admin (`is_admin`) — ADMIN_USER_IDS env var, comma-separated.
2. Assemble the data shown on /admin/metrics — both the global summary
   (Firestore-derivable tiles only) and the per-user timeline.

Event-driven tiles (DAU, activation funnel, retention, episode
completion, churn risk) cannot be computed from Firestore — events live
in Cloud Logging and flow to BigQuery via the sink documented in
infra/bigquery_setup.md. Those tiles render as placeholders pointing
at the BigQuery views in infra/bigquery_views.sql.

Admin traffic is tiny (one operator, occasional checks), so this module
deliberately does live Firestore reads on every request rather than
caching. Each call is bounded by the per-collection `limit` arg on the
repo methods.
"""
from __future__ import annotations

import html
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Optional

from .config import Settings
from .interest_vector import compute_user_vector
from .user_models import (
    SubscriptionRecord,
    SwipeRecord,
    UserEpisodeRecord,
    UserRecord,
)
from .user_repository import ControlPlaneRepository
from .utils import utc_now
from .weekly_update import iso_week_key


def parse_admin_user_ids(raw: Optional[str]) -> set[str]:
    """Split the comma-separated ADMIN_USER_IDS env value into a set.
    Empty string / None → empty set (effectively closes the endpoint)."""
    if not raw:
        return set()
    return {entry.strip() for entry in raw.split(",") if entry.strip()}


def is_admin(user_id: Optional[str], settings: Settings) -> bool:
    if not user_id:
        return False
    return user_id in parse_admin_user_ids(settings.admin_user_ids)


# Tile keys with no Firestore-derivable data — rendered as placeholders
# pointing at the BigQuery view they'll be populated from.
_BIGQUERY_TILES = [
    ("DAU / WAU / MAU", "vw_dau_wau_mau"),
    ("Activation funnel", "vw_activation_funnel"),
    ("Cohort retention", "vw_cohort_retention"),
    ("Episode completion (plays 30s)", "vw_episode_completion"),
    ("Churn-risk users", "vw_churn_risk_users"),
]


@dataclass
class AdminMetricsService:
    repository: ControlPlaneRepository
    settings: Settings

    def get_summary(self, *, now: Optional[datetime] = None) -> dict[str, Any]:
        """Tiles computable from Firestore today. See module docstring on
        why DAU/funnel/retention/completion need BigQuery."""
        now = now or utc_now()
        users = self.repository.list_all_users(limit=5000)
        subs = self.repository.list_all_subscriptions(limit=5000)
        recent_episodes = self.repository.list_recent_episodes_across_users(
            since=now - timedelta(days=30), limit=5000
        )
        recent_swipes = self.repository.list_recent_swipes_across_users(
            since=now - timedelta(days=7), limit=5000
        )

        episodes_7d = sum(
            1 for ep in recent_episodes if ep.published_at >= now - timedelta(days=7)
        )
        new_users_7d = sum(
            1 for u in users if u.created_at >= now - timedelta(days=7)
        )
        new_users_30d = sum(
            1 for u in users if u.created_at >= now - timedelta(days=30)
        )

        return {
            "generated_at": now.isoformat(),
            "totals": {
                "users": len(users),
                "new_users_7d": new_users_7d,
                "new_users_30d": new_users_30d,
                "subscriptions": len(subs),
                "episodes_30d": len(recent_episodes),
                "episodes_7d": episodes_7d,
                "swipes_7d": len(recent_swipes),
            },
            "tier_breakdown": _tier_breakdown(subs),
            "recent_episodes": [
                _episode_summary(ep) for ep in recent_episodes[:10]
            ],
            "recent_users": [_user_summary(u) for u in _newest_users(users, 10)],
            "bigquery_pending_tiles": [
                {"title": title, "view": view_name}
                for title, view_name in _BIGQUERY_TILES
            ],
        }

    def get_user_timeline(self, user_id: str) -> Optional[dict[str, Any]]:
        """Per-user view: episodes, swipes, runs, current vector + swipe
        trend. Returns None if the user_id doesn't exist."""
        user = self.repository.get_user(user_id)
        if user is None:
            return None
        subscription = self.repository.get_subscription(user_id)
        profile = self.repository.get_profile(user_id)
        episodes = self.repository.list_recent_user_episodes(user_id, limit=20)
        swipes = self.repository.list_user_swipes(user_id, limit=500)
        runs = self.repository.list_recent_user_runs(user_id, limit=20)
        sources = self.repository.list_user_sources(user_id)

        vector = compute_user_vector(swipes)
        vector_preview = (
            [round(value, 4) for value in vector[:8]] if vector else []
        )
        swipes_by_week = _swipes_per_iso_week(swipes, weeks=8)

        return {
            "user": {
                "id": user.id,
                "display_name": user.display_name,
                "timezone": user.timezone,
                "created_at": user.created_at.isoformat(),
                "current_week_iso": user.current_week_iso,
                "premium_pods_this_week": user.premium_pods_this_week,
                "default_pods_this_week": user.default_pods_this_week,
                "trial_premium_pods_remaining": user.trial_premium_pods_remaining,
            },
            "subscription": (
                {
                    "tier": subscription.tier,
                    "status": subscription.status,
                    "product_id": subscription.product_id,
                    "expires_at": (
                        subscription.expires_at.isoformat()
                        if subscription.expires_at else None
                    ),
                }
                if subscription else None
            ),
            "profile_summary": (
                {
                    "format_preset": profile.format_preset,
                    "voice_id": profile.voice_id,
                    "duration_minutes": profile.desired_duration_minutes,
                    "source_count": len(sources),
                }
                if profile else None
            ),
            "episodes": [_episode_summary(ep) for ep in episodes],
            "runs": [
                {
                    "id": run.id,
                    "status": run.status,
                    "completed_at": run.completed_at.isoformat(),
                    "local_run_date": run.local_run_date.isoformat(),
                    "candidate_count": run.candidate_count,
                    "processed_item_count": run.processed_item_count,
                    "dropped_item_count": run.dropped_item_count,
                    "cap_hit": run.cap_hit,
                }
                for run in runs
            ],
            "swipes_recent": [
                {
                    "swiped_at": swipe.swiped_at.isoformat(),
                    "direction": swipe.direction,
                    "source_id": swipe.source_id,
                    "seed_kind": swipe.seed_kind,
                }
                for swipe in swipes[:50]
            ],
            "interest": {
                "total_swipes": len(swipes),
                "vector_dim": len(vector) if vector else 0,
                "vector_preview": vector_preview,
                "swipes_per_iso_week": swipes_by_week,
            },
        }


def _tier_breakdown(subs: list[SubscriptionRecord]) -> list[dict[str, Any]]:
    counts: Counter[str] = Counter()
    statuses: dict[str, Counter[str]] = {}
    for sub in subs:
        tier = (sub.tier or "free").strip().lower()
        counts[tier] += 1
        statuses.setdefault(tier, Counter())[sub.status or "unknown"] += 1
    return [
        {
            "tier": tier,
            "count": count,
            "status_breakdown": dict(statuses[tier]),
        }
        for tier, count in counts.most_common()
    ]


def _episode_summary(episode: UserEpisodeRecord) -> dict[str, Any]:
    return {
        "id": episode.id,
        "user_id": episode.user_id,
        "title": episode.title,
        "published_at": episode.published_at.isoformat(),
        "duration_seconds": episode.duration_seconds,
        "processed_item_count": episode.processed_item_count,
        "cap_hit": episode.cap_hit,
    }


def _user_summary(user: UserRecord) -> dict[str, Any]:
    return {
        "id": user.id,
        "display_name": user.display_name,
        "created_at": user.created_at.isoformat(),
        "timezone": user.timezone,
    }


def _newest_users(users: list[UserRecord], limit: int) -> list[UserRecord]:
    return sorted(users, key=lambda u: u.created_at, reverse=True)[:limit]


def _swipes_per_iso_week(
    swipes: list[SwipeRecord], weeks: int
) -> list[dict[str, Any]]:
    """Bucket swipes by ISO week (newest `weeks` weeks). The last entry
    is the current week. Useful for the per-user trend display."""
    counts: Counter[str] = Counter()
    for swipe in swipes:
        counts[iso_week_key(swipe.swiped_at.date())] += 1
    keys = sorted(counts.keys(), reverse=True)[:weeks]
    return [
        {"iso_week": key, "swipes": counts[key]}
        for key in sorted(keys)
    ]


# ----- HTML rendering -----------------------------------------------------

_PAGE_CSS = """
body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto,
                 "Helvetica Neue", Arial, sans-serif;
    margin: 0; padding: 24px; background: #fafaf6; color: #222;
}
h1 { font-size: 20px; margin: 0 0 16px; }
h2 { font-size: 15px; margin: 24px 0 8px; color: #555;
     text-transform: uppercase; letter-spacing: 0.08em; }
.tiles { display: grid; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr));
         gap: 12px; }
.tile { background: #fff; border: 1px solid #e6e3d8; border-radius: 8px;
        padding: 16px; }
.tile .label { font-size: 11px; color: #777; text-transform: uppercase;
               letter-spacing: 0.08em; }
.tile .value { font-size: 28px; font-weight: 600; margin-top: 4px; }
.tile.placeholder { background: #f3f1ea; border-style: dashed; }
.tile.placeholder .value { font-size: 13px; color: #888; font-weight: 400; }
table { border-collapse: collapse; width: 100%; background: #fff;
        border: 1px solid #e6e3d8; border-radius: 8px; overflow: hidden; }
th, td { text-align: left; padding: 8px 12px; border-bottom: 1px solid #f0eee5;
         font-size: 13px; }
th { background: #f6f4ed; font-weight: 600; }
tr:last-child td { border-bottom: none; }
.muted { color: #888; }
.tier-pill { display: inline-block; padding: 2px 8px; border-radius: 999px;
             font-size: 11px; background: #efeadb; color: #5c4a1a; }
.section { margin: 24px 0; }
form { margin: 12px 0; }
input[type="text"] { padding: 6px 10px; border: 1px solid #ccc;
                     border-radius: 6px; font-size: 13px; width: 320px; }
button { padding: 6px 14px; border: 1px solid #ccc; background: #fff;
         border-radius: 6px; font-size: 13px; cursor: pointer; }
code { font-family: SFMono-Regular, Menlo, Consolas, monospace;
       font-size: 12px; background: #f3f1ea; padding: 2px 6px; border-radius: 4px; }
"""


def render_summary_html(summary: dict[str, Any]) -> str:
    totals = summary["totals"]
    tier_rows = "".join(
        f"<tr><td><span class='tier-pill'>{html.escape(t['tier'])}</span></td>"
        f"<td>{t['count']}</td>"
        f"<td class='muted'>{html.escape(', '.join(f'{k}={v}' for k, v in t['status_breakdown'].items()))}</td></tr>"
        for t in summary["tier_breakdown"]
    ) or "<tr><td colspan='3' class='muted'>No subscriptions on file.</td></tr>"

    episode_rows = "".join(
        f"<tr><td>{html.escape(ep['published_at'])}</td>"
        f"<td>{html.escape(ep['title'])}</td>"
        f"<td><a href='?user_id={html.escape(ep['user_id'])}'>"
        f"<code>{html.escape(ep['user_id'][:12])}…</code></a></td>"
        f"<td>{ep['duration_seconds'] or 0}s</td>"
        f"<td>{ep['processed_item_count'] or 0}</td></tr>"
        for ep in summary["recent_episodes"]
    ) or "<tr><td colspan='5' class='muted'>No episodes in the last 30 days.</td></tr>"

    user_rows = "".join(
        f"<tr><td>{html.escape(u['created_at'])}</td>"
        f"<td>{html.escape(u['display_name'] or '')}</td>"
        f"<td>{html.escape(u['timezone'] or '')}</td>"
        f"<td><a href='?user_id={html.escape(u['id'])}'>"
        f"<code>{html.escape(u['id'][:12])}…</code></a></td></tr>"
        for u in summary["recent_users"]
    ) or "<tr><td colspan='4' class='muted'>No users on file.</td></tr>"

    placeholder_html = "".join(
        f"<div class='tile placeholder'>"
        f"<div class='label'>{html.escape(tile['title'])}</div>"
        f"<div class='value'>Requires BigQuery sink<br>"
        f"<code>{html.escape(tile['view'])}</code></div></div>"
        for tile in summary["bigquery_pending_tiles"]
    )

    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<title>ClawCast admin metrics</title>
<style>{_PAGE_CSS}</style>
</head><body>
<h1>ClawCast admin metrics</h1>
<p class="muted">Generated {html.escape(summary['generated_at'])}.
Event-driven tiles populate from BigQuery (see
<code>infra/bigquery_setup.md</code>) once the log sink is wired.</p>

<form method="get">
  <input type="text" name="user_id" placeholder="Per-user timeline: paste a user_id">
  <button type="submit">View user</button>
</form>

<h2>Firestore-derived tiles</h2>
<div class="tiles">
  <div class="tile"><div class="label">Total users</div><div class="value">{totals['users']}</div></div>
  <div class="tile"><div class="label">New (7d)</div><div class="value">{totals['new_users_7d']}</div></div>
  <div class="tile"><div class="label">New (30d)</div><div class="value">{totals['new_users_30d']}</div></div>
  <div class="tile"><div class="label">Episodes (7d)</div><div class="value">{totals['episodes_7d']}</div></div>
  <div class="tile"><div class="label">Episodes (30d)</div><div class="value">{totals['episodes_30d']}</div></div>
  <div class="tile"><div class="label">Swipes (7d)</div><div class="value">{totals['swipes_7d']}</div></div>
</div>

<h2>BigQuery-pending tiles</h2>
<div class="tiles">{placeholder_html}</div>

<h2>Tier breakdown</h2>
<table>
  <thead><tr><th>Tier</th><th>Count</th><th>Status breakdown</th></tr></thead>
  <tbody>{tier_rows}</tbody>
</table>

<div class="section">
  <h2>Latest episodes</h2>
  <table>
    <thead><tr><th>Published</th><th>Title</th><th>User</th><th>Duration</th><th>Items</th></tr></thead>
    <tbody>{episode_rows}</tbody>
  </table>
</div>

<div class="section">
  <h2>Newest users</h2>
  <table>
    <thead><tr><th>Joined</th><th>Display name</th><th>Timezone</th><th>User</th></tr></thead>
    <tbody>{user_rows}</tbody>
  </table>
</div>

</body></html>"""


def render_user_timeline_html(timeline: dict[str, Any]) -> str:
    user = timeline["user"]
    sub = timeline["subscription"]
    interest = timeline["interest"]

    sub_block = (
        f"<table><tr><th>Tier</th><td><span class='tier-pill'>{html.escape(sub['tier'])}</span></td></tr>"
        f"<tr><th>Status</th><td>{html.escape(sub['status'])}</td></tr>"
        f"<tr><th>Product</th><td><code>{html.escape(sub['product_id'] or '')}</code></td></tr>"
        f"<tr><th>Expires</th><td class='muted'>{html.escape(sub['expires_at'] or '')}</td></tr></table>"
        if sub else "<p class='muted'>No subscription record.</p>"
    )

    episode_rows = "".join(
        f"<tr><td>{html.escape(ep['published_at'])}</td>"
        f"<td>{html.escape(ep['title'])}</td>"
        f"<td>{ep['duration_seconds'] or 0}s</td>"
        f"<td>{ep['processed_item_count'] or 0}</td>"
        f"<td>{'yes' if ep['cap_hit'] else ''}</td></tr>"
        for ep in timeline["episodes"]
    ) or "<tr><td colspan='5' class='muted'>No episodes yet.</td></tr>"

    swipe_rows = "".join(
        f"<tr><td>{html.escape(s['swiped_at'])}</td>"
        f"<td>{'right' if s['direction'] > 0 else 'left'}</td>"
        f"<td><code>{html.escape(s['source_id'] or '')}</code></td>"
        f"<td class='muted'>{html.escape(s['seed_kind'] or '')}</td></tr>"
        for s in timeline["swipes_recent"]
    ) or "<tr><td colspan='4' class='muted'>No swipes yet.</td></tr>"

    run_rows = "".join(
        f"<tr><td>{html.escape(r['completed_at'])}</td>"
        f"<td>{html.escape(r['status'])}</td>"
        f"<td>{r['candidate_count'] or 0}</td>"
        f"<td>{r['processed_item_count'] or 0}</td>"
        f"<td>{r['dropped_item_count'] or 0}</td></tr>"
        for r in timeline["runs"]
    ) or "<tr><td colspan='5' class='muted'>No runs yet.</td></tr>"

    swipe_trend_rows = "".join(
        f"<tr><td>{html.escape(row['iso_week'])}</td><td>{row['swipes']}</td></tr>"
        for row in interest["swipes_per_iso_week"]
    ) or "<tr><td colspan='2' class='muted'>No swipe activity.</td></tr>"

    vector_str = (
        ", ".join(str(v) for v in interest["vector_preview"])
        if interest["vector_preview"] else "(no vector — needs swipes)"
    )

    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<title>User {html.escape(user['id'][:12])}… — admin</title>
<style>{_PAGE_CSS}</style>
</head><body>
<h1>User <code>{html.escape(user['id'])}</code></h1>
<p><a href="?">← back to overview</a></p>

<h2>Profile</h2>
<table>
  <tr><th>Display name</th><td>{html.escape(user['display_name'] or '')}</td></tr>
  <tr><th>Timezone</th><td>{html.escape(user['timezone'] or '')}</td></tr>
  <tr><th>Joined</th><td>{html.escape(user['created_at'])}</td></tr>
  <tr><th>Current ISO week</th><td>{html.escape(user['current_week_iso'] or '')}</td></tr>
  <tr><th>Premium pods this week</th><td>{user['premium_pods_this_week']}</td></tr>
  <tr><th>Default pods this week</th><td>{user['default_pods_this_week']}</td></tr>
  <tr><th>Trial premium pods left</th><td>{user['trial_premium_pods_remaining']}</td></tr>
</table>

<h2>Subscription</h2>
{sub_block}

<h2>Current interest vector + swipe activity</h2>
<table>
  <tr><th>Total swipes</th><td>{interest['total_swipes']}</td></tr>
  <tr><th>Vector dim</th><td>{interest['vector_dim']}</td></tr>
  <tr><th>Vector (first 8 dims)</th><td><code>{html.escape(vector_str)}</code></td></tr>
</table>
<p class="muted">Snapshot taken on demand; we don't store historical vectors yet, so "drift" is approximated by the swipes-per-week trend below.</p>

<h2>Swipes per ISO week (last 8)</h2>
<table>
  <thead><tr><th>ISO week</th><th>Swipes</th></tr></thead>
  <tbody>{swipe_trend_rows}</tbody>
</table>

<h2>Recent episodes</h2>
<table>
  <thead><tr><th>Published</th><th>Title</th><th>Duration</th><th>Items</th><th>Cap hit</th></tr></thead>
  <tbody>{episode_rows}</tbody>
</table>

<h2>Recent generation runs</h2>
<table>
  <thead><tr><th>Completed</th><th>Status</th><th>Candidates</th><th>Processed</th><th>Dropped</th></tr></thead>
  <tbody>{run_rows}</tbody>
</table>

<h2>Recent swipes (last 50)</h2>
<table>
  <thead><tr><th>Swiped at</th><th>Direction</th><th>Source</th><th>Seed</th></tr></thead>
  <tbody>{swipe_rows}</tbody>
</table>

<p class="muted">For event-stream context (sign-ins, play pulses, subscription transitions),
query <code>analytics.events_raw</code> in BigQuery filtered to this user_id.</p>
</body></html>"""


def render_user_not_found_html(user_id: str) -> str:
    return f"""<!doctype html>
<html lang="en"><head>
<meta charset="utf-8">
<title>User not found — admin</title>
<style>{_PAGE_CSS}</style>
</head><body>
<h1>User not found</h1>
<p>No user with id <code>{html.escape(user_id)}</code>.</p>
<p><a href="?">← back to overview</a></p>
</body></html>"""
