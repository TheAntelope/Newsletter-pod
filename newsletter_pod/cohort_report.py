"""Phase 3 weekly cohort report.

`POST /jobs/weekly-cohort-report` runs Mondays. Pulls the cohort that
signed up in the just-ended ISO week, computes activation + paid
conversion, joins against the latest churn-risk snapshot for the
top-3 at-risk users globally, and emails the operator using the
same `Mailer` + recipient-resolution pattern as the weekly feedback
digest.

This is a separate email from the feedback digest because:
  * it runs on a different schedule (Mon 07:00 vs Sun 18:00)
  * the audience is the same but the subject line differs, so
    operators can route them to different filters/folders
The "(see /jobs/send-feedback-digest for the pattern)" in the brief
refers to the email-format style, not literal concatenation.

The churn-risk top-3 reads from `ChurnRiskRecord` (populated by the
daily `/jobs/score-churn-risk`). If churn scoring hasn't run yet the
section degrades to "(no churn scores recorded yet)" rather than
erroring.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Optional

from .config import Settings
from .mailer import Mailer
from .user_models import (
    ChurnRiskRecord,
    SubscriptionRecord,
    UserRecord,
)
from .user_repository import ControlPlaneRepository
from .utils import utc_now

logger = logging.getLogger(__name__)

JOB_STATE_NAME = "cohort_weekly_report"

_PAID_TIERS = frozenset({"pro", "max"})


@dataclass
class CohortReportService:
    repository: ControlPlaneRepository
    mailer: Mailer
    settings: Settings

    def send_weekly_cohort_report(
        self, *, now: Optional[datetime] = None
    ) -> dict[str, object]:
        if not self.settings.cohort_report_email_enabled:
            return {"status": "disabled"}

        now = now or utc_now()
        cohort_start, cohort_end = _last_iso_week_bounds(now.date())

        cohort_users = self._users_in_window(cohort_start, cohort_end)
        cohort_user_ids = {user.id for user in cohort_users}

        # Activation = at least one delivered episode (UserEpisodeRecord).
        # The signup window is last week, so we're measuring "did the
        # user receive episode #1 within ~1-7 days of signup". For free
        # users that depends on their schedule; for paid users it
        # depends on the dispatcher firing inside their first delivery
        # day after onboarding.
        activated = 0
        if cohort_user_ids:
            for user_id in cohort_user_ids:
                if self.repository.count_user_episodes(user_id) > 0:
                    activated += 1

        # Paid conversion = current tier is pro/max. We don't need
        # snapshotted historical state for this; the current
        # subscription doc is the authoritative answer.
        paid_converted = 0
        for user_id in cohort_user_ids:
            sub = self.repository.get_subscription(user_id)
            if sub is None:
                continue
            if (sub.tier or "").lower() in _PAID_TIERS and (sub.status or "").lower() == "active":
                paid_converted += 1

        churn_top3 = self.repository.list_churn_risks(at_risk_only=True)[:3]

        churn_user_lookup = {
            record.user_id: self.repository.get_user(record.user_id)
            for record in churn_top3
        }
        churn_tier_lookup = {
            record.user_id: _tier_label(
                self.repository.get_subscription(record.user_id)
            )
            for record in churn_top3
        }
        subject, body = format_cohort_report_email(
            cohort_start=cohort_start,
            cohort_end=cohort_end,
            cohort_size=len(cohort_users),
            activated=activated,
            paid_converted=paid_converted,
            churn_top3=churn_top3,
            churn_user_lookup=churn_user_lookup,
            churn_tier_lookup=churn_tier_lookup,
            now=now,
        )

        recipients = _cohort_report_recipients(self.settings)
        if not recipients:
            logger.warning(
                "Cohort report has no recipients configured — skipping send"
            )
            return {
                "status": "no_recipients",
                "cohort_size": len(cohort_users),
                "activated": activated,
                "paid_converted": paid_converted,
            }

        self.mailer.send(subject, body, recipients=recipients)
        # Mark the job state so a future "since last run" view (or
        # alert on missed runs) has a cursor to read.
        self.repository.set_job_state(JOB_STATE_NAME, now)
        return {
            "status": "sent",
            "cohort_start": cohort_start.isoformat(),
            "cohort_end": cohort_end.isoformat(),
            "cohort_size": len(cohort_users),
            "activated": activated,
            "paid_converted": paid_converted,
            "churn_top3_user_ids": [record.user_id for record in churn_top3],
            "recipients": recipients,
        }

    def _users_in_window(
        self, start: date, end: date
    ) -> list[UserRecord]:
        # Inclusive on start, inclusive on end. We pull the whole user
        # table once — the user base is small enough that this is
        # cheaper than per-day queries, and the cap on
        # `list_all_users` (5000) is the safety net.
        users = self.repository.list_all_users(limit=5000)
        return [
            user for user in users
            if start <= user.created_at.date() <= end
        ]


def format_cohort_report_email(
    *,
    cohort_start: date,
    cohort_end: date,
    cohort_size: int,
    activated: int,
    paid_converted: int,
    churn_top3: list[ChurnRiskRecord],
    churn_user_lookup: dict[str, Optional[UserRecord]],
    churn_tier_lookup: dict[str, str],
    now: datetime,
) -> tuple[str, str]:
    """Build (subject, body). Plain-text, mirroring feedback_digest's
    style — no markdown headers, just underline-delimited sections so
    every mail client renders it the same way."""
    window_label = f"{cohort_start.isoformat()} to {cohort_end.isoformat()}"
    subject_suffix = (
        f"{cohort_size} signup{'s' if cohort_size != 1 else ''}"
        if cohort_size else "no signups"
    )
    subject = (
        f"ClawCast cohort report — week of {window_label} — {subject_suffix}"
    )

    activation_pct = _pct(activated, cohort_size)
    paid_pct = _pct(paid_converted, cohort_size)

    body_lines: list[str] = []
    body_lines.append(f"Cohort: week of {window_label}")
    body_lines.append("=" * (8 + len(window_label) + 8))
    body_lines.append("")
    body_lines.append(f"New signups:       {cohort_size}")
    body_lines.append(
        f"Activation rate:   {activation_pct} "
        f"({activated} of {cohort_size} had at least one episode)"
        if cohort_size else "Activation rate:   n/a (no signups)"
    )
    body_lines.append(
        f"Paid conversion:   {paid_pct} "
        f"({paid_converted} of {cohort_size} on pro/max)"
        if cohort_size else "Paid conversion:   n/a (no signups)"
    )
    body_lines.append("")

    body_lines.append("Top churn-risk users (across all tiers)")
    body_lines.append("---------------------------------------")
    if not churn_top3:
        body_lines.append("(no at-risk users — run /jobs/score-churn-risk if missing)")
    else:
        for record in churn_top3:
            user = churn_user_lookup.get(record.user_id)
            display = user.display_name if user else "(unknown)"
            tier = churn_tier_lookup.get(record.user_id, "?")
            signals = record.signals
            line = (
                f"- score={record.score:.2f} | user={record.user_id} "
                f"| {display} | tier={tier} | "
                f"last episode {signals.get('days_since_last_episode', '?')}d ago, "
                f"swipes_14d={int(signals.get('swipes_14d', 0))}, "
                f"neg_feedback_30d={int(signals.get('feedback_negative_30d', 0))}"
            )
            body_lines.append(line)
    body_lines.append("")
    body_lines.append(
        "Scoring window: last churn-risk run was "
        f"{churn_top3[0].scored_at.strftime('%Y-%m-%d %H:%M UTC')}."
        if churn_top3 else "Scoring window: no churn-risk runs recorded."
    )
    body_lines.append(
        "See /admin/metrics?user_id=<id> for the full per-user timeline."
    )

    return subject, "\n".join(body_lines).rstrip() + "\n"


def _last_iso_week_bounds(today: date) -> tuple[date, date]:
    """Return (Monday, Sunday) of the ISO week that just ended.

    If `today` is itself a Monday, the just-ended week is Mon-Sun seven
    days back (i.e. the week prior, not the partial day-of week). The
    scheduler runs Mondays so this is the common case.
    """
    weekday = today.weekday()  # Monday=0 … Sunday=6
    # The most recent Sunday on or before `today` (yesterday if Monday).
    last_sunday = today - timedelta(days=weekday + 1)
    last_monday = last_sunday - timedelta(days=6)
    return last_monday, last_sunday


def _pct(numerator: int, denominator: int) -> str:
    if denominator <= 0:
        return "n/a"
    return f"{(numerator / denominator) * 100:.0f}%"


def _tier_label(subscription: Optional[SubscriptionRecord]) -> str:
    if subscription is None:
        return "free"
    tier = (subscription.tier or "free").lower()
    if (subscription.status or "").lower() in {"expired", "revoked"}:
        return "free"
    return tier


def _cohort_report_recipients(settings: Settings) -> list[str]:
    """Same resolution rule as the feedback digest — `alert_email_to`
    plus comma-separated extras — so the operator manages one list."""
    seen: set[str] = set()
    out: list[str] = []
    candidates: list[str] = []
    if settings.alert_email_to:
        candidates.append(settings.alert_email_to)
    for raw in settings.feedback_digest_extra_recipients.split(","):
        candidates.append(raw)
    for raw in candidates:
        address = raw.strip()
        if not address or address in seen:
            continue
        seen.add(address)
        out.append(address)
    return out
