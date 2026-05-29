"""Substack publication helpers: probing, URL canonicalization, confirm matching.

ClawCast subscribes users to Substack publications by deep-linking them to the
publication's own subscribe form with their per-user inbound alias. Substack
sends a double-opt-in email to the alias, which Mailgun delivers to our
inbound webhook. We then "click" the confirmation link server-side so the
user never has to chase a confirmation email that lives in our Firestore
rather than their personal inbox.

This module is the seam between that flow and the inbound handler. The
inbound handler stays focused on the Mailgun signature + alias bookkeeping;
anything Substack-specific lives here so we can iterate on the heuristic
without touching the webhook.
"""
from __future__ import annotations

import hashlib
import html as html_lib
import logging
import re
from dataclasses import dataclass
from datetime import datetime
from typing import Optional
from urllib.parse import urlparse

import feedparser
import requests

from .utils import parse_datetime, utc_now

logger = logging.getLogger(__name__)

# Browser-shaped UA. Substack's subscribe surface is sensitive to UA (see
# the spike we ran in scripts/probe_substack_subscribe.py); the homepage
# probe and confirm-link fetch use the same UA for consistency.
_PROBE_UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

_PROBE_TIMEOUT_SECONDS = 8.0
_CONFIRM_FETCH_TIMEOUT_SECONDS = 10.0

# Substack confirmation emails arrive from a no-reply address on substack.com.
# Their subject usually contains "Confirm" and the body has a button linking
# to https://substack.com/redeem/<token> (sometimes the publication subdomain
# instead). We're conservative on subject because looks_like_confirmation in
# the inbound handler has already filtered to the confirmation bucket; we
# only need to confirm it's a Substack-flavored confirmation, not a generic
# one from another newsletter platform.
_SUBSTACK_SENDER_PATTERN = re.compile(r"\bsubstack\.com$", re.IGNORECASE)
_SUBSTACK_CONFIRM_LINK_PATTERN = re.compile(
    r"https?://(?:[a-z0-9-]+\.)?substack\.com/(?:redeem|confirm|subscribe/confirm)[^\s\"'>]+",
    re.IGNORECASE,
)
# Substack's newer signup flow sends a one-time numeric code instead of a
# clickable confirm link — the user has to type the code back into the
# publication's subscribe page. The code is always carried in the subject
# line ("812807 is your Substack verification code"), which is the only
# reliable surface across HTML / plaintext renderings.
_SUBSTACK_VERIFICATION_CODE_SUBJECT = re.compile(
    r"^\s*(?P<code>\d{4,8})\s+is\s+your\s+substack\s+verification\s+code\b",
    re.IGNORECASE,
)

_TITLE_PATTERN = re.compile(r"<title[^>]*>(.*?)</title>", re.IGNORECASE | re.DOTALL)
_OG_TITLE_PATTERN = re.compile(
    r'<meta\s+property=["\']og:title["\']\s+content=["\']([^"\']+)["\']',
    re.IGNORECASE,
)
_OG_IMAGE_PATTERN = re.compile(
    r'<meta\s+property=["\']og:image["\']\s+content=["\']([^"\']+)["\']',
    re.IGNORECASE,
)
_AUTHOR_PATTERN = re.compile(
    r'<meta\s+name=["\']author["\']\s+content=["\']([^"\']+)["\']',
    re.IGNORECASE,
)
# Substack injects a JSON state blob with pricing info; presence of a paid
# plan is a strong signal. Fall back to a string match if the blob shape
# changes.
_PAID_PLAN_SIGNALS = (
    '"hasPaidPlans":true',
    '"is_premium":true',
    "subscribe to unlock",
    "for paid subscribers",
)


@dataclass(frozen=True)
class SubstackProbeResult:
    pub_url: str
    pub_host: str
    title: Optional[str]
    author: Optional[str]
    icon_url: Optional[str]
    has_paid_tier: bool
    feed_url: str


@dataclass(frozen=True)
class SubstackFeedPost:
    title: str
    link: str
    summary: str
    published_at: datetime


def canonicalize_pub_url(raw: str) -> tuple[str, str]:
    """Return (pub_url, pub_host) from a user-supplied string.

    Accepts: bare host, full URL with or without path, leading "@handle"
    (treated as <handle>.substack.com), with or without scheme. Raises
    ValueError on inputs that don't look like a usable publication URL.
    """
    if not raw or not raw.strip():
        raise ValueError("Empty publication URL")
    value = raw.strip()

    if value.startswith("@"):
        handle = value[1:].strip().lower()
        if not handle or not re.fullmatch(r"[a-z0-9-]+", handle):
            raise ValueError(f"Invalid Substack handle: {raw!r}")
        value = f"https://{handle}.substack.com"

    if "://" not in value:
        value = f"https://{value}"

    parsed = urlparse(value)
    host = (parsed.hostname or "").lower()
    if not host or "." not in host:
        raise ValueError(f"Could not parse publication host from {raw!r}")

    pub_url = f"{parsed.scheme}://{host}"
    return pub_url, host


def build_intent_id(user_id: str, pub_host: str) -> str:
    """Deterministic id so re-subscribing the same pub is idempotent."""
    digest = hashlib.sha256(f"{user_id}:{pub_host.lower()}".encode("utf-8")).hexdigest()
    return digest[:32]


def _strip_tags(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _extract_paid_signal(html: str) -> bool:
    lowered = html.lower()
    return any(signal.lower() in lowered for signal in _PAID_PLAN_SIGNALS)


def probe_publication(
    pub_url: str,
    *,
    session: Optional[requests.Session] = None,
) -> SubstackProbeResult:
    """Fetch a publication's homepage and extract display metadata.

    Best-effort: a probe failure raises requests.RequestException so the
    caller (a FastAPI route) can map it to a 4xx response. Successful probes
    always return a SubstackProbeResult even if individual fields are None
    (e.g., a custom-domain Substack with no og:title).
    """
    _, host = canonicalize_pub_url(pub_url)
    canonical_url = f"https://{host}"

    http = session or requests
    response = http.get(
        canonical_url,
        headers={
            "User-Agent": _PROBE_UA,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9",
        },
        timeout=_PROBE_TIMEOUT_SECONDS,
        allow_redirects=True,
    )
    response.raise_for_status()
    html = response.text or ""

    og_title = _OG_TITLE_PATTERN.search(html)
    title_match = og_title or _TITLE_PATTERN.search(html)
    title = _strip_tags(title_match.group(1)) if title_match else None

    author_match = _AUTHOR_PATTERN.search(html)
    author = _strip_tags(author_match.group(1)) if author_match else None

    icon_match = _OG_IMAGE_PATTERN.search(html)
    icon_url = icon_match.group(1).strip() if icon_match else None

    has_paid = _extract_paid_signal(html)

    return SubstackProbeResult(
        pub_url=canonical_url,
        pub_host=host,
        title=title,
        author=author,
        icon_url=icon_url,
        has_paid_tier=has_paid,
        feed_url=f"{canonical_url}/feed",
    )


def is_substack_sender(from_email: str) -> bool:
    """True if the sender's email domain ends with substack.com."""
    if not from_email or "@" not in from_email:
        return False
    domain = from_email.rsplit("@", 1)[-1].strip().lower()
    return bool(_SUBSTACK_SENDER_PATTERN.search(domain))


def is_substack_verification_code(subject: str) -> Optional[str]:
    """Return the numeric verification code if the subject matches Substack's
    one-time-code email shape, else None.

    Substack changed their signup flow to require typing a 6-digit code back
    into the publication's subscribe page instead of clicking a confirm link.
    These emails can't be auto-confirmed server-side — the code has to surface
    to the human within ~15 minutes — so the inbound handler diverts them
    out of the normal storage/auto-confirm path and stamps the code on the
    matching UserSubstackIntent instead.
    """
    if not subject:
        return None
    match = _SUBSTACK_VERIFICATION_CODE_SUBJECT.match(subject)
    if not match:
        return None
    return match.group("code")


def extract_confirm_url(body_text: str, body_html: str = "") -> Optional[str]:
    """Pull the first plausible Substack confirmation link from a message body.

    Substack confirmation emails have a "Confirm your subscription" button
    that resolves to substack.com/redeem/<token>, substack.com/confirm/...,
    or occasionally <pub>.substack.com/subscribe/confirm. The HTML body
    is the most reliable surface; we also check stripped-text as a
    fallback in case the email was forwarded or stripped.
    """
    for haystack in (body_html, body_text):
        if not haystack:
            continue
        match = _SUBSTACK_CONFIRM_LINK_PATTERN.search(haystack)
        if match:
            return match.group(0).rstrip(").,;'\"")
    return None


def match_intent_host(
    intents_pub_hosts: list[str],
    sender_domain: str,
    body_text: str = "",
    body_html: str = "",
) -> Optional[str]:
    """Return the first pub_host from the candidate list that the email
    looks like it came from, or None if nothing matches.

    Matching strategy:
      1. Direct sender_domain == pub_host (publication delivered via its own
         subdomain).
      2. sender_domain is a substack.com address AND the body contains the
         pub_host (confirmation emails come from no-reply@substack.com but
         the body links to the publication subdomain).
    """
    if not intents_pub_hosts:
        return None
    sender_domain = (sender_domain or "").lower()
    haystack = f"{body_text}\n{body_html}".lower()

    for pub_host in intents_pub_hosts:
        host = pub_host.lower()
        if sender_domain == host:
            return pub_host
        if sender_domain.endswith(".substack.com") and host == sender_domain:
            return pub_host
        if _SUBSTACK_SENDER_PATTERN.search(sender_domain) and host in haystack:
            return pub_host
    return None


_HTML_TAG_PATTERN = re.compile(r"<[^>]+>")
_FEED_FETCH_TIMEOUT_SECONDS = 10.0


def _clean_post_summary(value: str) -> str:
    if not value:
        return ""
    stripped = _HTML_TAG_PATTERN.sub(" ", value)
    unescaped = html_lib.unescape(stripped)
    return re.sub(r"\s+", " ", unescaped).strip()


def fetch_latest_post(
    feed_url: str,
    *,
    session: Optional[requests.Session] = None,
) -> Optional[SubstackFeedPost]:
    """Best-effort fetch of the most-recent free post from a Substack feed.

    Why: a new intent otherwise sits empty until the publication next sends
    out an email — which can be days for low-volume Substacks. Pulling the
    latest post from `/feed` gives the user immediate material to mix into
    their next podcast. Paid-only posts won't appear here (Substack's public
    feed only carries free content), which is the desired behavior.

    Returns None on any failure (network, parse, no entries with usable
    link) so the caller can treat it as a non-blocking enhancement.
    """
    http = session or requests
    try:
        response = http.get(
            feed_url,
            headers={
                "User-Agent": _PROBE_UA,
                "Accept": "application/rss+xml, application/atom+xml, application/xml;q=0.9, */*;q=0.8",
            },
            timeout=_FEED_FETCH_TIMEOUT_SECONDS,
            allow_redirects=True,
        )
    except requests.RequestException as exc:
        logger.info("Substack feed fetch raised: %s url=%s", exc, feed_url)
        return None
    if not response.ok:
        logger.info(
            "Substack feed fetch non-2xx: status=%s url=%s",
            response.status_code,
            feed_url,
        )
        return None

    parsed = feedparser.parse(response.text or "")
    entries = list(parsed.entries or [])
    if not entries:
        return None

    entry = entries[0]
    link = (entry.get("link") or "").strip()
    if not link:
        return None
    title = (entry.get("title") or "").strip() or "Untitled post"

    raw_summary = ""
    if entry.get("summary"):
        raw_summary = entry.get("summary")
    elif entry.get("description"):
        raw_summary = entry.get("description")
    elif entry.get("content"):
        content = entry.get("content")
        if isinstance(content, list) and content:
            raw_summary = content[0].get("value", "")
    summary = _clean_post_summary(raw_summary)

    published_at = (
        parse_datetime(entry.get("published"))
        or parse_datetime(entry.get("updated"))
        or utc_now()
    )

    return SubstackFeedPost(
        title=title,
        link=link,
        summary=summary,
        published_at=published_at,
    )


def fetch_confirm_url(url: str, *, session: Optional[requests.Session] = None) -> bool:
    """GET a Substack confirmation URL. Returns True on 2xx response.

    Substack's confirm endpoints redirect a few times before landing on a
    "You're subscribed!" page. We follow redirects and treat any non-error
    final response as success. Errors are logged but don't raise; the
    caller (inbound webhook) will simply not flip auto_confirmed_at, and
    the user can still receive content via the next probe pass.
    """
    http = session or requests
    try:
        response = http.get(
            url,
            headers={
                "User-Agent": _PROBE_UA,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
            },
            timeout=_CONFIRM_FETCH_TIMEOUT_SECONDS,
            allow_redirects=True,
        )
    except requests.RequestException as exc:
        logger.warning("Substack confirm fetch raised: %s url=%s", exc, url)
        return False

    if not response.ok:
        logger.warning(
            "Substack confirm fetch non-2xx: status=%s url=%s",
            response.status_code,
            url,
        )
        return False
    return True
