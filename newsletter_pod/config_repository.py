"""Versioned persistence + read-path cache for the admin show blueprint.

Mirrors the broadcast repository pattern (ABC + InMemory + Firestore) and the
job-state doc convention: the *active* blueprint lives in a single doc for an
O(1) read on the hot generation path, and every save also appends an immutable
history doc so the studio can list versions and roll back.

``BlueprintProvider`` is the read-path TTL cache: generation reads the active
blueprint through it so a dispatch sweep of N users costs one Firestore read per
TTL window, not N. The PUT handler calls ``invalidate()`` so the editing
instance reflects a change immediately; other Cloud Run instances converge
within the TTL.
"""

from __future__ import annotations

import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Optional

from google.cloud import firestore

from .blueprint import BlueprintVersionRecord, ShowBlueprint

if TYPE_CHECKING:  # pragma: no cover - typing only
    from .config import Settings


class BlueprintRepository(ABC):
    """Persistence for the versioned show blueprint."""

    @abstractmethod
    def get_active(self) -> Optional[BlueprintVersionRecord]:
        raise NotImplementedError

    @abstractmethod
    def save_new_version(
        self,
        blueprint: ShowBlueprint,
        *,
        updated_by: str = "admin",
        note: Optional[str] = None,
        now: Optional[datetime] = None,
    ) -> BlueprintVersionRecord:
        raise NotImplementedError

    @abstractmethod
    def get_version(self, version: int) -> Optional[BlueprintVersionRecord]:
        raise NotImplementedError

    @abstractmethod
    def list_history(self, *, limit: int = 50) -> list[BlueprintVersionRecord]:
        raise NotImplementedError

    def restore_version(
        self, version: int, *, updated_by: str = "admin", now: Optional[datetime] = None
    ) -> Optional[BlueprintVersionRecord]:
        """Re-activate an older version by saving it as a NEW version. Preserves
        the audit trail (the counter never rewinds). Returns None if the target
        version doesn't exist.
        """
        target = self.get_version(version)
        if target is None:
            return None
        return self.save_new_version(
            target.blueprint,
            updated_by=updated_by,
            note=f"restore of v{version}",
            now=now,
        )


def _now(now: Optional[datetime]) -> datetime:
    return now or datetime.now(timezone.utc)


class InMemoryBlueprintRepository(BlueprintRepository):
    def __init__(self) -> None:
        self._active: Optional[BlueprintVersionRecord] = None
        self._history: dict[int, BlueprintVersionRecord] = {}

    def get_active(self) -> Optional[BlueprintVersionRecord]:
        return self._active

    def save_new_version(
        self,
        blueprint: ShowBlueprint,
        *,
        updated_by: str = "admin",
        note: Optional[str] = None,
        now: Optional[datetime] = None,
    ) -> BlueprintVersionRecord:
        next_version = (self._active.version if self._active else 0) + 1
        record = BlueprintVersionRecord(
            version=next_version,
            blueprint=blueprint,
            updated_at=_now(now),
            updated_by=updated_by,
            note=note,
        )
        self._history[next_version] = record
        self._active = record
        return record

    def get_version(self, version: int) -> Optional[BlueprintVersionRecord]:
        return self._history.get(version)

    def list_history(self, *, limit: int = 50) -> list[BlueprintVersionRecord]:
        return sorted(self._history.values(), key=lambda r: r.version, reverse=True)[:limit]


class FirestoreBlueprintRepository(BlueprintRepository):
    """Active blueprint in ``<prefix>_show_blueprint/active``; each version also
    written to ``<prefix>_show_blueprint_history/<zero-padded version>``. Both
    writes happen in one batch so the active pointer and its history row can't
    diverge.
    """

    def __init__(self, collection_prefix: str) -> None:
        self._client = firestore.Client()
        self._active_collection = f"{collection_prefix}_show_blueprint"
        self._history_collection = f"{collection_prefix}_show_blueprint_history"

    def _active_doc(self):
        return self._client.collection(self._active_collection).document("active")

    def _history_doc(self, version: int):
        return self._client.collection(self._history_collection).document(f"{version:06d}")

    def get_active(self) -> Optional[BlueprintVersionRecord]:
        snap = self._active_doc().get()
        if not snap.exists:
            return None
        return BlueprintVersionRecord.model_validate(snap.to_dict())

    def save_new_version(
        self,
        blueprint: ShowBlueprint,
        *,
        updated_by: str = "admin",
        note: Optional[str] = None,
        now: Optional[datetime] = None,
    ) -> BlueprintVersionRecord:
        active = self.get_active()
        next_version = (active.version if active else 0) + 1
        record = BlueprintVersionRecord(
            version=next_version,
            blueprint=blueprint,
            updated_at=_now(now),
            updated_by=updated_by,
            note=note,
        )
        payload = record.model_dump(mode="json")
        batch = self._client.batch()
        batch.set(self._history_doc(next_version), payload)
        batch.set(self._active_doc(), payload)
        batch.commit()
        return record

    def get_version(self, version: int) -> Optional[BlueprintVersionRecord]:
        snap = self._history_doc(version).get()
        if not snap.exists:
            return None
        return BlueprintVersionRecord.model_validate(snap.to_dict())

    def list_history(self, *, limit: int = 50) -> list[BlueprintVersionRecord]:
        query = (
            self._client.collection(self._history_collection)
            .order_by("version", direction=firestore.Query.DESCENDING)
            .limit(limit)
        )
        return [BlueprintVersionRecord.model_validate(doc.to_dict()) for doc in query.stream()]


class BlueprintProvider:
    """Process-local TTL cache over ``BlueprintRepository.get_active``.

    Returns ``None`` when no version has been saved — deliberately, so shipping
    the code changes NOTHING about generation until an admin explicitly saves a
    blueprint (the structured-prompt / de-lint / music / market paths all no-op
    on a ``None`` blueprint). The studio's GET endpoint separately surfaces
    ``default_blueprint`` as the editable starting template.
    """

    def __init__(
        self,
        repository: BlueprintRepository,
        settings: "Settings",
        *,
        ttl_seconds: float = 60.0,
    ) -> None:
        self._repository = repository
        self._settings = settings  # reserved for future seed logic
        self._ttl_seconds = ttl_seconds
        self._cached: Optional[ShowBlueprint] = None
        self._fetched_at: float = 0.0
        self._loaded: bool = False

    def get(self) -> Optional[ShowBlueprint]:
        age = time.monotonic() - self._fetched_at
        if self._loaded and age < self._ttl_seconds:
            return self._cached
        try:
            active = self._repository.get_active()
        except Exception:
            # Never let a Firestore hiccup block generation — serve the last
            # loaded value (which may be None = legacy behaviour).
            return self._cached
        self._cached = active.blueprint if active else None
        self._fetched_at = time.monotonic()
        self._loaded = True
        return self._cached

    def invalidate(self) -> None:
        self._cached = None
        self._fetched_at = 0.0
        self._loaded = False
