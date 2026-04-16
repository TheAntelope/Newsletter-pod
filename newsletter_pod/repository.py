from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date, datetime
from typing import Optional

from google.cloud import firestore

from .models import DayState, EpisodeRecord, PublishStatus, RunRecord


class Repository(ABC):
    @abstractmethod
    def get_source_cursor(self, source_id: str) -> Optional[datetime]:
        raise NotImplementedError

    @abstractmethod
    def update_source_cursors(self, cursors: dict[str, datetime]) -> None:
        raise NotImplementedError

    @abstractmethod
    def save_episode(self, episode: EpisodeRecord) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_episode(self, episode_id: str) -> Optional[EpisodeRecord]:
        raise NotImplementedError

    @abstractmethod
    def list_recent_episodes(self, limit: int) -> list[EpisodeRecord]:
        raise NotImplementedError

    @abstractmethod
    def save_run(self, run: RunRecord) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_day_state(self, run_date: date) -> DayState:
        raise NotImplementedError


class InMemoryRepository(Repository):
    def __init__(self) -> None:
        self._cursors: dict[str, datetime] = {}
        self._episodes: dict[str, EpisodeRecord] = {}
        self._runs: list[RunRecord] = []

    def get_source_cursor(self, source_id: str) -> Optional[datetime]:
        return self._cursors.get(source_id)

    def update_source_cursors(self, cursors: dict[str, datetime]) -> None:
        self._cursors.update(cursors)

    def save_episode(self, episode: EpisodeRecord) -> None:
        self._episodes[episode.id] = episode

    def get_episode(self, episode_id: str) -> Optional[EpisodeRecord]:
        return self._episodes.get(episode_id)

    def list_recent_episodes(self, limit: int) -> list[EpisodeRecord]:
        episodes = sorted(self._episodes.values(), key=lambda ep: ep.published_at, reverse=True)
        return episodes[:limit]

    def save_run(self, run: RunRecord) -> None:
        self._runs.append(run)

    def get_day_state(self, run_date: date) -> DayState:
        day_runs = [run for run in self._runs if run.run_date == run_date]
        has_published = any(run.status == PublishStatus.PUBLISHED for run in day_runs)
        has_completed = any(
            run.status in {PublishStatus.PUBLISHED, PublishStatus.NO_CONTENT, PublishStatus.PRE_ACCESS}
            for run in day_runs
        )
        has_alert = any(run.alert_sent for run in day_runs)
        last_attempt = max((run.completed_at for run in day_runs), default=None)
        return DayState(
            run_date=run_date,
            has_published_episode=has_published,
            has_completed_run=has_completed,
            has_alert_sent=has_alert,
            last_attempt_at=last_attempt,
        )


class FirestoreRepository(Repository):
    def __init__(self, collection_prefix: str) -> None:
        self._db = firestore.Client()
        self._runs = self._db.collection(f"{collection_prefix}_runs")
        self._episodes = self._db.collection(f"{collection_prefix}_episodes")
        self._cursors = self._db.collection(f"{collection_prefix}_cursors")

    def get_source_cursor(self, source_id: str) -> Optional[datetime]:
        doc = self._cursors.document(source_id).get()
        if not doc.exists:
            return None
        cursor = doc.to_dict().get("cursor")
        if isinstance(cursor, datetime):
            return cursor
        return None

    def update_source_cursors(self, cursors: dict[str, datetime]) -> None:
        if not cursors:
            return
        batch = self._db.batch()
        for source_id, cursor in cursors.items():
            ref = self._cursors.document(source_id)
            batch.set(ref, {"cursor": cursor}, merge=True)
        batch.commit()

    def save_episode(self, episode: EpisodeRecord) -> None:
        payload = episode.model_dump(mode="python")
        self._episodes.document(episode.id).set(payload)

    def get_episode(self, episode_id: str) -> Optional[EpisodeRecord]:
        doc = self._episodes.document(episode_id).get()
        if not doc.exists:
            return None
        return EpisodeRecord.model_validate(doc.to_dict())

    def list_recent_episodes(self, limit: int) -> list[EpisodeRecord]:
        query = self._episodes.order_by("published_at", direction=firestore.Query.DESCENDING).limit(limit)
        return [EpisodeRecord.model_validate(doc.to_dict()) for doc in query.stream()]

    def save_run(self, run: RunRecord) -> None:
        payload = run.model_dump(mode="python")
        payload["run_date"] = run.run_date.isoformat()
        payload["run_date_iso"] = run.run_date.isoformat()
        self._runs.document(run.id).set(payload)

    def get_day_state(self, run_date: date) -> DayState:
        run_date_iso = run_date.isoformat()
        query = self._runs.where("run_date_iso", "==", run_date_iso)
        docs = list(query.stream())
        if not docs:
            return DayState(run_date=run_date)

        runs = [RunRecord.model_validate(doc.to_dict()) for doc in docs]
        has_published = any(run.status == PublishStatus.PUBLISHED for run in runs)
        has_completed = any(
            run.status in {PublishStatus.PUBLISHED, PublishStatus.NO_CONTENT, PublishStatus.PRE_ACCESS}
            for run in runs
        )
        has_alert = any(run.alert_sent for run in runs)
        last_attempt = max((run.completed_at for run in runs), default=None)
        return DayState(
            run_date=run_date,
            has_published_episode=has_published,
            has_completed_run=has_completed,
            has_alert_sent=has_alert,
            last_attempt_at=last_attempt,
        )
