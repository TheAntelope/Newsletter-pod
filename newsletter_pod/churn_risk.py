"""Phase 3 churn-risk scoring.

Daily job (`POST /jobs/score-churn-risk`) walks every active paid user,
derives engagement signals from Firestore, computes a weighted score,
and persists the latest snapshot per user.

Data-source caveat: the brief asks for `days_since_last_play` and
`schedule_day_count_delta_30d`. Phase 1 logs play pulses + schedule
changes to Cloud Logging only — neither is queryable from Firestore
until the BigQuery sink lands (Phase 4-ish). Until then this module
uses the closest Firestore-derivable proxies:

  * play recency  → `days_since_last_episode` (we know when we
    delivered, not whether the listener actually played).
  * schedule delta → `schedule_underuse_fraction`, the fraction of
    the user's tier-entitled delivery days they're not using right
    now. Catches "user shrank their schedule" indirectly; misses
    short-term flapping.

Recovery action (re-engagement push, email, regenerate episode) is
deliberately NOT done here — that decision is parked. We score and
log; the operator triages.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Optional

from .config import Settings
from .events import EventName, log_event
from .user_models import (
    ChurnRiskRecord,
    DeliveryScheduleRecord,
    FeedbackRecord,
    SubscriptionRecord,
    SwipeRecord,
    UserEpisodeRecord,
    UserRecord,
)
from .user_repository import ControlPlaneRepository
from .utils import utc_now

logger = logging.getLogger(__name__)


# Signal-normalisation caps. Tweak together with the weights — these
# are deliberately not Settings yet so the scoring contract stays in
# one file. Promote to Settings when we want to A/B them at deploy
# time without a code change.
_RECENCY_CAP_DAYS = 14
_SWIPE_RATE_TARGET_PER_DAY = 1.0  # ~14 swipes in 14d = no risk
_FEEDBACK_NEGATIVE_CAP = 3        # 3+ negative items = max risk
_NEW_USER_GRACE_DAYS = 14         # too new to score

# Weights — must sum to 1.0 so the final score lives in [0, 1].
_W_RECENCY = 0.40
_W_SWIPES = 0.30
_W_SCHEDULE = 0.15
_W_FEEDBACK = 0.15

# Lowercase substrings that flag a feedback item as negative. Order
# doesn't matter; matched against english_text (falling back to
# raw_text). Crude but predictable; an LLM sentiment pass would be
# more accurate but adds cost and slows the daily job.
_NEGATIVE_KEYWORDS = frozenset(
    {
        "bad", "terrible", "hate", "broken", "refund", "cancel",
        "sucks", "awful", "boring", "stop", "unsubscribe",
        "useless", "worst", "disappointed", "annoying",
    }
)

_PAID_TIERS = frozenset({"pro", "max"})


@dataclass
class ChurnRiskScoringService:
    repository: ControlPlaneRepository
    settings: Settings

    def score_all_active_paid_users(
        self, *, now: Optional[datetime] = None
    ) -> dict[str, Any]:
        """Walk every paid+active user, score them, persist the snapshot,
        and log CHURN_RISK_SCORED per at-risk user. Returns a summary so
        the job endpoint has something to return for the Cloud Scheduler
        log line.

        Idempotent: re-running on the same data produces the same score
        (deterministic) and overwrites the per-user Firestore doc rather
        than appending. Event-log entries DO accumulate (every run emits
        events for current at-risk users), which is by design — events
        are time-series.
        """
        now = now or utc_now()
        threshold = self.settings.churn_risk_threshold

        subs = self.repository.list_all_subscriptions(limit=5000)
        paid_active = [
            sub for sub in subs
            if (sub.tier or "").lower() in _PAID_TIERS
            and (sub.status or "").lower() == "active"
        ]

        scored = 0
        at_risk_count = 0
        skipped_new = 0
        skipped_missing_user = 0

        for sub in paid_active:
            user = self.repository.get_user(sub.user_id)
            if user is None:
                skipped_missing_user += 1
                continue
            if (now - user.created_at) < timedelta(days=_NEW_USER_GRACE_DAYS):
                # Too new to have a meaningful signal — scoring a 3-day-old
                # account as "at risk because no plays yet" is noise.
                skipped_new += 1
                continue

            signals = self._compute_signals(user=user, now=now)
            score = self._weighted_score(signals)
            at_risk = score >= threshold
            record = ChurnRiskRecord(
                user_id=user.id,
                score=round(score, 4),
                at_risk=at_risk,
                signals=signals,
                scored_at=now,
            )
            self.repository.save_churn_risk(record)
            scored += 1
            if at_risk:
                at_risk_count += 1
                log_event(
                    EventName.CHURN_RISK_SCORED,
                    user.id,
                    score=record.score,
                    tier=(sub.tier or "").lower(),
                    days_since_last_episode=signals.get("days_since_last_episode"),
                    swipes_14d=signals.get("swipes_14d"),
                    schedule_weekday_count=signals.get("schedule_weekday_count"),
                    feedback_negative_30d=signals.get("feedback_negative_30d"),
                )

        return {
            "status": "ok",
            "scored": scored,
            "at_risk": at_risk_count,
            "skipped_new_users": skipped_new,
            "skipped_missing_user": skipped_missing_user,
            "scored_at": now.isoformat(),
            "threshold": threshold,
        }

    def _compute_signals(
        self, *, user: UserRecord, now: datetime
    ) -> dict[str, float]:
        """Raw signal values for one user. Stored as floats on
        ChurnRiskRecord.signals so the admin metrics page can render
        them without extra typing logic. Each raw signal is reported
        alongside the normalised values used in scoring."""
        episodes = self.repository.list_recent_user_episodes(user.id, limit=1)
        days_since_last_episode = _days_since(
            episodes[0].published_at if episodes else None, now=now,
            fallback=float(_RECENCY_CAP_DAYS * 2),  # never-delivered → max risk
        )

        swipes = self.repository.list_user_swipes(user.id, limit=500)
        swipes_14d = sum(
            1 for swipe in swipes
            if swipe.swiped_at >= now - timedelta(days=14)
        )

        schedule = self.repository.get_schedule(user.id)
        schedule_weekday_count = float(len(schedule.weekdays)) if schedule else 0.0
        schedule_max = _max_weekday_count_for_tier(
            tier=_resolve_tier(user.id, self.repository), settings=self.settings,
        )
        schedule_underuse_fraction = _safe_underuse(
            current=schedule_weekday_count, maximum=schedule_max,
        )

        feedback_records = _list_recent_feedback(self.repository, user.id, limit=200)
        feedback_negative_30d = sum(
            1 for record in feedback_records
            if record.created_at >= now - timedelta(days=30)
            and _is_negative_feedback(record)
        )

        return {
            "days_since_last_episode": round(days_since_last_episode, 2),
            "swipes_14d": float(swipes_14d),
            "schedule_weekday_count": schedule_weekday_count,
            "schedule_max_weekday_count": float(schedule_max),
            "schedule_underuse_fraction": round(schedule_underuse_fraction, 4),
            "feedback_negative_30d": float(feedback_negative_30d),
        }

    @staticmethod
    def _weighted_score(signals: dict[str, float]) -> float:
        recency_risk = min(
            1.0, signals["days_since_last_episode"] / _RECENCY_CAP_DAYS
        )
        # 0 swipes in 14d = 1.0 risk; 14+ swipes (~1/day) = 0.0 risk.
        target_14d = _SWIPE_RATE_TARGET_PER_DAY * 14
        swipes_risk = max(0.0, 1.0 - signals["swipes_14d"] / target_14d)
        schedule_risk = signals["schedule_underuse_fraction"]
        feedback_risk = min(
            1.0, signals["feedback_negative_30d"] / _FEEDBACK_NEGATIVE_CAP
        )
        return (
            _W_RECENCY * recency_risk
            + _W_SWIPES * swipes_risk
            + _W_SCHEDULE * schedule_risk
            + _W_FEEDBACK * feedback_risk
        )


# --- helpers --------------------------------------------------------------


def _days_since(
    when: Optional[datetime], *, now: datetime, fallback: float
) -> float:
    if when is None:
        return fallback
    delta = now - when
    return max(0.0, delta.total_seconds() / 86400.0)


def _safe_underuse(*, current: float, maximum: float) -> float:
    if maximum <= 0:
        return 0.0
    used = max(0.0, min(current, maximum))
    return max(0.0, 1.0 - used / maximum)


def _is_negative_feedback(record: FeedbackRecord) -> bool:
    text = (record.english_text or record.raw_text or "").lower()
    if not text:
        return False
    return any(keyword in text for keyword in _NEGATIVE_KEYWORDS)


def _list_recent_feedback(
    repository: ControlPlaneRepository, user_id: str, *, limit: int
) -> list[FeedbackRecord]:
    """Wrapper so the scoring code reads cleanly and the call site is
    obvious when the repo method evolves. Returns newest-first."""
    return repository.list_recent_feedback(user_id, limit)


def _resolve_tier(user_id: str, repository: ControlPlaneRepository) -> str:
    sub = repository.get_subscription(user_id)
    if sub is None:
        return "free"
    tier = (sub.tier or "free").lower()
    if (sub.status or "").lower() in {"expired", "revoked"}:
        return "free"
    return tier if tier in {"pro", "max"} else "free"


def _max_weekday_count_for_tier(*, tier: str, settings: Settings) -> int:
    if tier == "max":
        return int(settings.max_max_delivery_days)
    if tier == "pro":
        return int(settings.pro_max_delivery_days)
    return int(settings.free_max_delivery_days)
