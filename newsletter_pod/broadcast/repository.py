from __future__ import annotations

import re
from abc import ABC, abstractmethod
from typing import Optional

from google.cloud import firestore

from .models import BroadcastEpisodeRecord, BroadcastLoopRecord


LOOP_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,47}$")
EPISODE_ID_RE = re.compile(r"^[0-9a-f]{16}$")


def validate_loop_id(loop_id: str) -> str:
    cleaned = (loop_id or "").strip().lower()
    if not LOOP_ID_RE.fullmatch(cleaned):
        raise ValueError(
            "loop_id must be 1-48 chars of lowercase alphanumerics, underscores, or hyphens"
        )
    return cleaned


class BroadcastRepository(ABC):
    """Persistence for the broadcast loop. Kept separate from
    ControlPlaneRepository so the broadcast workstream has its own
    collections and CRUD surface without bloating the user-facing repo.
    """

    @abstractmethod
    def save_loop(self, loop: BroadcastLoopRecord) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_loop(self, loop_id: str) -> Optional[BroadcastLoopRecord]:
        raise NotImplementedError

    @abstractmethod
    def list_loops(self, *, active_only: bool = False) -> list[BroadcastLoopRecord]:
        raise NotImplementedError

    @abstractmethod
    def delete_loop(self, loop_id: str) -> bool:
        raise NotImplementedError

    @abstractmethod
    def save_episode(self, episode: BroadcastEpisodeRecord) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_episode(self, episode_id: str) -> Optional[BroadcastEpisodeRecord]:
        raise NotImplementedError

    @abstractmethod
    def get_latest_episode_for_loop(self, loop_id: str) -> Optional[BroadcastEpisodeRecord]:
        raise NotImplementedError

    @abstractmethod
    def list_episodes_for_loop(self, loop_id: str, *, limit: int = 20) -> list[BroadcastEpisodeRecord]:
        raise NotImplementedError


class InMemoryBroadcastRepository(BroadcastRepository):
    def __init__(self) -> None:
        self._loops: dict[str, BroadcastLoopRecord] = {}
        self._episodes: dict[str, BroadcastEpisodeRecord] = {}

    def save_loop(self, loop: BroadcastLoopRecord) -> None:
        self._loops[loop.loop_id] = loop

    def get_loop(self, loop_id: str) -> Optional[BroadcastLoopRecord]:
        return self._loops.get(loop_id)

    def list_loops(self, *, active_only: bool = False) -> list[BroadcastLoopRecord]:
        loops = list(self._loops.values())
        if active_only:
            loops = [l for l in loops if l.active]
        return sorted(loops, key=lambda l: l.loop_id)

    def delete_loop(self, loop_id: str) -> bool:
        return self._loops.pop(loop_id, None) is not None

    def save_episode(self, episode: BroadcastEpisodeRecord) -> None:
        self._episodes[episode.episode_id] = episode

    def get_episode(self, episode_id: str) -> Optional[BroadcastEpisodeRecord]:
        return self._episodes.get(episode_id)

    def get_latest_episode_for_loop(self, loop_id: str) -> Optional[BroadcastEpisodeRecord]:
        candidates = [e for e in self._episodes.values() if e.loop_id == loop_id]
        if not candidates:
            return None
        return max(candidates, key=lambda e: (e.run_date, e.created_at))

    def list_episodes_for_loop(self, loop_id: str, *, limit: int = 20) -> list[BroadcastEpisodeRecord]:
        candidates = [e for e in self._episodes.values() if e.loop_id == loop_id]
        candidates.sort(key=lambda e: (e.run_date, e.created_at), reverse=True)
        return candidates[:limit]


class FirestoreBroadcastRepository(BroadcastRepository):
    """Stores loops under `<prefix>_broadcast_loops` and episodes under
    `<prefix>_broadcast_episodes`. Episode docs carry `loop_id` as a
    queryable field so "latest for loop" doesn't need a composite index
    beyond Firestore's built-in single-field ordering.
    """

    def __init__(self, collection_prefix: str) -> None:
        self._client = firestore.Client()
        self._loops_collection = f"{collection_prefix}_broadcast_loops"
        self._episodes_collection = f"{collection_prefix}_broadcast_episodes"

    def _loop_doc(self, loop_id: str):
        return self._client.collection(self._loops_collection).document(loop_id)

    def _episode_doc(self, episode_id: str):
        return self._client.collection(self._episodes_collection).document(episode_id)

    def save_loop(self, loop: BroadcastLoopRecord) -> None:
        self._loop_doc(loop.loop_id).set(loop.model_dump(mode="json"))

    def get_loop(self, loop_id: str) -> Optional[BroadcastLoopRecord]:
        snap = self._loop_doc(loop_id).get()
        if not snap.exists:
            return None
        return BroadcastLoopRecord.model_validate(snap.to_dict())

    def list_loops(self, *, active_only: bool = False) -> list[BroadcastLoopRecord]:
        query = self._client.collection(self._loops_collection)
        if active_only:
            query = query.where(filter=firestore.FieldFilter("active", "==", True))
        return [BroadcastLoopRecord.model_validate(doc.to_dict()) for doc in query.stream()]

    def delete_loop(self, loop_id: str) -> bool:
        doc = self._loop_doc(loop_id)
        if not doc.get().exists:
            return False
        doc.delete()
        return True

    def save_episode(self, episode: BroadcastEpisodeRecord) -> None:
        self._episode_doc(episode.episode_id).set(episode.model_dump(mode="json"))

    def get_episode(self, episode_id: str) -> Optional[BroadcastEpisodeRecord]:
        snap = self._episode_doc(episode_id).get()
        if not snap.exists:
            return None
        return BroadcastEpisodeRecord.model_validate(snap.to_dict())

    def get_latest_episode_for_loop(self, loop_id: str) -> Optional[BroadcastEpisodeRecord]:
        query = (
            self._client.collection(self._episodes_collection)
            .where(filter=firestore.FieldFilter("loop_id", "==", loop_id))
            .order_by("run_date", direction=firestore.Query.DESCENDING)
            .order_by("created_at", direction=firestore.Query.DESCENDING)
            .limit(1)
        )
        for doc in query.stream():
            return BroadcastEpisodeRecord.model_validate(doc.to_dict())
        return None

    def list_episodes_for_loop(self, loop_id: str, *, limit: int = 20) -> list[BroadcastEpisodeRecord]:
        query = (
            self._client.collection(self._episodes_collection)
            .where(filter=firestore.FieldFilter("loop_id", "==", loop_id))
            .order_by("run_date", direction=firestore.Query.DESCENDING)
            .order_by("created_at", direction=firestore.Query.DESCENDING)
            .limit(limit)
        )
        return [BroadcastEpisodeRecord.model_validate(doc.to_dict()) for doc in query.stream()]
