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


class _DeckRepository(Protocol):
    def list_embedded_source_items(self, limit: int = 5000) -> list[SourceItemRecord]: ...

    def list_recent_source_items_for_sources(
        self, source_ids: list[str], lookback_days: int, limit: int
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
    recent_deck_size: int
    recent_deck_lookback_days: int


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

    def get_recent_deck(
        self, user_id: str, source_ids: list[str]
    ) -> list[SourceItemRecord]:
        if not source_ids:
            return []
        deck_size = self._config.recent_deck_size
        already_swiped = self._user_swiped_keys(user_id)
        # Pull a wider candidate window than we need so the swipe filter has
        # something to chew on without re-querying.
        candidates = self._repository.list_recent_source_items_for_sources(
            source_ids=source_ids,
            lookback_days=self._config.recent_deck_lookback_days,
            limit=deck_size * 4,
        )
        filtered = [
            record for record in candidates if record.dedupe_key not in already_swiped
        ]
        return filtered[:deck_size]

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
