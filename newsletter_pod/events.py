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

import contextvars
import json
import logging
import sys
from enum import Enum
from typing import Any, Optional

from .utils import utc_now

logger = logging.getLogger(__name__)

# app_event lines must reach Cloud Run's logging agent as a *pure JSON* line so
# it parses them into `jsonPayload`: the clawcast-app-events sink filters on
# `jsonPayload.event="app_event"` and every analytics view reads `jsonPayload.*`.
# The root logger (configured in main.py via logging.basicConfig) uses the
# default "LEVELNAME:logger:message" format — that prefix made each line plain
# text, so Cloud Logging stored it as `textPayload` (jsonPayload=null), the sink
# matched nothing, and BigQuery stayed empty. Give this logger its own
# bare-message stdout handler and stop propagation so exactly one clean JSON
# line is emitted per event. (Tests attach caplog's handler directly — see
# tests/conftest.py — since propagate=False keeps records off the root handler.)
_event_stream_handler = logging.StreamHandler(sys.stdout)
_event_stream_handler.setFormatter(logging.Formatter("%(message)s"))
logger.addHandler(_event_stream_handler)
logger.propagate = False
logger.setLevel(logging.INFO)


# Platform of the calling client, stashed per-request so every log_event in
# the request gets tagged without each call site threading it through. Set by
# the X-Client-Platform middleware in main.py; None for server jobs / webhooks
# / unauthenticated paths that have no client header.
_current_platform: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "current_platform", default=None
)

# The only platform labels we record. Anything else is dropped to None rather
# than logged verbatim, so a malformed header can't pollute the dimension.
_ALLOWED_PLATFORMS = frozenset({"ios", "android", "web"})


def normalize_platform(value: Optional[str]) -> Optional[str]:
    """Lower-case + allow-list a platform string; None if unrecognised."""
    if not value:
        return None
    candidate = value.strip().lower()
    return candidate if candidate in _ALLOWED_PLATFORMS else None


def set_current_platform(value: Optional[str]) -> Optional[contextvars.Token]:
    """Record the requesting client's platform for the rest of this request.

    Returns a reset token (pass to reset_current_platform) or None if the
    value was unrecognised and nothing was set.
    """
    normalized = normalize_platform(value)
    if normalized is None:
        return None
    return _current_platform.set(normalized)


def reset_current_platform(token: Optional[contextvars.Token]) -> None:
    """Undo a set_current_platform call once the request is done."""
    if token is not None:
        _current_platform.reset(token)


# Substrings that identify a platform from a podcast client's User-Agent.
# Tuned against the real /media traffic mix (2026-06): the dominant iOS client
# is Apple Podcasts, which sends "Podcasts/<build> CFNetwork/<v> Darwin/<v>" —
# no "applecoremedia"/"itunes" token — so the Apple networking-stack markers
# (cfnetwork/darwin) and Apple-only apps/devices are what actually catch it.
# Android markers cover the Android runtime (dalvik), the standard Android HTTP
# client (okhttp), and Android-only podcast apps. Cross-platform clients that
# expose no OS token (Pocket Casts, Spotify, bare Player FM) deliberately stay
# None here — they're resolved per-user from the device token instead.
_ANDROID_UA_MARKERS = (
    "podcastaddict",
    "android",
    "dalvik",
    "okhttp",
    "antennapod",
)
_IOS_UA_MARKERS = (
    "applecoremedia",
    "cfnetwork",
    "darwin",
    "itunes",
    "apple podcasts",
    "overcast",
    "castro",
    "watchos",
    "iphone",
    "ipad",
)

# Link-preview / crawler User-Agents that fetch the media URL but are NOT a
# listen (chat-app unfurlers, search bots, embed players). We skip emitting a
# play-pulse for these so they don't inflate listen counts or get mis-attributed
# to a user's platform via the device-token fallback.
_BOT_UA_MARKERS = (
    "bot",
    "crawler",
    "spider",
    "whatsapp",
    "discord",
    "facebookexternalhit",
    "telegram",
    "slackbot",
    "wordpress.com - audio",
)


def platform_from_user_agent(user_agent: Optional[str]) -> Optional[str]:
    """Best-effort map of a podcast client's User-Agent to a platform.

    Used for the server-side /media listening event, where the audio fetch
    comes from an external podcast app rather than our own client — so there is
    no X-Client-Platform header to read. Single-platform clients map cleanly;
    cross-platform clients with no OS token return None (the caller then falls
    back to the user's device-token platform).
    """
    if not user_agent:
        return None
    ua = user_agent.lower()
    if any(marker in ua for marker in _ANDROID_UA_MARKERS):
        return "android"
    if any(marker in ua for marker in _IOS_UA_MARKERS):
        return "ios"
    return None


def is_bot_user_agent(user_agent: Optional[str]) -> bool:
    """True for link-preview/crawler User-Agents whose media fetch isn't a
    real listen, so the /media route can skip emitting a play-pulse for them."""
    if not user_agent:
        return False
    ua = user_agent.lower()
    return any(marker in ua for marker in _BOT_UA_MARKERS)


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
    SHARED_ITEM_RECEIVED = "shared_item_received"
    ACQUISITION_SOURCE_SELECTED = "acquisition_source_selected"


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
    *,
    platform: Optional[str] = None,
    **properties: Any,
) -> None:
    """Emit a single structured event log line.

    Args:
        name: The event identifier. Must be an EventName so typos turn
            into ImportErrors instead of orphan event names.
        user_id: The acting user, or None for unauthenticated events
            (e.g. a paywall view before sign-in).
        platform: The client stack the event came from ("ios" / "android" /
            "web"). When omitted, falls back to the per-request value set by
            the X-Client-Platform middleware; pass it explicitly for events
            whose platform is derived another way (e.g. the /media route reads
            it from the podcast client's User-Agent). Recorded top-level so
            analytics can slice every metric by platform in a single view.
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

    resolved_platform = normalize_platform(platform)
    if resolved_platform is None:
        resolved_platform = _current_platform.get()

    payload = {
        "event": "app_event",
        "event_name": name.value,
        "user_id": user_id,
        "platform": resolved_platform,
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


def bucket_body_length(char_count: int) -> str:
    """Coarse buckets for SHARED_ITEM_RECEIVED body sizes — answers "are
    users sharing tweet-sized snippets or full PDFs" without logging the
    exact length (which could be a weak fingerprint when combined with
    timestamps)."""
    if char_count < 500:
        return "0-500"
    if char_count < 2_000:
        return "500-2k"
    if char_count < 10_000:
        return "2k-10k"
    if char_count < 50_000:
        return "10k-50k"
    return "50k+"
