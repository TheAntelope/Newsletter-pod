from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from datetime import date, datetime, timedelta
from typing import Optional

from google.api_core import exceptions as gax_exceptions
from google.cloud import firestore

from .models import (
    NextEpisodeOverrideRecord,
    SourceItemRecord,
    SourcePollingStateRecord,
    SwipeDeckRecord,
)
from .utils import normalize_email, utc_now


def _identity_keys(user: UserRecord) -> list[str]:
    """Flatten a user's identities (plus the legacy apple_subject / neutral pair)
    into "provider:subject" strings for Firestore array-contains resolution.
    Folding the legacy fields in keeps a user resolvable even if its
    `identities` list hasn't been backfilled yet."""
    keys = {f"{ident.provider}:{ident.subject}" for ident in user.identities}
    if user.identity_provider and user.provider_subject:
        keys.add(f"{user.identity_provider}:{user.provider_subject}")
    if user.apple_subject:
        keys.add(f"apple:{user.apple_subject}")
    return sorted(keys)


def _source_item_doc_id(dedupe_key: str) -> str:
    """Hash the (potentially URL-shaped) dedupe_key into a Firestore-safe doc id.

    Raw RSS guids frequently look like `https://example.com/post/123`. Firestore
    rejects document ids that contain `/` (path separator), exceed 1500 bytes,
    or hit a few other reserved patterns. The dedupe_key still lives on the
    document as a field for queries / readability; this function only derives
    the id used to address the doc.
    """
    return hashlib.sha256(dedupe_key.encode("utf-8")).hexdigest()


def _next_episode_override_doc_id(user_id: str, dedupe_key: str) -> str:
    """Compose a deterministic Firestore-safe doc id for an override row.

    `(user_id, dedupe_key)` is unique by construction, but dedupe_key can
    contain `/` (it's often URL-shaped). The user_id prefix keeps the id
    self-identifying for debugging without leaking PII; the hashed dedupe
    suffix dodges Firestore's path-character rules. Same approach as
    `_source_item_doc_id`.
    """
    return f"{user_id}:{hashlib.sha256(dedupe_key.encode('utf-8')).hexdigest()}"
from .user_models import (
    BillingEventRecord,
    ChurnRiskRecord,
    CostRecord,
    DeliveryScheduleRecord,
    DeviceTokenRecord,
    FeedbackRecord,
    FeedTokenRecord,
    InboundEmailItem,
    PodcastProfileRecord,
    SubscriptionRecord,
    SwipeRecord,
    UserEpisodeRecord,
    UserRecord,
    UserRunRecord,
    UserSourceRecord,
    UserSubstackIntent,
)


class ControlPlaneRepository(ABC):
    @abstractmethod
    def get_user(self, user_id: str) -> Optional[UserRecord]:
        raise NotImplementedError

    @abstractmethod
    def get_user_by_apple_subject(self, apple_subject: str) -> Optional[UserRecord]:
        raise NotImplementedError

    @abstractmethod
    def get_user_by_identity(self, provider: str, subject: str) -> Optional[UserRecord]:
        raise NotImplementedError

    @abstractmethod
    def list_users_by_email(self, email: str) -> list[UserRecord]:
        """Return every user whose (normalized) email equals `email`. Used by
        cross-provider account linking to find an existing account to attach a
        new identity to. Returns [] for an empty email. More than one result
        means a pre-existing duplicate that the merge backfill should heal."""
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
    def upsert_source_items(self, records: list[SourceItemRecord]) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_source_item(self, dedupe_key: str) -> Optional[SourceItemRecord]:
        raise NotImplementedError

    @abstractmethod
    def get_source_items(self, dedupe_keys: list[str]) -> list[SourceItemRecord]:
        raise NotImplementedError

    @abstractmethod
    def list_embedded_source_items(self, limit: int = 5000) -> list[SourceItemRecord]:
        raise NotImplementedError

    @abstractmethod
    def list_recent_source_items_for_sources(
        self,
        source_ids: list[str],
        lookback_days: int,
        limit: int,
    ) -> list[SourceItemRecord]:
        raise NotImplementedError

    @abstractmethod
    def list_source_items_by_source_published_since(
        self,
        source_ids: list[str],
        since: datetime,
        limit: int,
    ) -> list[SourceItemRecord]:
        """Return source items for `source_ids` with `published_at >= since`,
        newest-first. Unlike `list_recent_source_items_for_sources`, this
        does NOT filter on embedding presence — the next-episode candidate
        view needs to surface items whether or not their embedding has
        landed yet."""
        raise NotImplementedError

    @abstractmethod
    def list_recent_embedded_items_excluding_sources(
        self,
        excluded_source_ids: list[str],
        lookback_days: int,
        limit: int,
    ) -> list[SourceItemRecord]:
        raise NotImplementedError

    @abstractmethod
    def save_swipe_deck(self, deck: SwipeDeckRecord) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_swipe_deck(self, deck_id: str) -> Optional[SwipeDeckRecord]:
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

    @abstractmethod
    def get_user_by_inbound_alias(self, alias: str) -> Optional[UserRecord]:
        raise NotImplementedError

    @abstractmethod
    def save_inbound_item(self, item: InboundEmailItem) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_inbound_item(self, item_id: str) -> Optional[InboundEmailItem]:
        raise NotImplementedError

    @abstractmethod
    def list_recent_inbound_items(self, user_id: str, limit: int) -> list[InboundEmailItem]:
        raise NotImplementedError

    @abstractmethod
    def list_unconsumed_inbound_items(self, user_id: str) -> list[InboundEmailItem]:
        """Return all inbound items for `user_id` where `consumed_at` is None,
        oldest-first so callers can include them in chronological order."""
        raise NotImplementedError

    @abstractmethod
    def mark_inbound_items_consumed(
        self, item_ids: list[str], consumed_at: datetime
    ) -> None:
        """Stamp `consumed_at` on the given inbound items. No-op for ids
        already consumed or not present."""
        raise NotImplementedError

    @abstractmethod
    def save_feedback(self, feedback: FeedbackRecord) -> None:
        raise NotImplementedError

    @abstractmethod
    def list_recent_feedback(self, user_id: str, limit: int) -> list[FeedbackRecord]:
        raise NotImplementedError

    @abstractmethod
    def list_feedback_since(self, since: Optional[datetime]) -> list[FeedbackRecord]:
        """Return all feedback records created at-or-after `since`, across every
        user, newest-first. When `since` is None, return everything ever
        recorded — used for the first run of the weekly digest job."""
        raise NotImplementedError

    @abstractmethod
    def get_job_state(self, name: str) -> Optional[datetime]:
        raise NotImplementedError

    @abstractmethod
    def set_job_state(self, name: str, last_run_at: datetime) -> None:
        raise NotImplementedError

    @abstractmethod
    def save_swipe(self, swipe: SwipeRecord) -> None:
        raise NotImplementedError

    @abstractmethod
    def list_user_swipes(self, user_id: str, limit: int = 500) -> list[SwipeRecord]:
        raise NotImplementedError

    @abstractmethod
    def count_user_swipes(self, user_id: str) -> int:
        raise NotImplementedError

    @abstractmethod
    def count_user_right_swipes_for_source(self, user_id: str, source_id: str) -> int:
        raise NotImplementedError

    @abstractmethod
    def add_user_source(self, source: UserSourceRecord) -> bool:
        """Attach a source to a user. Idempotent: returns False (and does
        nothing) if a record for the same (user_id, source_id) already
        exists; returns True on actual insert.
        """
        raise NotImplementedError

    @abstractmethod
    def save_substack_intent(self, intent: UserSubstackIntent) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_substack_intent(self, intent_id: str) -> Optional[UserSubstackIntent]:
        raise NotImplementedError

    @abstractmethod
    def list_user_substack_intents(self, user_id: str) -> list[UserSubstackIntent]:
        raise NotImplementedError

    @abstractmethod
    def delete_substack_intent(self, intent_id: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def save_device_token(self, record: DeviceTokenRecord) -> None:
        raise NotImplementedError

    @abstractmethod
    def get_device_token(self, token_id: str) -> Optional[DeviceTokenRecord]:
        raise NotImplementedError

    @abstractmethod
    def list_active_device_tokens(self, user_id: str) -> list[DeviceTokenRecord]:
        """Return active (non-invalidated) APNs device tokens for `user_id`,
        newest-first so the push sender uses the most recently seen device
        before older ones."""
        raise NotImplementedError

    @abstractmethod
    def delete_device_token(self, token_id: str) -> None:
        raise NotImplementedError

    @abstractmethod
    def list_all_user_sources(self) -> list[UserSourceRecord]:
        """Return every UserSourceRecord across all users — used by the
        global hourly source-poll job to walk distinct (source_id, rss_url)
        pairs once per tick instead of per-user."""
        raise NotImplementedError

    @abstractmethod
    def list_all_users(self, limit: int = 1000) -> list[UserRecord]:
        """Return up to `limit` UserRecords. Backs the admin metrics page
        (Phase 2 analytics) which iterates the user base for tier and
        signup-rate tiles. Order is unspecified."""
        raise NotImplementedError

    @abstractmethod
    def list_all_subscriptions(self, limit: int = 1000) -> list[SubscriptionRecord]:
        """Return up to `limit` SubscriptionRecords across every user.
        Backs the admin metrics tier-breakdown tile."""
        raise NotImplementedError

    @abstractmethod
    def list_recent_episodes_across_users(
        self, since: datetime, limit: int = 1000
    ) -> list[UserEpisodeRecord]:
        """Episodes published at-or-after `since` across every user,
        newest-first. Used by admin metrics to compute episodes-per-week.
        Bounded by `limit`."""
        raise NotImplementedError

    @abstractmethod
    def list_recent_swipes_across_users(
        self, since: datetime, limit: int = 5000
    ) -> list[SwipeRecord]:
        """Swipes recorded at-or-after `since` across every user,
        newest-first. Used by admin metrics to compute swipes-per-week."""
        raise NotImplementedError

    @abstractmethod
    def list_recent_user_runs(
        self, user_id: str, limit: int = 50
    ) -> list[UserRunRecord]:
        """Recent UserRunRecords for a single user, newest completed first.
        Used by the admin per-user timeline."""
        raise NotImplementedError

    @abstractmethod
    def save_churn_risk(self, record: ChurnRiskRecord) -> None:
        """Upsert the latest churn-risk snapshot for a user. Keyed by
        user_id so re-runs of /jobs/score-churn-risk replace rather than
        append (Phase 3 stores latest only; history can land later)."""
        raise NotImplementedError

    @abstractmethod
    def get_churn_risk(self, user_id: str) -> Optional[ChurnRiskRecord]:
        raise NotImplementedError

    @abstractmethod
    def list_churn_risks(self, *, at_risk_only: bool = False) -> list[ChurnRiskRecord]:
        """All churn-risk snapshots. When `at_risk_only` is True, returns
        only records flagged at-risk; otherwise returns every scored
        user. Sorted by score descending so the worst risks land first."""
        raise NotImplementedError

    @abstractmethod
    def get_source_polling_state(self, source_id: str) -> Optional[SourcePollingStateRecord]:
        raise NotImplementedError

    @abstractmethod
    def upsert_source_polling_state(self, record: SourcePollingStateRecord) -> None:
        raise NotImplementedError

    @abstractmethod
    def list_next_episode_overrides(
        self,
        user_id: str,
        *,
        kind: Optional[str] = None,
        only_unconsumed: bool = True,
    ) -> list[NextEpisodeOverrideRecord]:
        """Return per-user pin/exclude overrides for the next-episode queue.
        Pass `kind="pin"` or `kind="exclude"` to filter; `only_unconsumed`
        defaults True so once an override is honored by a published episode
        it drops off the active set."""
        raise NotImplementedError

    @abstractmethod
    def save_next_episode_override(self, record: NextEpisodeOverrideRecord) -> None:
        """Idempotent against (user_id, source_item_dedupe_key). If a record
        with the opposite kind already exists, it is replaced — pin/exclude
        are mutually exclusive."""
        raise NotImplementedError

    @abstractmethod
    def delete_next_episode_override(self, user_id: str, dedupe_key: str) -> bool:
        """Remove a user's override for a given item. Returns True if a row
        was deleted, False if no override existed."""
        raise NotImplementedError

    @abstractmethod
    def mark_next_episode_overrides_consumed(
        self, user_id: str, dedupe_keys: list[str], consumed_at: datetime
    ) -> None:
        """Stamp `consumed_at` on the given overrides. No-op for missing or
        already-consumed records."""
        raise NotImplementedError

    @abstractmethod
    def reset_user_state(self, user_id: str) -> dict[str, int]:
        """Wipe per-user onboarding state so the iOS wizard re-runs, while
        keeping the user record, Apple Sign-in linkage, feed token,
        subscription, episode history, runs, billing events, costs, inbound
        items, and feedback intact.

        Idempotent: safe to call on a user who has already been reset; counts
        will be zero or near-zero.

        Deletes:
          - user_sources           (where user_id == uid)
          - podcast_profiles/{uid}
          - delivery_schedules/{uid}
          - swipes                 (where user_id == uid — includes seeds)
          - user_substack_intents  (where user_id == uid)
          - user_cursors           (where user_id == uid — re-attached
                                    sources fetch from scratch)
        Resets:
          - users/{uid}.last_weekly_update_iso_week -> None

        Returns a per-collection count of what was removed, e.g.::

            {
                "user_sources": 5,
                "podcast_profiles": 1,
                "delivery_schedules": 1,
                "swipes": 240,
                "user_substack_intents": 3,
                "user_cursors": 5,
            }
        """
        raise NotImplementedError

    @abstractmethod
    def delete_user_account(self, user_id: str) -> dict[str, int]:
        """Wipe every per-user document we hold for `user_id` and return a
        per-collection count of what was removed.

        Idempotent: safe to call on an already-deleted user; in that case
        counts will be zero or near-zero.

        Returns a dict like::

            {
                "users": 1,
                "podcast_profiles": 1,
                "user_sources": 5,
                "feed_tokens": 1,
                "subscriptions": 1,
                "delivery_schedules": 1,
                "user_episodes": 12,
                "user_runs": 12,
                "user_cursors": 5,
                "cost_records": 12,
                "inbound_items": 30,
                "feedback": 2,
                "swipes": 240,
                "user_substack_intents": 3,
                "billing_events_anonymized": 4,
            }

        Audio blobs in object storage are NOT deleted by this method; the
        caller is responsible for enumerating episode `audio_object_name`
        values and deleting them through `AudioStorage.delete_audio` BEFORE
        invoking this method (after which the episode records are gone).

        Globally-shared collections are NOT touched: source_items,
        swipe_decks, and job_state are system-level data.

        `billing_events` is special: per Danish bookkeeping rules, financial
        records may need to be retained. Rather than delete those rows, we
        null out their `user_id` field so the transaction trail remains for
        accounting but is no longer linked to an identifiable account.
        """
        raise NotImplementedError


class InMemoryControlPlaneRepository(ControlPlaneRepository):
    def __init__(self) -> None:
        self._users: dict[str, UserRecord] = {}
        self._users_by_subject: dict[str, str] = {}
        # (identity_provider, provider_subject) -> user_id
        self._users_by_identity: dict[tuple[str, str], str] = {}
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
        self._inbound_items: dict[str, InboundEmailItem] = {}
        self._feedback: dict[str, FeedbackRecord] = {}
        self._job_state: dict[str, datetime] = {}
        self._source_items: dict[str, SourceItemRecord] = {}
        self._swipes: dict[str, SwipeRecord] = {}
        self._swipe_decks: dict[str, SwipeDeckRecord] = {}
        self._substack_intents: dict[str, UserSubstackIntent] = {}
        self._device_tokens: dict[str, DeviceTokenRecord] = {}
        self._source_polling_state: dict[str, SourcePollingStateRecord] = {}
        # Keyed by (user_id, dedupe_key) so pin/exclude flip is a single
        # write and we can do per-user listings cheaply.
        self._next_episode_overrides: dict[tuple[str, str], NextEpisodeOverrideRecord] = {}
        # Phase 3: latest churn-risk snapshot per user, keyed by user_id.
        self._churn_risks: dict[str, ChurnRiskRecord] = {}

    def get_user(self, user_id: str) -> Optional[UserRecord]:
        return self._users.get(user_id)

    def get_user_by_apple_subject(self, apple_subject: str) -> Optional[UserRecord]:
        user_id = self._users_by_subject.get(apple_subject)
        return self._users.get(user_id) if user_id else None

    def get_user_by_identity(self, provider: str, subject: str) -> Optional[UserRecord]:
        user_id = self._users_by_identity.get((provider, subject))
        if user_id:
            return self._users.get(user_id)
        # Fall back to the Apple index so pre-migration Apple rows (which have
        # apple_subject but no provider pair yet) still resolve.
        if provider == "apple":
            return self.get_user_by_apple_subject(subject)
        return None

    def list_users_by_email(self, email: str) -> list[UserRecord]:
        normalized = normalize_email(email)
        if not normalized:
            return []
        # Scan rather than index so a changed email can't leave a stale match
        # (the corpus is tiny in-memory / in tests).
        return [
            user
            for user in self._users.values()
            if normalize_email(user.email) == normalized
        ]

    def save_user(self, user: UserRecord) -> None:
        self._users[user.id] = user
        if user.apple_subject:
            self._users_by_subject[user.apple_subject] = user.id
        if user.identity_provider and user.provider_subject:
            self._users_by_identity[(user.identity_provider, user.provider_subject)] = user.id
        # Index every attached identity so linked providers all resolve here.
        for ident in user.identities:
            self._users_by_identity[(ident.provider, ident.subject)] = user.id

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

    def upsert_source_items(self, records: list[SourceItemRecord]) -> None:
        for record in records:
            existing = self._source_items.get(record.dedupe_key)
            if existing is None:
                self._source_items[record.dedupe_key] = record.model_copy()
                continue
            updated = record.model_copy()
            updated.first_seen_at = existing.first_seen_at
            if updated.embedding is None and existing.embedding is not None:
                updated.embedding = existing.embedding
                updated.embedding_model = existing.embedding_model
                updated.embedded_at = existing.embedded_at
            self._source_items[record.dedupe_key] = updated

    def get_source_item(self, dedupe_key: str) -> Optional[SourceItemRecord]:
        return self._source_items.get(dedupe_key)

    def get_source_items(self, dedupe_keys: list[str]) -> list[SourceItemRecord]:
        return [self._source_items[key] for key in dedupe_keys if key in self._source_items]

    def list_embedded_source_items(self, limit: int = 5000) -> list[SourceItemRecord]:
        items = [record for record in self._source_items.values() if record.embedding]
        items.sort(key=lambda record: record.last_seen_at, reverse=True)
        return items[:limit]

    def list_recent_source_items_for_sources(
        self,
        source_ids: list[str],
        lookback_days: int,
        limit: int,
    ) -> list[SourceItemRecord]:
        if not source_ids or limit <= 0:
            return []
        source_id_set = set(source_ids)
        cutoff = utc_now() - timedelta(days=lookback_days)
        items = [
            record
            for record in self._source_items.values()
            if record.source_id in source_id_set
            and record.embedding
            and record.last_seen_at >= cutoff
        ]
        items.sort(key=lambda record: record.last_seen_at, reverse=True)
        return items[:limit]

    def list_source_items_by_source_published_since(
        self,
        source_ids: list[str],
        since: datetime,
        limit: int,
    ) -> list[SourceItemRecord]:
        if not source_ids or limit <= 0:
            return []
        source_id_set = set(source_ids)
        items = [
            record
            for record in self._source_items.values()
            if record.source_id in source_id_set and record.published_at >= since
        ]
        items.sort(key=lambda record: record.published_at, reverse=True)
        return items[:limit]

    def list_recent_embedded_items_excluding_sources(
        self,
        excluded_source_ids: list[str],
        lookback_days: int,
        limit: int,
    ) -> list[SourceItemRecord]:
        if limit <= 0:
            return []
        excluded = set(excluded_source_ids)
        cutoff = utc_now() - timedelta(days=lookback_days)
        items = [
            record
            for record in self._source_items.values()
            if record.source_id not in excluded
            and record.embedding
            and record.last_seen_at >= cutoff
        ]
        items.sort(key=lambda record: record.last_seen_at, reverse=True)
        return items[:limit]

    def save_swipe_deck(self, deck: SwipeDeckRecord) -> None:
        self._swipe_decks[deck.id] = deck.model_copy()

    def get_swipe_deck(self, deck_id: str) -> Optional[SwipeDeckRecord]:
        return self._swipe_decks.get(deck_id)

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

    def get_user_by_inbound_alias(self, alias: str) -> Optional[UserRecord]:
        for user in self._users.values():
            if (user.inbound_alias or "").lower() == alias.lower():
                return user
        return None

    def save_inbound_item(self, item: InboundEmailItem) -> None:
        self._inbound_items[item.id] = item

    def get_inbound_item(self, item_id: str) -> Optional[InboundEmailItem]:
        return self._inbound_items.get(item_id)

    def list_recent_inbound_items(self, user_id: str, limit: int) -> list[InboundEmailItem]:
        items = [item for item in self._inbound_items.values() if item.user_id == user_id]
        items.sort(key=lambda item: item.received_at, reverse=True)
        return items[:limit]

    def list_unconsumed_inbound_items(self, user_id: str) -> list[InboundEmailItem]:
        items = [
            item
            for item in self._inbound_items.values()
            if item.user_id == user_id and item.consumed_at is None
        ]
        items.sort(key=lambda item: item.received_at)
        return items

    def mark_inbound_items_consumed(
        self, item_ids: list[str], consumed_at: datetime
    ) -> None:
        for item_id in item_ids:
            existing = self._inbound_items.get(item_id)
            if existing is None or existing.consumed_at is not None:
                continue
            self._inbound_items[item_id] = existing.model_copy(
                update={"consumed_at": consumed_at}
            )

    def save_feedback(self, feedback: FeedbackRecord) -> None:
        self._feedback[feedback.id] = feedback

    def list_recent_feedback(self, user_id: str, limit: int) -> list[FeedbackRecord]:
        items = [item for item in self._feedback.values() if item.user_id == user_id]
        items.sort(key=lambda item: item.created_at, reverse=True)
        return items[:limit]

    def list_feedback_since(self, since: Optional[datetime]) -> list[FeedbackRecord]:
        items = list(self._feedback.values())
        if since is not None:
            items = [item for item in items if item.created_at >= since]
        items.sort(key=lambda item: item.created_at, reverse=True)
        return items

    def get_job_state(self, name: str) -> Optional[datetime]:
        return self._job_state.get(name)

    def set_job_state(self, name: str, last_run_at: datetime) -> None:
        self._job_state[name] = last_run_at

    def save_swipe(self, swipe: SwipeRecord) -> None:
        self._swipes[swipe.id] = swipe

    def list_user_swipes(self, user_id: str, limit: int = 500) -> list[SwipeRecord]:
        items = [swipe for swipe in self._swipes.values() if swipe.user_id == user_id]
        items.sort(key=lambda swipe: swipe.swiped_at, reverse=True)
        return items[:limit]

    def count_user_swipes(self, user_id: str) -> int:
        return sum(1 for swipe in self._swipes.values() if swipe.user_id == user_id)

    def count_user_right_swipes_for_source(self, user_id: str, source_id: str) -> int:
        return sum(
            1
            for swipe in self._swipes.values()
            if swipe.user_id == user_id
            and swipe.source_id == source_id
            and swipe.direction > 0
        )

    def add_user_source(self, source: UserSourceRecord) -> bool:
        existing = self._sources.setdefault(source.user_id, [])
        for record in existing:
            if record.source_id == source.source_id:
                return False
        existing.append(source.model_copy())
        return True

    def save_substack_intent(self, intent: UserSubstackIntent) -> None:
        self._substack_intents[intent.id] = intent.model_copy()

    def get_substack_intent(self, intent_id: str) -> Optional[UserSubstackIntent]:
        return self._substack_intents.get(intent_id)

    def list_user_substack_intents(self, user_id: str) -> list[UserSubstackIntent]:
        intents = [
            intent
            for intent in self._substack_intents.values()
            if intent.user_id == user_id
        ]
        intents.sort(key=lambda intent: intent.created_at, reverse=True)
        return intents

    def delete_substack_intent(self, intent_id: str) -> None:
        self._substack_intents.pop(intent_id, None)

    def save_device_token(self, record: DeviceTokenRecord) -> None:
        self._device_tokens[record.id] = record.model_copy()

    def get_device_token(self, token_id: str) -> Optional[DeviceTokenRecord]:
        return self._device_tokens.get(token_id)

    def list_active_device_tokens(self, user_id: str) -> list[DeviceTokenRecord]:
        records = [
            record
            for record in self._device_tokens.values()
            if record.user_id == user_id and record.invalidated_at is None
        ]
        records.sort(key=lambda r: r.last_seen_at, reverse=True)
        return records

    def delete_device_token(self, token_id: str) -> None:
        self._device_tokens.pop(token_id, None)

    def list_all_user_sources(self) -> list[UserSourceRecord]:
        results: list[UserSourceRecord] = []
        for records in self._sources.values():
            results.extend(records)
        return results

    def list_all_users(self, limit: int = 1000) -> list[UserRecord]:
        return list(self._users.values())[:limit]

    def list_all_subscriptions(self, limit: int = 1000) -> list[SubscriptionRecord]:
        return list(self._subscriptions.values())[:limit]

    def list_recent_episodes_across_users(
        self, since: datetime, limit: int = 1000
    ) -> list[UserEpisodeRecord]:
        items = [
            episode for episode in self._episodes.values()
            if episode.published_at >= since
        ]
        items.sort(key=lambda episode: episode.published_at, reverse=True)
        return items[:limit]

    def list_recent_swipes_across_users(
        self, since: datetime, limit: int = 5000
    ) -> list[SwipeRecord]:
        items = [
            swipe for swipe in self._swipes.values()
            if swipe.swiped_at >= since
        ]
        items.sort(key=lambda swipe: swipe.swiped_at, reverse=True)
        return items[:limit]

    def list_recent_user_runs(
        self, user_id: str, limit: int = 50
    ) -> list[UserRunRecord]:
        runs = [run for run in self._runs.values() if run.user_id == user_id]
        runs.sort(key=lambda run: run.completed_at, reverse=True)
        return runs[:limit]

    def save_churn_risk(self, record: ChurnRiskRecord) -> None:
        self._churn_risks[record.user_id] = record.model_copy()

    def get_churn_risk(self, user_id: str) -> Optional[ChurnRiskRecord]:
        existing = self._churn_risks.get(user_id)
        return existing.model_copy() if existing else None

    def list_churn_risks(self, *, at_risk_only: bool = False) -> list[ChurnRiskRecord]:
        records = list(self._churn_risks.values())
        if at_risk_only:
            records = [record for record in records if record.at_risk]
        records.sort(key=lambda record: record.score, reverse=True)
        return [record.model_copy() for record in records]

    def get_source_polling_state(self, source_id: str) -> Optional[SourcePollingStateRecord]:
        existing = self._source_polling_state.get(source_id)
        return existing.model_copy() if existing else None

    def upsert_source_polling_state(self, record: SourcePollingStateRecord) -> None:
        self._source_polling_state[record.source_id] = record.model_copy()

    def list_next_episode_overrides(
        self,
        user_id: str,
        *,
        kind: Optional[str] = None,
        only_unconsumed: bool = True,
    ) -> list[NextEpisodeOverrideRecord]:
        results: list[NextEpisodeOverrideRecord] = []
        for (uid, _key), record in self._next_episode_overrides.items():
            if uid != user_id:
                continue
            if kind is not None and record.kind != kind:
                continue
            if only_unconsumed and record.consumed_at is not None:
                continue
            results.append(record.model_copy())
        results.sort(key=lambda r: r.created_at)
        return results

    def save_next_episode_override(self, record: NextEpisodeOverrideRecord) -> None:
        self._next_episode_overrides[
            (record.user_id, record.source_item_dedupe_key)
        ] = record.model_copy()

    def delete_next_episode_override(self, user_id: str, dedupe_key: str) -> bool:
        return self._next_episode_overrides.pop((user_id, dedupe_key), None) is not None

    def mark_next_episode_overrides_consumed(
        self, user_id: str, dedupe_keys: list[str], consumed_at: datetime
    ) -> None:
        for key in dedupe_keys:
            existing = self._next_episode_overrides.get((user_id, key))
            if existing is None or existing.consumed_at is not None:
                continue
            self._next_episode_overrides[(user_id, key)] = existing.model_copy(
                update={"consumed_at": consumed_at}
            )

    def reset_user_state(self, user_id: str) -> dict[str, int]:
        counts: dict[str, int] = {
            "user_sources": 0,
            "podcast_profiles": 0,
            "delivery_schedules": 0,
            "swipes": 0,
            "user_substack_intents": 0,
            "user_cursors": 0,
        }

        counts["user_sources"] = len(self._sources.pop(user_id, []) or [])
        counts["podcast_profiles"] = 1 if self._profiles.pop(user_id, None) else 0
        counts["delivery_schedules"] = 1 if self._schedules.pop(user_id, None) else 0

        swipe_keys = [
            key for key, swipe in self._swipes.items() if swipe.user_id == user_id
        ]
        for key in swipe_keys:
            self._swipes.pop(key, None)
        counts["swipes"] = len(swipe_keys)

        intent_keys = [
            key
            for key, intent in self._substack_intents.items()
            if intent.user_id == user_id
        ]
        for key in intent_keys:
            self._substack_intents.pop(key, None)
        counts["user_substack_intents"] = len(intent_keys)

        cursor_keys = [key for key in self._cursors if key[0] == user_id]
        for key in cursor_keys:
            self._cursors.pop(key, None)
        counts["user_cursors"] = len(cursor_keys)

        override_keys = [
            key for key in self._next_episode_overrides if key[0] == user_id
        ]
        for key in override_keys:
            self._next_episode_overrides.pop(key, None)

        # Wipe device tokens (no count returned) so a regenerated user_id
        # doesn't keep pushing through to the old device.
        device_keys = [
            key for key, record in self._device_tokens.items() if record.user_id == user_id
        ]
        for key in device_keys:
            self._device_tokens.pop(key, None)

        user = self._users.get(user_id)
        if user is not None:
            user.last_weekly_update_iso_week = None

        return counts

    def delete_user_account(self, user_id: str) -> dict[str, int]:
        counts: dict[str, int] = {}

        user = self._users.pop(user_id, None)
        counts["users"] = 1 if user else 0
        if user:
            if user.apple_subject:
                self._users_by_subject.pop(user.apple_subject, None)
            if user.identity_provider and user.provider_subject:
                self._users_by_identity.pop((user.identity_provider, user.provider_subject), None)

        counts["podcast_profiles"] = 1 if self._profiles.pop(user_id, None) else 0
        counts["user_sources"] = len(self._sources.pop(user_id, []) or [])

        token_record = self._feed_tokens_by_user.pop(user_id, None)
        if token_record is not None:
            self._feed_tokens.pop(token_record.token, None)
            counts["feed_tokens"] = 1
        else:
            counts["feed_tokens"] = 0

        counts["subscriptions"] = 1 if self._subscriptions.pop(user_id, None) else 0
        counts["delivery_schedules"] = 1 if self._schedules.pop(user_id, None) else 0

        cursor_keys = [key for key in self._cursors if key[0] == user_id]
        for key in cursor_keys:
            self._cursors.pop(key, None)
        counts["user_cursors"] = len(cursor_keys)

        episode_ids = [eid for eid, ep in self._episodes.items() if ep.user_id == user_id]
        for eid in episode_ids:
            self._episodes.pop(eid, None)
        counts["user_episodes"] = len(episode_ids)

        run_ids = [rid for rid, run in self._runs.items() if run.user_id == user_id]
        for rid in run_ids:
            self._runs.pop(rid, None)
        counts["user_runs"] = len(run_ids)

        cost_keys = [
            key for key, record in self._costs.items() if record.user_id == user_id
        ]
        for key in cost_keys:
            self._costs.pop(key, None)
        counts["cost_records"] = len(cost_keys)

        inbound_keys = [
            key for key, item in self._inbound_items.items() if item.user_id == user_id
        ]
        for key in inbound_keys:
            self._inbound_items.pop(key, None)
        counts["inbound_items"] = len(inbound_keys)

        feedback_keys = [
            key for key, item in self._feedback.items() if item.user_id == user_id
        ]
        for key in feedback_keys:
            self._feedback.pop(key, None)
        counts["feedback"] = len(feedback_keys)

        swipe_keys = [
            key for key, swipe in self._swipes.items() if swipe.user_id == user_id
        ]
        for key in swipe_keys:
            self._swipes.pop(key, None)
        counts["swipes"] = len(swipe_keys)

        intent_keys = [
            key for key, intent in self._substack_intents.items() if intent.user_id == user_id
        ]
        for key in intent_keys:
            self._substack_intents.pop(key, None)
        counts["user_substack_intents"] = len(intent_keys)

        anonymized = 0
        for key, event in list(self._billing_events.items()):
            if event.user_id == user_id:
                self._billing_events[key] = event.model_copy(update={"user_id": None})
                anonymized += 1
        counts["billing_events_anonymized"] = anonymized

        override_keys = [
            key for key in self._next_episode_overrides if key[0] == user_id
        ]
        for key in override_keys:
            self._next_episode_overrides.pop(key, None)

        device_keys = [
            key for key, record in self._device_tokens.items() if record.user_id == user_id
        ]
        for key in device_keys:
            self._device_tokens.pop(key, None)

        return counts


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
        self._inbound_items = self._db.collection(f"{collection_prefix}_inbound_items")
        self._feedback = self._db.collection(f"{collection_prefix}_feedback")
        self._source_items = self._db.collection(f"{collection_prefix}_source_items")
        self._swipes = self._db.collection(f"{collection_prefix}_swipes")
        self._swipe_decks = self._db.collection(f"{collection_prefix}_swipe_decks")
        self._substack_intents = self._db.collection(f"{collection_prefix}_user_substack_intents")
        self._device_tokens = self._db.collection(f"{collection_prefix}_device_tokens")
        self._job_state_col = self._db.collection(f"{collection_prefix}_job_state")
        self._source_polling_state = self._db.collection(
            f"{collection_prefix}_source_polling_state"
        )
        self._next_episode_overrides = self._db.collection(
            f"{collection_prefix}_next_episode_overrides"
        )
        # Phase 3: latest churn-risk snapshot per user. Keyed by user_id so
        # the daily scoring job is idempotent (set() overwrites).
        self._churn_risks = self._db.collection(
            f"{collection_prefix}_churn_risks"
        )

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

    def get_user_by_identity(self, provider: str, subject: str) -> Optional[UserRecord]:
        # Primary path: the denormalized identity_keys array (auto-indexed
        # array-contains) resolves a user by ANY of its linked identities.
        docs = list(
            self._users
            .where("identity_keys", "array_contains", f"{provider}:{subject}")
            .limit(1)
            .stream()
        )
        if docs:
            return UserRecord.model_validate(docs[0].to_dict())
        # Fallbacks for pre-migration rows that have no identity_keys yet: the
        # legacy neutral pair, then the Apple subject.
        docs = list(
            self._users
            .where("identity_provider", "==", provider)
            .where("provider_subject", "==", subject)
            .limit(1)
            .stream()
        )
        if docs:
            return UserRecord.model_validate(docs[0].to_dict())
        if provider == "apple":
            return self.get_user_by_apple_subject(subject)
        return None

    def list_users_by_email(self, email: str) -> list[UserRecord]:
        normalized = normalize_email(email)
        if not normalized:
            return []
        docs = list(self._users.where("email", "==", normalized).stream())
        return [UserRecord.model_validate(doc.to_dict()) for doc in docs]

    def save_user(self, user: UserRecord) -> None:
        data = user.model_dump(mode="python")
        # Denormalized index for cross-provider resolution. Not a model field;
        # model_validate ignores it on read.
        data["identity_keys"] = _identity_keys(user)
        self._users.document(user.id).set(data)

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

    def list_all_user_sources(self) -> list[UserSourceRecord]:
        # Full collection scan — bounded by total user count × per-user source
        # count (capped at max_sources_safety_cap). At spike scale this is
        # cheap; revisit if the user base grows past a few thousand.
        return [
            UserSourceRecord.model_validate(doc.to_dict())
            for doc in self._sources.stream()
        ]

    def list_all_users(self, limit: int = 1000) -> list[UserRecord]:
        # Admin metrics only. Bounded by `limit` so the scan never goes
        # unbounded if the user base grows; if/when it does, paginate.
        docs = list(self._users.limit(limit).stream())
        return [UserRecord.model_validate(doc.to_dict()) for doc in docs]

    def list_all_subscriptions(self, limit: int = 1000) -> list[SubscriptionRecord]:
        docs = list(self._subscriptions.limit(limit).stream())
        return [SubscriptionRecord.model_validate(doc.to_dict()) for doc in docs]

    def list_recent_episodes_across_users(
        self, since: datetime, limit: int = 1000
    ) -> list[UserEpisodeRecord]:
        docs = list(
            self._episodes
                .where("published_at", ">=", since)
                .order_by("published_at", direction=firestore.Query.DESCENDING)
                .limit(limit)
                .stream()
        )
        return [UserEpisodeRecord.model_validate(doc.to_dict()) for doc in docs]

    def list_recent_swipes_across_users(
        self, since: datetime, limit: int = 5000
    ) -> list[SwipeRecord]:
        docs = list(
            self._swipes
                .where("swiped_at", ">=", since)
                .order_by("swiped_at", direction=firestore.Query.DESCENDING)
                .limit(limit)
                .stream()
        )
        return [SwipeRecord.model_validate(doc.to_dict()) for doc in docs]

    def list_recent_user_runs(
        self, user_id: str, limit: int = 50
    ) -> list[UserRunRecord]:
        # Pull the user's runs and sort app-side to avoid needing a
        # composite (user_id, completed_at) index. Per-user run count is
        # bounded by their account age × daily delivery cadence.
        docs = list(self._runs.where("user_id", "==", user_id).stream())
        runs = [UserRunRecord.model_validate(doc.to_dict()) for doc in docs]
        runs.sort(key=lambda run: run.completed_at, reverse=True)
        return runs[:limit]

    def save_churn_risk(self, record: ChurnRiskRecord) -> None:
        self._churn_risks.document(record.user_id).set(
            record.model_dump(mode="python")
        )

    def get_churn_risk(self, user_id: str) -> Optional[ChurnRiskRecord]:
        doc = self._churn_risks.document(user_id).get()
        if not doc.exists:
            return None
        return ChurnRiskRecord.model_validate(doc.to_dict())

    def list_churn_risks(self, *, at_risk_only: bool = False) -> list[ChurnRiskRecord]:
        # Sort app-side: combining where(at_risk) with order_by(score)
        # would require a composite index, and at current user-base size
        # the full collection scan is bounded by paid-tier count anyway.
        query = self._churn_risks
        if at_risk_only:
            query = query.where("at_risk", "==", True)
        records = [
            ChurnRiskRecord.model_validate(doc.to_dict())
            for doc in query.stream()
        ]
        records.sort(key=lambda record: record.score, reverse=True)
        return records

    def get_source_polling_state(
        self, source_id: str
    ) -> Optional[SourcePollingStateRecord]:
        doc = self._source_polling_state.document(source_id).get()
        if not doc.exists:
            return None
        return SourcePollingStateRecord.model_validate(doc.to_dict())

    def upsert_source_polling_state(self, record: SourcePollingStateRecord) -> None:
        self._source_polling_state.document(record.source_id).set(
            record.model_dump(mode="python")
        )

    def list_next_episode_overrides(
        self,
        user_id: str,
        *,
        kind: Optional[str] = None,
        only_unconsumed: bool = True,
    ) -> list[NextEpisodeOverrideRecord]:
        # Single equality on user_id + app-side filter on kind/consumed_at
        # to avoid composite indexes — per-user override counts are bounded
        # (a user can pin at most a handful of items at a time).
        docs = list(self._next_episode_overrides.where("user_id", "==", user_id).stream())
        results: list[NextEpisodeOverrideRecord] = []
        for doc in docs:
            record = NextEpisodeOverrideRecord.model_validate(doc.to_dict())
            if kind is not None and record.kind != kind:
                continue
            if only_unconsumed and record.consumed_at is not None:
                continue
            results.append(record)
        results.sort(key=lambda r: r.created_at)
        return results

    def save_next_episode_override(self, record: NextEpisodeOverrideRecord) -> None:
        doc_id = _next_episode_override_doc_id(
            record.user_id, record.source_item_dedupe_key
        )
        self._next_episode_overrides.document(doc_id).set(
            record.model_dump(mode="python")
        )

    def delete_next_episode_override(self, user_id: str, dedupe_key: str) -> bool:
        doc_id = _next_episode_override_doc_id(user_id, dedupe_key)
        ref = self._next_episode_overrides.document(doc_id)
        snapshot = ref.get()
        if not snapshot.exists:
            return False
        ref.delete()
        return True

    def mark_next_episode_overrides_consumed(
        self, user_id: str, dedupe_keys: list[str], consumed_at: datetime
    ) -> None:
        for key in dedupe_keys:
            doc_id = _next_episode_override_doc_id(user_id, key)
            try:
                self._next_episode_overrides.document(doc_id).update(
                    {"consumed_at": consumed_at}
                )
            except gax_exceptions.NotFound:
                continue

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

    def upsert_source_items(self, records: list[SourceItemRecord]) -> None:
        if not records:
            return
        # Firestore caps a single batch at 500 ops and ~10 MiB payload. Each
        # SourceItemRecord carries a 1536-dim embedding (~12-18 KB), so the
        # size cap is the real ceiling — a single-batch write started hitting
        # "Transaction too big" once the corpus grew (2026-05-22). 200/batch
        # keeps us comfortably under both limits.
        BATCH_SIZE = 200
        for start in range(0, len(records), BATCH_SIZE):
            chunk = records[start : start + BATCH_SIZE]
            batch = self._db.batch()
            for record in chunk:
                ref = self._source_items.document(_source_item_doc_id(record.dedupe_key))
                existing_doc = ref.get()
                payload = record.model_dump(mode="python")
                if existing_doc.exists:
                    existing = existing_doc.to_dict() or {}
                    if "first_seen_at" in existing:
                        payload["first_seen_at"] = existing["first_seen_at"]
                    if payload.get("embedding") is None and existing.get("embedding") is not None:
                        payload["embedding"] = existing["embedding"]
                        payload["embedding_model"] = existing.get("embedding_model")
                        payload["embedded_at"] = existing.get("embedded_at")
                batch.set(ref, payload)
            batch.commit()

    def get_source_item(self, dedupe_key: str) -> Optional[SourceItemRecord]:
        doc = self._source_items.document(_source_item_doc_id(dedupe_key)).get()
        if not doc.exists:
            return None
        return SourceItemRecord.model_validate(doc.to_dict())

    def get_source_items(self, dedupe_keys: list[str]) -> list[SourceItemRecord]:
        if not dedupe_keys:
            return []
        refs = [self._source_items.document(_source_item_doc_id(key)) for key in dedupe_keys]
        docs = self._db.get_all(refs)
        records: list[SourceItemRecord] = []
        for doc in docs:
            if not doc.exists:
                continue
            records.append(SourceItemRecord.model_validate(doc.to_dict()))
        return records

    def list_embedded_source_items(self, limit: int = 5000) -> list[SourceItemRecord]:
        # Firestore can't filter on "field is non-null" directly; we order by
        # embedded_at (which is only set once an embedding is stored) and treat
        # the order_by as the de-facto null filter.
        docs = list(
            self._source_items
                .order_by("embedded_at", direction=firestore.Query.DESCENDING)
                .limit(limit)
                .stream()
        )
        records: list[SourceItemRecord] = []
        for doc in docs:
            data = doc.to_dict() or {}
            if not data.get("embedding"):
                continue
            records.append(SourceItemRecord.model_validate(data))
        return records

    def list_source_items_by_source_published_since(
        self,
        source_ids: list[str],
        since: datetime,
        limit: int,
    ) -> list[SourceItemRecord]:
        if not source_ids or limit <= 0:
            return []
        # Bounded, recency-ordered scan of the global source_items collection,
        # filtered to the user's sources + window in app code. The previous
        # implementation streamed the *entire* history of every source via a
        # `where("source_id", "in", chunk)` query with no server-side limit; for
        # a user with many high-volume sources that streamed thousands of docs
        # and blew the gRPC stream deadline (~77s observed), which the firestore
        # client's retry path then masked as an opaque AttributeError — 500ing
        # the whole candidate-queue endpoint. Ordering by published_at and
        # capping the scan keeps the read bounded (single-field index, no
        # composite needed); the trade-off is we don't surface items older than
        # the scan window, which is fine since the caller only wants the `limit`
        # newest items within `since`. Mirrors the recency-scan approach in
        # `list_recent_embedded_items_excluding_sources`.
        wanted = set(source_ids)
        scan_size = max(limit * 10, 500)
        docs = list(
            self._source_items
                .order_by("published_at", direction=firestore.Query.DESCENDING)
                .limit(scan_size)
                .stream()
        )
        results: list[SourceItemRecord] = []
        for doc in docs:
            data = doc.to_dict() or {}
            record = SourceItemRecord.model_validate(data)
            if record.source_id not in wanted:
                continue
            if record.published_at < since:
                continue
            results.append(record)
        results.sort(key=lambda record: record.published_at, reverse=True)
        return results[:limit]

    def list_recent_source_items_for_sources(
        self,
        source_ids: list[str],
        lookback_days: int,
        limit: int,
    ) -> list[SourceItemRecord]:
        if not source_ids or limit <= 0:
            return []
        include = set(source_ids)
        cutoff = utc_now() - timedelta(days=lookback_days)
        # Bounded scan: walk the global recent-embedded stream newest-first
        # (single-field `embedded_at` index) and keep items from the requested
        # sources, app-side. This replaces an unbounded per-chunk `in`-query
        # `.stream()` that read EVERY doc for up to 30 sources at a time and
        # blew the Firestore deadline (→ 500s) when onboarding selected every
        # topic. Combining `in` with `order_by`/range would need a composite
        # index per source-arity, which the repo deliberately avoids (see the
        # sibling list_recent_embedded_items_excluding_sources). We read a
        # multiple of `limit` to absorb the app-side filter without
        # re-querying; sources sparse in the recent window are covered by the
        # caller's global-cold-start backfill.
        scan_size = max(limit * 4, 50)
        docs = list(
            self._source_items
                .order_by("embedded_at", direction=firestore.Query.DESCENDING)
                .limit(scan_size)
                .stream()
        )
        results: list[SourceItemRecord] = []
        for doc in docs:
            data = doc.to_dict() or {}
            if not data.get("embedding"):
                continue
            record = SourceItemRecord.model_validate(data)
            if record.source_id not in include:
                continue
            if record.last_seen_at < cutoff:
                continue
            results.append(record)
        results.sort(key=lambda record: record.last_seen_at, reverse=True)
        return results[:limit]

    def list_recent_embedded_items_excluding_sources(
        self,
        excluded_source_ids: list[str],
        lookback_days: int,
        limit: int,
    ) -> list[SourceItemRecord]:
        if limit <= 0:
            return []
        excluded = set(excluded_source_ids)
        cutoff = utc_now() - timedelta(days=lookback_days)
        # Firestore has no cheap "not in" filter at arbitrary cardinality, so
        # we scan recent embedded items and filter app-side. `embedded_at`
        # ordering gives us a stable, recency-biased traversal; we read ~4x
        # the requested limit to absorb the filter without re-querying.
        scan_size = max(limit * 4, 50)
        docs = list(
            self._source_items
                .order_by("embedded_at", direction=firestore.Query.DESCENDING)
                .limit(scan_size)
                .stream()
        )
        results: list[SourceItemRecord] = []
        for doc in docs:
            data = doc.to_dict() or {}
            if not data.get("embedding"):
                continue
            record = SourceItemRecord.model_validate(data)
            if record.source_id in excluded:
                continue
            if record.last_seen_at < cutoff:
                continue
            results.append(record)
            if len(results) >= limit:
                break
        return results

    def save_swipe_deck(self, deck: SwipeDeckRecord) -> None:
        self._swipe_decks.document(deck.id).set(deck.model_dump(mode="python"))

    def get_swipe_deck(self, deck_id: str) -> Optional[SwipeDeckRecord]:
        doc = self._swipe_decks.document(deck_id).get()
        if not doc.exists:
            return None
        return SwipeDeckRecord.model_validate(doc.to_dict())

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

    def get_user_by_inbound_alias(self, alias: str) -> Optional[UserRecord]:
        docs = list(
            self._users.where("inbound_alias", "==", alias.lower()).limit(1).stream()
        )
        if not docs:
            return None
        return UserRecord.model_validate(docs[0].to_dict())

    def save_inbound_item(self, item: InboundEmailItem) -> None:
        self._inbound_items.document(item.id).set(item.model_dump(mode="python"))

    def get_inbound_item(self, item_id: str) -> Optional[InboundEmailItem]:
        doc = self._inbound_items.document(item_id).get()
        if not doc.exists:
            return None
        return InboundEmailItem.model_validate(doc.to_dict())

    def list_recent_inbound_items(self, user_id: str, limit: int) -> list[InboundEmailItem]:
        docs = list(
            self._inbound_items
                .where("user_id", "==", user_id)
                .order_by("received_at", direction=firestore.Query.DESCENDING)
                .limit(limit)
                .stream()
        )
        return [InboundEmailItem.model_validate(doc.to_dict()) for doc in docs]

    def list_unconsumed_inbound_items(self, user_id: str) -> list[InboundEmailItem]:
        # Firestore won't let us combine an equality filter with "consumed_at
        # IS NULL" without a composite index, so we filter consumed_at in
        # Python. The per-user inbound volume is small (one user's mail), so
        # the scan is cheap.
        docs = list(
            self._inbound_items
                .where("user_id", "==", user_id)
                .stream()
        )
        items: list[InboundEmailItem] = []
        for doc in docs:
            item = InboundEmailItem.model_validate(doc.to_dict())
            if item.consumed_at is None:
                items.append(item)
        items.sort(key=lambda item: item.received_at)
        return items

    def mark_inbound_items_consumed(
        self, item_ids: list[str], consumed_at: datetime
    ) -> None:
        # Volume per episode is small (a handful of inbound items at most),
        # so we do individual updates rather than a batch — that way a doc
        # deleted between read and write (NotFound) doesn't fail the others
        # and won't get recreated as a stub the way set(merge=True) would.
        for item_id in item_ids:
            try:
                self._inbound_items.document(item_id).update(
                    {"consumed_at": consumed_at}
                )
            except gax_exceptions.NotFound:
                continue

    def save_feedback(self, feedback: FeedbackRecord) -> None:
        self._feedback.document(feedback.id).set(feedback.model_dump(mode="python"))

    def list_recent_feedback(self, user_id: str, limit: int) -> list[FeedbackRecord]:
        docs = list(
            self._feedback
                .where("user_id", "==", user_id)
                .order_by("created_at", direction=firestore.Query.DESCENDING)
                .limit(limit)
                .stream()
        )
        return [FeedbackRecord.model_validate(doc.to_dict()) for doc in docs]

    def list_feedback_since(self, since: Optional[datetime]) -> list[FeedbackRecord]:
        query = self._feedback.order_by(
            "created_at", direction=firestore.Query.DESCENDING
        )
        if since is not None:
            query = query.where("created_at", ">=", since)
        docs = list(query.stream())
        return [FeedbackRecord.model_validate(doc.to_dict()) for doc in docs]

    def get_job_state(self, name: str) -> Optional[datetime]:
        doc = self._job_state_col.document(name).get()
        if not doc.exists:
            return None
        data = doc.to_dict() or {}
        value = data.get("last_run_at")
        if isinstance(value, datetime):
            return value
        return None

    def set_job_state(self, name: str, last_run_at: datetime) -> None:
        self._job_state_col.document(name).set(
            {"name": name, "last_run_at": last_run_at}
        )

    def save_swipe(self, swipe: SwipeRecord) -> None:
        self._swipes.document(swipe.id).set(swipe.model_dump(mode="python"))

    def list_user_swipes(self, user_id: str, limit: int = 500) -> list[SwipeRecord]:
        # No order_by/limit at query time: combining where(user_id) with
        # order_by(swiped_at) requires a composite index. Per-user swipe
        # counts are small enough at current scale that pulling all rows
        # and sorting in app code is fine. Revisit when a single user's
        # history exceeds a few thousand swipes.
        docs = list(self._swipes.where("user_id", "==", user_id).stream())
        records = [SwipeRecord.model_validate(doc.to_dict()) for doc in docs]
        records.sort(key=lambda swipe: swipe.swiped_at, reverse=True)
        return records[:limit]

    def count_user_swipes(self, user_id: str) -> int:
        return len(list(self._swipes.where("user_id", "==", user_id).stream()))

    def count_user_right_swipes_for_source(self, user_id: str, source_id: str) -> int:
        # Single equality where + app-side filter on source_id + direction
        # so we don't need a composite index. Per-user swipe counts are
        # bounded enough at current scale that this is fine.
        docs = list(self._swipes.where("user_id", "==", user_id).stream())
        return sum(
            1
            for doc in docs
            if (data := doc.to_dict() or {}).get("source_id") == source_id
            and data.get("direction", 0) > 0
        )

    def add_user_source(self, source: UserSourceRecord) -> bool:
        # Idempotent against (user_id, source_id). Fetching the user's
        # attachments (bounded by max_sources_safety_cap) and filtering
        # source_id app-side avoids needing a composite index for two
        # equality `where` clauses.
        existing = list(self._sources.where("user_id", "==", source.user_id).stream())
        for doc in existing:
            data = doc.to_dict() or {}
            if data.get("source_id") == source.source_id:
                return False
        self._sources.document(source.id).set(source.model_dump(mode="python"))
        return True

    def save_substack_intent(self, intent: UserSubstackIntent) -> None:
        self._substack_intents.document(intent.id).set(intent.model_dump(mode="python"))

    def get_substack_intent(self, intent_id: str) -> Optional[UserSubstackIntent]:
        doc = self._substack_intents.document(intent_id).get()
        if not doc.exists:
            return None
        return UserSubstackIntent.model_validate(doc.to_dict())

    def list_user_substack_intents(self, user_id: str) -> list[UserSubstackIntent]:
        # Single equality where + app-side sort avoids needing a composite
        # index for (user_id, created_at). Per-user intent counts are
        # bounded (a user has maybe tens of Substacks at most) so this is
        # fine.
        docs = list(self._substack_intents.where("user_id", "==", user_id).stream())
        records = [UserSubstackIntent.model_validate(doc.to_dict()) for doc in docs]
        records.sort(key=lambda intent: intent.created_at, reverse=True)
        return records

    def delete_substack_intent(self, intent_id: str) -> None:
        self._substack_intents.document(intent_id).delete()

    def save_device_token(self, record: DeviceTokenRecord) -> None:
        self._device_tokens.document(record.id).set(record.model_dump(mode="python"))

    def get_device_token(self, token_id: str) -> Optional[DeviceTokenRecord]:
        doc = self._device_tokens.document(token_id).get()
        if not doc.exists:
            return None
        return DeviceTokenRecord.model_validate(doc.to_dict())

    def list_active_device_tokens(self, user_id: str) -> list[DeviceTokenRecord]:
        # Single equality where + app-side filter on invalidated_at avoids
        # needing a composite index. Per-user device-token counts are tiny
        # (a user has 1-3 devices) so this is fine.
        docs = list(self._device_tokens.where("user_id", "==", user_id).stream())
        records = [DeviceTokenRecord.model_validate(d.to_dict() or {}) for d in docs]
        records = [r for r in records if r.invalidated_at is None]
        records.sort(key=lambda r: r.last_seen_at, reverse=True)
        return records

    def delete_device_token(self, token_id: str) -> None:
        self._device_tokens.document(token_id).delete()

    def reset_user_state(self, user_id: str) -> dict[str, int]:
        counts: dict[str, int] = {
            "user_sources": 0,
            "podcast_profiles": 0,
            "delivery_schedules": 0,
            "swipes": 0,
            "user_substack_intents": 0,
            "user_cursors": 0,
        }

        # Single-doc collections keyed by user_id.
        for collection, key in (
            (self._profiles, "podcast_profiles"),
            (self._schedules, "delivery_schedules"),
        ):
            ref = collection.document(user_id)
            snapshot = ref.get()
            if snapshot.exists:
                ref.delete()
                counts[key] = 1

        # Multi-doc per-user collections: query by user_id, batch-delete.
        for collection, key in (
            (self._sources, "user_sources"),
            (self._swipes, "swipes"),
            (self._substack_intents, "user_substack_intents"),
            (self._cursors, "user_cursors"),
        ):
            counts[key] = self._batch_delete_where_user(collection, user_id)

        # Device tokens are wiped on reset so a regenerated user_id doesn't
        # keep pushing through to the old device until the user re-opens the
        # app. Not counted in the returned summary — they're stateless.
        self._batch_delete_where_user(self._device_tokens, user_id)

        # Wipe next-episode overrides so a re-onboarded user doesn't carry
        # forward stale pins/excludes against items in their old source set.
        self._batch_delete_where_user(self._next_episode_overrides, user_id)

        # Clear the weekly-update marker so the next eligible run regenerates
        # the weekly summary card on the user's first post-reset episode.
        user_ref = self._users.document(user_id)
        if user_ref.get().exists:
            user_ref.update({"last_weekly_update_iso_week": None})

        return counts

    def delete_user_account(self, user_id: str) -> dict[str, int]:
        counts: dict[str, int] = {
            "users": 0,
            "podcast_profiles": 0,
            "user_sources": 0,
            "feed_tokens": 0,
            "subscriptions": 0,
            "delivery_schedules": 0,
            "user_episodes": 0,
            "user_runs": 0,
            "user_cursors": 0,
            "cost_records": 0,
            "inbound_items": 0,
            "feedback": 0,
            "swipes": 0,
            "user_substack_intents": 0,
            "billing_events_anonymized": 0,
        }

        # Single-doc collections keyed by user_id.
        for collection, key in (
            (self._users, "users"),
            (self._profiles, "podcast_profiles"),
            (self._subscriptions, "subscriptions"),
            (self._schedules, "delivery_schedules"),
        ):
            ref = collection.document(user_id)
            snapshot = ref.get()
            if snapshot.exists:
                ref.delete()
                counts[key] = 1

        # Multi-doc per-user collections: query by user_id, batch-delete.
        # `cost_records` is keyed by `run_id` and references `user_id`; we
        # query it just like any other per-user collection.
        for collection, key in (
            (self._sources, "user_sources"),
            (self._episodes, "user_episodes"),
            (self._runs, "user_runs"),
            (self._costs, "cost_records"),
            (self._inbound_items, "inbound_items"),
            (self._feedback, "feedback"),
            (self._swipes, "swipes"),
            (self._substack_intents, "user_substack_intents"),
        ):
            counts[key] = self._batch_delete_where_user(collection, user_id)

        # Device tokens are wiped on account delete (no count in the summary).
        self._batch_delete_where_user(self._device_tokens, user_id)

        # Feed token: doc id is the token (random string), not user_id, so we
        # have to query by user_id first.
        for doc in self._feed_tokens.where("user_id", "==", user_id).stream():
            doc.reference.delete()
            counts["feed_tokens"] += 1

        # Source cursors: doc id is `{user_id}:{source_id}`. We could prefix-
        # scan, but querying by user_id is simpler and matches how the rest
        # of the per-user data is wiped.
        for doc in self._cursors.where("user_id", "==", user_id).stream():
            doc.reference.delete()
            counts["user_cursors"] += 1

        # Billing events: anonymize rather than delete. The bookkeeping trail
        # stays; the link to the deleted user does not.
        for doc in self._billing_events.where("user_id", "==", user_id).stream():
            doc.reference.update({"user_id": None})
            counts["billing_events_anonymized"] += 1

        # Next-episode overrides — wiped silently (no per-collection count
        # since the spike-era surface doesn't need to expose it).
        self._batch_delete_where_user(self._next_episode_overrides, user_id)

        return counts

    def _batch_delete_where_user(
        self, collection: firestore.CollectionReference, user_id: str
    ) -> int:
        """Delete every doc in `collection` whose `user_id` field equals
        `user_id`. Batches in chunks of 400 (Firestore's per-batch limit is
        500; we leave headroom). Returns the total count deleted."""
        BATCH_LIMIT = 400
        deleted = 0
        batch = self._db.batch()
        pending = 0
        for doc in collection.where("user_id", "==", user_id).stream():
            batch.delete(doc.reference)
            pending += 1
            deleted += 1
            if pending >= BATCH_LIMIT:
                batch.commit()
                batch = self._db.batch()
                pending = 0
        if pending > 0:
            batch.commit()
        return deleted
