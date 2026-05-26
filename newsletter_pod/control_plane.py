from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional
from uuid import uuid4
from zoneinfo import ZoneInfo

import feedparser
import requests

from .auth import AppleIdentityVerifier, SessionManager
from .app_store_verifier import (
    AppStoreNotificationVerifier,
    AppStoreVerificationError,
    DecodedNotification,
)
from .config import Settings, load_sources, load_voices
from .costing import estimate_generation_cost
from .embeddings import EmbeddingProvider
from .events import EventName, log_event
from .feedback_digest import (
    JOB_STATE_NAME as FEEDBACK_DIGEST_JOB_STATE_NAME,
    format_digest_email,
    summarize_feedback_with_llm,
)
from .inbound import ensure_user_inbound_alias
from .substack import (
    SubstackFeedPost,
    SubstackProbeResult,
    build_intent_id,
    canonicalize_pub_url,
    extract_confirm_url,
    fetch_latest_post,
    probe_publication,
)
from .candidate_queue import CandidateQueueError, CandidateQueueService
from .ingestion import RSSIngestionService
from .interest_seeds import (
    SEED_KIND_SUBSTACK,
    SEED_KIND_VOICE,
    seed_user_interest,
)
from .interest_vector import compute_user_vector
from .mailer import Mailer
from .models import PodcastUxConfig, PublishStatus, SourceDefinition, SourceItem, SourceItemRecord, SourceItemRef
from .podcast_api import PodcastApiClient
from .prompting import build_digest_prompt
from .card_summary import CardSummarizer, CardSummaryService
from .ranker import rank_items
from .source_persistence import SourceItemPersistenceService
from .substack_discovery import (
    DiscoveredPublication,
    OpenAISubstackSuggester,
    SubstackDiscoveryService,
)
from .voice_intake import ExtractedIntake, IntakeExtractor, OpenAIIntakeExtractor
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
    InboundEmailItem,
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


def _inbound_item_to_source_item(
    item: InboundEmailItem,
    intent_by_host: dict[str, UserSubstackIntent],
) -> SourceItem:
    """Project an inbound newsletter email into the same shape as an RSS item
    so the digest pipeline (ranker, cap, prompt builder) can treat both
    uniformly. Source attribution prefers a matched Substack intent's title
    (the publication name the user actually subscribed to) over the raw
    sender domain.
    """
    host = (item.sender_domain or "").lower()
    intent = intent_by_host.get(host)
    if intent and intent.pub_title:
        source_name = intent.pub_title
    elif item.from_name:
        source_name = item.from_name
    else:
        source_name = host or "Forwarded mail"
    source_id = f"inbound:{host or item.from_email or item.id}"
    # SourceItem.link is required (not Optional). When the inbound mail has
    # no extractable "read on web" URL, fall back to a deterministic
    # synthetic link so the field is populated and ref-tracking still works.
    link = item.article_url or f"clawcast://inbound/{item.id}"
    summary = item.body_text or item.subject or ""
    return SourceItem(
        source_id=source_id,
        source_name=source_name,
        guid=item.message_id or item.id,
        link=link,
        title=item.subject or "Untitled newsletter",
        summary=summary,
        published_at=item.received_at,
        dedupe_key=f"inbound:{item.id}",
    )


def _is_substack_confirmation_email(item: InboundEmailItem) -> bool:
    """Substack double-opt-in confirmation mails are stored as InboundEmailItem
    alongside real posts (the inbound handler doesn't drop them). Detect
    them so the digest pipeline doesn't drag a "Confirm your subscription
    to X" into a user's podcast script.
    """
    if not item.sender_domain:
        return False
    if "substack.com" not in item.sender_domain.lower():
        return False
    return extract_confirm_url(item.body_text or "") is not None


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
    intake_extractor: Optional[IntakeExtractor] = None
    card_summarizer: Optional[CardSummarizer] = None
    substack_discovery: Optional[SubstackDiscoveryService] = None
    app_store_verifier: Optional[AppStoreNotificationVerifier] = None

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
        self._card_summary_service = CardSummaryService(
            repository=self.repository,
            summarizer=self.card_summarizer,
        )
        self._candidate_queue_service = CandidateQueueService(
            settings=self.settings,
            repository=self.repository,
            source_item_persistence=self._source_item_persistence,
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
        log_event(EventName.SIGN_IN, user.id, is_new_user=is_new)
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
        self._seed_interest_from_substack_intent(intent)
        self._prefetch_latest_post_for_intent(intent, probe.feed_url)
        logger.info(
            "Substack intent created: user=%s pub_host=%s intent_id=%s",
            user_id,
            host,
            intent_id,
        )
        return {"intent": self._serialize_intent(intent)}

    def _prefetch_latest_post_for_intent(
        self,
        intent: UserSubstackIntent,
        feed_url: str,
    ) -> None:
        """Pull the publication's most-recent free post from its RSS feed and
        store it as an InboundEmailItem so the user's next podcast can pick it
        up immediately, instead of waiting for the publication's next email.

        Best-effort: any failure (network, parse, no entries) is swallowed.
        The item id is keyed on the post URL so re-running this for an idempotent
        intent-create won't create duplicates.
        """
        try:
            post = fetch_latest_post(feed_url)
        except Exception:  # pragma: no cover — fetch is best-effort
            logger.warning(
                "Substack latest-post prefetch raised: user=%s pub_host=%s",
                intent.user_id,
                intent.pub_host,
                exc_info=True,
            )
            return
        if post is None:
            return

        item_id = link_hash(post.link)[:32]
        if self.repository.get_inbound_item(item_id) is not None:
            return

        item = InboundEmailItem(
            id=item_id,
            user_id=intent.user_id,
            message_id=None,
            from_email=f"rss@{intent.pub_host}",
            from_name=intent.pub_title or intent.pub_author or intent.pub_host,
            sender_domain=intent.pub_host,
            subject=post.title,
            body_text=post.summary[:8000],
            article_url=post.link,
            received_at=post.published_at,
        )
        try:
            self.repository.save_inbound_item(item)
        except Exception:  # pragma: no cover — storage is best-effort here
            logger.warning(
                "Substack latest-post prefetch save failed: user=%s pub_host=%s",
                intent.user_id,
                intent.pub_host,
                exc_info=True,
            )
            return
        logger.info(
            "Substack latest-post prefetched: user=%s pub_host=%s item_id=%s url=%s",
            intent.user_id,
            intent.pub_host,
            item_id,
            post.link,
        )

    def _seed_interest_from_substack_intent(self, intent: UserSubstackIntent) -> None:
        """Seed the user's interest vector with the publication metadata so
        the ranker pulls toward this publication's content even before any
        post arrives via the inbound alias. Best-effort: any failure (no
        embedding provider, embed call failed) is swallowed.
        """
        if self.embedding_provider is None:
            return
        title = (intent.pub_title or intent.pub_host).strip()
        if not title:
            return
        body_parts: list[str] = [title]
        if intent.pub_author:
            body_parts.append(f"by {intent.pub_author}")
        body_parts.append(intent.pub_host)
        body_text = " — ".join(body_parts)
        try:
            seed_user_interest(
                repository=self.repository,
                embeddings=self.embedding_provider,
                user_id=intent.user_id,
                kind=SEED_KIND_SUBSTACK,
                items=[(title, body_text)],
            )
        except Exception:  # pragma: no cover — seeding is best-effort
            logger.warning(
                "Substack intent interest-seed failed: user=%s pub_host=%s",
                intent.user_id,
                intent.pub_host,
                exc_info=True,
            )

    def submit_voice_intake(self, user_id: str, transcript: str) -> dict[str, Any]:
        """Turn the user's onboarding voice transcript into seeded interest
        signal + listener-anchor phrases + a tone hint on the podcast profile.

        Returns a small payload the iOS app uses to render confirmation
        ("we heard you talk about X, Y, Z"). Idempotent within reason:
        re-submitting the same transcript writes new synthetic swipes with
        a different hash key only if the text differs; identical text
        deduplicates on the seed dedupe-key.
        """
        user = self._require_user(user_id)
        if self.embedding_provider is None:
            raise ControlPlaneError("Voice intake is unavailable (embeddings not configured)")
        if self.intake_extractor is None:
            raise ControlPlaneError("Voice intake is unavailable (extractor not configured)")
        cleaned = (transcript or "").strip()
        if not cleaned:
            raise ControlPlaneError("Transcript is empty")

        extracted: ExtractedIntake = self.intake_extractor.extract(cleaned)
        items: list[tuple[str, str]] = []
        # Topics and named entities each get their own embedding so the
        # interest vector picks up multiple regions at once. Anchor phrases
        # are short and personal — they ride along as seeds AND surface in
        # listener_anchors via _compute_listener_anchors.
        for topic in extracted.topics:
            items.append((topic, topic))
        for entity in extracted.named_entities:
            items.append((entity, entity))
        for phrase in extracted.anchor_phrases:
            items.append((phrase, phrase))

        seeded = 0
        if items:
            try:
                seeded = seed_user_interest(
                    repository=self.repository,
                    embeddings=self.embedding_provider,
                    user_id=user.id,
                    kind=SEED_KIND_VOICE,
                    items=items,
                )
            except Exception:  # pragma: no cover — seeding is best-effort
                logger.warning(
                    "Voice intake seeding failed: user=%s", user.id, exc_info=True
                )
                seeded = 0

        # vibe_notes describes how the user wants the show to feel. Append to
        # the existing custom_guidance instead of overwriting so an
        # already-configured user keeps their prior preference.
        if extracted.vibe_notes:
            self._append_to_custom_guidance(user.id, extracted.vibe_notes)

        log_event(
            EventName.ONBOARDING_STEP,
            user.id,
            step="voice_intake",
            seeded_count=seeded,
            topic_count=len(extracted.topics),
            entity_count=len(extracted.named_entities),
            anchor_count=len(extracted.anchor_phrases),
            vibe_notes_present=bool(extracted.vibe_notes),
        )
        return {
            "seeded_count": seeded,
            "topics": extracted.topics,
            "named_entities": extracted.named_entities,
            "anchor_phrases": extracted.anchor_phrases,
            "vibe_notes": extracted.vibe_notes,
        }

    def _append_to_custom_guidance(self, user_id: str, addition: str) -> None:
        profile = self._get_profile(user_id)
        existing = (profile.custom_guidance or "").strip()
        addition_clean = addition.strip()
        if not addition_clean:
            return
        # Avoid duplicate appends across replays.
        if addition_clean.lower() in existing.lower():
            return
        merged = f"{existing}\n{addition_clean}".strip() if existing else addition_clean
        profile.custom_guidance = _sanitize_custom_guidance(merged) or addition_clean
        profile.updated_at = utc_now()
        self.repository.save_profile(profile)

    def discover_substacks(self, raw_query: str) -> dict[str, Any]:
        """Free-text / voice-transcript -> validated Substack candidate cards.

        Returns the same shape as the probe endpoint per candidate so the iOS
        layer can route each entry through the existing intent-creation flow.
        Best-effort: any LLM/probe failure returns an empty list rather than
        an error, so the onboarding step never blocks on the search.
        """
        if self.substack_discovery is None:
            raise ControlPlaneError(
                "Substack discovery is unavailable (LLM key not configured)"
            )
        cleaned = (raw_query or "").strip()
        if not cleaned:
            raise ControlPlaneError("Query is empty")
        candidates = self.substack_discovery.discover(cleaned)
        return {
            "candidates": [self._serialize_discovery(candidate) for candidate in candidates],
        }

    @staticmethod
    def _serialize_discovery(candidate: DiscoveredPublication) -> dict[str, Any]:
        payload = ControlPlaneService._serialize_probe(candidate.probe)
        payload["why"] = candidate.why
        return payload

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
        log_event(
            EventName.FEEDBACK_SUBMITTED,
            user_id,
            feedback_id=record.id,
            source=source,
            char_count=len(cleaned),
            locale_hint=locale_hint,
            english_present=english is not None,
        )
        return record.model_dump(mode="json")

    def send_feedback_weekly_digest(self) -> dict[str, Any]:
        """Send the weekly feedback summary email. First run pulls everything to
        date; later runs only include feedback created since the previous run.
        Sends even when empty (with a 'no feedback this week' body) so the
        operator always gets a heartbeat from the job."""
        if not self.settings.feedback_digest_email_enabled:
            return {"status": "disabled"}

        last_run_at = self.repository.get_job_state(FEEDBACK_DIGEST_JOB_STATE_NAME)
        now = utc_now()
        records = self.repository.list_feedback_since(last_run_at)

        users_by_id: dict[str, UserRecord] = {}
        for record in records:
            if record.user_id in users_by_id:
                continue
            user = self.repository.get_user(record.user_id)
            if user is not None:
                users_by_id[record.user_id] = user

        summary: Optional[str] = None
        if records:
            try:
                summary = summarize_feedback_with_llm(
                    records,
                    api_key=self.podcast_client.api_key,
                    text_model=self.podcast_client.text_model,
                    base_url=self.podcast_client.base_url,
                )
            except (TranslationError, requests.RequestException) as exc:
                logger.warning("Feedback digest summarization failed: %s", exc)
                summary = None

        subject, body = format_digest_email(
            records,
            summary=summary,
            since=last_run_at,
            now=now,
            users_by_id=users_by_id,
        )

        recipients = self._feedback_digest_recipients()
        if not recipients:
            raise ControlPlaneError(
                "Feedback digest has no recipients configured"
            )

        self.mailer.send(subject, body, recipients=recipients)
        self.repository.set_job_state(FEEDBACK_DIGEST_JOB_STATE_NAME, now)

        return {
            "status": "sent",
            "feedback_count": len(records),
            "since": last_run_at.isoformat() if last_run_at else None,
            "now": now.isoformat(),
            "recipients": recipients,
            "summary_present": summary is not None,
        }

    def _feedback_digest_recipients(self) -> list[str]:
        seen: set[str] = set()
        recipients: list[str] = []
        candidates: list[str] = []
        if self.settings.alert_email_to:
            candidates.append(self.settings.alert_email_to)
        for raw in self.settings.feedback_digest_extra_recipients.split(","):
            candidates.append(raw)
        for raw in candidates:
            address = raw.strip()
            if not address or address in seen:
                continue
            seen.add(address)
            recipients.append(address)
        return recipients

    def get_cold_start_swipe_deck(self, user_id: str) -> dict[str, Any]:
        self._require_user(user_id)
        records = self._swipe_deck_service.get_cold_start_deck(user_id)
        records = self._card_summary_service.ensure_summaries(records)
        return {"items": [_swipe_card_payload(record) for record in records]}

    def refresh_cold_start_deck(self) -> dict[str, Any]:
        """Force-refresh the global cold-start swipe deck.

        Invoked by the weekly scheduler so the deck stays fresh even on weeks
        when no user opens it (lazy refresh on access only kicks in when a
        client requests the deck).
        """
        deck = self._swipe_deck_service.refresh_cold_start_deck()
        if deck is None:
            return {"status": "skipped", "reason": "empty_corpus"}
        return {
            "status": "refreshed",
            "deck_size": len(deck.dedupe_keys),
            "corpus_size": deck.corpus_size,
            "computed_at": deck.computed_at.isoformat(),
            "version": deck.version,
        }

    def poll_sources(self) -> dict[str, Any]:
        """Hourly global source-poll target (Cloud Scheduler). No-op when
        candidate-queue is flag-disabled."""
        return self._candidate_queue_service.run_poll()

    def list_next_episode_candidates(self, user_id: str) -> dict[str, Any]:
        if not self.settings.candidate_queue_enabled:
            return {"enabled": False, "candidates": []}
        entitlements = self._entitlements_for_user(user_id)
        payload = self._candidate_queue_service.list_candidates(
            user_id,
            per_episode_cap=entitlements.max_items_per_episode,
        )
        payload["enabled"] = True
        return payload

    def pin_next_episode_item(self, user_id: str, dedupe_key: str) -> dict[str, Any]:
        if not self.settings.candidate_queue_enabled:
            raise ControlPlaneError("Candidate queue is not enabled")
        try:
            return self._candidate_queue_service.pin_item(user_id, dedupe_key)
        except CandidateQueueError as exc:
            raise ControlPlaneError(str(exc)) from exc

    def exclude_next_episode_item(self, user_id: str, dedupe_key: str) -> dict[str, Any]:
        if not self.settings.candidate_queue_enabled:
            raise ControlPlaneError("Candidate queue is not enabled")
        try:
            return self._candidate_queue_service.exclude_item(user_id, dedupe_key)
        except CandidateQueueError as exc:
            raise ControlPlaneError(str(exc)) from exc

    def clear_next_episode_override(
        self, user_id: str, dedupe_key: str
    ) -> dict[str, Any]:
        if not self.settings.candidate_queue_enabled:
            raise ControlPlaneError("Candidate queue is not enabled")
        return self._candidate_queue_service.clear_override(user_id, dedupe_key)

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
        records = self._card_summary_service.ensure_summaries(records)
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
        attached_source_id: Optional[str] = None
        if direction > 0:
            attached_source_id = self._maybe_auto_attach_source(user_id, record.source_id)
            if attached_source_id:
                result["auto_attached_source_id"] = attached_source_id
        log_event(
            EventName.SWIPE_RECORDED,
            user_id,
            direction=direction,
            source_id=record.source_id,
            auto_attached=bool(attached_source_id),
        )
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
        custom_count = sum(1 for source in resolved if source.is_custom)
        log_event(
            EventName.SOURCES_SAVED,
            user_id,
            source_count=len(resolved),
            custom_count=custom_count,
            catalog_count=len(resolved) - custom_count,
        )
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
        log_event(
            EventName.SCHEDULE_CHANGED,
            user_id,
            weekday_count=len(schedule.weekdays),
            local_time=schedule.local_time,
            timezone=schedule.timezone,
        )
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

    def reset_user_account(self, user_id: str) -> dict[str, Any]:
        """Wipe per-user onboarding state so the iOS wizard re-runs while
        keeping the account itself (Apple Sign-in linkage, feed token,
        subscription, episode history, billing events) intact.

        Mirrors `scripts/reset_user.py` but is callable from inside the app
        so users can self-serve via a "Reset my algorithm" button instead of
        an operator running the admin script.

        Idempotent: if the user has nothing to reset, returns zero counts.
        Raises ControlPlaneError if the user record cannot be found.
        """
        user = self.repository.get_user(user_id)
        if user is None:
            raise ControlPlaneError(f"Unknown user: {user_id}")

        counts = self.repository.reset_user_state(user_id)
        logger.info("Account reset: user=%s records=%s", user_id, counts)
        return {
            "user_id": user_id,
            "records": counts,
        }

    def delete_user_account(self, user_id: str) -> dict[str, Any]:
        """Hard-delete every per-user record we hold for `user_id`, plus all
        of the user's audio blobs in object storage. Idempotent: if the user
        has already been deleted, returns zero counts.

        Billing event rows are kept but anonymized (user_id nulled) so the
        bookkeeping trail required under Danish accounting rules survives
        without remaining linked to an identifiable user.
        """
        user = self.repository.get_user(user_id)
        if user is None:
            # Already gone — nothing to do, but stay idempotent so retries
            # from a flaky client don't 404.
            return {
                "user_id": user_id,
                "already_deleted": True,
                "audio_objects_deleted": 0,
                "audio_objects_missing": 0,
                "records": {},
            }

        # We have to pull the episode list BEFORE wiping the records so we
        # know which audio blobs to remove from object storage.
        episodes = self.repository.list_recent_user_episodes(user_id, limit=10_000)
        audio_deleted = 0
        audio_missing = 0
        for episode in episodes:
            object_name = (episode.audio_object_name or "").strip()
            if not object_name:
                continue
            try:
                if self.storage.delete_audio(object_name):
                    audio_deleted += 1
                else:
                    audio_missing += 1
            except Exception:
                # A single blob failure shouldn't block the rest of the
                # delete. Log and continue; an operator can sweep up
                # orphaned objects later from logs.
                logger.warning(
                    "Audio blob delete failed during account wipe: user=%s object=%s",
                    user_id,
                    object_name,
                    exc_info=True,
                )

        counts = self.repository.delete_user_account(user_id)
        logger.info(
            "Account deleted: user=%s audio_deleted=%s audio_missing=%s records=%s",
            user_id,
            audio_deleted,
            audio_missing,
            counts,
        )
        return {
            "user_id": user_id,
            "already_deleted": False,
            "audio_objects_deleted": audio_deleted,
            "audio_objects_missing": audio_missing,
            "records": counts,
        }

    # ----- App Store Server Notifications -----------------------------

    # Notification types that flip the subscription INTO an active state.
    # "DID_CHANGE_RENEWAL_PREF" lands when a user upgrades/downgrades
    # between Pro and Max — the new product id is in the transaction.
    _APP_STORE_ACTIVATE_TYPES = frozenset(
        {"SUBSCRIBED", "DID_RENEW", "OFFER_REDEEMED", "DID_CHANGE_RENEWAL_PREF"}
    )
    # Notification types that revoke entitlement.
    _APP_STORE_REVOKE_TYPES = frozenset(
        {"EXPIRED", "REVOKE", "REFUND", "GRACE_PERIOD_EXPIRED"}
    )

    def apply_app_store_notification(self, payload: dict[str, Any]) -> dict[str, Any]:
        signed_payload = payload.get("signedPayload") or payload.get("signed_payload")
        if signed_payload:
            if self.app_store_verifier is None:
                # Defensive — only happens if the deployment skipped the
                # verifier wiring. Refuse rather than silently trusting the
                # encoded payload without checking the signature.
                raise ControlPlaneError(
                    "App Store signedPayload verification is not configured"
                )
            try:
                decoded = self.app_store_verifier.verify(signed_payload)
            except AppStoreVerificationError as exc:
                logger.warning("App Store notification rejected: %s", exc)
                raise ControlPlaneError(str(exc)) from exc
            return self._apply_verified_app_store_notification(decoded, raw=payload)

        if self.settings.app_store_notifications_require_signed:
            raise ControlPlaneError(
                "App Store notifications must include signedPayload"
            )
        return self._apply_legacy_app_store_notification(payload)

    def _apply_verified_app_store_notification(
        self,
        decoded: DecodedNotification,
        *,
        raw: dict[str, Any],
    ) -> dict[str, Any]:
        event = BillingEventRecord(
            id=uuid4().hex,
            user_id=_normalize_app_account_token(decoded.app_account_token),
            notification_type=decoded.notification_type or "unknown",
            subtype=decoded.subtype,
            product_id=decoded.product_id,
            raw_payload=raw,
            created_at=utc_now(),
        )
        self.repository.save_billing_event(event)

        if not event.user_id:
            # Apple delivered a verified notification but the transaction
            # had no appAccountToken — should not happen if the iOS app
            # always passes one through StoreKit2 .appAccountToken option.
            logger.warning(
                "Verified App Store notification missing app_account_token: %s",
                event.notification_type,
            )
            return {"accepted": True, "event_id": event.id, "warning": "no app_account_token"}

        user = self.repository.get_user(event.user_id)
        if user is None:
            logger.warning(
                "Verified App Store notification for unknown user: %s",
                event.user_id,
            )
            return {"accepted": True, "event_id": event.id, "warning": "user not found"}

        subscription = self._get_subscription(event.user_id)
        previous_tier = subscription.tier
        previous_status = subscription.status
        self._mutate_subscription_from_notification(
            subscription,
            notification_type=decoded.notification_type,
            product_id=decoded.product_id,
            expires_date_ms=decoded.expires_date_ms,
            revocation_date_ms=decoded.revocation_date_ms,
        )
        subscription.updated_at = utc_now()
        self.repository.save_subscription(subscription)
        self._log_subscription_mutation(
            user_id=event.user_id,
            subscription=subscription,
            previous_tier=previous_tier,
            previous_status=previous_status,
            notification_type=decoded.notification_type or "unknown",
            via="app_store_notification",
        )
        return {"accepted": True, "event_id": event.id}

    def apply_client_verified_transaction(
        self,
        *,
        user_id: str,
        signed_transaction_info: str,
    ) -> dict[str, Any]:
        """Verify a StoreKit2 transaction JWS the iOS client pushed
        directly and update the user's subscription tier.

        Mirrors the ASN webhook path, but the trigger is the client
        immediately after `transaction.finish()` rather than Apple's
        server. Necessary because sandbox ASN delivery is unreliable —
        without this, TestFlight purchases never propagate to the
        backend and the user stays on `free`.
        """
        if self.app_store_verifier is None:
            raise ControlPlaneError(
                "App Store signedPayload verification is not configured"
            )
        try:
            decoded = self.app_store_verifier.verify_transaction(signed_transaction_info)
        except AppStoreVerificationError as exc:
            logger.warning("Client-verified transaction rejected: %s", exc)
            raise ControlPlaneError(str(exc)) from exc

        verified_user_id = _normalize_app_account_token(decoded.app_account_token)
        if not verified_user_id:
            raise ControlPlaneError(
                "transaction is missing app_account_token"
            )
        if verified_user_id != user_id:
            # JWS is Apple-signed, but the appAccountToken inside may
            # not match the authenticated session — refuse to attach
            # someone else's purchase to this user.
            raise ControlPlaneError(
                "transaction app_account_token does not match authenticated user"
            )

        event = BillingEventRecord(
            id=uuid4().hex,
            user_id=user_id,
            notification_type="CLIENT_VERIFIED",
            subtype=None,
            product_id=decoded.product_id,
            raw_payload={
                "transaction_id": decoded.transaction_id,
                "product_id": decoded.product_id,
                "environment": decoded.environment,
                "bundle_id": decoded.bundle_id,
                "expires_date_ms": decoded.expires_date_ms,
                "revocation_date_ms": decoded.revocation_date_ms,
            },
            created_at=utc_now(),
        )
        self.repository.save_billing_event(event)

        subscription = self._get_subscription(user_id)
        previous_tier = subscription.tier
        previous_status = subscription.status
        self._mutate_subscription_from_notification(
            subscription,
            notification_type="SUBSCRIBED",
            product_id=decoded.product_id,
            expires_date_ms=decoded.expires_date_ms,
            revocation_date_ms=decoded.revocation_date_ms,
        )
        subscription.updated_at = utc_now()
        self.repository.save_subscription(subscription)
        self._log_subscription_mutation(
            user_id=user_id,
            subscription=subscription,
            previous_tier=previous_tier,
            previous_status=previous_status,
            notification_type="CLIENT_VERIFIED",
            via="client_verified",
        )
        return {
            "accepted": True,
            "event_id": event.id,
            "subscription": {
                "tier": subscription.tier,
                "status": subscription.status,
                "product_id": subscription.product_id,
                "expires_at": subscription.expires_at.isoformat() if subscription.expires_at else None,
            },
        }

    def _apply_legacy_app_store_notification(
        self, payload: dict[str, Any]
    ) -> dict[str, Any]:
        """Legacy unsigned-payload path. Retained so internal smoke tests
        and the existing test suite keep working until
        APP_STORE_NOTIFICATIONS_REQUIRE_SIGNED is flipped on for prod."""
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
            previous_tier = subscription.tier
            previous_status = subscription.status
            pro_ids = {
                self.settings.app_store_pro_monthly_product_id,
                self.settings.app_store_pro_annual_product_id,
            }
            max_ids = {
                self.settings.app_store_max_monthly_product_id,
                self.settings.app_store_max_annual_product_id,
            }
            if event.product_id in pro_ids:
                subscription.tier = "pro"
                subscription.status = "active"
                subscription.product_id = event.product_id
            elif event.product_id in max_ids:
                subscription.tier = "max"
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
            self._log_subscription_mutation(
                user_id=event.user_id,
                subscription=subscription,
                previous_tier=previous_tier,
                previous_status=previous_status,
                notification_type=event.notification_type,
                via="app_store_notification_legacy",
            )

        return {
            "accepted": True,
            "event_id": event.id,
        }

    def _mutate_subscription_from_notification(
        self,
        subscription: SubscriptionRecord,
        *,
        notification_type: str,
        product_id: Optional[str],
        expires_date_ms: Optional[int],
        revocation_date_ms: Optional[int],
    ) -> None:
        pro_ids = {
            self.settings.app_store_pro_monthly_product_id,
            self.settings.app_store_pro_annual_product_id,
        }
        max_ids = {
            self.settings.app_store_max_monthly_product_id,
            self.settings.app_store_max_annual_product_id,
        }

        if notification_type in self._APP_STORE_ACTIVATE_TYPES:
            if product_id in pro_ids:
                subscription.tier = "pro"
                subscription.status = "active"
                subscription.product_id = product_id
            elif product_id in max_ids:
                subscription.tier = "max"
                subscription.status = "active"
                subscription.product_id = product_id
            else:
                logger.warning(
                    "App Store notification %s referenced unknown product_id=%r — "
                    "skipping tier mutation",
                    notification_type,
                    product_id,
                )
        elif notification_type in self._APP_STORE_REVOKE_TYPES:
            subscription.tier = "free"
            if notification_type == "EXPIRED":
                subscription.status = "expired"
            elif notification_type == "REVOKE":
                subscription.status = "revoked"
            elif notification_type == "REFUND":
                subscription.status = "refunded"
            else:
                subscription.status = "expired"
            subscription.product_id = None

        if expires_date_ms is not None:
            subscription.expires_at = datetime.fromtimestamp(
                expires_date_ms / 1000, tz=timezone.utc
            )

    def _log_subscription_mutation(
        self,
        *,
        user_id: str,
        subscription: SubscriptionRecord,
        previous_tier: str,
        previous_status: str,
        notification_type: str,
        via: str,
    ) -> None:
        """Emit SUBSCRIPTION_STARTED on a paid activation and
        SUBSCRIPTION_CHANGED on any other tier/status mutation.

        Both can fire (a brand-new paid activation is also a "change");
        the receiver differentiates by event_name. Skips logging when
        nothing actually moved so retries don't double-count.
        """
        tier_moved = subscription.tier != previous_tier
        status_moved = subscription.status != previous_status
        if not tier_moved and not status_moved:
            return
        common = {
            "tier": subscription.tier,
            "previous_tier": previous_tier,
            "status": subscription.status,
            "previous_status": previous_status,
            "product_id": subscription.product_id,
            "notification_type": notification_type,
            "via": via,
        }
        paid_now = subscription.tier in {"pro", "max"} and subscription.status == "active"
        was_paid = previous_tier in {"pro", "max"} and previous_status == "active"
        if paid_now and not was_paid:
            log_event(EventName.SUBSCRIPTION_STARTED, user_id, **common)
        log_event(EventName.SUBSCRIPTION_CHANGED, user_id, **common)

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
        # Rollover weekly counters if we're now in a new ISO week so the
        # entitlements + downstream gate operate on the current bucket.
        user_changed = False
        if self._rollover_weekly_counters(user, now_utc):
            user_changed = True
        if self._ensure_trial_state(user):
            user_changed = True
        entitlements = self._compute_entitlements(subscription, user, now_utc)
        # Decide voice tier for this episode: prefer premium when available
        # (the better voice for the first 3 pods of the week on Pro, all 7
        # on Max, trial pods, and first-month free pods).
        if entitlements.premium_pods_remaining_this_week > 0:
            voice_tier_for_episode = "premium"
        elif entitlements.default_pods_remaining_this_week > 0:
            voice_tier_for_episode = "default"
        else:
            voice_tier_for_episode = None
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

        if voice_tier_for_episode is None:
            # No quota left in either bucket for the current ISO week. Persist
            # rollover/trial bookkeeping so the next call sees fresh state if
            # we cross a week boundary, then skip cleanly.
            if user_changed:
                user.updated_at = utc_now()
                self.repository.save_user(user)
            run = UserRunRecord(
                id=run_id,
                user_id=user_id,
                local_run_date=local_date,
                started_at=now_utc,
                completed_at=now_utc,
                status=PublishStatus.SKIPPED.value,
                message="Weekly podcast quota reached for your plan",
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

        # Pull unconsumed inbound items (Substack newsletter posts via alias,
        # forwarded mail, prefetched latest-post-on-intent-create) and project
        # them into the same SourceItem shape as RSS items so they flow
        # through the existing ranker/cap/prompt pipeline. consumed_at gets
        # stamped after the episode publishes, but only on items that survive
        # into source_item_refs.
        try:
            raw_inbound = self.repository.list_unconsumed_inbound_items(user_id)
        except Exception:  # pragma: no cover — non-fatal, fall back to RSS-only
            logger.warning(
                "Listing unconsumed inbound items failed for user=%s; "
                "continuing without inbound content",
                user_id,
                exc_info=True,
            )
            raw_inbound = []
        try:
            intents = self.repository.list_user_substack_intents(user_id)
        except Exception:  # pragma: no cover
            intents = []
        intent_by_host = {intent.pub_host.lower(): intent for intent in intents}
        inbound_items: list[InboundEmailItem] = []
        inbound_source_items: list[SourceItem] = []
        inbound_dedupe_to_item_id: dict[str, str] = {}
        for inbound_item in raw_inbound:
            if _is_substack_confirmation_email(inbound_item):
                continue
            source_item = _inbound_item_to_source_item(inbound_item, intent_by_host)
            inbound_items.append(inbound_item)
            inbound_source_items.append(source_item)
            inbound_dedupe_to_item_id[source_item.dedupe_key] = inbound_item.id
        if inbound_source_items:
            logger.info(
                "Inbound items merged into candidate pool: user=%s count=%d "
                "intents=%d",
                user_id,
                len(inbound_source_items),
                len(intent_by_host),
            )

        combined_candidates = ingestion.items + inbound_source_items
        combined_candidates.sort(key=lambda item: item.published_at)
        candidate_count = len(combined_candidates)
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

        items = combined_candidates
        dropped_count = 0
        cap_hit = False

        # Hard-exclude items the user explicitly swiped left on. The ranker
        # only soft-downweights via vector similarity, and below
        # swipe_ranker_min_swipes it's bypassed entirely — so without this
        # filter an item the user just declined in the swipe deck can
        # immediately resurface in the first briefing.
        left_swipe_keys = {
            swipe.source_item_dedupe_key
            for swipe in self.repository.list_user_swipes(user_id)
            if swipe.direction < 0 and swipe.source_item_dedupe_key
        }
        if left_swipe_keys:
            before = len(items)
            items = [item for item in items if item.dedupe_key not in left_swipe_keys]
            removed = before - len(items)
            if removed:
                logger.info(
                    "left_swipe_exclusion user=%s removed=%d remaining=%d",
                    user_id, removed, len(items),
                )

        # Next-episode queue overrides (flag-gated spike). Excludes drop from
        # the candidate pool entirely; pins force-include up to the per-tier
        # item cap, with the ranker (or chronological fallback) filling
        # remaining slots. Honored_pin_keys is what we'll mark consumed
        # once the episode actually publishes.
        honored_pin_keys: set[str] = set()
        if self.settings.candidate_queue_enabled:
            pin_overrides = self.repository.list_next_episode_overrides(
                user_id, kind="pin", only_unconsumed=True
            )
            exclude_overrides = self.repository.list_next_episode_overrides(
                user_id, kind="exclude", only_unconsumed=True
            )
            pinned_keys = {p.source_item_dedupe_key for p in pin_overrides}
            excluded_keys = {e.source_item_dedupe_key for e in exclude_overrides}
            if excluded_keys:
                items = [item for item in items if item.dedupe_key not in excluded_keys]
            if pinned_keys:
                cap = entitlements.max_items_per_episode
                pinned_in_pool = [item for item in items if item.dedupe_key in pinned_keys]
                # Apply max_pins cap (oldest pins first — same tiebreaker the
                # candidates view uses, so the UI and generation agree on
                # which pins survive the cap).
                pin_budget = min(self.settings.next_episode_max_pins, cap)
                if len(pinned_in_pool) > pin_budget:
                    pin_created_at = {
                        p.source_item_dedupe_key: p.created_at for p in pin_overrides
                    }
                    pinned_in_pool.sort(
                        key=lambda i: pin_created_at.get(i.dedupe_key, utc_now())
                    )
                    pinned_in_pool = pinned_in_pool[:pin_budget]
                honored_pin_keys = {item.dedupe_key for item in pinned_in_pool}
                unpinned = [item for item in items if item.dedupe_key not in honored_pin_keys]
                remaining_budget = max(0, cap - len(honored_pin_keys))
                ranked_unpinned = self._apply_swipe_ranker(
                    user_id,
                    unpinned,
                    remaining_budget,
                    boosted_dedupe_keys=set(inbound_dedupe_to_item_id),
                )
                if ranked_unpinned is None:
                    if len(unpinned) > remaining_budget:
                        ranked_unpinned = unpinned[-remaining_budget:] if remaining_budget > 0 else []
                    else:
                        ranked_unpinned = list(unpinned)
                final_items = pinned_in_pool + ranked_unpinned
                final_items.sort(key=lambda item: item.published_at)
                if len(final_items) < len(items):
                    cap_hit = True
                    dropped_count = len(items) - len(final_items)
                items = final_items
            else:
                ranked_items = self._apply_swipe_ranker(
                    user_id,
                    items,
                    entitlements.max_items_per_episode,
                    boosted_dedupe_keys=set(inbound_dedupe_to_item_id),
                )
                if ranked_items is not None:
                    if len(ranked_items) < len(items):
                        cap_hit = True
                        dropped_count = len(items) - len(ranked_items)
                    items = ranked_items
                elif len(items) > entitlements.max_items_per_episode:
                    cap_hit = True
                    dropped_count = len(items) - entitlements.max_items_per_episode
                    items = items[-entitlements.max_items_per_episode :]
        else:
            ranked_items = self._apply_swipe_ranker(
                user_id,
                items,
                entitlements.max_items_per_episode,
                boosted_dedupe_keys=set(inbound_dedupe_to_item_id),
            )
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
        ux.listener_anchors = self._compute_listener_anchors(user_id)
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
            force_default_voice=(voice_tier_for_episode == "default"),
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

        # Stamp consumed_at on the inbound items that survived ranker + cap
        # into this episode. Items that got dropped stay unconsumed so they
        # can be picked up on the next run. Best-effort: a failure here
        # would only cause an item to be retried (i.e. duplicated in a
        # later episode), so we log and continue rather than fail the run.
        consumed_inbound_ids = [
            inbound_dedupe_to_item_id[item.dedupe_key]
            for item in items
            if item.dedupe_key in inbound_dedupe_to_item_id
        ]
        if consumed_inbound_ids:
            try:
                self.repository.mark_inbound_items_consumed(
                    consumed_inbound_ids, consumed_at=utc_now()
                )
            except Exception:  # pragma: no cover — non-fatal
                logger.warning(
                    "Marking inbound items consumed failed: user=%s count=%d",
                    user_id,
                    len(consumed_inbound_ids),
                    exc_info=True,
                )

        # Stamp consumed_at on pins that survived into this episode so they
        # drop off the candidate-queue UI. Mirrors the inbound-item pattern:
        # only the pins that actually landed in the cut are consumed; bumped
        # pins stay active for the next run. Best-effort — duplication is
        # the failure mode, not data loss.
        consumed_pin_keys = [
            item.dedupe_key for item in items if item.dedupe_key in honored_pin_keys
        ]
        if consumed_pin_keys:
            try:
                self.repository.mark_next_episode_overrides_consumed(
                    user_id, consumed_pin_keys, consumed_at=utc_now()
                )
            except Exception:  # pragma: no cover — non-fatal
                logger.warning(
                    "Marking next-episode pins consumed failed: user=%s count=%d",
                    user_id,
                    len(consumed_pin_keys),
                    exc_info=True,
                )

        # Charge this episode against the appropriate per-week counter. If we
        # used premium voice and the user is still in trial, also decrement
        # the trial counter and (when trial exhausts) start the first-month
        # grace window.
        if voice_tier_for_episode == "premium":
            user.premium_pods_this_week += 1
            user_changed = True
            if (user.trial_premium_pods_remaining or 0) > 0:
                user.trial_premium_pods_remaining = (user.trial_premium_pods_remaining or 0) - 1
                if user.trial_premium_pods_remaining <= 0 and user.trial_exhausted_at is None:
                    exhaust_at = utc_now()
                    user.trial_exhausted_at = exhaust_at
                    user.first_month_ends_at = exhaust_at + timedelta(
                        days=self.settings.free_first_month_grace_days
                    )
        elif voice_tier_for_episode == "default":
            user.default_pods_this_week += 1
            user_changed = True
        if weekly_update_due:
            user.last_weekly_update_iso_week = current_iso_week
            user_changed = True
        if user_changed:
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

        log_event(
            EventName.EPISODE_GENERATED,
            user_id,
            run_id=run.id,
            episode_id=episode.id,
            voice_tier=voice_tier_for_episode,
            candidate_count=candidate_count,
            processed_item_count=len(items),
            dropped_item_count=dropped_count,
            cap_hit=cap_hit,
            duration_seconds=generated.duration_seconds,
            weekly_update_included=weekly_update_due,
            inbound_item_count=len(consumed_inbound_ids),
            pinned_item_count=len(consumed_pin_keys),
        )

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
            log_event(
                EventName.EPISODE_REQUESTED,
                user_id,
                run_id=existing.id,
                force=force,
                started=False,
            )
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
        log_event(
            EventName.EPISODE_REQUESTED,
            user_id,
            run_id=run.id,
            force=force,
            started=True,
        )
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
            log_event(
                EventName.EPISODE_FAILED,
                user_id,
                run_id=run_id,
                error_class=type(exc).__name__,
            )

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
            trial_premium_pods_remaining=self.settings.trial_premium_pods_total,
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

    # --- Tier resolution and entitlements (launch tier model 2026-05-16) ---

    _PRO_PRODUCT_IDS_ATTR = ("app_store_pro_monthly_product_id", "app_store_pro_annual_product_id")
    _MAX_PRODUCT_IDS_ATTR = ("app_store_max_monthly_product_id", "app_store_max_annual_product_id")

    def _resolve_tier(self, subscription: SubscriptionRecord) -> str:
        """Returns one of "free" | "pro" | "max". Legacy "paid" rows map to "pro"."""
        if subscription.status in {"expired", "revoked"}:
            return "free"
        tier = (subscription.tier or "").strip().lower()
        if tier == "max":
            return "max"
        if tier in {"pro", "paid"}:
            return "pro"
        return "free"

    def _ensure_trial_state(self, user: UserRecord) -> bool:
        """Backfill trial_premium_pods_remaining for users created before the
        launch tier model. Returns True if the user record was modified."""
        if user.trial_premium_pods_remaining is None:
            user.trial_premium_pods_remaining = self.settings.trial_premium_pods_total
            return True
        return False

    def _user_week_iso(self, user: UserRecord, now_utc: datetime) -> str:
        tz = user.timezone or self.settings.app_timezone or "UTC"
        try:
            local_date = now_utc.astimezone(ZoneInfo(tz)).date()
        except Exception:
            local_date = now_utc.date()
        return iso_week_key(local_date)

    def _rollover_weekly_counters(self, user: UserRecord, now_utc: datetime) -> bool:
        """If `user.current_week_iso` is stale, zero the per-week counters.
        Returns True if the user record was modified."""
        week = self._user_week_iso(user, now_utc)
        if user.current_week_iso == week:
            return False
        user.current_week_iso = week
        user.premium_pods_this_week = 0
        user.default_pods_this_week = 0
        return True

    def _compute_entitlements(
        self,
        subscription: SubscriptionRecord,
        user: UserRecord,
        now_utc: datetime,
    ) -> UserEntitlements:
        tier = self._resolve_tier(subscription)
        self._ensure_trial_state(user)

        trial_remaining = max(0, user.trial_premium_pods_remaining or 0)
        first_month_ends_at = user.first_month_ends_at

        is_in_trial = tier == "free" and trial_remaining > 0
        is_in_first_month = (
            tier == "free"
            and not is_in_trial
            and first_month_ends_at is not None
            and first_month_ends_at > now_utc
        )

        s = self.settings
        if tier == "max":
            premium_pw = s.max_premium_pods_per_week
            default_pw = 0
            min_d, max_d = s.max_min_duration_minutes, s.max_max_duration_minutes
            items_cap = s.max_max_items_per_episode
            days_cap = s.max_max_delivery_days
        elif tier == "pro":
            premium_pw = s.pro_premium_pods_per_week
            default_pw = s.pro_default_pods_per_week
            min_d, max_d = s.pro_min_duration_minutes, s.pro_max_duration_minutes
            items_cap = s.pro_max_items_per_episode
            days_cap = s.pro_max_delivery_days
        else:  # free
            if is_in_trial:
                # Trial: every pod the user generates this week is premium-voice,
                # drained against the global trial counter. The weekly budget is
                # effectively whatever remains in the trial counter (capped at 7
                # for sanity, since there are only 7 weekdays).
                premium_pw = min(7, trial_remaining)
                default_pw = 0
            elif is_in_first_month:
                premium_pw = s.free_first_month_premium_pods_per_week
                default_pw = 0
            else:
                premium_pw = 0
                default_pw = s.free_post_month_default_pods_per_week
            min_d, max_d = s.free_min_duration_minutes, s.free_max_duration_minutes
            items_cap = s.free_max_items_per_episode
            days_cap = s.free_max_delivery_days

        # Compute remaining capacity for the current ISO week. We don't
        # mutate the user record here — counters are persisted by the
        # generation flow when an episode is actually produced.
        current_week = self._user_week_iso(user, now_utc)
        if user.current_week_iso == current_week:
            premium_used = user.premium_pods_this_week
            default_used = user.default_pods_this_week
        else:
            premium_used = 0
            default_used = 0

        return UserEntitlements(
            tier=tier,
            max_delivery_days=days_cap,
            min_duration_minutes=min_d,
            max_duration_minutes=max_d,
            max_items_per_episode=items_cap,
            premium_pods_per_week=premium_pw,
            default_pods_per_week=default_pw,
            premium_pods_remaining_this_week=max(0, premium_pw - premium_used),
            default_pods_remaining_this_week=max(0, default_pw - default_used),
            is_in_trial=is_in_trial,
            trial_premium_pods_remaining=trial_remaining,
            is_in_first_month=is_in_first_month,
            first_month_ends_at=first_month_ends_at,
        )

    def _entitlements_for_user(self, user_id: str) -> UserEntitlements:
        user = self._require_user(user_id)
        subscription = self._get_subscription(user_id)
        return self._compute_entitlements(subscription, user, utc_now())

    # Back-compat shim: a few legacy callers still pass just `subscription`.
    # Used by paths where the user record isn't already on hand; they pay
    # an extra repo read but avoid the broader refactor for now.
    def _entitlements_for(self, subscription: SubscriptionRecord) -> UserEntitlements:
        user = self.repository.get_user(subscription.user_id)
        if user is None:
            # Fall back to free-tier defaults if the user record is gone —
            # shouldn't happen in practice since a subscription presupposes
            # a user, but defensive.
            return UserEntitlements(
                tier="free",
                max_delivery_days=self.settings.free_max_delivery_days,
                min_duration_minutes=self.settings.free_min_duration_minutes,
                max_duration_minutes=self.settings.free_max_duration_minutes,
                max_items_per_episode=self.settings.free_max_items_per_episode,
                premium_pods_per_week=0,
                default_pods_per_week=self.settings.free_post_month_default_pods_per_week,
            )
        return self._compute_entitlements(subscription, user, utc_now())

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

    def _compute_listener_anchors(self, user_id: str) -> list[str]:
        """Best-effort list of names/topics the user volunteered.

        Drawn from (a) titles of synthetic onboarding swipes (voice intake,
        Substack paste), (b) confirmed Substack intent publication titles,
        and (c) recent forwarded-mail sender names. Capped at 8 entries with
        the most-personal sources first (voice > paste > Substack > forwarded).
        Best-effort: any sub-fetch failure is swallowed.
        """
        anchors: list[str] = []
        seen: set[str] = set()

        def _push(value: Optional[str]) -> None:
            if not value:
                return
            cleaned = value.strip()
            if not cleaned:
                return
            key = cleaned.lower()
            if key in seen:
                return
            seen.add(key)
            anchors.append(cleaned)

        try:
            swipes = self.repository.list_user_swipes(user_id, limit=200)
        except Exception:  # pragma: no cover — anchors are best-effort
            swipes = []
        # Voice intake anchors are richest — surface them first.
        for swipe in swipes:
            if swipe.seed_kind == "voice_intake" and swipe.direction > 0:
                _push(swipe.title)
        for swipe in swipes:
            if swipe.seed_kind == "substack_paste" and swipe.direction > 0:
                _push(swipe.title)
        try:
            intents = self.repository.list_user_substack_intents(user_id)
        except Exception:  # pragma: no cover
            intents = []
        for intent in intents:
            _push(intent.pub_title or intent.pub_host)
        try:
            inbound_items = self.repository.list_recent_inbound_items(
                user_id, limit=10
            )
        except Exception:  # pragma: no cover
            inbound_items = []
        for item in inbound_items:
            _push(item.from_name or item.sender_domain)

        return anchors[:8]

    def _apply_swipe_ranker(
        self,
        user_id: str,
        items: list[SourceItem],
        top_n: int,
        boosted_dedupe_keys: Optional[set[str]] = None,
    ) -> Optional[list[SourceItem]]:
        """Score and select items by similarity to the user's interest vector.

        Returns None when the ranker is disabled, the user has too few swipes
        to produce a meaningful vector, or no usable embeddings can be loaded —
        in which case the caller falls back to chronological selection.

        `boosted_dedupe_keys`, if provided, receives a positive score bonus
        (`settings.inbound_ranker_bias`) so high-intent content like inbound
        newsletter mail outranks neutrally-scored RSS items at the cap.
        """
        candidate_count = len(items)
        if not self.settings.swipe_ranker_enabled or top_n <= 0:
            logger.info(
                "swipe_ranker user=%s used=false reason=disabled "
                "candidates=%d top_n=%d",
                user_id,
                candidate_count,
                top_n,
            )
            return None
        swipe_count = self.repository.count_user_swipes(user_id)
        if swipe_count < self.settings.swipe_ranker_min_swipes:
            logger.info(
                "swipe_ranker user=%s used=false reason=below_min_swipes "
                "swipes=%d min=%d candidates=%d top_n=%d",
                user_id,
                swipe_count,
                self.settings.swipe_ranker_min_swipes,
                candidate_count,
                top_n,
            )
            return None
        swipes = self.repository.list_user_swipes(user_id)
        user_vector = compute_user_vector(swipes)
        if user_vector is None:
            logger.info(
                "swipe_ranker user=%s used=false reason=no_user_vector "
                "swipes=%d candidates=%d top_n=%d",
                user_id,
                swipe_count,
                candidate_count,
                top_n,
            )
            return None
        records = self.repository.get_source_items([item.dedupe_key for item in items])
        embedding_by_key = {record.dedupe_key: record.embedding for record in records}
        bias_value = self.settings.inbound_ranker_bias
        boosted = boosted_dedupe_keys or set()
        bias_lookup = (
            (lambda key: bias_value if key in boosted else 0.0)
            if boosted and bias_value
            else None
        )
        ranked = rank_items(
            items, user_vector, embedding_by_key.get, top_n, bias_lookup=bias_lookup
        )
        embeddings_resolved = sum(
            1 for item in items if embedding_by_key.get(item.dedupe_key)
        )
        logger.info(
            "swipe_ranker user=%s used=true swipes=%d candidates=%d "
            "embeddings_resolved=%d boosted=%d bias=%.3f top_n=%d returned=%d",
            user_id,
            swipe_count,
            candidate_count,
            embeddings_resolved,
            len(boosted),
            bias_value,
            top_n,
            len(ranked),
        )
        return ranked

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
        "card_summary": record.card_summary,
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


def _normalize_app_account_token(token: Optional[str]) -> Optional[str]:
    """Map Apple's `appAccountToken` (formatted UUID with hyphens) back
    to the 32-char hex form we store on `UserRecord.id`. The iOS
    `PurchaseManager.uuidFromHex` formats user ids into the hyphenated
    UUID Apple expects; this is the inverse."""
    if not token:
        return None
    raw = token.replace("-", "").strip().lower()
    if len(raw) != 32 or any(c not in "0123456789abcdef" for c in raw):
        return token.strip()
    return raw
