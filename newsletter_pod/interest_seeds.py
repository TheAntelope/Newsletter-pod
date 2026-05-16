"""Synthetic interest-vector seeds from non-swipe signals.

The swipe-based ranker reads a user's interest vector from `SwipeRecord` rows.
Three onboarding/post-onboarding moments produce signal that should feed the
same vector without requiring the user to physically swipe a card:

  - Voice intake: a 60-second spoken brief at onboarding. Extracted topics
    and named entities each become a positive seed.
  - Substack paste: the publication metadata (title + author + tagline) the
    user types in.
  - Forwarded mail: an inbound email whose sender matches the user's
    verified email address — i.e. the user personally forwarded a newsletter
    to their ClawCast alias, a strong "I care about this" signal.

Each seed is stored as a SwipeRecord with a `seed:<kind>:<digest>` dedupe key
so it never collides with a real source item, and with `seed_kind` set so
auditing and UI can distinguish synthetic seeds from real swipes.
"""
from __future__ import annotations

import hashlib
import logging
from typing import Optional
from uuid import uuid4

from .embeddings import EmbeddingProvider
from .user_models import SwipeRecord
from .user_repository import ControlPlaneRepository
from .utils import utc_now

logger = logging.getLogger(__name__)

_MAX_SEED_TEXT_CHARS = 2000

# Recognized seed kinds. Anything else passed in is rejected so we don't end
# up with a sprawling set of fingerprints in production.
SEED_KIND_VOICE = "voice_intake"
SEED_KIND_SUBSTACK = "substack_paste"
SEED_KIND_FORWARDED = "forwarded_mail"
_VALID_SEED_KINDS = {SEED_KIND_VOICE, SEED_KIND_SUBSTACK, SEED_KIND_FORWARDED}


def _seed_dedupe_key(kind: str, content: str) -> str:
    digest = hashlib.sha256(f"{kind}:{content}".encode("utf-8")).hexdigest()[:32]
    return f"seed:{kind}:{digest}"


def seed_user_interest(
    *,
    repository: ControlPlaneRepository,
    embeddings: EmbeddingProvider,
    user_id: str,
    kind: str,
    items: list[tuple[str, str]],
) -> int:
    """Embed each (title, body) pair and persist as a synthetic positive swipe.

    `items` is a list of (title, body_to_embed) tuples. The title becomes the
    `listener_anchors` surface and is bounded to 200 chars; the body is fed
    into the embedder (truncated to MAX_SEED_TEXT_CHARS, falls back to title
    when empty). Returns the number of seeds actually written. Items whose
    embedding fails (provider returns None) are silently skipped.
    """
    if kind not in _VALID_SEED_KINDS:
        raise ValueError(f"Unknown seed kind: {kind!r}")
    if not items:
        return 0

    inputs: list[str] = []
    for title, body in items:
        text = (body or title or "").strip()
        if len(text) > _MAX_SEED_TEXT_CHARS:
            text = text[:_MAX_SEED_TEXT_CHARS]
        inputs.append(text)

    vectors = embeddings.embed_texts(inputs)
    written = 0
    for (title, body), embed_input, vector in zip(items, inputs, vectors):
        if vector is None or not embed_input:
            continue
        title_clean = (title or "").strip()[:200] or embed_input[:60]
        seed = SwipeRecord(
            id=uuid4().hex,
            user_id=user_id,
            source_item_dedupe_key=_seed_dedupe_key(kind, embed_input),
            direction=1,
            title=title_clean,
            link="",
            source_id=f"seed_{kind}",
            source_name=f"Interest seed ({kind.replace('_', ' ')})",
            embedding=vector,
            embedding_model=embeddings.model,
            swiped_at=utc_now(),
            seed_kind=kind,
        )
        try:
            repository.save_swipe(seed)
        except Exception:  # pragma: no cover — seeding is best-effort
            logger.warning(
                "Failed to persist interest seed: user=%s kind=%s",
                user_id,
                kind,
                exc_info=True,
            )
            continue
        written += 1
    return written


def is_user_forwarded_mail(user_email: Optional[str], from_email: Optional[str]) -> bool:
    """True when an inbound email's sender matches the user's verified email
    (case-insensitive). Used to upweight self-forwarded newsletters: when a
    user pushes a newsletter to their alias themselves, that's a much stronger
    "I care about this" signal than a regular subscription delivery.
    """
    if not user_email or not from_email:
        return False
    return user_email.strip().lower() == from_email.strip().lower()
