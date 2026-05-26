"""First-party event logging.

Emits one structured `app_event` log line per call so Cloud Run's
jsonPayload parser indexes it the same way as the existing
`swipe_ranker` / `billing_event` lines. Deliberately *not* a metrics
backend: no BigQuery, no dashboards, no in-process aggregation — just
log lines other tooling can lift later.

PII rule: the privacy policy (newsletter_pod.legal.PRIVACY_HTML)
promises no third-party advertising or analytics SDKs and only basic
operational data. To keep that promise, `log_event` refuses property
keys that would carry user content: email addresses, raw feedback
text, email subject lines, inbound email bodies, etc. Only IDs and
derived flags (counts, booleans, enums, buckets) belong here.
"""
from __future__ import annotations

import json
import logging
from enum import Enum
from typing import Any, Optional

from .utils import utc_now

logger = logging.getLogger(__name__)


class EventName(str, Enum):
    SIGN_IN = "sign_in"
    ONBOARDING_STEP = "onboarding_step"
    SWIPE_RECORDED = "swipe_recorded"
    SOURCES_SAVED = "sources_saved"
    EPISODE_REQUESTED = "episode_requested"
    EPISODE_GENERATED = "episode_generated"
    EPISODE_FAILED = "episode_failed"
    EPISODE_PLAY_PULSE = "episode_play_pulse"
    PAYWALL_VIEWED = "paywall_viewed"
    SUBSCRIPTION_STARTED = "subscription_started"
    SUBSCRIPTION_CHANGED = "subscription_changed"
    FEEDBACK_SUBMITTED = "feedback_submitted"
    SCHEDULE_CHANGED = "schedule_changed"
    CHURN_RISK_SCORED = "churn_risk_scored"


# Property keys we refuse to log. These are the fields most likely to
# carry user content; keep IDs / counts / enums / booleans only.
_FORBIDDEN_PROPERTY_KEYS = frozenset(
    {
        "email",
        "email_address",
        "from_email",
        "to_email",
        "raw_text",
        "feedback_text",
        "text",
        "transcript",
        "transcript_text",
        "body",
        "body_text",
        "body_html",
        "subject",
        "subject_line",
        "title",
        "summary",
        "message",
        "content",
        "given_name",
        "display_name",
        "first_name",
        "last_name",
    }
)


class EventPIIError(ValueError):
    """Raised when log_event is called with a forbidden property key.

    Surfaces as a hard failure rather than a silent drop so a regression
    that tries to ship PII into the event stream blows up in tests
    instead of leaking into prod logs.
    """


def log_event(
    name: EventName,
    user_id: Optional[str],
    **properties: Any,
) -> None:
    """Emit a single structured event log line.

    Args:
        name: The event identifier. Must be an EventName so typos turn
            into ImportErrors instead of orphan event names.
        user_id: The acting user, or None for unauthenticated events
            (e.g. a paywall view before sign-in).
        **properties: ID-only / derived-flag context. Forbidden keys
            (see _FORBIDDEN_PROPERTY_KEYS) raise EventPIIError.
    """
    if not isinstance(name, EventName):
        raise TypeError(
            f"log_event requires an EventName, got {type(name).__name__}"
        )
    forbidden = _FORBIDDEN_PROPERTY_KEYS & properties.keys()
    if forbidden:
        raise EventPIIError(
            f"log_event refused PII property keys: {sorted(forbidden)}"
        )

    payload = {
        "event": "app_event",
        "event_name": name.value,
        "user_id": user_id,
        "ts": utc_now().isoformat(),
        "properties": properties,
    }
    logger.info(json.dumps(payload, sort_keys=True, default=str))


def bucket_play_position_seconds(position_seconds: int) -> str:
    """Coarse buckets for EPISODE_PLAY_PULSE so the event stream stays
    cardinality-bounded and we can tell "did they get past the intro"
    without ever logging an exact timestamp."""
    if position_seconds < 30:
        return "0-30"
    if position_seconds < 120:
        return "30-120"
    if position_seconds < 600:
        return "120-600"
    return "600+"
