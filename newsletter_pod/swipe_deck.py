from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import Optional, Protocol

from .clustering import kmeans_representative_indices
from .models import SourceItemRecord, SwipeDeckRecord
from .user_models import SwipeRecord
from .utils import utc_now

logger = logging.getLogger(__name__)

COLD_START_DECK_ID = "cold_start"
COLD_START_DECK_VERSION = "v1"

# Per-topic onboarding decks share the SwipeDeckRecord storage, keyed
# `topic::<casefolded-topic-name>`. Pre-baked daily by the refresh job so the
# request path serves cached keys instead of an unbounded live scan.
TOPIC_DECK_ID_PREFIX = "topic::"
TOPIC_DECK_VERSION = "v1"


def topic_deck_id(topic: str) -> str:
    return f"{TOPIC_DECK_ID_PREFIX}{topic.strip().casefold()}"


class _DeckRepository(Protocol):
    def list_embedded_source_items(self, limit: int = 5000) -> list[SourceItemRecord]: ...

    def list_recent_source_items_for_sources(
        self, source_ids: list[str], lookback_days: int, limit: int
    ) -> list[SourceItemRecord]: ...

    def list_recent_embedded_items_excluding_sources(
        self, excluded_source_ids: list[str], lookback_days: int, limit: int
    ) -> list[SourceItemRecord]: ...

    def get_source_items(self, dedupe_keys: list[str]) -> list[SourceItemRecord]: ...

    def list_user_swipes(self, user_id: str, limit: int = 500) -> list[SwipeRecord]: ...

    def save_swipe_deck(self, deck: SwipeDeckRecord) -> None: ...

    def get_swipe_deck(self, deck_id: str) -> Optional[SwipeDeckRecord]: ...


class SwipeDeckConfig(Protocol):
    """Live settings surface read on every deck call. Backed by Settings in
    production so flag flips take effect without service rebuilds.
    """

    cold_start_deck_size: int
    cold_start_deck_ttl_hours: int
    cold_start_corpus_limit: int
    topic_deck_ttl_hours: int
    recent_deck_size: int
    recent_deck_lookback_days: int
    recent_deck_exploration_ratio: float


class SwipeDeckService:
    """Cold-start + recent-items deck composer for the iOS swipe UI.

    The cold-start deck is global (k-means over the whole embedded corpus),
    cached as a SwipeDeckRecord, and recomputed lazily once the cache is
    older than `cold_start_deck_ttl_hours`. The recent-items deck is per-user
    (items from the user's currently-attached sources) and never cached
    because it shifts every generation run.

    Both decks filter out items the user has already swiped on, so the same
    item never reappears on a refresh.
    """

    def __init__(
        self,
        repository: _DeckRepository,
        config: SwipeDeckConfig,
        kmeans_max_iterations: int = 25,
    ) -> None:
        self._repository = repository
        self._config = config
        self._kmeans_max_iterations = kmeans_max_iterations

    def get_cold_start_deck(self, user_id: str) -> list[SourceItemRecord]:
        deck = self._load_or_refresh_cold_start_deck()
        if deck is None:
            return []
        already_swiped = self._user_swiped_keys(user_id)
        keys = [key for key in deck.dedupe_keys if key not in already_swiped]
        if not keys:
            return []
        records_by_key = {
            record.dedupe_key: record
            for record in self._repository.get_source_items(keys)
        }
        return [records_by_key[key] for key in keys if key in records_by_key]

    def get_topic_seeded_deck(
        self,
        user_id: str,
        source_ids: list[str],
        preferred_source_ids: Optional[list[str]] = None,
        source_id_groups: Optional[list[list[str]]] = None,
    ) -> list[SourceItemRecord]:
        """Onboarding deck seeded from the catalog sources behind the topics the
        user just picked. Prefers fresh items from those sources, then backfills
        from the diverse global cold-start deck so a thin or just-added topic
        never yields an empty deck. Already-swiped items are filtered out.

        [preferred_source_ids] (a subset of [source_ids], e.g. sources matching
        the user's region) are floated to the front so region-relevant stories
        lead the deck without excluding the rest.

        [source_id_groups] (one source-id list per picked topic) makes the deck
        round-robin across topics so a low-cadence topic (e.g. Sports) is
        represented rather than crowded out of the size-capped deck by a
        high-cadence one (e.g. Tech). Omitted / single-group degrades to plain
        recency order — the legacy behavior.
        """
        if not source_ids:
            return self.get_cold_start_deck(user_id)
        deck_size = self._config.cold_start_deck_size
        if deck_size <= 0:
            return []
        seeded = self._repository.list_recent_source_items_for_sources(
            source_ids=source_ids,
            lookback_days=self._config.recent_deck_lookback_days,
            limit=deck_size * 4,
        )
        return self._assemble_topic_deck(
            user_id, seeded, preferred_source_ids, source_id_groups
        )

    def get_topic_seeded_deck_cached(
        self,
        user_id: str,
        topic_source_groups: list[tuple[str, list[str]]],
        preferred_source_ids: Optional[list[str]] = None,
    ) -> list[SourceItemRecord]:
        """Cached counterpart of :meth:`get_topic_seeded_deck`. Sources each
        topic's candidates from its pre-baked `topic::<name>` deck (cheap key
        reads) instead of a live recency scan, then runs the identical
        region-float / round-robin / swipe-filter / cold-start-backfill
        assembly. A missing or stale topic deck (daily job skipped/late) falls
        back to a bounded live query for that one topic, so the deck is never
        empty and never unbounded.

        [topic_source_groups] is the ordered (topic-name, source-ids) list for
        the topics the user picked. Order is preserved so the round-robin gives
        each picked topic a fair share of the size-capped deck.
        """
        deck_size = self._config.cold_start_deck_size
        if not topic_source_groups or deck_size <= 0:
            return self.get_cold_start_deck(user_id)
        seeded: list[SourceItemRecord] = []
        seen_keys: set[str] = set()
        for topic, source_ids in topic_source_groups:
            for record in self._cached_topic_records(topic, source_ids):
                if record.dedupe_key in seen_keys:
                    continue
                seeded.append(record)
                seen_keys.add(record.dedupe_key)
        source_id_groups = [source_ids for _, source_ids in topic_source_groups]
        return self._assemble_topic_deck(
            user_id, seeded, preferred_source_ids, source_id_groups
        )

    def refresh_topic_decks(
        self, topic_source_ids: dict[str, list[str]]
    ) -> list[SourceItemRecord]:
        """Pre-bake one cached deck per catalog topic. For each topic, runs the
        (now-bounded) recent-items query and persists a SwipeDeckRecord keyed
        `topic::<name>`. Returns the deduped union of baked records so the
        caller can pre-warm their card summaries in the same job. Topics with
        no recent embedded items are skipped (no deck written — the request
        path falls back to the global cold-start deck for them).
        """
        deck_size = self._config.cold_start_deck_size
        if deck_size <= 0:
            return []
        baked: dict[str, SourceItemRecord] = {}
        for topic, source_ids in topic_source_ids.items():
            if not source_ids:
                continue
            records = self._repository.list_recent_source_items_for_sources(
                source_ids=source_ids,
                lookback_days=self._config.recent_deck_lookback_days,
                limit=deck_size * 4,
            )
            if not records:
                continue
            self._repository.save_swipe_deck(
                SwipeDeckRecord(
                    id=topic_deck_id(topic),
                    dedupe_keys=[record.dedupe_key for record in records],
                    corpus_size=len(records),
                    computed_at=utc_now(),
                    version=TOPIC_DECK_VERSION,
                )
            )
            for record in records:
                baked.setdefault(record.dedupe_key, record)
        return list(baked.values())

    def _cached_topic_records(
        self, topic: str, source_ids: list[str]
    ) -> list[SourceItemRecord]:
        deck = self._repository.get_swipe_deck(topic_deck_id(topic))
        if deck is not None and not self._is_topic_deck_stale(deck):
            records_by_key = {
                record.dedupe_key: record
                for record in self._repository.get_source_items(deck.dedupe_keys)
            }
            # Preserve the deck's stored (recency) order.
            return [
                records_by_key[key]
                for key in deck.dedupe_keys
                if key in records_by_key
            ]
        # Missing or stale → bounded live fallback for this one topic only.
        return self._repository.list_recent_source_items_for_sources(
            source_ids=source_ids,
            lookback_days=self._config.recent_deck_lookback_days,
            limit=self._config.cold_start_deck_size * 4,
        )

    def _is_topic_deck_stale(self, deck: SwipeDeckRecord) -> bool:
        age = utc_now() - _ensure_aware(deck.computed_at)
        return age > timedelta(hours=self._config.topic_deck_ttl_hours)

    def _assemble_topic_deck(
        self,
        user_id: str,
        seeded: list[SourceItemRecord],
        preferred_source_ids: Optional[list[str]],
        source_id_groups: Optional[list[list[str]]],
    ) -> list[SourceItemRecord]:
        """Shared assembly for the live and cached topic-seeded decks: float
        region-preferred sources, round-robin across topic streams, drop
        already-swiped items, then backfill from the global cold-start deck so
        the deck always fills."""
        deck_size = self._config.cold_start_deck_size
        if deck_size <= 0:
            return []
        already_swiped = self._user_swiped_keys(user_id)
        if preferred_source_ids:
            preferred = set(preferred_source_ids)
            # Stable sort keeps recency order within the preferred / other groups.
            seeded = sorted(
                seeded, key=lambda record: 0 if record.source_id in preferred else 1
            )
        deck: list[SourceItemRecord] = []
        seen: set[str] = set()
        streams = self._partition_into_topic_streams(seeded, source_id_groups)
        for record in self._round_robin(streams):
            if record.dedupe_key in already_swiped or record.dedupe_key in seen:
                continue
            deck.append(record)
            seen.add(record.dedupe_key)
            if len(deck) >= deck_size:
                return deck
        # Backfill from the global cold-start deck (already swipe-filtered) so the
        # deck always fills, even when the picked topics have little fresh corpus.
        for record in self.get_cold_start_deck(user_id):
            if record.dedupe_key in seen:
                continue
            deck.append(record)
            seen.add(record.dedupe_key)
            if len(deck) >= deck_size:
                break
        return deck

    @staticmethod
    def _partition_into_topic_streams(
        records: list[SourceItemRecord],
        source_id_groups: Optional[list[list[str]]],
    ) -> list[list[SourceItemRecord]]:
        """Split the (already-ordered) candidate list into one stream per topic
        group, preserving order within each stream. With no grouping or a single
        group, returns one stream — i.e. the original recency order untouched.
        Sources not in any group (shouldn't normally happen) collect in a
        trailing catch-all stream so nothing is dropped.
        """
        if not source_id_groups or len(source_id_groups) <= 1:
            return [list(records)]
        group_of_source: dict[str, int] = {}
        for index, group in enumerate(source_id_groups):
            for source_id in group:
                group_of_source.setdefault(source_id, index)
        streams: list[list[SourceItemRecord]] = [[] for _ in source_id_groups]
        overflow: list[SourceItemRecord] = []
        for record in records:
            index = group_of_source.get(record.source_id)
            (overflow if index is None else streams[index]).append(record)
        if overflow:
            streams.append(overflow)
        return [stream for stream in streams if stream]

    @staticmethod
    def _round_robin(
        streams: list[list[SourceItemRecord]],
    ) -> list[SourceItemRecord]:
        """Flatten parallel streams by taking one item from each in turn (each
        stream is already newest-first), so every topic gets a fair share of the
        size-capped deck instead of the highest-cadence topic dominating.
        """
        ordered: list[SourceItemRecord] = []
        cursors = [0] * len(streams)
        remaining = sum(len(stream) for stream in streams)
        while remaining:
            for index, stream in enumerate(streams):
                if cursors[index] < len(stream):
                    ordered.append(stream[cursors[index]])
                    cursors[index] += 1
                    remaining -= 1
        return ordered

    def refresh_cold_start_deck(self) -> Optional[SwipeDeckRecord]:
        """Force a recompute of the global cold-start deck regardless of TTL.

        Used by the weekly scheduler job so the deck is kept fresh even when
        no user happens to hit the lazy path. Returns the new deck record on
        success, or None if the corpus is empty (no embedded items yet).
        """
        refreshed = self._compute_cold_start_deck()
        if refreshed is None:
            return None
        self._repository.save_swipe_deck(refreshed)
        return refreshed

    def get_recent_deck(
        self, user_id: str, source_ids: list[str]
    ) -> list[SourceItemRecord]:
        deck_size = self._config.recent_deck_size
        if deck_size <= 0:
            return []
        lookback_days = self._config.recent_deck_lookback_days
        ratio = max(0.0, min(1.0, self._config.recent_deck_exploration_ratio))
        already_swiped = self._user_swiped_keys(user_id)

        # Split target counts. With no attached sources, the deck is pure
        # exploration; otherwise the ratio governs how many slots go to
        # discovery vs. familiar.
        if not source_ids:
            attached_target, exploration_target = 0, deck_size
        else:
            exploration_target = max(1, int(round(deck_size * ratio))) if ratio > 0 else 0
            exploration_target = min(exploration_target, deck_size)
            attached_target = deck_size - exploration_target

        attached_candidates: list[SourceItemRecord] = []
        if attached_target > 0 and source_ids:
            attached_candidates = self._repository.list_recent_source_items_for_sources(
                source_ids=source_ids,
                lookback_days=lookback_days,
                limit=attached_target * 4,
            )

        exploration_candidates: list[SourceItemRecord] = []
        if exploration_target > 0:
            exploration_candidates = (
                self._repository.list_recent_embedded_items_excluding_sources(
                    excluded_source_ids=source_ids,
                    lookback_days=lookback_days,
                    limit=exploration_target * 4,
                )
            )

        attached_filtered = [
            record for record in attached_candidates if record.dedupe_key not in already_swiped
        ][:attached_target]
        exploration_filtered = [
            record for record in exploration_candidates if record.dedupe_key not in already_swiped
        ][:exploration_target]

        # If one side underdelivered (e.g. corpus thin on exploration items),
        # backfill from the other so the user still gets a full deck.
        attached_shortfall = attached_target - len(attached_filtered)
        exploration_shortfall = exploration_target - len(exploration_filtered)
        if exploration_shortfall > 0:
            extras = [
                record
                for record in attached_candidates
                if record.dedupe_key not in already_swiped
                and record not in attached_filtered
            ][:exploration_shortfall]
            attached_filtered += extras
        if attached_shortfall > 0:
            extras = [
                record
                for record in exploration_candidates
                if record.dedupe_key not in already_swiped
                and record not in exploration_filtered
            ][:attached_shortfall]
            exploration_filtered += extras

        return _interleave(attached_filtered, exploration_filtered, ratio)[:deck_size]

    def _load_or_refresh_cold_start_deck(self) -> Optional[SwipeDeckRecord]:
        existing = self._repository.get_swipe_deck(COLD_START_DECK_ID)
        if existing is not None and not self._is_stale(existing):
            return existing
        refreshed = self._compute_cold_start_deck()
        if refreshed is None:
            # Couldn't recompute (corpus empty?). Fall back to whatever's cached
            # — even stale data is better than no deck.
            return existing
        self._repository.save_swipe_deck(refreshed)
        return refreshed

    def _is_stale(self, deck: SwipeDeckRecord) -> bool:
        age = utc_now() - _ensure_aware(deck.computed_at)
        return age > timedelta(hours=self._config.cold_start_deck_ttl_hours)

    def _compute_cold_start_deck(self) -> Optional[SwipeDeckRecord]:
        corpus = self._repository.list_embedded_source_items(
            limit=self._config.cold_start_corpus_limit
        )
        if not corpus:
            return None
        vectors = [record.embedding for record in corpus if record.embedding]
        if not vectors:
            return None
        representative_indices = kmeans_representative_indices(
            vectors,
            k=self._config.cold_start_deck_size,
            max_iterations=self._kmeans_max_iterations,
        )
        if not representative_indices:
            return None
        dedupe_keys = [corpus[index].dedupe_key for index in representative_indices]
        return SwipeDeckRecord(
            id=COLD_START_DECK_ID,
            dedupe_keys=dedupe_keys,
            corpus_size=len(corpus),
            computed_at=utc_now(),
            version=COLD_START_DECK_VERSION,
        )

    def _user_swiped_keys(self, user_id: str) -> set[str]:
        swipes = self._repository.list_user_swipes(user_id)
        return {swipe.source_item_dedupe_key for swipe in swipes}


def _ensure_aware(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value


def _interleave(
    attached: list[SourceItemRecord],
    exploration: list[SourceItemRecord],
    exploration_ratio: float,
) -> list[SourceItemRecord]:
    """Round-robin merge with the cadence shaped by `exploration_ratio`.

    At ratio=0.3 the resulting deck spaces exploration items roughly 1 in 3.
    Order within each list is preserved; ties go to attached so the first
    card the user sees is usually from a familiar source.
    """
    if not exploration:
        return list(attached)
    if not attached:
        return list(exploration)
    if exploration_ratio <= 0:
        return attached + exploration
    if exploration_ratio >= 1:
        return exploration + attached

    merged: list[SourceItemRecord] = []
    attached_idx, exploration_idx = 0, 0
    # Position-based decision: take from exploration when the running ratio
    # of exploration picks is below the target. Cheap and deterministic.
    total_target = len(attached) + len(exploration)
    for _ in range(total_target):
        exploration_so_far = exploration_idx
        emitted = len(merged)
        want_exploration = (
            exploration_idx < len(exploration)
            and (emitted == 0 or exploration_so_far / max(emitted, 1) < exploration_ratio)
        )
        if want_exploration and attached_idx < len(attached):
            merged.append(exploration[exploration_idx])
            exploration_idx += 1
        elif attached_idx < len(attached):
            merged.append(attached[attached_idx])
            attached_idx += 1
        elif exploration_idx < len(exploration):
            merged.append(exploration[exploration_idx])
            exploration_idx += 1
        else:
            break
    return merged
