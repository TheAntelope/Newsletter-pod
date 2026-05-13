from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4
from zoneinfo import ZoneInfo

import feedparser
import requests

from .auth import AppleIdentityVerifier, SessionManager
from .config import Settings, load_sources, load_voices
from .costing import estimate_generation_cost
from .embeddings import EmbeddingProvider
from .inbound import ensure_user_inbound_alias
from .substack import (
    SubstackProbeResult,
    build_intent_id,
    canonicalize_pub_url,
    probe_publication,
)
from .ingestion import RSSIngestionService
from .interest_vector import compute_user_vector
from .mailer import Mailer
from .models import PodcastUxConfig, PublishStatus, SourceDefinition, SourceItem, SourceItemRecord, SourceItemRef
from .podcast_api import PodcastApiClient
from .prompting import build_digest_prompt
from .ranker import rank_items
from .source_persistence import SourceItemPersistenceService
from .storage import AudioStorage
from .swipe_deck import SwipeDeckService
from .weather import fetch_weather_summary
from .translation import TranslationError, translate_to_english
from .weekly_update import iso_week_key, load_recent_commits
from .user_models import (
    BillingEventRecord,
    CostRecord,
    DeliveryScheduleRecord,
    FeedbackRecord,
    FeedTokenRecord,
    PodcastProfileRecord,
    SubscriptionRecord,
    SwipeRecord,
    UserEntitlements,
    UserEpisodeRecord,
    UserRecord,
    UserRunRecord,
    UserSourceRecord,
    UserSubstackIntent,
)
from .user_repository import ControlPlaneRepository

logger = logging.getLogger(__name__)
from .utils import link_hash, utc_now

_PROJECT_ROOT = Path(__file__).resolve().parent.parent

WELCOME_EPISODE_TITLE = "Welcome to ClawCast"
WELCOME_EPISODE_DESCRIPTION = (
    "Hi there, and welcome to ClawCast. In this short intro, Vinnie and Demi walk you "
    "through what ClawCast does, how to set up your sources, and how to get the most out "
    "of your custom podcast. Once you've finished setting up your show, your first real "
    "episode will arrive in this feed shortly."
)

COMPLETED_RUN_STATUSES = {PublishStatus.PUBLISHED.value, PublishStatus.NO_CONTENT.value}
WEEKDAY_NAMES = [
    "monday",
    "tuesday",
    "wednesday",
    "thursday",
    "friday",
    "saturday",
    "sunday",
]


class ControlPlaneError(RuntimeError):
    pass


@dataclass
class TaskEnqueuer:
    def enqueue_user_generation(self, user_id: str, force: bool = False) -> dict[str, Any]:
        raise NotImplementedError


@dataclass
class InMemoryTaskEnqueuer(TaskEnqueuer):
    jobs: list[dict[str, Any]] = field(default_factory=list)

    def enqueue_user_generation(self, user_id: str, force: bool = False) -> dict[str, Any]:
        job = {"user_id": user_id, "force": force}
        self.jobs.append(job)
        return job


@dataclass
class CloudTasksEnqueuer(TaskEnqueuer):
    queue_path: str
    service_url: str
    service_account_email: Optional[str]
    job_trigger_token: Optional[str]
    client: Any = None

    def enqueue_user_generation(self, user_id: str, force: bool = False) -> dict[str, Any]:
        if self.client is None:
            from google.cloud import tasks_v2

            self.client = tasks_v2.CloudTasksClient()
        from google.cloud import tasks_v2

        headers = {"Content-Type": "application/json"}
        if self.job_trigger_token:
            headers["X-Job-Trigger-Token"] = self.job_trigger_token

        task: dict[str, Any] = {
            "http_request": {
                "http_method": tasks_v2.HttpMethod.POST,
                "url": f"{self.service_url.rstrip('/')}/jobs/process-user-podcast",
                "headers": headers,
                "body": f'{{"user_id":"{user_id}","force":{str(force).lower()}}}'.encode("utf-8"),
            }
        }
        if self.service_account_email:
            task["http_request"]["oidc_token"] = {"service_account_email": self.service_account_email}

        created = self.client.create_task(parent=self.queue_path, task=task)
        return {"name": created.name, "user_id": user_id, "force": force}


class _UserCursorRepositoryAdapter:
    def __init__(self, repository: ControlPlaneRepository, user_id: str) -> None:
        self._repository = repository
        self._user_id = user_id

    def get_source_cursor(self, source_id: str) -> Optional[datetime]:
        return self._repository.get_user_source_cursor(self._user_id, source_id)

    def update_source_cursors(self, cursors: dict[str, datetime]) -> None:
        self._repository.update_user_source_cursors(self._user_id, cursors)


@dataclass
class ControlPlaneService:
    settings: Settings
    repository: ControlPlaneRepository
    storage: AudioStorage
    podcast_client: PodcastApiClient
    mailer: Mailer
    session_manager: SessionManager
    apple_identity_verifier: AppleIdentityVerifier
    task_enqueuer: TaskEnqueuer
    embedding_provider: Optional[EmbeddingProvider] = None

    def __post_init__(self) -> None:
        self._catalog = {source.id: source for source in load_sources(self.settings.sources_file)}
        self._voice_catalog = {voice.id: voice for voice in load_voices(self.settings.voices_file)}
        self._source_item_persistence = SourceItemPersistenceService(
            repository=self.repository,
            embeddings=self.embedding_provider,
        )
        self._swipe_deck_service = SwipeDeckService(
            repository=self.repository,
            config=self.settings,
        )

    def authenticate_with_apple(
        self,
        identity_token: str,
        given_name: Optional[str] = None,
    ) -> dict[str, Any]:
        identity = self.apple_identity_verifier.verify(identity_token)
        existing_user = self.repository.get_user_by_apple_subject(identity.subject)
        is_new = existing_user is None
        user = existing_user or self._create_default_user(
            identity.subject, identity.email, given_name=given_name
        )
        if existing_user is None:
            self._persist_default_records(user)

        ensure_user_inbound_alias(self.repository, user)
        token, session = self.session_manager.issue(user.id)
        return {
            "session_token": token,
            "session": session.model_dump(mode="json"),
            "is_new_user": is_new,
            "user": self._user_payload(user),
            "subscription": self._get_subscription(user.id).model_dump(mode="json"),
        }

    def get_authenticated_user(self, session_token: str) -> UserRecord:
        session = self.session_manager.verify(session_token)
        user = self.repository.get_user(session.user_id)
        if not user:
            raise ControlPlaneError("User not found")
        return user

    def get_me(self, user_id: str) -> dict[str, Any]:
        user = self._require_user(user_id)
        ensure_user_inbound_alias(self.repository, user)
        subscription = self._get_subscription(user_id)
        entitlements = self._entitlements_for(subscription)
        return {
            "user": self._user_payload(user),
            "profile": self._get_profile(user_id).model_dump(mode="json"),
            "schedule": self._get_schedule(user_id).model_dump(mode="json"),
            "subscription": subscription.model_dump(mode="json"),
            "entitlements": entitlements.model_dump(mode="json"),
        }

    def list_inbound_items(self, user_id: str, limit: int = 20) -> dict[str, Any]:
        user = self._require_user(user_id)
        ensure_user_inbound_alias(self.repository, user)
        items = self.repository.list_recent_inbound_items(user_id, limit)
        return {
            "inbound_address": self._inbound_address_for(user),
            "items": [item.model_dump(mode="json") for item in items],
        }

    def probe_substack_publication(self, raw_url: str) -> dict[str, Any]:
        """Resolve a user-typed Substack URL/handle to display metadata.

        Wraps newsletter_pod.substack.probe_publication. Raises
        ControlPlaneError on inputs we can't parse or fetch so the route
        layer can return 400.
        """
        try:
            _, host = canonicalize_pub_url(raw_url)
        except ValueError as exc:
            raise ControlPlaneError(str(exc)) from exc
        try:
            result = probe_publication(f"https://{host}")
        except requests.RequestException as exc:
            logger.info("Substack probe failed for %s: %s", host, exc)
            raise ControlPlaneError(f"Could not reach {host}") from exc
        return self._serialize_probe(result)

    def create_substack_intent(self, user_id: str, raw_url: str) -> dict[str, Any]:
        """Create or return an existing intent for (user, pub_host).

        Idempotent against the deterministic intent_id, so a user tapping
        Subscribe twice for the same pub doesn't duplicate the row.
        """
        user = self._require_user(user_id)
        ensure_user_inbound_alias(self.repository, user)
        try:
            _, host = canonicalize_pub_url(raw_url)
        except ValueError as exc:
            raise ControlPlaneError(str(exc)) from exc

        intent_id = build_intent_id(user_id, host)
        existing = self.repository.get_substack_intent(intent_id)
        if existing is not None:
            return {"intent": self._serialize_intent(existing)}

        try:
            probe = probe_publication(f"https://{host}")
        except requests.RequestException as exc:
            logger.info("Substack probe failed during intent creation for %s: %s", host, exc)
            raise ControlPlaneError(f"Could not reach {host}") from exc

        intent = UserSubstackIntent(
            id=intent_id,
            user_id=user_id,
            pub_url=probe.pub_url,
            pub_host=probe.pub_host,
            pub_title=probe.title,
            pub_author=probe.author,
            pub_icon_url=probe.icon_url,
            has_paid_tier=probe.has_paid_tier,
            alias_email=self._inbound_address_for(user),
            created_at=utc_now(),
        )
        self.repository.save_substack_intent(intent)
        logger.info(
            "Substack intent created: user=%s pub_host=%s intent_id=%s",
            user_id,
            host,
            intent_id,
        )
        return {"intent": self._serialize_intent(intent)}

    def list_substack_intents(self, user_id: str) -> dict[str, Any]:
        user = self._require_user(user_id)
        ensure_user_inbound_alias(self.repository, user)
        intents = self.repository.list_user_substack_intents(user_id)
        return {
            "inbound_address": self._inbound_address_for(user),
            "intents": [self._serialize_intent(intent) for intent in intents],
        }

    def delete_substack_intent(self, user_id: str, intent_id: str) -> dict[str, Any]:
        self._require_user(user_id)
        existing = self.repository.get_substack_intent(intent_id)
        if existing is None or existing.user_id != user_id:
            raise ControlPlaneError("Substack subscription not found")
        self.repository.delete_substack_intent(intent_id)
        return {"deleted": True, "intent_id": intent_id}

    @staticmethod
    def _serialize_probe(result: SubstackProbeResult) -> dict[str, Any]:
        return {
            "pub_url": result.pub_url,
            "pub_host": result.pub_host,
            "title": result.title,
            "author": result.author,
            "icon_url": result.icon_url,
            "has_paid_tier": result.has_paid_tier,
            "feed_url": result.feed_url,
        }

    @staticmethod
    def _serialize_intent(intent: UserSubstackIntent) -> dict[str, Any]:
        payload = intent.model_dump(mode="json")
        if intent.confirmed_at is not None:
            payload["status"] = "confirmed"
        elif intent.auto_confirmed_at is not None:
            payload["status"] = "auto_confirmed"
        else:
            payload["status"] = "pending"
        return payload

    def submit_feedback(
        self,
        user_id: str,
        raw_text: str,
        locale_hint: Optional[str] = None,
        source: str = "text",
    ) -> dict[str, Any]:
        self._require_user(user_id)
        cleaned = (raw_text or "").strip()
        if not cleaned:
            raise ControlPlaneError("Feedback cannot be empty")
        if len(cleaned) > 4000:
            raise ControlPlaneError("Feedback exceeds the 4000-character limit")

        try:
            english = translate_to_english(
                cleaned,
                api_key=self.podcast_client.api_key,
                text_model=self.podcast_client.text_model,
                base_url=self.podcast_client.base_url,
                locale_hint=locale_hint,
            )
        except (TranslationError, requests.RequestException) as exc:
            logger.warning("feedback translation failed for user=%s: %s", user_id, exc)
            english = None

        record = FeedbackRecord(
            id=uuid4().hex,
            user_id=user_id,
            raw_text=cleaned,
            english_text=english,
            locale_hint=locale_hint,
            source=source,
            created_at=utc_now(),
        )
        self.repository.save_feedback(record)
        return record.model_dump(mode="json")

    def get_cold_start_swipe_deck(self, user_id: str) -> dict[str, Any]:
        self._require_user(user_id)
        records = self._swipe_deck_service.get_cold_start_deck(user_id)
        return {"items": [_swipe_card_payload(record) for record in records]}

    def get_recent_swipe_deck(self, user_id: str) -> dict[str, Any]:
        self._require_user(user_id)
        sources = self.repository.list_user_sources(user_id)
        source_ids = [source.source_id for source in sources if source.enabled]
        records = self._swipe_deck_service.get_recent_deck(user_id, source_ids)
        # Lazy warm: if the user has sources attached but the corpus turned up
        # nothing to swipe, fetch + embed their feeds inline and try again
        # once. The cold-start case (fresh sign-up, never generated) shouldn't
        # require the user to manually trigger a generation just to see cards.
        if not records and source_ids:
            try:
                self.warm_user_corpus(user_id)
            except Exception:  # pragma: no cover — best-effort warm
                logger.warning(
                    "Lazy corpus warm failed for user=%s; returning empty deck",
                    user_id,
                    exc_info=True,
                )
            records = self._swipe_deck_service.get_recent_deck(user_id, source_ids)
        return {"items": [_swipe_card_payload(record) for record in records]}

    def warm_user_corpus(self, user_id: str) -> dict[str, Any]:
        """Fetch + embed items from the user's currently-attached sources
        WITHOUT generating an episode. Used to populate `source_items` so the
        swipe deck has cards to show before the first generation. Idempotent
        and bounded by the per-source cursor — sources with a cursor only get
        new items; first-time sources bootstrap with
        `podcast_bootstrap_max_items_per_source`.
        """
        self._require_user(user_id)
        sources = [s for s in self.repository.list_user_sources(user_id) if s.enabled]
        if not sources:
            return {"sources_processed": 0, "items_ingested": 0}
        source_defs = [
            SourceDefinition(id=s.source_id, name=s.name, rss_url=s.rss_url, enabled=s.enabled)
            for s in sources
        ]
        cursor_repo = _UserCursorRepositoryAdapter(self.repository, user_id)
        ingestion_service = RSSIngestionService(
            repository=cursor_repo,
            bootstrap_max_items_per_source=self.settings.podcast_bootstrap_max_items_per_source,
        )
        ingestion = ingestion_service.fetch_new_items(source_defs)
        try:
            self._source_item_persistence.persist(ingestion.items)
        except Exception:  # pragma: no cover — embeddings are best-effort
            logger.warning(
                "Corpus warm: persistence failed for user=%s", user_id, exc_info=True
            )
        if ingestion.cursor_updates:
            self.repository.update_user_source_cursors(user_id, ingestion.cursor_updates)
        return {
            "sources_processed": len(source_defs),
            "items_ingested": len(ingestion.items),
        }

    def submit_swipe(
        self,
        user_id: str,
        source_item_dedupe_key: str,
        direction: int,
    ) -> dict[str, Any]:
        self._require_user(user_id)
        if direction not in (-1, 1):
            raise ControlPlaneError("direction must be -1 or 1")
        record = self.repository.get_source_item(source_item_dedupe_key)
        if record is None:
            raise ControlPlaneError("Unknown source item")
        if not record.embedding or not record.embedding_model:
            raise ControlPlaneError("Source item has no embedding yet")
        swipe = SwipeRecord(
            id=uuid4().hex,
            user_id=user_id,
            source_item_dedupe_key=source_item_dedupe_key,
            direction=direction,
            title=record.title,
            link=record.link,
            source_id=record.source_id,
            source_name=record.source_name,
            embedding=record.embedding,
            embedding_model=record.embedding_model,
            swiped_at=utc_now(),
        )
        self.repository.save_swipe(swipe)
        result = swipe.model_dump(mode="json")
        if direction > 0:
            attached_source_id = self._maybe_auto_attach_source(user_id, record.source_id)
            if attached_source_id:
                result["auto_attached_source_id"] = attached_source_id
        return result

    def _maybe_auto_attach_source(self, user_id: str, source_id: str) -> Optional[str]:
        """Silently attach a catalog source after enough right-swipes from it.

        Only triggers for catalog sources (custom user-pasted RSS is never
        auto-attached). Any failure is swallowed — auto-attach is a quality
        improvement, never a reason to fail a swipe.
        """
        threshold = self.settings.auto_attach_right_swipe_threshold
        if threshold <= 0:
            return None
        try:
            catalog_source = self._catalog.get(source_id)
            if catalog_source is None:
                return None  # Custom or no-longer-curated source; skip.
            already_attached = any(
                existing.source_id == source_id
                for existing in self.repository.list_user_sources(user_id)
            )
            if already_attached:
                return None
            right_swipes = self.repository.count_user_right_swipes_for_source(
                user_id, source_id
            )
            if right_swipes < threshold:
                return None
            now = utc_now()
            attached = self.repository.add_user_source(
                UserSourceRecord(
                    id=f"{user_id}:{catalog_source.id}",
                    user_id=user_id,
                    source_id=catalog_source.id,
                    name=catalog_source.name,
                    rss_url=catalog_source.rss_url,
                    is_custom=False,
                    enabled=True,
                    validated_at=now,
                    created_at=now,
                    updated_at=now,
                )
            )
            if attached:
                logger.info(
                    "auto-attached source %s for user %s after %d right-swipes",
                    source_id,
                    user_id,
                    right_swipes,
                )
                return catalog_source.id
            return None
        except Exception:  # pragma: no cover — best-effort, never block a swipe
            logger.warning(
                "auto-attach failed for user=%s source=%s",
                user_id,
                source_id,
                exc_info=True,
            )
            return None

    def _user_payload(self, user: UserRecord) -> dict[str, Any]:
        payload = user.model_dump(mode="json")
        payload["inbound_address"] = self._inbound_address_for(user)
        return payload

    def _inbound_address_for(self, user: UserRecord) -> Optional[str]:
        alias = user.inbound_alias
        if not alias:
            return None
        return f"{alias}@{self.settings.inbound_email_domain}"

    def update_me(self, user_id: str, display_name: Optional[str], timezone_name: Optional[str]) -> dict[str, Any]:
        user = self._require_user(user_id)
        ensure_user_inbound_alias(self.repository, user)
        if display_name is not None:
            user.display_name = display_name.strip() or user.display_name
        if timezone_name is not None:
            _validate_timezone(timezone_name)
            user.timezone = timezone_name
        user.updated_at = utc_now()
        self.repository.save_user(user)

        schedule = self._get_schedule(user_id)
        if timezone_name is not None and schedule.timezone != timezone_name:
            schedule.timezone = timezone_name
            schedule.updated_at = utc_now()
            self.repository.save_schedule(schedule)

        return self.get_me(user_id)

    def get_source_catalog(self) -> list[dict[str, Any]]:
        return [
            {
                "source_id": source.id,
                "name": source.name,
                "rss_url": source.rss_url,
                "enabled": source.enabled,
                "topic": source.topic,
            }
            for source in self._catalog.values()
        ]

    def get_voice_catalog(self) -> list[dict[str, Any]]:
        return [
            {
                "id": voice.id,
                "name": voice.name,
                "gender": voice.gender,
                "description": voice.description,
                "preview_url": voice.preview_url,
            }
            for voice in self._voice_catalog.values()
        ]

    def validate_custom_source(self, rss_url: str) -> dict[str, Any]:
        return self._build_custom_source_from_url(rss_url).model_dump(mode="json")

    def list_user_sources(self, user_id: str) -> dict[str, Any]:
        subscription = self._get_subscription(user_id)
        entitlements = self._entitlements_for(subscription)
        return {
            "sources": [source.model_dump(mode="json") for source in self.repository.list_user_sources(user_id)],
            "entitlements": entitlements.model_dump(mode="json"),
        }

    def replace_user_sources(self, user_id: str, requested_sources: list[dict[str, Any]]) -> dict[str, Any]:
        resolved: list[UserSourceRecord] = []
        seen_keys: set[str] = set()

        for item in requested_sources:
            source_id = (item.get("source_id") or "").strip()
            rss_url = (item.get("rss_url") or "").strip()
            is_custom = bool(item.get("is_custom"))

            if source_id and not is_custom:
                catalog_source = self._catalog.get(source_id)
                if not catalog_source:
                    raise ControlPlaneError(f"Unknown catalog source: {source_id}")
                source = UserSourceRecord(
                    id=f"{user_id}:{catalog_source.id}",
                    user_id=user_id,
                    source_id=catalog_source.id,
                    name=catalog_source.name,
                    rss_url=catalog_source.rss_url,
                    is_custom=False,
                    enabled=True,
                    validated_at=utc_now(),
                    created_at=utc_now(),
                    updated_at=utc_now(),
                )
            else:
                if not rss_url:
                    raise ControlPlaneError("Custom sources require rss_url")
                source = self._build_custom_source_from_url(rss_url, user_id=user_id)
                if item.get("name"):
                    source.name = item["name"].strip() or source.name

            dedupe_key = f"{source.source_id}:{source.rss_url}"
            if dedupe_key in seen_keys:
                continue
            seen_keys.add(dedupe_key)
            resolved.append(source)

        if len(resolved) > self.settings.max_sources_safety_cap:
            raise ControlPlaneError(
                f"Too many sources: please keep under {self.settings.max_sources_safety_cap}"
            )

        self.repository.replace_user_sources(user_id, resolved)
        return self.list_user_sources(user_id)

    def get_podcast_config(self, user_id: str) -> dict[str, Any]:
        return {
            "profile": self._get_profile(user_id).model_dump(mode="json"),
            "entitlements": self._entitlements_for(self._get_subscription(user_id)).model_dump(mode="json"),
        }

    def update_podcast_config(
        self,
        user_id: str,
        title: Optional[str],
        format_preset: Optional[str],
        host_primary_name: Optional[str],
        host_secondary_name: Optional[str],
        guest_names: Optional[list[str]],
        desired_duration_minutes: Optional[int],
        voice_id: Optional[str] = None,
        secondary_voice_id: Optional[str] = None,
        tone: Optional[str] = None,
        key_findings_count: Optional[int] = None,
        humor_style: Optional[str] = None,
        personalized_greeting: Optional[bool] = None,
        include_top_takeaways: Optional[bool] = None,
        include_weather: Optional[bool] = None,
        weather_location: Optional[str] = None,
        custom_guidance: Optional[str] = None,
        custom_guidance_preset_id: Optional[str] = None,
    ) -> dict[str, Any]:
        profile = self._get_profile(user_id)
        entitlements = self._entitlements_for(self._get_subscription(user_id))

        if title is not None:
            profile.title = title.strip() or profile.title
        if format_preset is not None:
            _validate_format_preset(format_preset)
            profile.format_preset = format_preset
        if host_primary_name is not None:
            profile.host_primary_name = host_primary_name.strip() or profile.host_primary_name
        if host_secondary_name is not None:
            profile.host_secondary_name = host_secondary_name.strip() or None
        if guest_names is not None:
            profile.guest_names = [guest.strip() for guest in guest_names if guest.strip()]
        if desired_duration_minutes is not None:
            if not (entitlements.min_duration_minutes <= desired_duration_minutes <= entitlements.max_duration_minutes):
                raise ControlPlaneError(
                    f"Duration must be between {entitlements.min_duration_minutes} and "
                    f"{entitlements.max_duration_minutes} minutes"
                )
            profile.desired_duration_minutes = desired_duration_minutes
        if voice_id is not None:
            if voice_id not in self._voice_catalog:
                raise ControlPlaneError("Unsupported voice selection")
            profile.voice_id = voice_id
        if secondary_voice_id is not None:
            if secondary_voice_id == "":
                profile.secondary_voice_id = None
            else:
                if secondary_voice_id not in self._voice_catalog:
                    raise ControlPlaneError("Unsupported commenter voice selection")
                profile.secondary_voice_id = secondary_voice_id
        if tone is not None:
            _validate_tone(tone)
            profile.tone = tone
        if key_findings_count is not None:
            profile.key_findings_count = max(3, min(7, int(key_findings_count)))
        if humor_style is not None:
            _validate_humor_style(humor_style)
            profile.humor_style = humor_style
        if personalized_greeting is not None:
            profile.personalized_greeting = bool(personalized_greeting)
        if include_top_takeaways is not None:
            profile.include_top_takeaways = bool(include_top_takeaways)
        if include_weather is not None:
            profile.include_weather = bool(include_weather)
        if weather_location is not None:
            trimmed = weather_location.strip()[:_WEATHER_LOCATION_MAX_LEN]
            profile.weather_location = trimmed or None
        if custom_guidance is not None:
            profile.custom_guidance = _sanitize_custom_guidance(custom_guidance)
        if custom_guidance_preset_id is not None:
            preset_value = custom_guidance_preset_id.strip()[:64]
            profile.custom_guidance_preset_id = preset_value or None

        if profile.secondary_voice_id and profile.secondary_voice_id == profile.voice_id:
            raise ControlPlaneError("Host and commenter voices must be different")

        self._validate_profile(profile)
        profile.updated_at = utc_now()
        self.repository.save_profile(profile)
        return self.get_podcast_config(user_id)

    def get_schedule_config(self, user_id: str) -> dict[str, Any]:
        return {
            "schedule": self._get_schedule(user_id).model_dump(mode="json"),
            "entitlements": self._entitlements_for(self._get_subscription(user_id)).model_dump(mode="json"),
        }

    def update_schedule(
        self,
        user_id: str,
        timezone_name: Optional[str],
        weekdays: Optional[list[str]],
        local_time: Optional[str] = None,
    ) -> dict[str, Any]:
        schedule = self._get_schedule(user_id)
        entitlements = self._entitlements_for(self._get_subscription(user_id))

        if timezone_name is not None:
            _validate_timezone(timezone_name)
            schedule.timezone = timezone_name
        if weekdays is not None:
            normalized = [_normalize_weekday(day) for day in weekdays]
            if len(normalized) > entitlements.max_delivery_days:
                raise ControlPlaneError(
                    f"Plan limit exceeded: max {entitlements.max_delivery_days} delivery days"
                )
            if not normalized:
                raise ControlPlaneError("At least one delivery day is required")
            schedule.weekdays = normalized
        if local_time is not None:
            schedule.local_time = _normalize_local_time(local_time)

        schedule.updated_at = utc_now()
        self.repository.save_schedule(schedule)
        return self.get_schedule_config(user_id)

    def get_feed_details(self, user_id: str) -> dict[str, Any]:
        token_record = self._get_or_create_feed_token(user_id)
        latest_episode = next(iter(self.repository.list_recent_user_episodes(user_id, limit=1)), None)
        latest_run = self._latest_run_for_user(user_id)
        subscription = self._get_subscription(user_id)
        return {
            "feed_url": f"{self.settings.app_base_url.rstrip('/')}/feeds/{token_record.token}.xml",
            "token": token_record.token,
            "latest_episode": latest_episode.model_dump(mode="json") if latest_episode else None,
            "latest_run": latest_run.model_dump(mode="json") if latest_run else None,
            "subscription": subscription.model_dump(mode="json"),
            "entitlements": self._entitlements_for(subscription).model_dump(mode="json"),
        }

    def list_user_episodes(self, user_id: str, limit: int = 50) -> dict[str, Any]:
        episodes = self.repository.list_recent_user_episodes(user_id, limit=limit)
        return {
            "episodes": [episode.model_dump(mode="json") for episode in episodes],
        }

    def apply_app_store_notification(self, payload: dict[str, Any]) -> dict[str, Any]:
        event = BillingEventRecord(
            id=uuid4().hex,
            user_id=(payload.get("user_id") or payload.get("app_account_token")),
            notification_type=payload.get("notification_type") or payload.get("notificationType") or "unknown",
            subtype=payload.get("subtype"),
            product_id=payload.get("product_id") or payload.get("productId"),
            raw_payload=payload,
            created_at=utc_now(),
        )
        self.repository.save_billing_event(event)

        if event.user_id:
            subscription = self._get_subscription(event.user_id)
            if event.product_id in {
                self.settings.app_store_monthly_product_id,
                self.settings.app_store_annual_product_id,
            }:
                subscription.tier = "paid"
                subscription.status = "active"
                subscription.product_id = event.product_id
            if payload.get("status") in {"expired", "revoked"}:
                subscription.tier = "free"
                subscription.status = payload.get("status")
                subscription.product_id = None
            expires_at = payload.get("expires_at")
            if expires_at:
                subscription.expires_at = _parse_client_datetime(expires_at)
            subscription.updated_at = utc_now()
            self.repository.save_subscription(subscription)

        return {
            "accepted": True,
            "event_id": event.id,
        }

    def dispatch_due_users(self, now_utc: Optional[datetime] = None) -> dict[str, Any]:
        now_utc = now_utc or utc_now()
        processed: list[dict[str, Any]] = []
        for schedule in self.repository.list_schedules():
            if not schedule.enabled:
                continue
            if not self._is_due(schedule, now_utc):
                continue
            if not self._should_attempt_user(schedule.user_id, schedule, now_utc):
                continue
            try:
                result = self.process_user_generation(schedule.user_id, now_utc=now_utc)
                run_status = (result.get("run") or {}).get("status") or result.get("status")
                processed.append({"user_id": schedule.user_id, "status": run_status})
            except Exception as exc:
                processed.append({"user_id": schedule.user_id, "status": "error", "error": str(exc)})

        return {
            "status": "ok",
            "processed_count": len(processed),
            "processed": processed,
        }

    def process_user_generation(
        self,
        user_id: str,
        now_utc: Optional[datetime] = None,
        force: bool = False,
        run_id: Optional[str] = None,
    ) -> dict[str, Any]:
        now_utc = now_utc or utc_now()
        user = self._require_user(user_id)
        schedule = self._get_schedule(user_id)
        subscription = self._get_subscription(user_id)
        entitlements = self._entitlements_for(subscription)
        profile = self._get_profile(user_id)
        sources = [source for source in self.repository.list_user_sources(user_id) if source.enabled]
        local_date = now_utc.astimezone(ZoneInfo(schedule.timezone)).date()
        if run_id is None:
            run_id = uuid4().hex

        if not force and not self._should_attempt_user(user_id, schedule, now_utc):
            run = UserRunRecord(
                id=run_id,
                user_id=user_id,
                local_run_date=local_date,
                started_at=now_utc,
                completed_at=now_utc,
                status=PublishStatus.SKIPPED.value,
                message="Run skipped by retry policy",
            )
            self.repository.save_user_run(run)
            return run.model_dump(mode="json")

        if not sources:
            run = UserRunRecord(
                id=run_id,
                user_id=user_id,
                local_run_date=local_date,
                started_at=now_utc,
                completed_at=now_utc,
                status=PublishStatus.NO_CONTENT.value,
                message="No configured sources",
            )
            self.repository.save_user_run(run)
            return run.model_dump(mode="json")

        source_defs = [
            SourceDefinition(id=source.source_id, name=source.name, rss_url=source.rss_url, enabled=source.enabled)
            for source in sources
        ]
        cursor_repo = _UserCursorRepositoryAdapter(self.repository, user_id)
        ingestion_service = RSSIngestionService(
            repository=cursor_repo,
            bootstrap_max_items_per_source=self.settings.podcast_bootstrap_max_items_per_source,
        )
        ingestion = ingestion_service.fetch_new_items(source_defs)
        try:
            self._source_item_persistence.persist(ingestion.items)
        except Exception:  # pragma: no cover — persistence is best-effort
            logger.warning(
                "Source-item persistence failed for user=%s; continuing with in-memory items",
                user_id,
                exc_info=True,
            )
        candidate_count = len(ingestion.items)
        if candidate_count == 0:
            self.repository.update_user_source_cursors(user_id, ingestion.cursor_updates)
            run = UserRunRecord(
                id=run_id,
                user_id=user_id,
                local_run_date=local_date,
                started_at=now_utc,
                completed_at=utc_now(),
                status=PublishStatus.NO_CONTENT.value,
                message="No new source items",
                candidate_count=0,
            )
            self.repository.save_user_run(run)
            return run.model_dump(mode="json")

        items = ingestion.items
        dropped_count = 0
        cap_hit = False
        ranked_items = self._apply_swipe_ranker(user_id, items, entitlements.max_items_per_episode)
        if ranked_items is not None:
            if len(ranked_items) < len(items):
                cap_hit = True
                dropped_count = len(items) - len(ranked_items)
            items = ranked_items
        elif len(items) > entitlements.max_items_per_episode:
            cap_hit = True
            dropped_count = len(items) - entitlements.max_items_per_episode
            items = items[-entitlements.max_items_per_episode :]

        # Legacy profiles may store a duration outside the user's current
        # entitlements (e.g. saved before a tier cap tightened). Clamp at
        # generation time so the LLM prompt and TTS spend match the tier.
        profile.desired_duration_minutes = max(
            entitlements.min_duration_minutes,
            min(entitlements.max_duration_minutes, profile.desired_duration_minutes),
        )
        primary_voice_id, secondary_voice_id, secondary_speaker_name = self._resolve_voice_pair(
            profile, local_date
        )
        weather_summary: Optional[str] = None
        if profile.include_weather and profile.weather_location:
            try:
                weather_summary = fetch_weather_summary(
                    profile.weather_location, today=local_date
                )
            except Exception:  # pragma: no cover — weather is best-effort
                logger.warning(
                    "Weather fetch failed for user=%s location=%r",
                    user_id,
                    profile.weather_location,
                )
                weather_summary = None
        ux = self._build_user_ux(
            profile,
            primary_voice_id,
            secondary_speaker_name,
            listener_name=user.display_name,
            weather_summary=weather_summary,
        )
        current_iso_week = iso_week_key(local_date)
        weekly_update_due = user.last_weekly_update_iso_week != current_iso_week
        if weekly_update_due:
            commits = load_recent_commits(project_root=_PROJECT_ROOT)
            if commits:
                ux.weekly_update_commits = commits
            else:
                weekly_update_due = False
        guest_name = secondary_speaker_name if profile.format_preset == "rotating_guest" else None
        prompt = build_digest_prompt(items, run_date=local_date, ux=ux, skip_closing=True)
        title_hint = f"{local_date.isoformat()} weekly briefing"
        generated = self.podcast_client.generate(
            prompt=prompt,
            title=title_hint,
            voice_id=primary_voice_id,
            secondary_voice_id=secondary_voice_id,
            primary_speaker_name=ux.host_primary_name,
            secondary_speaker_name=ux.host_secondary_name or None,
            ux=ux,
        )

        episode_id = f"{user_id[:8]}-{local_date.isoformat()}-{uuid4().hex[:8]}"
        object_name, size_bytes = self.storage.upload_audio(
            episode_id=episode_id,
            audio_bytes=generated.audio_bytes,
            mime_type=generated.mime_type,
        )
        show_notes = self._build_show_notes(generated.show_notes, items, cap_hit, dropped_count)
        transcript_text = generated.transcript or "\n\n".join(
            f"{segment.speaker}: {segment.text}" for segment in generated.audio_segments
        )
        episode = UserEpisodeRecord(
            id=episode_id,
            user_id=user_id,
            title=generated.episode_title,
            description=show_notes,
            published_at=utc_now(),
            audio_object_name=object_name,
            audio_mime_type=generated.mime_type,
            audio_size_bytes=size_bytes,
            source_item_refs=[
                SourceItemRef(
                    source_id=item.source_id,
                    source_name=item.source_name,
                    title=item.title,
                    link=item.link,
                    guid=item.guid,
                )
                for item in items
            ],
            duration_seconds=generated.duration_seconds,
            processed_item_count=len(items),
            dropped_item_count=dropped_count,
            cap_hit=cap_hit,
            guest_name=guest_name,
            transcript_text=transcript_text or None,
        )
        self.repository.save_user_episode(episode)
        self.repository.update_user_source_cursors(user_id, ingestion.cursor_updates)
        if weekly_update_due:
            user.last_weekly_update_iso_week = current_iso_week
            user.updated_at = utc_now()
            self.repository.save_user(user)

        cost_estimate = estimate_generation_cost(
            prompt_text=prompt,
            transcript_text=transcript_text,
            show_notes_text=generated.show_notes,
            duration_seconds=generated.duration_seconds,
            tts_provider=self.settings.podcast_tts_provider,
        )
        self.repository.save_cost_record(
            CostRecord(
                run_id=run_id,
                user_id=user_id,
                text_input_tokens_estimate=cost_estimate.text_input_tokens_estimate,
                text_output_tokens_estimate=cost_estimate.text_output_tokens_estimate,
                tts_input_tokens_estimate=cost_estimate.tts_input_tokens_estimate,
                tts_output_minutes_estimate=cost_estimate.tts_output_minutes_estimate,
                openai_cost_usd=cost_estimate.openai_cost_usd,
                infra_reserve_cost_usd=cost_estimate.infra_reserve_cost_usd,
                total_cost_usd=cost_estimate.total_cost_usd,
                recorded_at=utc_now(),
            )
        )

        run = UserRunRecord(
            id=run_id,
            user_id=user_id,
            local_run_date=local_date,
            started_at=now_utc,
            completed_at=utc_now(),
            status=PublishStatus.PUBLISHED.value,
            message="Episode published",
            candidate_count=candidate_count,
            processed_item_count=len(items),
            dropped_item_count=dropped_count,
            cap_hit=cap_hit,
            published_episode_id=episode.id,
        )
        self.repository.save_user_run(run)

        return {
            "run": run.model_dump(mode="json"),
            "episode": episode.model_dump(mode="json"),
            "cost": cost_estimate.__dict__,
            "feed_url": self.get_feed_details(user_id)["feed_url"],
            "user": user.model_dump(mode="json"),
        }

    def start_user_generation(self, user_id: str, force: bool = False) -> dict[str, Any]:
        self._require_user(user_id)
        existing = self.repository.find_in_progress_user_run(user_id)
        if existing is not None:
            return {"run": existing.model_dump(mode="json"), "started": False}

        schedule = self._get_schedule(user_id)
        now_utc = utc_now()
        local_date = now_utc.astimezone(ZoneInfo(schedule.timezone)).date()
        run = UserRunRecord(
            id=uuid4().hex,
            user_id=user_id,
            local_run_date=local_date,
            started_at=now_utc,
            completed_at=now_utc,
            status=PublishStatus.IN_PROGRESS.value,
            message="Generation in progress",
        )
        self.repository.save_user_run(run)
        return {"run": run.model_dump(mode="json"), "started": True}

    def run_user_generation_in_background(
        self, *, run_id: str, user_id: str, force: bool = True
    ) -> None:
        try:
            self.process_user_generation(user_id=user_id, force=force, run_id=run_id)
        except Exception as exc:
            logger.exception("Background generation failed for run %s", run_id)
            run = self.repository.get_user_run(run_id)
            now = utc_now()
            if run is None:
                schedule = self._get_schedule(user_id)
                local_date = now.astimezone(ZoneInfo(schedule.timezone)).date()
                run = UserRunRecord(
                    id=run_id,
                    user_id=user_id,
                    local_run_date=local_date,
                    started_at=now,
                    completed_at=now,
                    status=PublishStatus.FAILED.value,
                    message=str(exc)[:500] or "Generation failed",
                )
            else:
                run.status = PublishStatus.FAILED.value
                run.message = (str(exc)[:500] or "Generation failed")
                run.completed_at = now
            self.repository.save_user_run(run)

    def get_user_run_status(self, user_id: str, run_id: str) -> dict[str, Any]:
        run = self.repository.get_user_run(run_id)
        if run is None or run.user_id != user_id:
            raise ControlPlaneError("Run not found")
        payload: dict[str, Any] = {"run": run.model_dump(mode="json")}
        if run.published_episode_id:
            episode = self.repository.get_user_episode(run.published_episode_id)
            if episode is not None:
                payload["episode"] = episode.model_dump(mode="json")
        return payload

    def _create_default_user(
        self,
        subject: str,
        email: Optional[str],
        given_name: Optional[str] = None,
    ) -> UserRecord:
        now = utc_now()
        cleaned_given = (given_name or "").strip()
        display_name = cleaned_given or "Listener"
        return UserRecord(
            id=uuid4().hex,
            apple_subject=subject,
            email=email,
            display_name=display_name,
            timezone="UTC",
            created_at=now,
            updated_at=now,
        )

    def _persist_default_records(self, user: UserRecord) -> None:
        now = utc_now()
        self.repository.save_user(user)
        self.repository.save_profile(
            PodcastProfileRecord(
                user_id=user.id,
                title="ClawCast",
                format_preset="two_hosts",
                host_primary_name="Vinnie",
                host_secondary_name="Demi",
                guest_names=[],
                desired_duration_minutes=self.settings.free_default_duration_minutes,
                voice_id=self.settings.elevenlabs_voice_primary_id,
                secondary_voice_id=self.settings.elevenlabs_voice_secondary_id,
                created_at=now,
                updated_at=now,
            )
        )
        # New users land on the free tier; cap the default delivery schedule
        # to the free max so the first /v1/me/schedule save doesn't 400.
        default_weekdays = WEEKDAY_NAMES[: self.settings.free_max_delivery_days]
        self.repository.save_schedule(
            DeliveryScheduleRecord(
                user_id=user.id,
                timezone=user.timezone,
                weekdays=default_weekdays,
                local_time=self.settings.weekly_target_local,
                cutoff_time=self.settings.weekly_cutoff_local,
                enabled=True,
                created_at=now,
                updated_at=now,
            )
        )
        self.repository.save_subscription(
            SubscriptionRecord(
                user_id=user.id,
                tier="free",
                status="active",
                updated_at=now,
            )
        )
        self._get_or_create_feed_token(user.id)
        self._seed_welcome_episode(user.id, now)

    def _seed_welcome_episode(self, user_id: str, now: datetime) -> None:
        object_name = self.settings.welcome_episode_object_name
        if not object_name:
            return
        version = self.settings.welcome_episode_version or "v1"
        self.repository.save_user_episode(
            UserEpisodeRecord(
                id=f"{user_id[:8]}-welcome-{version}",
                user_id=user_id,
                title=WELCOME_EPISODE_TITLE,
                description=WELCOME_EPISODE_DESCRIPTION,
                published_at=now,
                audio_object_name=object_name,
                audio_mime_type="audio/mpeg",
                audio_size_bytes=self.settings.welcome_episode_size_bytes,
                duration_seconds=self.settings.welcome_episode_duration_seconds or None,
            )
        )

    def _build_custom_source_from_url(self, rss_url: str, user_id: str = "preview") -> UserSourceRecord:
        response = requests.get(rss_url, timeout=20)
        response.raise_for_status()
        parsed = feedparser.parse(response.text)
        entries = list(parsed.entries)
        if not entries:
            raise ControlPlaneError("Feed did not contain any entries")
        title = parsed.feed.get("title") or rss_url
        now = utc_now()
        source_hash = link_hash(rss_url)[:12]
        return UserSourceRecord(
            id=f"{user_id}:custom-{source_hash}",
            user_id=user_id,
            source_id=f"custom-{source_hash}",
            name=title,
            rss_url=rss_url,
            is_custom=True,
            enabled=True,
            validated_at=now,
            created_at=now,
            updated_at=now,
        )

    def _entitlements_for(self, subscription: SubscriptionRecord) -> UserEntitlements:
        if subscription.tier == "paid" and subscription.status not in {"expired", "revoked"}:
            return UserEntitlements(
                tier="paid",
                max_delivery_days=self.settings.paid_max_delivery_days,
                min_duration_minutes=self.settings.paid_min_duration_minutes,
                max_duration_minutes=self.settings.paid_max_duration_minutes,
                max_items_per_episode=self.settings.paid_max_items_per_episode,
            )
        return UserEntitlements(
            tier="free",
            max_delivery_days=self.settings.free_max_delivery_days,
            min_duration_minutes=self.settings.free_min_duration_minutes,
            max_duration_minutes=self.settings.free_max_duration_minutes,
            max_items_per_episode=self.settings.free_max_items_per_episode,
        )

    def _get_subscription(self, user_id: str) -> SubscriptionRecord:
        subscription = self.repository.get_subscription(user_id)
        if subscription:
            return subscription
        subscription = SubscriptionRecord(user_id=user_id, tier="free", status="active", updated_at=utc_now())
        self.repository.save_subscription(subscription)
        return subscription

    def _get_profile(self, user_id: str) -> PodcastProfileRecord:
        profile = self.repository.get_profile(user_id)
        if not profile:
            now = utc_now()
            profile = PodcastProfileRecord(
                user_id=user_id,
                title="ClawCast",
                desired_duration_minutes=self.settings.free_default_duration_minutes,
                voice_id=self.settings.elevenlabs_voice_primary_id,
                secondary_voice_id=self.settings.elevenlabs_voice_secondary_id,
                created_at=now,
                updated_at=now,
            )
            self.repository.save_profile(profile)
        return profile

    def _get_schedule(self, user_id: str) -> DeliveryScheduleRecord:
        schedule = self.repository.get_schedule(user_id)
        if not schedule:
            now = utc_now()
            schedule = DeliveryScheduleRecord(
                user_id=user_id,
                timezone=self._require_user(user_id).timezone,
                weekdays=["monday"],
                local_time=self.settings.weekly_target_local,
                cutoff_time=self.settings.weekly_cutoff_local,
                enabled=True,
                created_at=now,
                updated_at=now,
            )
            self.repository.save_schedule(schedule)
        return schedule

    def _require_user(self, user_id: str) -> UserRecord:
        user = self.repository.get_user(user_id)
        if not user:
            raise ControlPlaneError("User not found")
        return user

    def _get_or_create_feed_token(self, user_id: str) -> FeedTokenRecord:
        token = self.repository.get_feed_token(user_id)
        if token:
            return token
        token = FeedTokenRecord(
            token=secrets.token_hex(32),
            user_id=user_id,
            created_at=utc_now(),
        )
        self.repository.save_feed_token(token)
        return token

    def _validate_profile(self, profile: PodcastProfileRecord) -> None:
        _validate_format_preset(profile.format_preset)
        if profile.format_preset == "solo_host":
            profile.host_secondary_name = None
            profile.guest_names = []
            profile.secondary_voice_id = None
        elif profile.format_preset == "two_hosts":
            profile.guest_names = []
        elif profile.format_preset == "rotating_guest":
            profile.host_secondary_name = None
            profile.secondary_voice_id = None

    def _voice_name(self, voice_id: Optional[str], fallback: str) -> str:
        if voice_id and voice_id in self._voice_catalog:
            return self._voice_catalog[voice_id].name
        return fallback

    def _resolve_voice_pair(
        self,
        profile: PodcastProfileRecord,
        local_date: date,
    ) -> tuple[str, Optional[str], Optional[str]]:
        """Pick the (primary, secondary) voice IDs and the secondary speaker name
        used for this episode.

        - solo_host: secondary is None.
        - two_hosts: secondary is the user-selected commenter voice. Falls back to
          the legacy default pair when no commenter has been picked yet.
        - rotating_guest: secondary cycles daily through every catalog voice that
          isn't the host, indexed by the local episode date.
        """
        primary_id = profile.voice_id or self.settings.elevenlabs_voice_primary_id

        if profile.format_preset == "solo_host":
            return primary_id, None, None

        if profile.format_preset == "rotating_guest":
            others = [vid for vid in self._voice_catalog if vid != primary_id]
            if not others:
                return primary_id, None, None
            others.sort()
            secondary_id = others[local_date.toordinal() % len(others)]
            return primary_id, secondary_id, self._voice_name(secondary_id, "Guest")

        # two_hosts
        secondary_id = profile.secondary_voice_id
        if not secondary_id or secondary_id == primary_id or secondary_id not in self._voice_catalog:
            secondary_id = (
                self.settings.elevenlabs_voice_secondary_id
                if primary_id == self.settings.elevenlabs_voice_primary_id
                else self.settings.elevenlabs_voice_primary_id
            )
        return primary_id, secondary_id, self._voice_name(secondary_id, "Co-host")

    def _apply_swipe_ranker(
        self,
        user_id: str,
        items: list[SourceItem],
        top_n: int,
    ) -> Optional[list[SourceItem]]:
        """Score and select items by similarity to the user's interest vector.

        Returns None when the ranker is disabled, the user has too few swipes
        to produce a meaningful vector, or no usable embeddings can be loaded —
        in which case the caller falls back to chronological selection.
        """
        if not self.settings.swipe_ranker_enabled or top_n <= 0:
            return None
        swipe_count = self.repository.count_user_swipes(user_id)
        if swipe_count < self.settings.swipe_ranker_min_swipes:
            return None
        swipes = self.repository.list_user_swipes(user_id)
        user_vector = compute_user_vector(swipes)
        if user_vector is None:
            return None
        records = self.repository.get_source_items([item.dedupe_key for item in items])
        embedding_by_key = {record.dedupe_key: record.embedding for record in records}
        return rank_items(items, user_vector, embedding_by_key.get, top_n)

    def _build_user_ux(
        self,
        profile: PodcastProfileRecord,
        primary_voice_id: str,
        secondary_speaker_name: Optional[str],
        listener_name: Optional[str] = None,
        weather_summary: Optional[str] = None,
    ) -> PodcastUxConfig:
        duration = profile.desired_duration_minutes
        primary_name = self._voice_name(primary_voice_id, profile.host_primary_name or "Host")
        tone = profile.tone if profile.tone in _TONE_OPTIONS else "calm_analyst"
        humor = profile.humor_style if profile.humor_style in _HUMOR_OPTIONS else "none"
        key_findings = max(3, min(7, profile.key_findings_count or 3))
        effective_listener = listener_name if profile.personalized_greeting else None
        return PodcastUxConfig(
            host_primary_name=primary_name,
            host_secondary_name=secondary_speaker_name or "",
            format=profile.format_preset,
            tone=tone,
            target_minutes=duration,
            max_minutes=duration,
            thin_day_minutes=min(5, duration),
            listener_name=effective_listener,
            key_findings_count=key_findings,
            humor_style=humor,
            include_top_takeaways=profile.include_top_takeaways,
            custom_guidance=profile.custom_guidance,
            weather_summary=weather_summary,
        )

    def _build_show_notes(
        self,
        generated_notes: str,
        items: list,
        cap_hit: bool,
        dropped_count: int,
    ) -> str:
        sections: list[str] = []
        notes = (generated_notes or "").strip()
        if notes:
            if len(notes) > 1200:
                notes = notes[:1200].rsplit(" ", 1)[0].rstrip(",;:") + "…"
            sections.append(notes)
        if cap_hit:
            sections.append(
                f"_{dropped_count} additional source item(s) were omitted to fit this episode's item cap._"
            )

        seen: set[str] = set()
        source_lines: list[str] = []
        for item in items:
            if item.link in seen:
                continue
            seen.add(item.link)
            title = (item.title or "").strip() or item.source_name
            source_lines.append(f"- **{item.source_name}** — [{title}]({item.link})")
        if source_lines:
            sections.append("**Sources**\n" + "\n".join(source_lines))

        return "\n\n".join(sections)

    def _latest_run_for_user(self, user_id: str) -> Optional[UserRunRecord]:
        schedule = self.repository.get_schedule(user_id)
        if not schedule:
            return None
        local_date = utc_now().astimezone(ZoneInfo(schedule.timezone)).date()
        runs = self.repository.list_user_runs_for_date(user_id, local_date)
        if not runs:
            return None
        runs.sort(key=lambda run: run.completed_at, reverse=True)
        return runs[0]

    def _is_due(self, schedule: DeliveryScheduleRecord, now_utc: datetime) -> bool:
        local_now = now_utc.astimezone(ZoneInfo(schedule.timezone))
        weekday = WEEKDAY_NAMES[local_now.weekday()]
        if weekday not in schedule.weekdays:
            return False
        local_hhmm = local_now.strftime("%H:%M")
        return schedule.local_time <= local_hhmm <= schedule.cutoff_time

    def _should_attempt_user(self, user_id: str, schedule: DeliveryScheduleRecord, now_utc: datetime) -> bool:
        local_date = now_utc.astimezone(ZoneInfo(schedule.timezone)).date()
        runs = self.repository.list_user_runs_for_date(user_id, local_date)
        if any(run.status in COMPLETED_RUN_STATUSES for run in runs):
            return False
        if not runs:
            return True
        last_attempt = max(run.completed_at for run in runs)
        return (now_utc - last_attempt).total_seconds() >= self.settings.dispatch_interval_minutes * 60


def build_task_enqueuer(settings: Settings) -> TaskEnqueuer:
    if not settings.cloud_tasks_queue:
        return InMemoryTaskEnqueuer()

    project_id = settings.cloud_tasks_project_id or settings.google_cloud_project
    if not project_id or not settings.cloud_tasks_location:
        raise RuntimeError("Cloud Tasks requires project id and location")

    from google.cloud import tasks_v2

    queue_path = tasks_v2.CloudTasksClient.queue_path(
        project_id,
        settings.cloud_tasks_location,
        settings.cloud_tasks_queue,
    )
    return CloudTasksEnqueuer(
        queue_path=queue_path,
        service_url=settings.app_base_url,
        service_account_email=settings.cloud_tasks_service_account,
        job_trigger_token=settings.job_trigger_token,
    )


def _validate_timezone(timezone_name: str) -> None:
    try:
        ZoneInfo(timezone_name)
    except Exception as exc:  # pragma: no cover
        raise ControlPlaneError(f"Unknown timezone: {timezone_name}") from exc


def _swipe_card_payload(record: SourceItemRecord) -> dict[str, Any]:
    return {
        "source_item_dedupe_key": record.dedupe_key,
        "title": record.title,
        "summary": record.summary,
        "source_id": record.source_id,
        "source_name": record.source_name,
        "link": record.link,
        "published_at": record.published_at.isoformat(),
    }


def _normalize_weekday(value: str) -> str:
    normalized = value.strip().lower()
    if normalized not in WEEKDAY_NAMES:
        raise ControlPlaneError(f"Invalid weekday: {value}")
    return normalized


def _normalize_local_time(value: str) -> str:
    """Validate and normalize a HH:MM 24-hour time string."""
    raw = value.strip()
    parts = raw.split(":")
    if len(parts) != 2:
        raise ControlPlaneError(f"Invalid local time (expected HH:MM): {value}")
    try:
        hour = int(parts[0])
        minute = int(parts[1])
    except ValueError as exc:
        raise ControlPlaneError(f"Invalid local time (expected HH:MM): {value}") from exc
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ControlPlaneError(f"Invalid local time (out of range): {value}")
    return f"{hour:02d}:{minute:02d}"


def _validate_format_preset(value: str) -> None:
    if value not in {"solo_host", "two_hosts", "rotating_guest"}:
        raise ControlPlaneError(f"Invalid format preset: {value}")


_TONE_OPTIONS = {"calm_analyst", "warm_friendly", "snappy_news", "playful"}
_HUMOR_OPTIONS = {"none", "dad_jokes", "dry_wit"}
# Output-schema keys we don't want users smuggling into the listener-prefs block.
_GUIDANCE_DENYLIST = ("audio_segments", "episode_title", "show_notes")
_GUIDANCE_MAX_LEN = 500
_WEATHER_LOCATION_MAX_LEN = 80


def _validate_tone(value: str) -> None:
    if value not in _TONE_OPTIONS:
        raise ControlPlaneError(f"Invalid tone: {value}")


def _validate_humor_style(value: str) -> None:
    if value not in _HUMOR_OPTIONS:
        raise ControlPlaneError(f"Invalid humor style: {value}")


def _sanitize_custom_guidance(value: str) -> Optional[str]:
    """Trim, collapse whitespace, strip control chars, enforce length + denylist.

    Returns ``None`` for an empty/whitespace-only input so the caller can clear
    the field by sending an empty string. Raises ``ControlPlaneError`` on a
    denylist hit so the user sees a clear message instead of silent truncation.
    """
    if value is None:
        return None
    cleaned_chars = [ch for ch in value if ch.isprintable() or ch in (" ", "\n")]
    cleaned = " ".join("".join(cleaned_chars).split())
    if not cleaned:
        return None
    if len(cleaned) > _GUIDANCE_MAX_LEN:
        cleaned = cleaned[:_GUIDANCE_MAX_LEN]
    lowered = cleaned.casefold()
    for token in _GUIDANCE_DENYLIST:
        if token in lowered:
            raise ControlPlaneError(
                f"Custom guidance cannot reference output-schema fields ({token})."
            )
    return cleaned


def _parse_client_datetime(value: Any) -> Optional[datetime]:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
