from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import date, datetime
from typing import Optional

from google.cloud import firestore

from .user_models import (
    BillingEventRecord,
    CostRecord,
    DeliveryScheduleRecord,
    FeedTokenRecord,
    PodcastProfileRecord,
    SubscriptionRecord,
    UserEpisodeRecord,
    UserRecord,
    UserRunRecord,
    UserSourceRecord,
)


class ControlPlaneRepository(ABC):
    @abstractmethod
    def get_user(self, user_id: str) -> Optional[UserRecord]:
        raise NotImplementedError

    @abstractmethod
    def get_user_by_apple_subject(self, apple_subject: str) -> Optional[UserRecord]:
        raise NotImplementedError

    @abstractmethod
    def save_user(self, user: UserRecord) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_profile(self, user_id: str) -> Optional[PodcastProfileRecord]:
        raise NotImplementedError

    @abstractmethod
    def save_profile(self, profile: PodcastProfileRecord) -> None:
        raise NotImplementedError

    @abstractmethod
    def list_user_sources(self, user_id: str) -> list[UserSourceRecord]:
        raise NotImplementedError

    @abstractmethod
    def replace_user_sources(self, user_id: str, sources: list[UserSourceRecord]) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_feed_token(self, user_id: str) -> Optional[FeedTokenRecord]:
        raise NotImplementedError

    @abstractmethod
    def save_feed_token(self, token_record: FeedTokenRecord) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_feed_token_record(self, token: str) -> Optional[FeedTokenRecord]:
        raise NotImplementedError

    @abstractmethod
    def get_subscription(self, user_id: str) -> Optional[SubscriptionRecord]:
        raise NotImplementedError

    @abstractmethod
    def save_subscription(self, subscription: SubscriptionRecord) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_schedule(self, user_id: str) -> Optional[DeliveryScheduleRecord]:
        raise NotImplementedError

    @abstractmethod
    def save_schedule(self, schedule: DeliveryScheduleRecord) -> None:
        raise NotImplementedError

    @abstractmethod
    def list_schedules(self) -> list[DeliveryScheduleRecord]:
        raise NotImplementedError

    @abstractmethod
    def get_user_source_cursor(self, user_id: str, source_id: str) -> Optional[datetime]:
        raise NotImplementedError

    @abstractmethod
    def update_user_source_cursors(self, user_id: str, cursors: dict[str, datetime]) -> None:
        raise NotImplementedError

    @abstractmethod
    def save_user_episode(self, episode: UserEpisodeRecord) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_user_episode(self, episode_id: str) -> Optional[UserEpisodeRecord]:
        raise NotImplementedError

    @abstractmethod
    def list_recent_user_episodes(self, user_id: str, limit: int) -> list[UserEpisodeRecord]:
        raise NotImplementedError

    @abstractmethod
    def count_user_episodes(self, user_id: str) -> int:
        raise NotImplementedError

    @abstractmethod
    def save_user_run(self, run: UserRunRecord) -> None:
        raise NotImplementedError

    @abstractmethod
    def list_user_runs_for_date(self, user_id: str, local_run_date: date) -> list[UserRunRecord]:
        raise NotImplementedError

    @abstractmethod
    def get_user_run(self, run_id: str) -> Optional[UserRunRecord]:
        raise NotImplementedError

    @abstractmethod
    def find_in_progress_user_run(self, user_id: str) -> Optional[UserRunRecord]:
        raise NotImplementedError

    @abstractmethod
    def save_cost_record(self, cost_record: CostRecord) -> None:
        raise NotImplementedError

    @abstractmethod
    def save_billing_event(self, event: BillingEventRecord) -> None:
        raise NotImplementedError


class InMemoryControlPlaneRepository(ControlPlaneRepository):
    def __init__(self) -> None:
        self._users: dict[str, UserRecord] = {}
        self._users_by_subject: dict[str, str] = {}
        self._profiles: dict[str, PodcastProfileRecord] = {}
        self._sources: dict[str, list[UserSourceRecord]] = {}
        self._feed_tokens_by_user: dict[str, FeedTokenRecord] = {}
        self._feed_tokens: dict[str, FeedTokenRecord] = {}
        self._subscriptions: dict[str, SubscriptionRecord] = {}
        self._schedules: dict[str, DeliveryScheduleRecord] = {}
        self._cursors: dict[tuple[str, str], datetime] = {}
        self._episodes: dict[str, UserEpisodeRecord] = {}
        self._runs: dict[str, UserRunRecord] = {}
        self._costs: dict[str, CostRecord] = {}
        self._billing_events: dict[str, BillingEventRecord] = {}

    def get_user(self, user_id: str) -> Optional[UserRecord]:
        return self._users.get(user_id)

    def get_user_by_apple_subject(self, apple_subject: str) -> Optional[UserRecord]:
        user_id = self._users_by_subject.get(apple_subject)
        return self._users.get(user_id) if user_id else None

    def save_user(self, user: UserRecord) -> None:
        self._users[user.id] = user
        self._users_by_subject[user.apple_subject] = user.id

    def get_profile(self, user_id: str) -> Optional[PodcastProfileRecord]:
        return self._profiles.get(user_id)

    def save_profile(self, profile: PodcastProfileRecord) -> None:
        self._profiles[profile.user_id] = profile

    def list_user_sources(self, user_id: str) -> list[UserSourceRecord]:
        return list(self._sources.get(user_id, []))

    def replace_user_sources(self, user_id: str, sources: list[UserSourceRecord]) -> None:
        self._sources[user_id] = list(sources)

    def get_feed_token(self, user_id: str) -> Optional[FeedTokenRecord]:
        return self._feed_tokens_by_user.get(user_id)

    def save_feed_token(self, token_record: FeedTokenRecord) -> None:
        self._feed_tokens_by_user[token_record.user_id] = token_record
        self._feed_tokens[token_record.token] = token_record

    def get_feed_token_record(self, token: str) -> Optional[FeedTokenRecord]:
        return self._feed_tokens.get(token)

    def get_subscription(self, user_id: str) -> Optional[SubscriptionRecord]:
        return self._subscriptions.get(user_id)

    def save_subscription(self, subscription: SubscriptionRecord) -> None:
        self._subscriptions[subscription.user_id] = subscription

    def get_schedule(self, user_id: str) -> Optional[DeliveryScheduleRecord]:
        return self._schedules.get(user_id)

    def save_schedule(self, schedule: DeliveryScheduleRecord) -> None:
        self._schedules[schedule.user_id] = schedule

    def list_schedules(self) -> list[DeliveryScheduleRecord]:
        return list(self._schedules.values())

    def get_user_source_cursor(self, user_id: str, source_id: str) -> Optional[datetime]:
        return self._cursors.get((user_id, source_id))

    def update_user_source_cursors(self, user_id: str, cursors: dict[str, datetime]) -> None:
        for source_id, value in cursors.items():
            self._cursors[(user_id, source_id)] = value

    def save_user_episode(self, episode: UserEpisodeRecord) -> None:
        self._episodes[episode.id] = episode

    def get_user_episode(self, episode_id: str) -> Optional[UserEpisodeRecord]:
        return self._episodes.get(episode_id)

    def list_recent_user_episodes(self, user_id: str, limit: int) -> list[UserEpisodeRecord]:
        episodes = [episode for episode in self._episodes.values() if episode.user_id == user_id]
        episodes.sort(key=lambda episode: episode.published_at, reverse=True)
        return episodes[:limit]

    def count_user_episodes(self, user_id: str) -> int:
        return sum(1 for episode in self._episodes.values() if episode.user_id == user_id)

    def save_user_run(self, run: UserRunRecord) -> None:
        self._runs[run.id] = run

    def list_user_runs_for_date(self, user_id: str, local_run_date: date) -> list[UserRunRecord]:
        return [
            run
            for run in self._runs.values()
            if run.user_id == user_id and run.local_run_date == local_run_date
        ]

    def get_user_run(self, run_id: str) -> Optional[UserRunRecord]:
        return self._runs.get(run_id)

    def find_in_progress_user_run(self, user_id: str) -> Optional[UserRunRecord]:
        for run in self._runs.values():
            if run.user_id == user_id and run.status == "in_progress":
                return run
        return None

    def save_cost_record(self, cost_record: CostRecord) -> None:
        self._costs[cost_record.run_id] = cost_record

    def save_billing_event(self, event: BillingEventRecord) -> None:
        self._billing_events[event.id] = event


class FirestoreControlPlaneRepository(ControlPlaneRepository):
    def __init__(self, collection_prefix: str) -> None:
        self._db = firestore.Client()
        self._users = self._db.collection(f"{collection_prefix}_users")
        self._profiles = self._db.collection(f"{collection_prefix}_podcast_profiles")
        self._sources = self._db.collection(f"{collection_prefix}_user_sources")
        self._feed_tokens = self._db.collection(f"{collection_prefix}_feed_tokens")
        self._subscriptions = self._db.collection(f"{collection_prefix}_subscriptions")
        self._schedules = self._db.collection(f"{collection_prefix}_delivery_schedules")
        self._episodes = self._db.collection(f"{collection_prefix}_user_episodes")
        self._runs = self._db.collection(f"{collection_prefix}_user_runs")
        self._cursors = self._db.collection(f"{collection_prefix}_user_cursors")
        self._costs = self._db.collection(f"{collection_prefix}_cost_records")
        self._billing_events = self._db.collection(f"{collection_prefix}_billing_events")

    def get_user(self, user_id: str) -> Optional[UserRecord]:
        doc = self._users.document(user_id).get()
        if not doc.exists:
            return None
        return UserRecord.model_validate(doc.to_dict())

    def get_user_by_apple_subject(self, apple_subject: str) -> Optional[UserRecord]:
        docs = list(self._users.where("apple_subject", "==", apple_subject).limit(1).stream())
        if not docs:
            return None
        return UserRecord.model_validate(docs[0].to_dict())

    def save_user(self, user: UserRecord) -> None:
        self._users.document(user.id).set(user.model_dump(mode="python"))

    def get_profile(self, user_id: str) -> Optional[PodcastProfileRecord]:
        doc = self._profiles.document(user_id).get()
        if not doc.exists:
            return None
        return PodcastProfileRecord.model_validate(doc.to_dict())

    def save_profile(self, profile: PodcastProfileRecord) -> None:
        self._profiles.document(profile.user_id).set(profile.model_dump(mode="python"))

    def list_user_sources(self, user_id: str) -> list[UserSourceRecord]:
        docs = list(self._sources.where("user_id", "==", user_id).stream())
        return [UserSourceRecord.model_validate(doc.to_dict()) for doc in docs]

    def replace_user_sources(self, user_id: str, sources: list[UserSourceRecord]) -> None:
        existing = list(self._sources.where("user_id", "==", user_id).stream())
        batch = self._db.batch()
        for doc in existing:
            batch.delete(doc.reference)
        for source in sources:
            batch.set(self._sources.document(source.id), source.model_dump(mode="python"))
        batch.commit()

    def get_feed_token(self, user_id: str) -> Optional[FeedTokenRecord]:
        docs = list(self._feed_tokens.where("user_id", "==", user_id).limit(1).stream())
        if not docs:
            return None
        return FeedTokenRecord.model_validate(docs[0].to_dict())

    def save_feed_token(self, token_record: FeedTokenRecord) -> None:
        self._feed_tokens.document(token_record.token).set(token_record.model_dump(mode="python"))

    def get_feed_token_record(self, token: str) -> Optional[FeedTokenRecord]:
        doc = self._feed_tokens.document(token).get()
        if not doc.exists:
            return None
        return FeedTokenRecord.model_validate(doc.to_dict())

    def get_subscription(self, user_id: str) -> Optional[SubscriptionRecord]:
        doc = self._subscriptions.document(user_id).get()
        if not doc.exists:
            return None
        return SubscriptionRecord.model_validate(doc.to_dict())

    def save_subscription(self, subscription: SubscriptionRecord) -> None:
        self._subscriptions.document(subscription.user_id).set(subscription.model_dump(mode="python"))

    def get_schedule(self, user_id: str) -> Optional[DeliveryScheduleRecord]:
        doc = self._schedules.document(user_id).get()
        if not doc.exists:
            return None
        return DeliveryScheduleRecord.model_validate(doc.to_dict())

    def save_schedule(self, schedule: DeliveryScheduleRecord) -> None:
        self._schedules.document(schedule.user_id).set(schedule.model_dump(mode="python"))

    def list_schedules(self) -> list[DeliveryScheduleRecord]:
        return [DeliveryScheduleRecord.model_validate(doc.to_dict()) for doc in self._schedules.stream()]

    def get_user_source_cursor(self, user_id: str, source_id: str) -> Optional[datetime]:
        doc = self._cursors.document(f"{user_id}:{source_id}").get()
        if not doc.exists:
            return None
        cursor = doc.to_dict().get("cursor")
        return cursor if isinstance(cursor, datetime) else None

    def update_user_source_cursors(self, user_id: str, cursors: dict[str, datetime]) -> None:
        if not cursors:
            return
        batch = self._db.batch()
        for source_id, cursor in cursors.items():
            ref = self._cursors.document(f"{user_id}:{source_id}")
            batch.set(ref, {"user_id": user_id, "source_id": source_id, "cursor": cursor}, merge=True)
        batch.commit()

    def save_user_episode(self, episode: UserEpisodeRecord) -> None:
        self._episodes.document(episode.id).set(episode.model_dump(mode="python"))

    def get_user_episode(self, episode_id: str) -> Optional[UserEpisodeRecord]:
        doc = self._episodes.document(episode_id).get()
        if not doc.exists:
            return None
        return UserEpisodeRecord.model_validate(doc.to_dict())

    def list_recent_user_episodes(self, user_id: str, limit: int) -> list[UserEpisodeRecord]:
        docs = list(self._episodes.where("user_id", "==", user_id).stream())
        episodes = [UserEpisodeRecord.model_validate(doc.to_dict()) for doc in docs]
        episodes.sort(key=lambda episode: episode.published_at, reverse=True)
        return episodes[:limit]

    def count_user_episodes(self, user_id: str) -> int:
        return len(list(self._episodes.where("user_id", "==", user_id).stream()))

    def save_user_run(self, run: UserRunRecord) -> None:
        payload = run.model_dump(mode="python")
        payload["local_run_date"] = run.local_run_date.isoformat()
        payload["local_run_date_iso"] = run.local_run_date.isoformat()
        self._runs.document(run.id).set(payload)

    def list_user_runs_for_date(self, user_id: str, local_run_date: date) -> list[UserRunRecord]:
        run_date_iso = local_run_date.isoformat()
        docs = list(
            self._runs.where("user_id", "==", user_id).where("local_run_date_iso", "==", run_date_iso).stream()
        )
        return [UserRunRecord.model_validate(doc.to_dict()) for doc in docs]

    def get_user_run(self, run_id: str) -> Optional[UserRunRecord]:
        doc = self._runs.document(run_id).get()
        if not doc.exists:
            return None
        return UserRunRecord.model_validate(doc.to_dict())

    def find_in_progress_user_run(self, user_id: str) -> Optional[UserRunRecord]:
        docs = list(
            self._runs
                .where("user_id", "==", user_id)
                .where("status", "==", "in_progress")
                .limit(1)
                .stream()
        )
        if not docs:
            return None
        return UserRunRecord.model_validate(docs[0].to_dict())

    def save_cost_record(self, cost_record: CostRecord) -> None:
        self._costs.document(cost_record.run_id).set(cost_record.model_dump(mode="python"))

    def save_billing_event(self, event: BillingEventRecord) -> None:
        self._billing_events.document(event.id).set(event.model_dump(mode="python"))
