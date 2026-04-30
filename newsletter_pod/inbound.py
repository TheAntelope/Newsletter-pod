"""Inbound newsletter email handling.

Mailgun POSTs to /webhooks/mailgun/inbound when an email arrives at any
<alias>@INBOUND_EMAIL_DOMAIN address. We:

1. Verify the HMAC signature (Mailgun's webhook signing key).
2. Look up the recipient alias against UserRecord.inbound_alias.
3. Skip "confirmation"-style emails (subscription verification links).
4. Persist a deduplicated InboundEmailItem keyed on Message-Id.

A future generation pass reads recent unconsumed inbound items and merges
them with RSS items.
"""
from __future__ import annotations

import hashlib
import hmac
import logging
import re
import secrets
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from .user_models import InboundEmailItem, UserRecord
from .user_repository import ControlPlaneRepository
from .utils import utc_now

logger = logging.getLogger(__name__)

# Crockford-ish base32: lowercase, no 0/1/o/l/i to avoid eyeballing mistakes
# when a user reads the alias off a Sources screen and types it into a
# newsletter signup. ~10^11 collision space at length 8.
_ALIAS_ALPHABET = "abcdefghjkmnpqrstuvwxyz23456789"
_ALIAS_LENGTH = 8
_MAX_ALIAS_GENERATION_ATTEMPTS = 8

_CONFIRMATION_SUBJECT_PATTERN = re.compile(
    r"\b(confirm(ation)?|verify|verification|please\s+confirm|activate|subscription)\b",
    re.IGNORECASE,
)
_CONFIRMATION_BODY_PATTERN = re.compile(
    r"\b(confirm\s+your\s+(subscription|email)|verify\s+your\s+email|click\s+(here|the\s+link)\s+to\s+(confirm|verify|subscribe|activate))\b",
    re.IGNORECASE,
)


def generate_alias() -> str:
    return "".join(secrets.choice(_ALIAS_ALPHABET) for _ in range(_ALIAS_LENGTH))


def ensure_user_inbound_alias(repository: ControlPlaneRepository, user: UserRecord) -> str:
    """Return the user's alias, generating + persisting one on first read.

    Idempotent: if the user already has an alias, returns it. Otherwise picks
    a new alias that does not collide with any existing user, persists it on
    the user record, and returns it.
    """
    if user.inbound_alias:
        return user.inbound_alias
    for _ in range(_MAX_ALIAS_GENERATION_ATTEMPTS):
        candidate = generate_alias()
        if repository.get_user_by_inbound_alias(candidate) is None:
            user.inbound_alias = candidate
            user.updated_at = utc_now()
            repository.save_user(user)
            return candidate
    raise RuntimeError("Could not allocate an inbound alias after retries")


def verify_mailgun_signature(
    *,
    signing_key: str,
    timestamp: str,
    token: str,
    signature: str,
) -> bool:
    """HMAC-SHA256 of (timestamp + token) keyed with the webhook signing key.

    Mailgun docs: https://documentation.mailgun.com/docs/mailgun/user-manual/tracking-messages/#webhooks
    """
    if not (signing_key and timestamp and token and signature):
        return False
    expected = hmac.new(
        key=signing_key.encode("utf-8"),
        msg=f"{timestamp}{token}".encode("utf-8"),
        digestmod=hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


def extract_alias_from_recipient(recipient: str, domain: str) -> Optional[str]:
    if not recipient or "@" not in recipient:
        return None
    local, _, recipient_domain = recipient.partition("@")
    if recipient_domain.lower() != domain.lower():
        return None
    # Strip plus-tag suffixes (e.g., "alias+marketing@theclawcast.com").
    alias = local.split("+", 1)[0].strip().lower()
    return alias or None


def parse_email_address(value: str) -> tuple[str, Optional[str]]:
    """Return (email, display_name). value may be 'Name <a@b>' or 'a@b'."""
    if not value:
        return ("", None)
    value = value.strip()
    match = re.match(r"^(?P<name>.+?)\s*<(?P<addr>[^>]+)>\s*$", value)
    if match:
        addr = match.group("addr").strip().lower()
        name = match.group("name").strip().strip('"').strip()
        return (addr, name or None)
    return (value.lower(), None)


def looks_like_confirmation(subject: str, body_text: str) -> bool:
    """Heuristic for double-opt-in / verification emails.

    Conservative: must hit BOTH a subject keyword and a body phrase to flag,
    so a regular newsletter that happens to mention "subscription" in the
    subject doesn't get dropped.
    """
    if not subject:
        return False
    if not _CONFIRMATION_SUBJECT_PATTERN.search(subject):
        return False
    if not body_text:
        # Subject screams confirmation; trust it.
        return True
    return bool(_CONFIRMATION_BODY_PATTERN.search(body_text))


_URL_PATTERN = re.compile(r"https?://[^\s<>\"]+", re.IGNORECASE)
_LINK_DENY_PATTERN = re.compile(
    r"(unsubscribe|/track/|/click/|/open/|/pixel/|tracking|list-manage\.com|click\.email|/wf/click)",
    re.IGNORECASE,
)


def extract_article_url(body_text: str) -> Optional[str]:
    """Best-effort 'read on the web' URL extraction.

    Picks the first http(s) URL in the body that doesn't look like a tracker,
    pixel, or unsubscribe link. False positives are fine — the field is a
    convenience pointer, not a guarantee.
    """
    if not body_text:
        return None
    for match in _URL_PATTERN.finditer(body_text):
        url = match.group(0).rstrip(").,;'\"")
        if _LINK_DENY_PATTERN.search(url):
            continue
        return url
    return None


def build_inbound_item_id(message_id: Optional[str], user_id: str, fallback: str) -> str:
    seed = (message_id or fallback).strip() or fallback
    digest = hashlib.sha256(f"{user_id}:{seed}".encode("utf-8")).hexdigest()
    return digest[:32]


def parse_received_at(date_header: Optional[str]) -> datetime:
    """Parse the email Date header; fall back to now() on any failure."""
    if date_header:
        try:
            from email.utils import parsedate_to_datetime

            value = parsedate_to_datetime(date_header)
            if value.tzinfo is None:
                value = value.replace(tzinfo=timezone.utc)
            return value
        except (TypeError, ValueError):
            pass
    return utc_now()


@dataclass
class InboundEmailHandler:
    repository: ControlPlaneRepository
    inbound_email_domain: str
    mailgun_signing_key: Optional[str]

    def handle(self, payload: dict[str, str]) -> dict[str, str]:
        """Process one Mailgun multipart-form payload.

        Returns a dict the webhook handler can serialize as JSON. Raises on
        signature failure so the route layer can return 401.
        """
        if not self.mailgun_signing_key:
            raise InboundConfigError("Mailgun webhook signing key is not configured")

        if not verify_mailgun_signature(
            signing_key=self.mailgun_signing_key,
            timestamp=payload.get("timestamp", ""),
            token=payload.get("token", ""),
            signature=payload.get("signature", ""),
        ):
            raise InboundSignatureError("Invalid Mailgun signature")

        recipient = payload.get("recipient") or payload.get("To") or ""
        alias = extract_alias_from_recipient(recipient, self.inbound_email_domain)
        if alias is None:
            logger.info("Inbound email rejected: recipient %r outside inbound domain", recipient)
            return {"status": "ignored", "reason": "recipient_domain_mismatch"}

        user = self.repository.get_user_by_inbound_alias(alias)
        if user is None:
            logger.info("Inbound email rejected: no user for alias %r", alias)
            return {"status": "ignored", "reason": "unknown_alias"}

        subject = (payload.get("subject") or payload.get("Subject") or "").strip()
        body_text = (
            payload.get("stripped-text")
            or payload.get("body-plain")
            or payload.get("body-html")
            or ""
        ).strip()

        if looks_like_confirmation(subject, body_text):
            logger.info(
                "Inbound email skipped (confirmation): user=%s subject=%r",
                user.id,
                subject[:80],
            )
            return {"status": "skipped", "reason": "confirmation"}

        sender_raw = payload.get("from") or payload.get("From") or payload.get("sender") or ""
        from_email, from_name = parse_email_address(sender_raw)
        if not from_email:
            logger.warning("Inbound email rejected: no parseable sender for user %s", user.id)
            return {"status": "ignored", "reason": "missing_sender"}

        sender_domain = from_email.rsplit("@", 1)[-1].lower() if "@" in from_email else from_email
        message_id = (payload.get("Message-Id") or payload.get("message-id") or "").strip() or None

        item_id = build_inbound_item_id(message_id, user.id, fallback=f"{from_email}:{subject}:{payload.get('timestamp','')}")
        if self.repository.get_inbound_item(item_id) is not None:
            return {"status": "duplicate", "item_id": item_id}

        item = InboundEmailItem(
            id=item_id,
            user_id=user.id,
            message_id=message_id,
            from_email=from_email,
            from_name=from_name,
            sender_domain=sender_domain,
            subject=subject or "(no subject)",
            body_text=body_text[:8000],  # bound the per-item size
            article_url=extract_article_url(body_text),
            received_at=parse_received_at(payload.get("Date")),
        )
        self.repository.save_inbound_item(item)
        logger.info(
            "Inbound email stored: user=%s sender=%s subject=%r item_id=%s",
            user.id,
            sender_domain,
            subject[:80],
            item_id,
        )
        return {"status": "stored", "item_id": item_id}


class InboundError(Exception):
    pass


class InboundConfigError(InboundError):
    pass


class InboundSignatureError(InboundError):
    pass
