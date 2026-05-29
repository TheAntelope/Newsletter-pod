"""Next-episode candidate queue (spike).

Two responsibilities:
1. Hourly global poll — walk every distinct source attached by any user,
   fetch new items once per source (not per user), and persist them through
   the existing source_items pipeline.
2. Per-user candidate view — surface what's likely to land in the next
   pod, with pin / exclude levers the user can pull between episodes.

Both are flag-gated by `settings.candidate_queue_enabled`. Pins are honored
by generation (see ControlPlaneService.process_user_generation); excludes
filter the candidate pool. Neither lever affects the swipe ranker's
interest-learning loop — pin/exclude are episode-local commitments.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Optional

from .config import Settings
from .ingestion import RSSIngestionService
from .interest_vector import compute_user_vector
from .models import (
    NextEpisodeOverrideRecord,
    SourceDefinition,
    SourceItem,
    SourceItemRecord,
    SourcePollingStateRecord,
)
from .ranker import rank_items
from .source_persistence import SourceItemPersistenceService
from .user_repository import ControlPlaneRepository
from .utils import utc_now

logger = logging.getLogger(__name__)


class _PollingCursorAdapter:
    """Adapts ControlPlaneRepository onto the CursorRepository protocol that
    RSSIngestionService expects, mapping cursor lookups to the global
    `source_polling_state` collection rather than any per-user cursor."""

    def __init__(self, repository: ControlPlaneRepository) -> None:
        self._repository = repository

    def get_source_cursor(self, source_id: str) -> Optional[datetime]:
        state = self._repository.get_source_polling_state(source_id)
        return state.cursor if state else None


def _record_to_source_item(record: SourceItemRecord) -> SourceItem:
    return SourceItem(
        source_id=record.source_id,
        source_name=record.source_name,
        guid=record.guid,
        link=record.link,
        title=record.title,
        summary=record.summary,
        published_at=record.published_at,
        dedupe_key=record.dedupe_key,
    )


@dataclass
class CandidateQueueService:
    settings: Settings
    repository: ControlPlaneRepository
    source_item_persistence: SourceItemPersistenceService

    def run_poll(self, now_utc: Optional[datetime] = None) -> dict[str, Any]:
        """Walk every distinct attached source once, ingest new items, and
        update the per-source cursor. Returns a counts payload suitable
        for the Cloud Scheduler job response."""
        now = now_utc or utc_now()
        if not self.settings.candidate_queue_enabled:
            return {"status": "skipped", "reason": "candidate_queue_disabled"}

        all_records = self.repository.list_all_user_sources()
        # Dedupe by source_id, preserving the first rss_url we see. For
        # curated sources the URL is identical across users; for Substack
        # the URL is canonicalized at attach time. If two users ever
        # disagree (e.g. one pasted a stale URL), the first-wins choice
        # will get corrected the next time the catalog is refreshed.
        unique: dict[str, SourceDefinition] = {}
        for record in all_records:
            if not record.enabled or record.source_id in unique:
                continue
            unique[record.source_id] = SourceDefinition(
                id=record.source_id,
                name=record.name,
                rss_url=record.rss_url,
                enabled=True,
            )
        if not unique:
            return {
                "status": "ok",
                "sources_polled": 0,
                "items_ingested": 0,
                "per_source": [],
            }

        cursor_adapter = _PollingCursorAdapter(self.repository)
        ingestion = RSSIngestionService(
            repository=cursor_adapter,
            bootstrap_max_items_per_source=self.settings.podcast_bootstrap_max_items_per_source,
        )

        items_ingested = 0
        sources_with_items = 0
        per_source: list[dict[str, Any]] = []
        # One source at a time so a single bad feed can't poison the batch
        # and so we can stamp per-source error / last-polled state.
        for source_def in unique.values():
            try:
                result = ingestion.fetch_new_items([source_def])
            except Exception as exc:  # pragma: no cover — fetch is best-effort
                logger.warning(
                    "poll-sources fetch raised for source=%s: %s",
                    source_def.id,
                    exc,
                )
                existing = self.repository.get_source_polling_state(source_def.id)
                self.repository.upsert_source_polling_state(
                    SourcePollingStateRecord(
                        source_id=source_def.id,
                        last_polled_at=now,
                        cursor=existing.cursor if existing else None,
                        last_item_count=0,
                        last_error=str(exc)[:200],
                    )
                )
                per_source.append(
                    {"source_id": source_def.id, "items": 0, "error": str(exc)[:200]}
                )
                continue

            persisted = 0
            if result.items:
                try:
                    self.source_item_persistence.persist(result.items)
                    persisted = len(result.items)
                except Exception:  # pragma: no cover — non-fatal
                    logger.warning(
                        "poll-sources persist raised for source=%s",
                        source_def.id,
                        exc_info=True,
                    )

            new_cursor = result.cursor_updates.get(source_def.id)
            existing = self.repository.get_source_polling_state(source_def.id)
            cursor = new_cursor or (existing.cursor if existing else None)
            self.repository.upsert_source_polling_state(
                SourcePollingStateRecord(
                    source_id=source_def.id,
                    last_polled_at=now,
                    cursor=cursor,
                    last_item_count=persisted,
                    last_error=None,
                )
            )
            items_ingested += persisted
            if persisted:
                sources_with_items += 1
            per_source.append({"source_id": source_def.id, "items": persisted})

        logger.info(
            "poll_sources sources_polled=%d sources_with_items=%d items_ingested=%d",
            len(unique),
            sources_with_items,
            items_ingested,
        )
        return {
            "status": "ok",
            "sources_polled": len(unique),
            "sources_with_items": sources_with_items,
            "items_ingested": items_ingested,
            "per_source": per_source,
        }

    def list_candidates(
        self,
        user_id: str,
        *,
        per_episode_cap: int,
    ) -> dict[str, Any]:
        """Build the per-user "Coming in your next pod" view.

        `per_episode_cap` is the user's tier item cap, passed in by the
        caller (who has the entitlements snapshot already). We use it to
        compute the "likely to be included" pill — pinned items always
        likely; remaining slots go to the ranker (or chronological top-N
        when the user has too few swipes).
        """
        sources = [
            s for s in self.repository.list_user_sources(user_id) if s.enabled
        ]
        pins = self.repository.list_next_episode_overrides(
            user_id, kind="pin", only_unconsumed=True
        )
        excludes = self.repository.list_next_episode_overrides(
            user_id, kind="exclude", only_unconsumed=True
        )
        pinned_keys = {p.source_item_dedupe_key for p in pins}
        excluded_keys = {e.source_item_dedupe_key for e in excludes}

        max_pins = self.settings.next_episode_max_pins
        pinned_count = len(pinned_keys)
        pins_remaining = max(0, max_pins - pinned_count)

        if not sources and not pinned_keys:
            return {
                "candidates": [],
                "pinned_count": 0,
                "max_pins": max_pins,
                "pins_remaining": max_pins,
                "ranker_used": False,
            }

        since = utc_now() - timedelta(
            days=self.settings.next_episode_candidates_lookback_days
        )
        source_ids = [s.source_id for s in sources]
        records: list[SourceItemRecord] = []
        if source_ids:
            records = self.repository.list_source_items_by_source_published_since(
                source_ids,
                since=since,
                limit=self.settings.next_episode_candidates_limit,
            )

        # Drop excluded items from the visible list — exclude is "remove
        # from queue," not "show as struck-through."
        records = [r for r in records if r.dedupe_key not in excluded_keys]

        # Pinned items always surface, even if they fell out of the
        # lookback window or their source has since been disabled. Resolve
        # any not already in the candidate set.
        present = {r.dedupe_key for r in records}
        for pin in pins:
            if pin.source_item_dedupe_key in present:
                continue
            extra = self.repository.get_source_item(pin.source_item_dedupe_key)
            if extra is not None and extra.dedupe_key not in excluded_keys:
                records.append(extra)
                present.add(extra.dedupe_key)

        records.sort(key=lambda r: r.published_at, reverse=True)

        # Compute the "likely to be included" set: pins (up to max_pins)
        # always likely; remaining budget goes to ranker (or chronological
        # tail when below min-swipes). Mirrors the generation-time logic
        # so the pill stays honest.
        likely_keys: set[str] = set()
        ranker_used = False
        capped_pinned_keys = self._cap_pinned_keys(pins, max_pins)
        likely_keys.update(capped_pinned_keys)

        unpinned_records = [r for r in records if r.dedupe_key not in pinned_keys]
        unpinned_budget = max(0, per_episode_cap - len(capped_pinned_keys))
        if unpinned_budget > 0 and unpinned_records:
            ranked = self._rank_unpinned(user_id, unpinned_records, unpinned_budget)
            if ranked is not None:
                likely_keys.update(item.dedupe_key for item in ranked)
                ranker_used = True
            else:
                # Chronological fallback: most-recent N within the budget.
                # `unpinned_records` is already newest-first.
                for r in unpinned_records[:unpinned_budget]:
                    likely_keys.add(r.dedupe_key)

        source_candidates = [
            self._candidate_payload(
                record,
                pinned=record.dedupe_key in pinned_keys,
                likely=record.dedupe_key in likely_keys,
            )
            for record in records
        ]

        # Shared items (POST /v1/items/shared) live in the inbound_items
        # collection, not source_items, so they don't surface via the
        # source-record query above. Pull unconsumed kind="share" rows and
        # prepend them — they're always pinned + always likely_included
        # since generation force-includes them regardless of cap/ranker.
        # Within the shared block, newest share-time first.
        shared_candidates = self._shared_item_candidates(user_id, excluded_keys)

        return {
            "candidates": shared_candidates + source_candidates,
            "pinned_count": pinned_count,
            "max_pins": max_pins,
            "pins_remaining": pins_remaining,
            "ranker_used": ranker_used,
        }

    def pin_item(self, user_id: str, dedupe_key: str) -> dict[str, Any]:
        """Force the given item into the user's next episode. Idempotent:
        re-pinning is a no-op; pinning a previously-excluded item flips
        the override. Errors when the pin cap is already reached or the
        item is unknown."""
        record = self.repository.get_source_item(dedupe_key)
        if record is None:
            raise CandidateQueueError("Unknown source item")

        existing_pins = self.repository.list_next_episode_overrides(
            user_id, kind="pin", only_unconsumed=True
        )
        already_pinned = any(
            p.source_item_dedupe_key == dedupe_key for p in existing_pins
        )
        if not already_pinned and len(existing_pins) >= self.settings.next_episode_max_pins:
            raise CandidateQueueError(
                f"Pin cap reached ({self.settings.next_episode_max_pins})"
            )

        override = NextEpisodeOverrideRecord(
            user_id=user_id,
            source_item_dedupe_key=dedupe_key,
            kind="pin",
            created_at=utc_now(),
        )
        self.repository.save_next_episode_override(override)
        return {
            "status": "pinned",
            "dedupe_key": dedupe_key,
            "pins_remaining": max(
                0,
                self.settings.next_episode_max_pins
                - (len(existing_pins) + (0 if already_pinned else 1)),
            ),
        }

    def exclude_item(self, user_id: str, dedupe_key: str) -> dict[str, Any]:
        record = self.repository.get_source_item(dedupe_key)
        if record is None:
            raise CandidateQueueError("Unknown source item")
        override = NextEpisodeOverrideRecord(
            user_id=user_id,
            source_item_dedupe_key=dedupe_key,
            kind="exclude",
            created_at=utc_now(),
        )
        self.repository.save_next_episode_override(override)
        return {"status": "excluded", "dedupe_key": dedupe_key}

    def clear_override(self, user_id: str, dedupe_key: str) -> dict[str, Any]:
        removed = self.repository.delete_next_episode_override(user_id, dedupe_key)
        return {"status": "cleared" if removed else "noop", "dedupe_key": dedupe_key}

    def _cap_pinned_keys(
        self, pins: list[NextEpisodeOverrideRecord], cap: int
    ) -> set[str]:
        if cap <= 0:
            return set()
        if len(pins) <= cap:
            return {p.source_item_dedupe_key for p in pins}
        # Oldest pins survive the cap — newer ones get bumped. Rationale:
        # a user who pinned 6 items days ago has been waiting on those;
        # the 7th pin is the one that overflowed and the user can see it
        # has no "likely" pill in the UI.
        ordered = sorted(pins, key=lambda p: p.created_at)
        return {p.source_item_dedupe_key for p in ordered[:cap]}

    def _rank_unpinned(
        self,
        user_id: str,
        records: list[SourceItemRecord],
        top_n: int,
    ) -> Optional[list[SourceItem]]:
        """Mirror of ControlPlaneService._apply_swipe_ranker, but operating
        on records (so we have embeddings on hand) and without the inbound
        bias — candidate-queue ranking is informational, not the final
        say. Returns None when the ranker shouldn't fire (disabled,
        below-min-swipes, no vector) so callers can fall back."""
        if not self.settings.swipe_ranker_enabled or top_n <= 0 or not records:
            return None
        swipe_count = self.repository.count_user_swipes(user_id)
        if swipe_count < self.settings.swipe_ranker_min_swipes:
            return None
        swipes = self.repository.list_user_swipes(user_id)
        user_vector = compute_user_vector(swipes)
        if user_vector is None:
            return None
        items = [_record_to_source_item(r) for r in records]
        embedding_by_key = {r.dedupe_key: r.embedding for r in records}
        return rank_items(items, user_vector, embedding_by_key.get, top_n)

    def _candidate_payload(
        self,
        record: SourceItemRecord,
        *,
        pinned: bool,
        likely: bool,
        shared: bool = False,
    ) -> dict[str, Any]:
        return {
            "dedupe_key": record.dedupe_key,
            "source_id": record.source_id,
            "source_name": record.source_name,
            "title": record.title,
            "summary": record.summary,
            "link": record.link,
            "published_at": record.published_at.isoformat(),
            "pinned": pinned,
            "likely_included": likely,
            "shared": shared,
        }

    def _shared_item_candidates(
        self,
        user_id: str,
        excluded_keys: set[str],
    ) -> list[dict[str, Any]]:
        """Project unconsumed kind="share" InboundEmailItems into the
        candidate-payload shape so the iOS queue surfaces them.

        Shared items skip the ranker/cap entirely at generation time
        (control_plane.process_user_generation), so they're always
        pinned + likely_included here too. Sorted newest share-time
        first — most recent share appears at the very top of the queue.
        """
        try:
            inbound = self.repository.list_unconsumed_inbound_items(user_id)
        except Exception:  # pragma: no cover — non-fatal, omit shared block
            logger.warning(
                "Listing inbound items for candidate queue failed: user=%s",
                user_id,
                exc_info=True,
            )
            return []

        shared = [item for item in inbound if getattr(item, "kind", "email") == "share"]
        shared.sort(key=lambda i: i.received_at, reverse=True)

        payloads: list[dict[str, Any]] = []
        for item in shared:
            dedupe_key = f"inbound:{item.id}"
            if dedupe_key in excluded_keys:
                continue
            summary = item.body_text or item.subject or ""
            payloads.append({
                "dedupe_key": dedupe_key,
                "source_id": f"inbound:{item.sender_domain or item.id}",
                "source_name": item.from_name or "Shared by you",
                "title": item.subject or "Shared item",
                "summary": summary[:500],
                "link": item.article_url or f"clawcast://inbound/{item.id}",
                "published_at": item.received_at.isoformat(),
                "pinned": True,
                "likely_included": True,
                "shared": True,
            })
        return payloads


class CandidateQueueError(RuntimeError):
    """Surface-level error raised by user-facing methods (pin/exclude).
    The API layer maps this to 400."""

    pass
