from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from zoneinfo import ZoneInfo

from .models import DayState


@dataclass
class RetryDecision:
    should_attempt: bool
    reason: str
    should_send_failure_alert: bool


class RetryPolicy:
    def __init__(
        self,
        timezone_name: str,
        start_local: str,
        target_local: str,
        cutoff_local: str,
        rapid_retry_minutes: int,
        periodic_retry_minutes: int,
    ) -> None:
        self.tz = ZoneInfo(timezone_name)
        self.start_local = _parse_hhmm(start_local)
        self.target_local = _parse_hhmm(target_local)
        self.cutoff_local = _parse_hhmm(cutoff_local)
        self.rapid_interval = timedelta(minutes=rapid_retry_minutes)
        self.periodic_interval = timedelta(minutes=periodic_retry_minutes)

    def local_date(self, now_utc: datetime) -> date:
        return now_utc.astimezone(self.tz).date()

    def evaluate(self, now_utc: datetime, state: DayState, force: bool = False) -> RetryDecision:
        if force:
            return RetryDecision(True, "forced", False)

        local_now = now_utc.astimezone(self.tz)
        local_time = local_now.time()

        if state.has_completed_run:
            return RetryDecision(False, "day already completed", False)

        if state.has_published_episode:
            return RetryDecision(False, "episode already published today", False)

        if local_time < self.start_local:
            return RetryDecision(False, "before schedule window", False)

        if local_time > self.cutoff_local:
            send_alert = not state.has_alert_sent
            return RetryDecision(False, "past cutoff", send_alert)

        min_interval = self.rapid_interval if local_time < self.target_local else self.periodic_interval

        if state.last_attempt_at is None:
            return RetryDecision(True, "first attempt in window", False)

        elapsed = now_utc - state.last_attempt_at
        if elapsed >= min_interval:
            return RetryDecision(True, "retry interval elapsed", False)

        return RetryDecision(False, "waiting for next retry interval", False)


def _parse_hhmm(value: str) -> time:
    hours, minutes = value.split(":", maxsplit=1)
    return time(hour=int(hours), minute=int(minutes))
