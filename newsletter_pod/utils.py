from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from dateutil import parser as date_parser

TRACKING_QUERY_PREFIXES = ("utm_",)
TRACKING_QUERY_KEYS = {"fbclid", "gclid", "mc_cid", "mc_eid", "igshid"}


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None

    try:
        parsed = parsedate_to_datetime(value)
        if parsed is not None:
            return ensure_utc(parsed)
    except (TypeError, ValueError):
        pass

    try:
        parsed = date_parser.parse(value)
        return ensure_utc(parsed)
    except (TypeError, ValueError, OverflowError):
        return None


def ensure_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def canonicalize_url(url: str) -> str:
    parsed = urlparse(url)
    query = []
    for key, value in parse_qsl(parsed.query, keep_blank_values=True):
        key_lower = key.lower()
        if key_lower in TRACKING_QUERY_KEYS:
            continue
        if any(key_lower.startswith(prefix) for prefix in TRACKING_QUERY_PREFIXES):
            continue
        query.append((key, value))

    cleaned = parsed._replace(
        scheme=parsed.scheme.lower(),
        netloc=parsed.netloc.lower(),
        query=urlencode(sorted(query)),
        fragment="",
    )
    return urlunparse(cleaned)


def link_hash(url: str) -> str:
    normalized = canonicalize_url(url)
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def guid_or_link_hash(guid: str | None, link: str) -> str:
    return guid.strip() if guid else link_hash(link)


def format_rfc2822(value: datetime) -> str:
    return ensure_utc(value).strftime("%a, %d %b %Y %H:%M:%S +0000")
