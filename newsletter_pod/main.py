from __future__ import annotations

import hashlib
import logging
import re
import secrets
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from email.utils import format_datetime, parsedate_to_datetime
from pathlib import Path
from typing import Optional

from fastapi import (
    BackgroundTasks,
    FastAPI,
    File,
    Form,
    Header,
    HTTPException,
    Request,
    Response,
    UploadFile,
    status,
)
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .auth import (
    AppleIdentityVerifier,
    AuthError,
    FirebaseIdentityVerifier,
    SessionManager,
)
from .broadcast.feedback import OpenAIFeedbackSummarizer, format_replies_as_feedback_text
from .broadcast.models import BroadcastEpisodeRecord, BroadcastLoopRecord
from .broadcast.prompting import BroadcastBrief
from .broadcast.publisher import BroadcastPublisher, DEFAULT_FEEDBACK_PROMPT
from .broadcast.repository import (
    BroadcastRepository,
    EPISODE_ID_RE,
    FirestoreBroadcastRepository,
    InMemoryBroadcastRepository,
    validate_loop_id,
)
from .broadcast.runner import (
    LoopInactive,
    LoopNotFound,
    ScheduledBroadcastRunner,
)
from .broadcast.service import BroadcastService, BroadcastSettings
from .broadcast.topic_picker import BroadcastTopicPicker, OpenAITopicProposer
from .broadcast.video import FfmpegFailed, FfmpegUnavailable
from .broadcast.x_client import (
    XClient,
    XClientUnavailable,
    XPostFailed,
    XReadFailed,
)
from .config import Settings, load_voices
from .admin_metrics import (
    AdminMetricsService,
    is_admin,
    render_summary_html,
    render_user_not_found_html,
    render_user_timeline_html,
)
from .analytics_export import BigQueryTableWriter, run_export
from .churn_risk import ChurnRiskScoringService
from .cohort_report import CohortReportService
from .control_plane import ControlPlaneError, ControlPlaneService, build_task_enqueuer
from .embeddings import EmbeddingProvider, OpenAIEmbeddingProvider
from .events import (
    EventName,
    bucket_play_position_seconds,
    is_bot_user_agent,
    log_event,
    normalize_platform,
    platform_from_user_agent,
    reset_current_platform,
    set_current_platform,
)
from .feed import build_feed_xml
from .inbound import (
    InboundConfigError,
    InboundEmailHandler,
    InboundSignatureError,
)
from .legal import PRIVACY_HTML, TERMS_HTML
from .mailer import NoopMailer, SMTPMailer
from .models import PublishStatus, SourceItem
from .podcast_api import PodcastApiClient, PodcastApiUnavailable
from .push import (
    FcmSender,
    PushSender,
    build_fcm_sender_from_settings,
    build_push_sender_from_settings,
    send_pod_ready_push,
    send_trial_gift_push,
)
from .shared_items import MAX_UPLOAD_BYTES as SHARED_MAX_UPLOAD_BYTES, SUPPORTED_KINDS as SHARED_SUPPORTED_KINDS
from .storage import AudioStorage, GCSAudioStorage, InMemoryAudioStorage
from .user_models import DeviceTokenRecord
from .user_repository import ControlPlaneRepository, FirestoreControlPlaneRepository, InMemoryControlPlaneRepository
from .utils import utc_now

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


_BROADCAST_EPISODE_ID_RE = re.compile(r"^[0-9a-f]{16}$")


class AppleAuthRequest(BaseModel):
    identity_token: str
    given_name: Optional[str] = None


class FirebaseAuthRequest(BaseModel):
    id_token: str
    given_name: Optional[str] = None


class UpdateMeRequest(BaseModel):
    display_name: Optional[str] = None
    timezone: Optional[str] = None


class AcquisitionSourceRequest(BaseModel):
    # One of control_plane.ACQUISITION_SOURCES or "skipped"; validated there.
    source: str
    # Free text for the "other" choice; ignored for every other source.
    detail: Optional[str] = None


class ValidateSourceRequest(BaseModel):
    rss_url: str


class RedeemPromoCodeRequest(BaseModel):
    code: str


class ReplaceSourcesRequest(BaseModel):
    sources: list[dict]


class UpdatePodcastConfigRequest(BaseModel):
    title: Optional[str] = None
    format_preset: Optional[str] = None
    host_primary_name: Optional[str] = None
    host_secondary_name: Optional[str] = None
    guest_names: Optional[list[str]] = None
    desired_duration_minutes: Optional[int] = None
    voice_id: Optional[str] = None
    secondary_voice_id: Optional[str] = None
    tone: Optional[str] = None
    key_findings_count: Optional[int] = None
    humor_style: Optional[str] = None
    personalized_greeting: Optional[bool] = None
    include_top_takeaways: Optional[bool] = None
    include_weather: Optional[bool] = None
    weather_location: Optional[str] = None
    weather_lat: Optional[float] = None
    weather_lon: Optional[float] = None
    weather_country_code: Optional[str] = None
    custom_guidance: Optional[str] = None
    custom_guidance_preset_id: Optional[str] = None


class UpdateScheduleRequest(BaseModel):
    timezone: Optional[str] = None
    weekdays: Optional[list[str]] = None
    local_time: Optional[str] = None


class BillingNotificationRequest(BaseModel):
    # Apple's V2 server-notification body is `{"signedPayload": "<JWS>"}`.
    # Allow snake_case as an internal alias since other internal posters
    # historically used it; legacy unsigned fields below are retained for
    # the in-test path until APP_STORE_NOTIFICATIONS_REQUIRE_SIGNED flips on.
    signedPayload: Optional[str] = None
    signed_payload: Optional[str] = None
    notification_type: Optional[str] = None
    notificationType: Optional[str] = None
    subtype: Optional[str] = None
    user_id: Optional[str] = None
    app_account_token: Optional[str] = None
    product_id: Optional[str] = None
    productId: Optional[str] = None
    status: Optional[str] = None
    expires_at: Optional[str] = None


class VerifyTransactionRequest(BaseModel):
    # StoreKit2 `Transaction.jwsRepresentation`. The iOS client posts this
    # directly after `transaction.finish()` so the backend doesn't depend
    # on Apple's ASN webhook (which is unreliable in sandbox/TestFlight).
    signed_transaction_info: Optional[str] = None
    signedTransactionInfo: Optional[str] = None


class ProcessUserRequest(BaseModel):
    user_id: str
    force: bool = False


class SubmitFeedbackRequest(BaseModel):
    text: str
    locale_hint: Optional[str] = None
    source: Optional[str] = None


class SubmitSwipeRequest(BaseModel):
    source_item_dedupe_key: str
    direction: int


class NextEpisodeOverrideRequest(BaseModel):
    """Body for POST /v1/me/next-episode/pin and /exclude. The dedupe_key
    is the SourceItemRecord.dedupe_key from the candidates payload."""

    source_item_dedupe_key: str


class PlayPulseRequest(BaseModel):
    position_seconds: int


class CreateSubstackIntentRequest(BaseModel):
    pub_url: str


class SubmitVoiceIntakeRequest(BaseModel):
    transcript: str


class DiscoverSubstacksRequest(BaseModel):
    query: str


class RegisterDeviceTokenRequest(BaseModel):
    token: str
    environment: Optional[str] = "production"
    bundle_id: Optional[str] = None
    platform: Optional[str] = "ios"  # "ios" | "android"
    # Push service the token belongs to. None → derived from platform
    # (android→fcm, ios→apns). The Flutter app sends "fcm" on both platforms.
    transport: Optional[str] = None  # "apns" | "fcm" | None


class BroadcastGenerateOnceRequest(BaseModel):
    topic: str
    title: Optional[str] = None
    audience_hint: Optional[str] = None
    prior_feedback_summary: Optional[str] = None
    desired_minutes: int = 5


class BroadcastPublishRequest(BaseModel):
    episode_id: str
    tweet_text: str
    # Set to empty string to suppress the follow-up feedback prompt reply.
    # Omit to use the bundled default copy.
    feedback_prompt_text: Optional[str] = None


class BroadcastGenerateAndPublishRequest(BaseModel):
    topic: str
    tweet_text: str
    title: Optional[str] = None
    audience_hint: Optional[str] = None
    prior_feedback_summary: Optional[str] = None
    desired_minutes: int = 5
    feedback_prompt_text: Optional[str] = None


class BroadcastLoopUpsertRequest(BaseModel):
    loop_id: str
    region: str
    timezone: str
    audience_persona: str
    post_local_time: str = "08:00"
    seed_topics: list[str] = []
    active: bool = True
    feedback_prompt_text: Optional[str] = None
    source_ids: list[str] = []
    # Optional per-loop target length in minutes; None falls back to the default
    # ~1-min short clip (see BroadcastLoopRecord.desired_minutes).
    desired_minutes: Optional[int] = None


class BroadcastScheduledRunRequest(BaseModel):
    loop_id: str
    tweet_text_override: Optional[str] = None
    feedback_prompt_override: Optional[str] = None


class BroadcastPasteFeedbackRequest(BaseModel):
    feedback_text: str


@dataclass
class ServiceContainer:
    settings: Settings
    storage: AudioStorage
    control_repository: ControlPlaneRepository | None = None
    control_plane: ControlPlaneService | None = None
    # APNs push sender; None when APNs is disabled or unconfigured. Lazily
    # built once per process so the JWT cache + HTTP/2 client are reused
    # across every push attempt.
    push_sender: PushSender | None = None
    # FCM sender (Android). Built once so the OAuth token + HTTP client are
    # reused; None when FCM isn't configured.
    fcm_sender: FcmSender | None = None
    # Shared OpenAI/ElevenLabs client. Reused by both the per-user generation
    # path (via control_plane) and the broadcast loop, so we configure it
    # once and pass the same instance to both.
    podcast_client: PodcastApiClient | None = None
    # X (Twitter) client for the broadcast-loop poster. Always non-None
    # once the container is built; calling .post_*() with missing creds
    # raises XClientUnavailable, surfaced as 503 by the endpoint.
    x_client: XClient | None = None
    # Phase 2 broadcast-loop persistence. In-memory in dev, Firestore in
    # prod — paralleling AudioStorage.
    broadcast_repository: BroadcastRepository | None = None


def create_app(container: ServiceContainer | None = None) -> FastAPI:
    if container is None:
        settings = Settings.from_env()
        container = _build_container(settings)
    if container.control_plane is None or container.control_repository is None:
        control_repository, control_plane = _build_control_plane(container.settings, container.storage)
        container.control_repository = control_repository
        container.control_plane = control_plane

    app = FastAPI(title="Newsletter Pod", version="0.1.0")
    app.state.container = container

    @app.middleware("http")
    async def _tag_client_platform(request: Request, call_next):
        """Stamp every event emitted during this request with the calling
        client's platform (iOS / Android / web) from the X-Client-Platform
        header, so analytics can slice any metric by stack. Starlette copies
        the context into the threadpool, so the value reaches sync routes too.
        """
        token = set_current_platform(request.headers.get("x-client-platform"))
        try:
            return await call_next(request)
        finally:
            reset_current_platform(token)

    static_dir = Path(__file__).resolve().parent / "static"
    if static_dir.is_dir():
        app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/legal/terms", response_class=Response)
    def legal_terms() -> Response:
        return Response(content=TERMS_HTML, media_type="text/html; charset=utf-8")

    @app.get("/legal/privacy", response_class=Response)
    def legal_privacy() -> Response:
        return Response(content=PRIVACY_HTML, media_type="text/html; charset=utf-8")

    @app.post("/jobs/dispatch-due-users")
    def dispatch_due_users(
        authorization: str | None = Header(default=None),
        x_job_trigger_token: str | None = Header(default=None),
    ) -> dict:
        _validate_job_auth(container.settings, authorization, x_job_trigger_token)
        assert container.control_plane is not None
        return container.control_plane.dispatch_due_users()

    @app.post("/jobs/process-user-podcast")
    def process_user_podcast(
        request_payload: ProcessUserRequest,
        authorization: str | None = Header(default=None),
        x_job_trigger_token: str | None = Header(default=None),
    ) -> dict:
        _validate_job_auth(container.settings, authorization, x_job_trigger_token)
        assert container.control_plane is not None
        result = container.control_plane.process_user_generation_job(
            user_id=request_payload.user_id,
            force=request_payload.force,
        )
        # Best-effort "your pod is ready" push when a new episode actually
        # published. Failures must never fail the generation job (the episode
        # is already saved and will appear in the user's feed regardless).
        run = result.get("run") or {}
        episode = result.get("episode") or {}
        if run.get("status") == PublishStatus.PUBLISHED.value and episode.get("id"):
            try:
                send_pod_ready_push(
                    sender=container.push_sender,
                    fcm_sender=container.fcm_sender,
                    repository=container.control_repository,
                    user_id=request_payload.user_id,
                    episode_title=episode.get("title") or "Your latest briefing is ready.",
                    episode_id=episode.get("id"),
                    feed_url=result.get("feed_url"),
                )
            except Exception:  # pragma: no cover — push is non-critical
                logger.warning(
                    "Pod-ready push failed: user=%s episode=%s",
                    request_payload.user_id,
                    episode.get("id"),
                    exc_info=True,
                )
        return result

    @app.post("/jobs/send-feedback-digest")
    def send_feedback_digest(
        authorization: str | None = Header(default=None),
        x_job_trigger_token: str | None = Header(default=None),
    ) -> dict:
        _validate_job_auth(container.settings, authorization, x_job_trigger_token)
        assert container.control_plane is not None
        try:
            return container.control_plane.send_feedback_weekly_digest()
        except ControlPlaneError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
            )

    @app.post("/jobs/refresh-cold-start-deck")
    def refresh_cold_start_deck(
        authorization: str | None = Header(default=None),
        x_job_trigger_token: str | None = Header(default=None),
    ) -> dict:
        _validate_job_auth(container.settings, authorization, x_job_trigger_token)
        assert container.control_plane is not None
        return container.control_plane.refresh_cold_start_deck()

    @app.post("/jobs/export-analytics-snapshot")
    def export_analytics_snapshot(
        authorization: str | None = Header(default=None),
        x_job_trigger_token: str | None = Header(default=None),
    ) -> dict:
        """Daily snapshot of Firestore subscriptions + device tokens into
        BigQuery (analytics.subscriptions_export / device_tokens_export), which
        back the tier/churn views and the per-user platform join. No-op unless
        ANALYTICS_EXPORT_ENABLED — so it's safe to schedule before BigQuery
        IAM/config is in place, and never touches BigQuery in tests."""
        _validate_job_auth(container.settings, authorization, x_job_trigger_token)
        if not container.settings.analytics_export_enabled:
            return {"skipped": "analytics_export_disabled"}
        assert container.control_repository is not None
        writer = BigQueryTableWriter(container.settings)
        return {"exported": run_export(container.control_repository, writer)}

    @app.post("/jobs/score-churn-risk")
    def score_churn_risk(
        authorization: str | None = Header(default=None),
        x_job_trigger_token: str | None = Header(default=None),
    ) -> dict:
        """Phase 3 daily job. Scores every active paid user against the
        churn-risk heuristic in newsletter_pod/churn_risk.py and persists
        the latest snapshot per user. Idempotent: re-running on the same
        data overwrites (it doesn't append) and produces a deterministic
        score."""
        _validate_job_auth(container.settings, authorization, x_job_trigger_token)
        assert container.control_repository is not None
        service = ChurnRiskScoringService(
            repository=container.control_repository,
            settings=container.settings,
        )
        return service.score_all_active_paid_users()

    @app.post("/jobs/weekly-cohort-report")
    def weekly_cohort_report(
        authorization: str | None = Header(default=None),
        x_job_trigger_token: str | None = Header(default=None),
    ) -> dict:
        """Phase 3 Monday job. Emails last week's signup cohort
        activation + paid-conversion stats and the global top-3
        churn-risk users to the operator. Short-circuits when
        COHORT_REPORT_EMAIL_ENABLED is False so the job can be paused
        from the Cloud Run env without touching the scheduler."""
        _validate_job_auth(container.settings, authorization, x_job_trigger_token)
        assert container.control_repository is not None
        assert container.control_plane is not None
        service = CohortReportService(
            repository=container.control_repository,
            mailer=container.control_plane.mailer,
            settings=container.settings,
        )
        return service.send_weekly_cohort_report()

    @app.post("/jobs/poll-sources")
    def poll_sources(
        authorization: str | None = Header(default=None),
        x_job_trigger_token: str | None = Header(default=None),
    ) -> dict:
        """Hourly Cloud Scheduler target. Walks every distinct attached
        source once, ingests new items into the `source_items` corpus.
        No-op when CANDIDATE_QUEUE_ENABLED is off."""
        _validate_job_auth(container.settings, authorization, x_job_trigger_token)
        assert container.control_plane is not None
        return container.control_plane.poll_sources()

    @app.post("/jobs/reap-stale-runs")
    def reap_stale_runs(
        authorization: str | None = Header(default=None),
        x_job_trigger_token: str | None = Header(default=None),
    ) -> dict:
        """Frequent Cloud Scheduler target. Marks user podcast runs stuck
        `in_progress` past STALE_RUN_TIMEOUT_MINUTES as failed — they were
        orphaned when the in-process generation task's instance was
        recycled/OOM-killed/timed out before it could finalize the run. Clears
        the wedge so the user's next "Generate" works and the client poll
        terminates. Idempotent; returns {status, reaped, run_ids}."""
        _validate_job_auth(container.settings, authorization, x_job_trigger_token)
        assert container.control_plane is not None
        return container.control_plane.reap_stale_runs()

    @app.post("/jobs/broadcast/generate-once")
    def broadcast_generate_once(
        request_payload: BroadcastGenerateOnceRequest,
        authorization: str | None = Header(default=None),
        x_job_trigger_token: str | None = Header(default=None),
    ) -> dict:
        """Phase 0 broadcast loop entrypoint: take a hand-written topic
        brief, return a postable audio + waveform-video pair stored under
        `broadcast/<episode_id>.{mp3,mp4}` on the same bucket as user
        episodes. Stateless — no Firestore writes. Callers are responsible
        for remembering the episode_id if they want to find the assets
        again outside of GCS object listing."""
        _validate_job_auth(container.settings, authorization, x_job_trigger_token)
        if container.podcast_client is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Podcast client not initialized",
            )
        topic = (request_payload.topic or "").strip()
        if not topic:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="topic is required",
            )

        broadcast_settings = BroadcastSettings(
            app_base_url=container.settings.app_base_url,
            primary_voice_id=container.settings.elevenlabs_voice_primary_id,
            secondary_voice_id=container.settings.elevenlabs_voice_secondary_id,
            primary_host_name=container.settings.podcast_host_primary_name,
            secondary_host_name=container.settings.podcast_host_secondary_name,
            cover_image_path=static_dir / "cover.png",
        )
        service = BroadcastService(
            settings=broadcast_settings,
            storage=container.storage,
            podcast_client=container.podcast_client,
        )
        brief = BroadcastBrief(
            topic=topic,
            audience_hint=(request_payload.audience_hint or None),
            prior_feedback_summary=(request_payload.prior_feedback_summary or None),
            desired_minutes=request_payload.desired_minutes,
        )
        title = (request_payload.title or "").strip() or f"ClawCast Broadcast: {topic[:60]}"
        try:
            result = service.generate_once(
                brief=brief,
                title=title,
                ux=container.settings.podcast_ux_config(),
            )
        except PodcastApiUnavailable as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
            )
        except FfmpegUnavailable as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
            )
        except FfmpegFailed as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)
            )

        return {
            "episode_id": result.episode_id,
            "title": result.title,
            "show_notes": result.show_notes,
            "audio_url": result.audio_url,
            "audio_size_bytes": result.audio_size_bytes,
            "video_url": result.video_url,
            "video_size_bytes": result.video_size_bytes,
            "duration_seconds": result.duration_seconds,
        }

    @app.post("/jobs/broadcast/publish")
    def broadcast_publish(
        request_payload: BroadcastPublishRequest,
        authorization: str | None = Header(default=None),
        x_job_trigger_token: str | None = Header(default=None),
    ) -> dict:
        """Post a previously-generated broadcast episode to X. Reads the
        MP4 from `broadcast/<episode_id>.mp4` in storage and posts it as
        a tweet, then attaches a feedback-prompt reply (suppress by
        sending `feedback_prompt_text: ""`)."""
        _validate_job_auth(container.settings, authorization, x_job_trigger_token)
        if container.x_client is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="X client not initialized",
            )
        episode_id = (request_payload.episode_id or "").strip().lower()
        if not _BROADCAST_EPISODE_ID_RE.fullmatch(episode_id):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="episode_id must be 16 hex characters",
            )
        tweet_text = (request_payload.tweet_text or "").strip()
        if not tweet_text:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="tweet_text is required",
            )
        feedback_prompt = _resolve_feedback_prompt(request_payload.feedback_prompt_text)

        publisher = BroadcastPublisher(storage=container.storage, x_client=container.x_client)
        try:
            post = publisher.publish(
                episode_id=episode_id,
                tweet_text=tweet_text,
                feedback_prompt_text=feedback_prompt,
            )
        except FileNotFoundError:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No broadcast video found for episode_id={episode_id}",
            )
        except XClientUnavailable as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
            )
        except XPostFailed as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)
            )

        return {
            "episode_id": episode_id,
            "episode_tweet_id": post.episode_tweet_id,
            "episode_tweet_url": post.episode_tweet_url,
            "feedback_prompt_tweet_id": post.feedback_prompt_tweet_id,
            "feedback_prompt_tweet_url": post.feedback_prompt_tweet_url,
        }

    @app.post("/jobs/broadcast/generate-and-publish")
    def broadcast_generate_and_publish(
        request_payload: BroadcastGenerateAndPublishRequest,
        authorization: str | None = Header(default=None),
        x_job_trigger_token: str | None = Header(default=None),
    ) -> dict:
        """Phase 1 happy path: generate an episode from a topic brief
        and immediately post it to X with the supplied tweet text.
        Equivalent to /jobs/broadcast/generate-once followed by
        /jobs/broadcast/publish; the only state shared between the two
        steps is the GCS object the generate step writes."""
        _validate_job_auth(container.settings, authorization, x_job_trigger_token)
        if container.podcast_client is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Podcast client not initialized",
            )
        if container.x_client is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="X client not initialized",
            )
        topic = (request_payload.topic or "").strip()
        if not topic:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="topic is required",
            )
        tweet_text = (request_payload.tweet_text or "").strip()
        if not tweet_text:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="tweet_text is required",
            )
        feedback_prompt = _resolve_feedback_prompt(request_payload.feedback_prompt_text)

        broadcast_settings = BroadcastSettings(
            app_base_url=container.settings.app_base_url,
            primary_voice_id=container.settings.elevenlabs_voice_primary_id,
            secondary_voice_id=container.settings.elevenlabs_voice_secondary_id,
            primary_host_name=container.settings.podcast_host_primary_name,
            secondary_host_name=container.settings.podcast_host_secondary_name,
            cover_image_path=static_dir / "cover.png",
        )
        service = BroadcastService(
            settings=broadcast_settings,
            storage=container.storage,
            podcast_client=container.podcast_client,
        )
        publisher = BroadcastPublisher(storage=container.storage, x_client=container.x_client)
        brief = BroadcastBrief(
            topic=topic,
            audience_hint=(request_payload.audience_hint or None),
            prior_feedback_summary=(request_payload.prior_feedback_summary or None),
            desired_minutes=request_payload.desired_minutes,
        )
        title = (request_payload.title or "").strip() or f"ClawCast Broadcast: {topic[:60]}"
        try:
            generated = service.generate_once(
                brief=brief,
                title=title,
                ux=container.settings.podcast_ux_config(),
            )
        except PodcastApiUnavailable as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
            )
        except FfmpegUnavailable as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
            )
        except FfmpegFailed as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)
            )

        try:
            post = publisher.publish(
                episode_id=generated.episode_id,
                tweet_text=tweet_text,
                feedback_prompt_text=feedback_prompt,
            )
        except XClientUnavailable as exc:
            # Episode is already in GCS; surface it in the error so the
            # operator can hit /jobs/broadcast/publish manually instead
            # of losing the generated artifact.
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={
                    "error": str(exc),
                    "episode_id": generated.episode_id,
                    "video_url": generated.video_url,
                },
            )
        except XPostFailed as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail={
                    "error": str(exc),
                    "episode_id": generated.episode_id,
                    "video_url": generated.video_url,
                },
            )

        return {
            "episode_id": generated.episode_id,
            "title": generated.title,
            "show_notes": generated.show_notes,
            "video_url": generated.video_url,
            "audio_url": generated.audio_url,
            "episode_tweet_id": post.episode_tweet_id,
            "episode_tweet_url": post.episode_tweet_url,
            "feedback_prompt_tweet_id": post.feedback_prompt_tweet_id,
            "feedback_prompt_tweet_url": post.feedback_prompt_tweet_url,
        }

    @app.post("/jobs/broadcast/loops")
    def broadcast_loops_upsert(
        request_payload: BroadcastLoopUpsertRequest,
        authorization: str | None = Header(default=None),
        x_job_trigger_token: str | None = Header(default=None),
    ) -> dict:
        """Create or update one loop. Idempotent on loop_id — same id
        overwrites the existing row, so this is also the edit endpoint."""
        _validate_job_auth(container.settings, authorization, x_job_trigger_token)
        assert container.broadcast_repository is not None
        try:
            loop_id = validate_loop_id(request_payload.loop_id)
        except ValueError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
            )
        existing = container.broadcast_repository.get_loop(loop_id)
        now = utc_now()
        # Dedupe + trim the source_ids list while preserving submission
        # order so the operator's intended priority survives the round-trip.
        seen_source_ids: set[str] = set()
        deduped_source_ids: list[str] = []
        for raw in request_payload.source_ids:
            cleaned = (raw or "").strip()
            if not cleaned or cleaned in seen_source_ids:
                continue
            seen_source_ids.add(cleaned)
            deduped_source_ids.append(cleaned)
        loop = BroadcastLoopRecord(
            loop_id=loop_id,
            region=request_payload.region.strip(),
            timezone=request_payload.timezone.strip(),
            audience_persona=request_payload.audience_persona.strip(),
            post_local_time=request_payload.post_local_time.strip(),
            seed_topics=[t.strip() for t in request_payload.seed_topics if t.strip()],
            active=request_payload.active,
            feedback_prompt_text=request_payload.feedback_prompt_text,
            source_ids=deduped_source_ids,
            desired_minutes=request_payload.desired_minutes,
            created_at=(existing.created_at if existing else now),
            updated_at=now,
        )
        container.broadcast_repository.save_loop(loop)
        return loop.model_dump(mode="json")

    @app.get("/jobs/broadcast/loops")
    def broadcast_loops_list(
        active_only: bool = False,
        authorization: str | None = Header(default=None),
        x_job_trigger_token: str | None = Header(default=None),
    ) -> dict:
        _validate_job_auth(container.settings, authorization, x_job_trigger_token)
        assert container.broadcast_repository is not None
        loops = container.broadcast_repository.list_loops(active_only=active_only)
        return {"loops": [l.model_dump(mode="json") for l in loops]}

    @app.get("/jobs/broadcast/loops/{loop_id}")
    def broadcast_loop_get(
        loop_id: str,
        authorization: str | None = Header(default=None),
        x_job_trigger_token: str | None = Header(default=None),
    ) -> dict:
        _validate_job_auth(container.settings, authorization, x_job_trigger_token)
        assert container.broadcast_repository is not None
        loop = container.broadcast_repository.get_loop(loop_id)
        if loop is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND, detail="Loop not found"
            )
        return loop.model_dump(mode="json")

    @app.delete("/jobs/broadcast/loops/{loop_id}")
    def broadcast_loop_delete(
        loop_id: str,
        authorization: str | None = Header(default=None),
        x_job_trigger_token: str | None = Header(default=None),
    ) -> dict:
        _validate_job_auth(container.settings, authorization, x_job_trigger_token)
        assert container.broadcast_repository is not None
        deleted = container.broadcast_repository.delete_loop(loop_id)
        return {"loop_id": loop_id, "deleted": deleted}

    @app.get("/jobs/broadcast/loops/{loop_id}/episodes")
    def broadcast_loop_episodes(
        loop_id: str,
        limit: int = 20,
        authorization: str | None = Header(default=None),
        x_job_trigger_token: str | None = Header(default=None),
    ) -> dict:
        _validate_job_auth(container.settings, authorization, x_job_trigger_token)
        assert container.broadcast_repository is not None
        episodes = container.broadcast_repository.list_episodes_for_loop(loop_id, limit=max(1, min(limit, 200)))
        return {
            "loop_id": loop_id,
            "episodes": [e.model_dump(mode="json") for e in episodes],
        }

    @app.post("/jobs/broadcast/loops/{loop_id}/run")
    def broadcast_loop_run(
        loop_id: str,
        request_payload: Optional[BroadcastScheduledRunRequest] = None,
        authorization: str | None = Header(default=None),
        x_job_trigger_token: str | None = Header(default=None),
    ) -> dict:
        """Scheduled run for one loop. Cloud Scheduler hits this on the
        loop's daily cadence. Picks a topic from prior feedback + seed
        topics, generates the episode, posts it to X, and persists the
        episode row so tomorrow's run has signal to read."""
        _validate_job_auth(container.settings, authorization, x_job_trigger_token)
        if container.podcast_client is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="Podcast client not initialized",
            )
        if container.x_client is None:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="X client not initialized",
            )
        assert container.broadcast_repository is not None

        runner = _build_scheduled_runner(container, static_dir)
        try:
            result = runner.run(
                loop_id,
                tweet_text_override=(request_payload.tweet_text_override if request_payload else None),
                feedback_prompt_override=(
                    request_payload.feedback_prompt_override if request_payload else None
                ),
            )
        except LoopNotFound as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
        except LoopInactive as exc:
            # 200 with a skipped marker: Cloud Scheduler retries on non-2xx,
            # and an inactive loop is intentional state, not a failure.
            logger.info("Scheduled run skipped: %s", exc)
            return {"loop_id": loop_id, "status": "skipped", "reason": str(exc)}
        except PodcastApiUnavailable as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
            )
        except FfmpegUnavailable as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
            )
        except FfmpegFailed as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)
            )
        except XClientUnavailable as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
            )
        except XPostFailed as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)
            )

        return {
            "loop_id": result.loop_id,
            "episode_id": result.episode_id,
            "topic": result.topic,
            "run_date": result.run_date.isoformat(),
            "audio_url": result.audio_url,
            "video_url": result.video_url,
            "episode_tweet_id": result.episode_tweet_id,
            "episode_tweet_url": result.episode_tweet_url,
            "feedback_prompt_tweet_id": result.feedback_prompt_tweet_id,
            "feedback_prompt_tweet_url": result.feedback_prompt_tweet_url,
        }

    @app.post("/jobs/broadcast/episodes/{episode_id}/feedback")
    def broadcast_episode_paste_feedback(
        episode_id: str,
        request_payload: BroadcastPasteFeedbackRequest,
        authorization: str | None = Header(default=None),
        x_job_trigger_token: str | None = Header(default=None),
    ) -> dict:
        """Operator-pasted feedback. Kept alongside the auto-poll path
        (POST .../poll-replies) as the manual fallback — when the X read
        endpoint is rate-limited, out of credits, or the operator wants
        to hand-edit the raw text before summarization."""
        _validate_job_auth(container.settings, authorization, x_job_trigger_token)
        assert container.broadcast_repository is not None

        episode_id = (episode_id or "").strip().lower()
        if not EPISODE_ID_RE.fullmatch(episode_id):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="episode_id must be 16 hex characters",
            )
        episode = container.broadcast_repository.get_episode(episode_id)
        if episode is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No broadcast episode with id={episode_id!r}",
            )

        feedback_text = (request_payload.feedback_text or "").strip()
        if not feedback_text:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="feedback_text is required",
            )

        summarizer = _build_feedback_summarizer(container.settings)
        summary = None
        if summarizer is not None:
            summary = summarizer.summarize(
                replies_text=feedback_text, topic=episode.topic_used
            )

        updated = episode.model_copy(update={
            "feedback_raw": feedback_text,
            "feedback_summary": summary,
            "feedback_pasted_at": utc_now(),
        })
        container.broadcast_repository.save_episode(updated)
        return {
            "episode_id": episode_id,
            "feedback_summary": summary,
            "feedback_summary_status": (
                "summarized" if summary
                else ("summarizer_unavailable" if summarizer is None else "no_useful_content")
            ),
        }

    @app.post("/jobs/broadcast/episodes/{episode_id}/poll-replies")
    def broadcast_episode_poll_replies(
        episode_id: str,
        authorization: str | None = Header(default=None),
        x_job_trigger_token: str | None = Header(default=None),
    ) -> dict:
        """Automated counterpart to the paste-feedback path: hit X's
        /2/tweets/search/recent for replies in the episode tweet's
        conversation, join them into the same multi-line shape the
        summarizer expects, and persist feedback_raw / feedback_summary
        / feedback_pasted_at exactly like a manual paste. Intended to be
        called by Cloud Scheduler shortly before the next loop run, so
        tomorrow's topic-picker reads a fresh signal."""
        _validate_job_auth(container.settings, authorization, x_job_trigger_token)
        assert container.broadcast_repository is not None
        assert container.x_client is not None

        episode_id = (episode_id or "").strip().lower()
        if not EPISODE_ID_RE.fullmatch(episode_id):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="episode_id must be 16 hex characters",
            )
        episode = container.broadcast_repository.get_episode(episode_id)
        if episode is None:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"No broadcast episode with id={episode_id!r}",
            )
        if not episode.episode_tweet_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Episode has no episode_tweet_id — nothing to poll replies against",
            )

        try:
            replies = container.x_client.fetch_conversation_replies(
                conversation_id=episode.episode_tweet_id,
            )
        except XClientUnavailable as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail=str(exc),
            )
        except XReadFailed as exc:
            raise HTTPException(
                status_code=status.HTTP_502_BAD_GATEWAY,
                detail=f"X reply search failed: {exc}",
            )

        if not replies:
            return {
                "episode_id": episode_id,
                "replies_count": 0,
                "feedback_summary": episode.feedback_summary,
                "feedback_summary_status": "no_replies",
            }

        feedback_text = format_replies_as_feedback_text(replies)
        summarizer = _build_feedback_summarizer(container.settings)
        summary = None
        if summarizer is not None:
            summary = summarizer.summarize(
                replies_text=feedback_text, topic=episode.topic_used
            )

        updated = episode.model_copy(update={
            "feedback_raw": feedback_text,
            "feedback_summary": summary,
            "feedback_pasted_at": utc_now(),
        })
        container.broadcast_repository.save_episode(updated)
        return {
            "episode_id": episode_id,
            "replies_count": len(replies),
            "feedback_summary": summary,
            "feedback_summary_status": (
                "summarized" if summary
                else ("summarizer_unavailable" if summarizer is None else "no_useful_content")
            ),
        }

    @app.post("/v1/auth/apple")
    def auth_with_apple(request_payload: AppleAuthRequest) -> dict:
        assert container.control_plane is not None
        try:
            return container.control_plane.authenticate_with_apple(
                request_payload.identity_token,
                given_name=request_payload.given_name,
            )
        except (ControlPlaneError, AuthError) as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    @app.post("/v1/auth/firebase")
    def auth_with_firebase(request_payload: FirebaseAuthRequest) -> dict:
        assert container.control_plane is not None
        try:
            return container.control_plane.authenticate_with_firebase(
                request_payload.id_token,
                given_name=request_payload.given_name,
            )
        except (ControlPlaneError, AuthError) as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    @app.get("/v1/me")
    def get_me(authorization: str | None = Header(default=None)) -> dict:
        user = _require_session_user(container, authorization)
        assert container.control_plane is not None
        return container.control_plane.get_me(user.id)

    @app.patch("/v1/me")
    def patch_me(
        request_payload: UpdateMeRequest,
        authorization: str | None = Header(default=None),
    ) -> dict:
        user = _require_session_user(container, authorization)
        assert container.control_plane is not None
        try:
            return container.control_plane.update_me(
                user.id,
                display_name=request_payload.display_name,
                timezone_name=request_payload.timezone,
            )
        except ControlPlaneError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    @app.delete("/v1/me")
    def delete_me(authorization: str | None = Header(default=None)) -> dict:
        """Delete the authenticated user's account and all associated data.
        Idempotent and irreversible. After this returns, the caller's
        session token will no longer authenticate any other endpoint."""
        user = _require_session_user(container, authorization)
        assert container.control_plane is not None
        return container.control_plane.delete_user_account(user.id)

    @app.post("/v1/me/reset")
    def reset_me(authorization: str | None = Header(default=None)) -> dict:
        """Wipe the caller's onboarding state so the iOS wizard re-runs:
        deletes sources, schedule, podcast profile, swipes, substack intents,
        and per-source cursors. Keeps the account, feed token, subscription,
        and episode history. Idempotent."""
        user = _require_session_user(container, authorization)
        assert container.control_plane is not None
        try:
            return container.control_plane.reset_user_account(user.id)
        except ControlPlaneError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    @app.post("/v1/me/trial-gift/ack")
    def acknowledge_trial_gift(authorization: str | None = Header(default=None)) -> dict:
        """Dismiss the one-time "A gift from theclawcast" trial-reset card.
        Sets trial_gift_acknowledged_at (flipping trial_gift_pending False).
        Idempotent — re-acking is a no-op."""
        user = _require_session_user(container, authorization)
        assert container.control_plane is not None
        try:
            return container.control_plane.acknowledge_trial_gift(user.id)
        except ControlPlaneError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    @app.post("/v1/me/redeem")
    def redeem_promo_code(
        request_payload: RedeemPromoCodeRequest,
        authorization: str | None = Header(default=None),
    ) -> dict:
        """Redeem a promo code for the calling user. On success grants a window
        of full-access (Max) time by extending the trial; the app reloads
        /v1/me to surface it. Every failure (invalid / inactive / expired /
        exhausted / already-redeemed / already-subscribed) is a ControlPlaneError
        → HTTP 400 whose `detail` is a user-facing message the client shows."""
        user = _require_session_user(container, authorization)
        assert container.control_plane is not None
        try:
            return container.control_plane.redeem_promo_code(
                user.id, request_payload.code
            )
        except ControlPlaneError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    @app.post("/v1/me/acquisition-source")
    def post_acquisition_source(
        request_payload: AcquisitionSourceRequest,
        authorization: str | None = Header(default=None),
    ) -> dict:
        """Record the answer to "where did you find us?" (asked once, during the
        first-pod generation wait). Write-once and idempotent; returns the same
        payload as GET /v1/me so the client refreshes in place."""
        user = _require_session_user(container, authorization)
        assert container.control_plane is not None
        try:
            return container.control_plane.record_acquisition_source(
                user.id, request_payload.source, request_payload.detail
            )
        except ControlPlaneError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    @app.get("/v1/sources/catalog")
    def get_source_catalog() -> dict:
        assert container.control_plane is not None
        return {"sources": container.control_plane.get_source_catalog()}

    @app.get("/v1/voices/catalog")
    def get_voice_catalog() -> dict:
        assert container.control_plane is not None
        return {"voices": container.control_plane.get_voice_catalog()}

    @app.post("/v1/sources/validate")
    def validate_source(request_payload: ValidateSourceRequest, authorization: str | None = Header(default=None)) -> dict:
        _require_session_user(container, authorization)
        assert container.control_plane is not None
        try:
            return container.control_plane.validate_custom_source(request_payload.rss_url)
        except Exception as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    @app.get("/v1/me/sources")
    def get_user_sources(authorization: str | None = Header(default=None)) -> dict:
        user = _require_session_user(container, authorization)
        assert container.control_plane is not None
        return container.control_plane.list_user_sources(user.id)

    @app.put("/v1/me/sources")
    def put_user_sources(
        request_payload: ReplaceSourcesRequest,
        background_tasks: BackgroundTasks,
        authorization: str | None = Header(default=None),
    ) -> dict:
        user = _require_session_user(container, authorization)
        assert container.control_plane is not None
        try:
            result = container.control_plane.replace_user_sources(user.id, request_payload.sources)
        except Exception as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
        # Warm the swipe-deck corpus for the newly-attached sources after the
        # response is sent. Bootstrap cursor caps the cost; sources the user
        # already had won't re-fetch.
        background_tasks.add_task(_warm_corpus_safely, container, user.id)
        return result

    @app.get("/v1/me/podcast-config")
    def get_podcast_config(authorization: str | None = Header(default=None)) -> dict:
        user = _require_session_user(container, authorization)
        assert container.control_plane is not None
        return container.control_plane.get_podcast_config(user.id)

    @app.patch("/v1/me/podcast-config")
    def patch_podcast_config(
        request_payload: UpdatePodcastConfigRequest,
        authorization: str | None = Header(default=None),
    ) -> dict:
        user = _require_session_user(container, authorization)
        assert container.control_plane is not None
        try:
            return container.control_plane.update_podcast_config(
                user_id=user.id,
                title=request_payload.title,
                format_preset=request_payload.format_preset,
                host_primary_name=request_payload.host_primary_name,
                host_secondary_name=request_payload.host_secondary_name,
                guest_names=request_payload.guest_names,
                desired_duration_minutes=request_payload.desired_duration_minutes,
                voice_id=request_payload.voice_id,
                secondary_voice_id=request_payload.secondary_voice_id,
                tone=request_payload.tone,
                key_findings_count=request_payload.key_findings_count,
                humor_style=request_payload.humor_style,
                personalized_greeting=request_payload.personalized_greeting,
                include_top_takeaways=request_payload.include_top_takeaways,
                include_weather=request_payload.include_weather,
                weather_location=request_payload.weather_location,
                weather_lat=request_payload.weather_lat,
                weather_lon=request_payload.weather_lon,
                weather_country_code=request_payload.weather_country_code,
                custom_guidance=request_payload.custom_guidance,
                custom_guidance_preset_id=request_payload.custom_guidance_preset_id,
            )
        except ControlPlaneError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    @app.get("/v1/me/schedule")
    def get_schedule(authorization: str | None = Header(default=None)) -> dict:
        user = _require_session_user(container, authorization)
        assert container.control_plane is not None
        return container.control_plane.get_schedule_config(user.id)

    @app.patch("/v1/me/schedule")
    def patch_schedule(
        request_payload: UpdateScheduleRequest,
        authorization: str | None = Header(default=None),
    ) -> dict:
        user = _require_session_user(container, authorization)
        assert container.control_plane is not None
        try:
            return container.control_plane.update_schedule(
                user.id,
                timezone_name=request_payload.timezone,
                weekdays=request_payload.weekdays,
                local_time=request_payload.local_time,
            )
        except ControlPlaneError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    @app.get("/v1/me/feed")
    def get_feed_details(authorization: str | None = Header(default=None)) -> dict:
        user = _require_session_user(container, authorization)
        assert container.control_plane is not None
        return container.control_plane.get_feed_details(user.id)

    @app.get("/v1/me/inbound-items")
    def get_inbound_items(authorization: str | None = Header(default=None)) -> dict:
        user = _require_session_user(container, authorization)
        assert container.control_plane is not None
        return container.control_plane.list_inbound_items(user.id)

    @app.post("/v1/me/device-tokens", status_code=status.HTTP_201_CREATED)
    def register_device_token(
        request_payload: RegisterDeviceTokenRequest,
        authorization: str | None = Header(default=None),
    ) -> dict:
        user = _require_session_user(container, authorization)
        assert container.control_repository is not None
        platform = (request_payload.platform or "ios").strip().lower()
        if platform not in {"ios", "android"}:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="platform must be 'ios' or 'android'",
            )
        # Resolve the push transport. Explicit wins; otherwise derive from
        # platform for backward compat (android→fcm, ios→apns).
        transport = (request_payload.transport or "").strip().lower() or (
            "fcm" if platform == "android" else "apns"
        )
        if transport not in {"apns", "fcm"}:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="transport must be 'apns' or 'fcm'",
            )
        # APNs tokens are hex (case-insensitive) — normalize to lowercase for a
        # stable idempotency key. FCM tokens are case-sensitive (on either
        # platform), so preserve their case.
        raw_token = (request_payload.token or "").strip()
        token = raw_token.lower() if transport == "apns" else raw_token
        if not token or len(token) < 32:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid device token",
            )
        environment = (request_payload.environment or "production").strip().lower()
        if environment not in {"production", "sandbox"}:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="environment must be 'production' or 'sandbox'",
            )
        bundle_id = (
            (request_payload.bundle_id or "").strip()
            or container.settings.apns_bundle_id
        )
        # Idempotent on (user_id, platform, token): re-registering the same
        # device refreshes last_seen_at and clears any prior invalidated_at
        # marker. platform is in the key so an iOS and an Android token that
        # happen to normalize to the same string get distinct records (and so a
        # platform never silently flips on an existing record).
        token_id = hashlib.sha256(
            f"{user.id}:{platform}:{token}".encode("utf-8")
        ).hexdigest()[:32]
        now = utc_now()
        existing = container.control_repository.get_device_token(token_id)
        if existing is not None:
            updated = existing.model_copy(
                update={
                    "last_seen_at": now,
                    "environment": environment,
                    "bundle_id": bundle_id,
                    "transport": transport,
                    "invalidated_at": None,
                }
            )
            container.control_repository.save_device_token(updated)
            return {"token_id": token_id, "status": "refreshed"}
        record = DeviceTokenRecord(
            id=token_id,
            user_id=user.id,
            token=token,
            platform=platform,
            transport=transport,
            environment=environment,
            bundle_id=bundle_id,
            created_at=now,
            last_seen_at=now,
        )
        container.control_repository.save_device_token(record)
        return {"token_id": token_id, "status": "registered"}

    @app.delete("/v1/me/device-tokens/{token_id}", status_code=status.HTTP_204_NO_CONTENT)
    def delete_device_token(
        token_id: str,
        authorization: str | None = Header(default=None),
    ) -> Response:
        user = _require_session_user(container, authorization)
        assert container.control_repository is not None
        existing = container.control_repository.get_device_token(token_id)
        if existing is None or existing.user_id != user.id:
            # Same response shape either way — don't leak whether a token id
            # belongs to a different user.
            return Response(status_code=status.HTTP_204_NO_CONTENT)
        container.control_repository.delete_device_token(token_id)
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    @app.post("/v1/items/shared", status_code=status.HTTP_201_CREATED)
    async def share_item(
        kind: str = Form(...),
        url: Optional[str] = Form(default=None),
        title: Optional[str] = Form(default=None),
        file: Optional[UploadFile] = File(default=None),
        authorization: str | None = Header(default=None),
    ) -> dict:
        """Accept a URL or file shared from the iOS Share extension and pin it
        to the user's next pod. `kind` is one of: url | pdf | epub | docx | text.
        For kind=url, set `url`. For all other kinds, set `file` (multipart).
        `title` is an optional user override; otherwise extracted from content."""
        user = _require_session_user(container, authorization)
        assert container.control_plane is not None

        if kind not in SHARED_SUPPORTED_KINDS:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Unsupported kind {kind!r}; expected one of {sorted(SHARED_SUPPORTED_KINDS)}",
            )

        file_bytes: Optional[bytes] = None
        if kind != "url":
            if file is None:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail=f"file is required when kind={kind!r}",
                )
            # Stream the upload but cap it at SHARED_MAX_UPLOAD_BYTES so a
            # client uploading a 5GB blob doesn't OOM the worker. FastAPI's
            # UploadFile is backed by a SpooledTemporaryFile, so .read() is safe
            # but unbounded — we read in chunks and bail on overflow.
            chunks: list[bytes] = []
            total = 0
            while True:
                chunk = await file.read(64 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > SHARED_MAX_UPLOAD_BYTES:
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail=f"Upload exceeds {SHARED_MAX_UPLOAD_BYTES} bytes",
                    )
                chunks.append(chunk)
            file_bytes = b"".join(chunks)

        try:
            return container.control_plane.share_item(
                user.id,
                kind=kind,
                url=url,
                file_bytes=file_bytes,
                user_title=title,
            )
        except ControlPlaneError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
            )

    @app.get("/v1/me/next-episode/candidates")
    def get_next_episode_candidates(
        authorization: str | None = Header(default=None),
    ) -> dict:
        """Return the live "Coming in your next pod" queue for the user.
        When the candidate-queue feature flag is off the response is
        `{"enabled": false, "candidates": []}` so clients can hide the UI
        without surfacing an error."""
        user = _require_session_user(container, authorization)
        assert container.control_plane is not None
        return container.control_plane.list_next_episode_candidates(user.id)

    @app.post("/v1/me/next-episode/pin", status_code=status.HTTP_201_CREATED)
    def pin_next_episode_item(
        request_payload: NextEpisodeOverrideRequest,
        authorization: str | None = Header(default=None),
    ) -> dict:
        user = _require_session_user(container, authorization)
        assert container.control_plane is not None
        try:
            return container.control_plane.pin_next_episode_item(
                user.id, request_payload.source_item_dedupe_key
            )
        except ControlPlaneError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
            )

    @app.post("/v1/me/next-episode/exclude", status_code=status.HTTP_201_CREATED)
    def exclude_next_episode_item(
        request_payload: NextEpisodeOverrideRequest,
        authorization: str | None = Header(default=None),
    ) -> dict:
        user = _require_session_user(container, authorization)
        assert container.control_plane is not None
        try:
            return container.control_plane.exclude_next_episode_item(
                user.id, request_payload.source_item_dedupe_key
            )
        except ControlPlaneError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
            )

    @app.delete("/v1/me/next-episode/override")
    def clear_next_episode_override(
        source_item_dedupe_key: str,
        authorization: str | None = Header(default=None),
    ) -> dict:
        """Remove a previously-saved pin or exclude. Query param keeps the
        DELETE body-less, which some HTTP stacks insist on."""
        user = _require_session_user(container, authorization)
        assert container.control_plane is not None
        try:
            return container.control_plane.clear_next_episode_override(
                user.id, source_item_dedupe_key
            )
        except ControlPlaneError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
            )

    @app.get("/v1/substack/probe")
    def probe_substack(url: str) -> dict:
        assert container.control_plane is not None
        try:
            return container.control_plane.probe_substack_publication(url)
        except ControlPlaneError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    @app.post("/v1/substack/discover")
    def discover_substacks(
        request_payload: DiscoverSubstacksRequest,
        authorization: str | None = Header(default=None),
    ) -> dict:
        _require_session_user(container, authorization)
        assert container.control_plane is not None
        try:
            return container.control_plane.discover_substacks(request_payload.query)
        except ControlPlaneError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    @app.get("/v1/me/substack/intents")
    def list_substack_intents(authorization: str | None = Header(default=None)) -> dict:
        user = _require_session_user(container, authorization)
        assert container.control_plane is not None
        return container.control_plane.list_substack_intents(user.id)

    @app.post("/v1/me/substack/intents", status_code=status.HTTP_201_CREATED)
    def create_substack_intent(
        request_payload: CreateSubstackIntentRequest,
        authorization: str | None = Header(default=None),
    ) -> dict:
        user = _require_session_user(container, authorization)
        assert container.control_plane is not None
        try:
            return container.control_plane.create_substack_intent(user.id, request_payload.pub_url)
        except ControlPlaneError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    @app.delete("/v1/me/substack/intents/{intent_id}")
    def delete_substack_intent(
        intent_id: str,
        authorization: str | None = Header(default=None),
    ) -> dict:
        user = _require_session_user(container, authorization)
        assert container.control_plane is not None
        try:
            return container.control_plane.delete_substack_intent(user.id, intent_id)
        except ControlPlaneError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))

    @app.post("/v1/me/feedback", status_code=status.HTTP_201_CREATED)
    def submit_feedback(
        request_payload: SubmitFeedbackRequest,
        authorization: str | None = Header(default=None),
    ) -> dict:
        user = _require_session_user(container, authorization)
        assert container.control_plane is not None
        try:
            return container.control_plane.submit_feedback(
                user_id=user.id,
                raw_text=request_payload.text,
                locale_hint=request_payload.locale_hint,
                source=(request_payload.source or "text"),
            )
        except ControlPlaneError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    @app.post("/v1/me/voice-intake", status_code=status.HTTP_201_CREATED)
    def submit_voice_intake(
        request_payload: SubmitVoiceIntakeRequest,
        authorization: str | None = Header(default=None),
    ) -> dict:
        user = _require_session_user(container, authorization)
        assert container.control_plane is not None
        try:
            return container.control_plane.submit_voice_intake(
                user_id=user.id,
                transcript=request_payload.transcript,
            )
        except ControlPlaneError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    @app.post("/v1/me/swipes", status_code=status.HTTP_201_CREATED)
    def submit_swipe(
        request_payload: SubmitSwipeRequest,
        background_tasks: BackgroundTasks,
        authorization: str | None = Header(default=None),
    ) -> dict:
        user = _require_session_user(container, authorization)
        assert container.control_plane is not None
        try:
            result = container.control_plane.submit_swipe(
                user_id=user.id,
                source_item_dedupe_key=request_payload.source_item_dedupe_key,
                direction=request_payload.direction,
            )
        except ControlPlaneError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
        # Auto-attach happened? Warm the corpus so the newly-attached source
        # shows up in the deck on next pull.
        if result.get("auto_attached_source_id"):
            background_tasks.add_task(_warm_corpus_safely, container, user.id)
        return result

    @app.get("/v1/me/swipe-deck/cold-start")
    def get_cold_start_swipe_deck(
        background_tasks: BackgroundTasks,
        topics: str | None = None,
        authorization: str | None = Header(default=None),
    ) -> dict:
        user = _require_session_user(container, authorization)
        assert container.control_plane is not None
        # Comma-separated catalog topic names from onboarding; seeds the deck so
        # the first stories match the categories the user just picked.
        topic_list = (
            [topic for topic in topics.split(",") if topic.strip()] if topics else None
        )
        # Return the deck immediately (cards fall back to their cleaned raw
        # summary) and generate the nicer LLM card summaries after the response
        # is sent. Generating them inline blocks the response on serial OpenAI
        # calls, which made the onboarding "Tune your pod" step appear to hang.
        deck = container.control_plane.get_cold_start_swipe_deck(
            user.id, topics=topic_list, defer_summaries=True
        )
        background_tasks.add_task(
            _warm_cold_start_summaries_safely, container, user.id, topic_list
        )
        return deck

    @app.get("/v1/me/swipe-deck/recent")
    def get_recent_swipe_deck(
        background_tasks: BackgroundTasks,
        authorization: str | None = Header(default=None),
    ) -> dict:
        user = _require_session_user(container, authorization)
        assert container.control_plane is not None
        deck = container.control_plane.get_recent_swipe_deck(
            user.id, defer_summaries=True
        )
        background_tasks.add_task(_warm_recent_summaries_safely, container, user.id)
        return deck

    @app.post("/v1/me/corpus/refresh")
    def refresh_corpus(authorization: str | None = Header(default=None)) -> dict:
        user = _require_session_user(container, authorization)
        assert container.control_plane is not None
        return container.control_plane.warm_user_corpus(user.id)

    @app.get("/v1/me/episodes")
    def list_my_episodes(authorization: str | None = Header(default=None)) -> dict:
        user = _require_session_user(container, authorization)
        assert container.control_plane is not None
        return container.control_plane.list_user_episodes(user.id)

    @app.post(
        "/v1/me/episodes/{episode_id}/play-pulse",
        status_code=status.HTTP_202_ACCEPTED,
    )
    def post_play_pulse(
        episode_id: str,
        request_payload: PlayPulseRequest,
        authorization: str | None = Header(default=None),
    ) -> dict:
        """Heartbeat from any in-app player while an episode plays.
        Logs-only — no DB write. Position is bucketed so the event
        stream never carries an exact playhead timestamp."""
        user = _require_session_user(container, authorization)
        position = max(0, int(request_payload.position_seconds))
        log_event(
            EventName.EPISODE_PLAY_PULSE,
            user.id,
            episode_id=episode_id,
            position_bucket=bucket_play_position_seconds(position),
        )
        return {"accepted": True}

    @app.get("/admin/metrics", response_class=Response)
    def admin_metrics(
        user_id: str | None = None,
        authorization: str | None = Header(default=None),
    ) -> Response:
        """Admin-only metrics page. Without `?user_id=` renders a global
        summary; with one, renders that user's timeline. Gated by
        ADMIN_USER_IDS; returns 403 (not 404) when an authenticated
        non-admin tries to access it so the operator gets a clear
        signal in logs."""
        session_user = _require_session_user(container, authorization)
        if not is_admin(session_user.id, container.settings):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Admin access required",
            )
        assert container.control_repository is not None
        service = AdminMetricsService(
            repository=container.control_repository,
            settings=container.settings,
        )
        if user_id:
            timeline = service.get_user_timeline(user_id)
            if timeline is None:
                html_body = render_user_not_found_html(user_id)
                return Response(
                    content=html_body,
                    media_type="text/html; charset=utf-8",
                    status_code=status.HTTP_404_NOT_FOUND,
                )
            return Response(
                content=render_user_timeline_html(timeline),
                media_type="text/html; charset=utf-8",
            )
        summary = service.get_summary()
        return Response(
            content=render_summary_html(summary),
            media_type="text/html; charset=utf-8",
        )

    @app.post("/admin/trial-gift/notify")
    def admin_trial_gift_notify(
        authorization: str | None = Header(default=None),
    ) -> dict:
        """Admin-only: announce the "gift" trial reset. Finds every user whose
        trial gift has been granted (trial_gift_granted_at set) but not yet
        announced (trial_gift_pushed_at None), sends the gift push, and stamps
        trial_gift_pushed_at so a re-run only targets newcomers. Gated by
        ADMIN_USER_IDS exactly like /admin/metrics (403 for non-admins)."""
        session_user = _require_session_user(container, authorization)
        if not is_admin(session_user.id, container.settings):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Admin access required",
            )
        assert container.control_repository is not None
        repository = container.control_repository

        candidates = [
            user
            for user in repository.list_all_users(limit=5000)
            if user.trial_gift_granted_at is not None
            and user.trial_gift_pushed_at is None
        ]
        pushed = 0
        deregistered = 0
        for user in candidates:
            try:
                result = send_trial_gift_push(
                    sender=container.push_sender,
                    fcm_sender=container.fcm_sender,
                    repository=repository,
                    user_id=user.id,
                )
            except Exception:  # pragma: no cover — push is best-effort
                logger.warning("Trial-gift push failed: user=%s", user.id)
                continue
            deregistered += result.get("deregistered", 0)
            user.trial_gift_pushed_at = utc_now()
            repository.save_user(user)
            pushed += 1

        return {
            "candidates": len(candidates),
            "pushed": pushed,
            "deregistered": deregistered,
        }

    @app.post("/v1/me/generate", status_code=status.HTTP_202_ACCEPTED)
    def generate_episode_now(
        background_tasks: BackgroundTasks,
        response: Response,
        authorization: str | None = Header(default=None),
    ) -> dict:
        user = _require_session_user(container, authorization)
        assert container.control_plane is not None
        result = container.control_plane.start_user_generation(user_id=user.id, force=True)
        if result.get("started"):
            run_id = result["run"]["id"]
            background_tasks.add_task(
                container.control_plane.run_user_generation_in_background,
                run_id=run_id,
                user_id=user.id,
                force=True,
            )
        else:
            response.status_code = status.HTTP_200_OK
        return result

    @app.get("/v1/me/runs/{run_id}")
    def get_user_run(
        run_id: str,
        authorization: str | None = Header(default=None),
    ) -> dict:
        user = _require_session_user(container, authorization)
        assert container.control_plane is not None
        try:
            return container.control_plane.get_user_run_status(user_id=user.id, run_id=run_id)
        except ControlPlaneError as exc:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))

    @app.post("/v1/billing/app-store/notifications")
    def receive_billing_notification(request_payload: BillingNotificationRequest) -> dict:
        assert container.control_plane is not None
        try:
            return container.control_plane.apply_app_store_notification(
                request_payload.model_dump(exclude_none=True, by_alias=False)
            )
        except ControlPlaneError as exc:
            # Verification failure / unsigned-payload rejection / config
            # missing. Apple retries on non-2xx, so a legitimate retry still
            # lands once the cause is fixed.
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
            )

    @app.post("/v1/me/subscription/verify")
    def verify_subscription(
        request_payload: VerifyTransactionRequest,
        authorization: str | None = Header(default=None),
    ) -> dict:
        user = _require_session_user(container, authorization)
        assert container.control_plane is not None
        jws = request_payload.signed_transaction_info or request_payload.signedTransactionInfo
        if not jws:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="signed_transaction_info is required",
            )
        try:
            return container.control_plane.apply_client_verified_transaction(
                user_id=user.id,
                signed_transaction_info=jws,
            )
        except ControlPlaneError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
            )

    @app.post("/webhooks/revenuecat")
    async def receive_revenuecat_webhook(
        request: Request,
        authorization: str | None = Header(default=None),
    ) -> dict:
        """RevenueCat webhook (Android / Play Billing subscription events).

        RevenueCat authenticates by sending the exact Authorization header
        value configured in its dashboard; we compare it constant-time against
        REVENUECAT_WEBHOOK_AUTH_SECRET. 503 until that secret is set (so this
        ships ahead of the RevenueCat project), 401 on mismatch.
        """
        assert container.control_plane is not None
        secret = container.settings.revenuecat_webhook_auth_secret
        if not secret:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail="RevenueCat webhook is not configured",
            )
        # RevenueCat sends the dashboard-configured Authorization value verbatim.
        # That value is conventionally "Bearer <token>"; accept either form by
        # stripping an optional Bearer prefix, then constant-time compare against
        # the bare secret.
        provided = (authorization or "").strip()
        if provided.startswith("Bearer "):
            provided = provided[len("Bearer ") :].strip()
        if not provided or not secrets.compare_digest(provided, secret):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="invalid authorization",
            )
        payload = await request.json()
        try:
            return container.control_plane.apply_revenuecat_event(payload)
        except ControlPlaneError as exc:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)
            )

    @app.post("/webhooks/mailgun/inbound")
    async def receive_mailgun_inbound(request: Request) -> dict:
        assert container.control_repository is not None
        form = await request.form()
        # Mailgun sends multipart/form-data; we don't care about attachments,
        # only the textual fields. Coerce everything we read into strings.
        payload = {key: (value if isinstance(value, str) else "") for key, value in form.items()}
        handler = InboundEmailHandler(
            repository=container.control_repository,
            inbound_email_domain=container.settings.inbound_email_domain,
            mailgun_signing_key=container.settings.mailgun_webhook_signing_key,
            embeddings=_build_embedding_provider(container.settings),
            push_sender=container.push_sender,
            fcm_sender=container.fcm_sender,
        )
        try:
            return handler.handle(payload)
        except InboundSignatureError as exc:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc))
        except InboundConfigError as exc:
            raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))

    @app.api_route("/broadcast/{episode_id}.mp3", methods=["GET", "HEAD"])
    def get_broadcast_audio(episode_id: str, request: Request) -> Response:
        """Public download for a broadcast-loop audio asset. Intentionally
        unauthenticated — these are marketing assets meant to be embedded
        in tweets and shared. Returns 404 for any id that doesn't match
        the broadcast id shape, so the route doubles as a path-traversal
        guard."""
        return _serve_broadcast_object(
            container, episode_id, suffix="mp3", media_type="audio/mpeg", request=request
        )

    @app.api_route("/broadcast/{episode_id}.mp4", methods=["GET", "HEAD"])
    def get_broadcast_video(episode_id: str, request: Request) -> Response:
        """Public download for a broadcast-loop video asset. See
        get_broadcast_audio for the auth + id-validation rationale."""
        return _serve_broadcast_object(
            container, episode_id, suffix="mp4", media_type="video/mp4", request=request
        )

    @app.api_route(
        "/broadcast/{loop_id}/feed.xml",
        methods=["GET", "HEAD"],
        response_class=Response,
    )
    def get_broadcast_feed(loop_id: str, request: Request) -> Response:
        """Public podcast RSS for one broadcast loop — the same daily
        episodes posted to X, as a subscribable feed. Intentionally
        unauthenticated, like the /broadcast/<id>.mp3 assets it points at:
        this is what the marketing site embeds and what podcast players
        ingest. Enclosures reuse the existing public audio route, so no
        asset has to be made public at the bucket level."""
        assert container.broadcast_repository is not None
        try:
            clean_loop_id = validate_loop_id(loop_id)
        except ValueError:
            # Don't leak the validation rule on a public route; a bad id is
            # simply "no such feed".
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

        episodes = container.broadcast_repository.list_episodes_for_loop(
            clean_loop_id, limit=container.settings.max_feed_episodes
        )
        base = container.settings.app_base_url.rstrip("/")
        items: list[_BroadcastFeedItem] = []
        for episode in episodes:
            try:
                size = container.storage.object_size(episode.audio_object_name)
            except FileNotFoundError:
                # Episode row exists but its audio never landed (failed run).
                # Skip it rather than emit an item that 404s on play.
                continue
            items.append(_broadcast_feed_item(episode, size))

        loop = container.broadcast_repository.get_loop(clean_loop_id)
        xml_content = build_feed_xml(
            title=_broadcast_feed_title(loop),
            description=_BROADCAST_FEED_DESCRIPTION,
            author=container.settings.podcast_author,
            language=container.settings.podcast_language,
            feed_url=f"{base}/broadcast/{clean_loop_id}/feed.xml",
            image_url=container.settings.podcast_image_url,
            episodes=items,
            media_url_builder=lambda item: f"{base}/broadcast/{item.id}.mp3",
            owner_email=container.settings.podcast_owner_email,
            category=container.settings.podcast_category,
        )
        return _build_xml_response(xml_content, request)

    @app.api_route("/media/{secret_token}/{episode_id}.mp3", methods=["GET", "HEAD"])
    def get_private_media(
        secret_token: str,
        episode_id: str,
        request: Request,
        range_header: str | None = Header(default=None, alias="Range"),
        if_range_header: str | None = Header(default=None, alias="If-Range"),
        if_none_match_header: str | None = Header(default=None, alias="If-None-Match"),
        if_modified_since_header: str | None = Header(default=None, alias="If-Modified-Since"),
    ) -> Response:
        assert container.control_repository is not None
        episode = None
        token_record = container.control_repository.get_feed_token_record(secret_token)
        if token_record:
            user_episode = container.control_repository.get_user_episode(episode_id)
            if user_episode and user_episode.user_id == token_record.user_id:
                episode = user_episode

        if not episode:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

        try:
            audio_bytes = container.storage.download_audio(episode.audio_object_name)
        except FileNotFoundError:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

        if request.method == "GET":
            # Server-side listening pulse. External podcast apps fetch audio
            # here, so this route is the only place we observe listening across
            # both the iOS and Flutter stacks. Attribute the stack from the
            # podcast client's User-Agent; for cross-platform clients we can't
            # resolve from the UA (e.g. Pocket Casts), fall back to the user's
            # own stack from their newest device token. Skip link-preview bots
            # (their fetch isn't a listen). Position is approximated from the
            # Range start. Best-effort — analytics must never break delivery.
            user_agent = request.headers.get("user-agent")
            if not is_bot_user_agent(user_agent):
                try:
                    platform = platform_from_user_agent(
                        user_agent
                    ) or _user_device_platform(container, token_record.user_id)
                    approx_seconds = (
                        _range_start_bytes(range_header)
                        // _MEDIA_APPROX_BYTES_PER_SECOND
                    )
                    log_event(
                        EventName.EPISODE_PLAY_PULSE,
                        token_record.user_id,
                        platform=platform,
                        episode_id=episode_id,
                        position_bucket=bucket_play_position_seconds(approx_seconds),
                        source="media_fetch",
                    )
                except Exception:  # pragma: no cover - never fail audio
                    logger.warning("media play-pulse event failed", exc_info=True)

        return _build_media_response(
            audio_bytes=audio_bytes,
            media_type=episode.audio_mime_type,
            request=request,
            range_header=range_header,
            if_range_header=if_range_header,
            if_none_match_header=if_none_match_header,
            if_modified_since_header=if_modified_since_header,
            etag=_episode_etag(episode.id, len(audio_bytes)),
            last_modified=episode.published_at,
        )

    @app.api_route("/feeds/{feed_token}.xml", methods=["GET", "HEAD"], response_class=Response)
    def get_user_feed(feed_token: str, request: Request) -> Response:
        assert container.control_repository is not None
        token_record = container.control_repository.get_feed_token_record(feed_token)
        if not token_record:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")

        episodes = container.control_repository.list_recent_user_episodes(
            token_record.user_id,
            container.settings.max_feed_episodes,
        )
        profile = container.control_repository.get_profile(token_record.user_id)
        xml_content = build_feed_xml(
            title=(profile.title if profile else "Weekly Briefing"),
            description="Private weekly podcast briefing.",
            author=container.settings.podcast_author,
            language=container.settings.podcast_language,
            feed_url=f"{container.settings.app_base_url.rstrip('/')}/feeds/{feed_token}.xml",
            image_url=container.settings.podcast_image_url,
            episodes=episodes,
            media_url_builder=lambda episode: (
                f"{container.settings.app_base_url.rstrip('/')}/media/{feed_token}/{episode.id}.mp3"
            ),
            owner_email=container.settings.podcast_owner_email,
            category=container.settings.podcast_category,
        )
        return _build_xml_response(xml_content, request)

    return app


def _build_container(settings: Settings) -> ServiceContainer:
    if settings.use_inmemory_adapters:
        storage: AudioStorage = InMemoryAudioStorage()
    else:
        if not settings.gcs_bucket_name:
            raise RuntimeError("GCS_BUCKET_NAME is required when USE_INMEMORY_ADAPTERS=false")
        storage = GCSAudioStorage(settings.gcs_bucket_name, prefix=settings.gcs_prefix)

    voice_speed_by_id = {
        voice.id: voice.speed
        for voice in load_voices(settings.voices_file)
        if voice.speed is not None
    }
    podcast_client = PodcastApiClient(
        enabled=settings.podcast_api_enabled,
        provider=settings.podcast_provider,
        base_url=settings.podcast_api_base_url,
        api_key=settings.podcast_api_key,
        timeout_seconds=settings.podcast_api_timeout_seconds,
        poll_seconds=settings.podcast_api_poll_seconds,
        text_model=settings.podcast_text_model,
        tts_model=settings.podcast_tts_model,
        tts_voice=settings.podcast_tts_voice,
        tts_instructions=settings.podcast_tts_instructions,
        tts_provider=settings.podcast_tts_provider,
        elevenlabs_api_key=settings.elevenlabs_api_key,
        elevenlabs_model=settings.elevenlabs_model,
        voice_speed_by_id=voice_speed_by_id,
        audio_mastering_enabled=settings.podcast_audio_mastering_enabled,
        audio_target_lufs=settings.podcast_audio_target_lufs,
        audio_crossfade_ms=settings.podcast_audio_crossfade_ms,
    )

    mailer_required = (
        settings.alert_email_enabled
        or settings.publish_summary_email_enabled
        or settings.feedback_digest_email_enabled
    )
    if mailer_required:
        if not settings.smtp_host or not settings.alert_email_from:
            raise RuntimeError("Email delivery is enabled but SMTP host or sender is missing")
        legacy_features = settings.alert_email_enabled or settings.publish_summary_email_enabled
        if legacy_features and not settings.alert_email_to:
            raise RuntimeError("ALERT_EMAIL_TO is required when alert/summary emails are enabled")
        if (
            settings.feedback_digest_email_enabled
            and not settings.alert_email_to
            and not settings.feedback_digest_extra_recipients.strip()
        ):
            raise RuntimeError(
                "Feedback digest is enabled but no recipients are configured"
            )
        mailer = SMTPMailer(
            host=settings.smtp_host or "",
            port=settings.smtp_port,
            username=settings.smtp_username,
            password=settings.smtp_password,
            sender=settings.alert_email_from or "",
            default_recipients=[settings.alert_email_to] if settings.alert_email_to else [],
            use_tls=settings.smtp_use_tls,
        )
    else:
        mailer = NoopMailer()

    control_repository, control_plane = _build_control_plane(
        settings=settings,
        storage=storage,
        podcast_client=podcast_client,
        mailer=mailer,
    )

    push_sender = build_push_sender_from_settings(
        enabled=settings.apns_enabled,
        team_id=settings.apns_team_id,
        key_id=settings.apns_key_id,
        auth_key_pem=settings.apns_auth_key,
        bundle_id=settings.apns_bundle_id,
        environment=settings.apns_environment,
    )

    fcm_sender = build_fcm_sender_from_settings(
        enabled=settings.fcm_enabled,
        service_account_json=settings.fcm_service_account_json,
        project_id=settings.firebase_project_id,
    )

    x_client = XClient(
        api_key=settings.x_api_key,
        api_secret=settings.x_api_secret,
        access_token=settings.x_access_token,
        access_token_secret=settings.x_access_token_secret,
        username=settings.broadcast_x_username,
    )

    if settings.use_inmemory_adapters:
        broadcast_repository: BroadcastRepository = InMemoryBroadcastRepository()
    else:
        broadcast_repository = FirestoreBroadcastRepository(settings.firestore_collection_prefix)

    return ServiceContainer(
        settings=settings,
        storage=storage,
        control_repository=control_repository,
        control_plane=control_plane,
        push_sender=push_sender,
        fcm_sender=fcm_sender,
        podcast_client=podcast_client,
        x_client=x_client,
        broadcast_repository=broadcast_repository,
    )


def _warm_corpus_safely(container, user_id: str) -> None:
    """Background-task wrapper around warm_user_corpus that swallows
    exceptions so a failed warm never bubbles into a request that already
    returned a successful response.
    """
    if container.control_plane is None:
        return
    try:
        container.control_plane.warm_user_corpus(user_id)
    except Exception:  # pragma: no cover — best-effort
        logger.warning("Background corpus warm failed for user=%s", user_id, exc_info=True)


def _warm_cold_start_summaries_safely(
    container, user_id: str, topics: Optional[list[str]]
) -> None:
    """Background-task wrapper that generates + persists cold-start (onboarding)
    swipe-deck card summaries after the deck response has already been returned.
    ``topics`` is None for the global cold-start deck. Swallows exceptions so a
    failed summarization never affects the request that already succeeded.
    """
    if container.control_plane is None:
        return
    try:
        container.control_plane.warm_cold_start_card_summaries(user_id, topics)
    except Exception:  # pragma: no cover — best-effort
        logger.warning(
            "Background cold-start card-summary warm failed for user=%s",
            user_id,
            exc_info=True,
        )


def _warm_recent_summaries_safely(container, user_id: str) -> None:
    """Background-task wrapper that generates + persists recent swipe-deck card
    summaries after the deck response has already been returned. Swallows
    exceptions so a failed summarization never affects the request.
    """
    if container.control_plane is None:
        return
    try:
        container.control_plane.warm_recent_card_summaries(user_id)
    except Exception:  # pragma: no cover — best-effort
        logger.warning(
            "Background recent card-summary warm failed for user=%s",
            user_id,
            exc_info=True,
        )


def _build_control_plane(
    settings: Settings,
    storage: AudioStorage,
    podcast_client: PodcastApiClient | None = None,
    mailer=None,
) -> tuple[ControlPlaneRepository, ControlPlaneService]:
    if settings.use_inmemory_adapters:
        control_repository: ControlPlaneRepository = InMemoryControlPlaneRepository()
    else:
        control_repository = FirestoreControlPlaneRepository(settings.firestore_collection_prefix)

    if podcast_client is None:
        voice_speed_by_id = {
            voice.id: voice.speed
            for voice in load_voices(settings.voices_file)
            if voice.speed is not None
        }
        podcast_client = PodcastApiClient(
            enabled=settings.podcast_api_enabled,
            provider=settings.podcast_provider,
            base_url=settings.podcast_api_base_url,
            api_key=settings.podcast_api_key,
            timeout_seconds=settings.podcast_api_timeout_seconds,
            poll_seconds=settings.podcast_api_poll_seconds,
            text_model=settings.podcast_text_model,
            tts_model=settings.podcast_tts_model,
            tts_voice=settings.podcast_tts_voice,
            tts_instructions=settings.podcast_tts_instructions,
            tts_provider=settings.podcast_tts_provider,
            elevenlabs_api_key=settings.elevenlabs_api_key,
            elevenlabs_model=settings.elevenlabs_model,
            voice_speed_by_id=voice_speed_by_id,
            audio_mastering_enabled=settings.podcast_audio_mastering_enabled,
            audio_target_lufs=settings.podcast_audio_target_lufs,
            audio_crossfade_ms=settings.podcast_audio_crossfade_ms,
        )
    session_manager = SessionManager(
        signing_secret=settings.session_signing_secret,
        ttl_hours=settings.session_ttl_hours,
    )
    apple_verifier = AppleIdentityVerifier(settings.apple_client_id)
    firebase_verifier = FirebaseIdentityVerifier(settings.firebase_project_id)
    task_enqueuer = build_task_enqueuer(settings)
    embedding_provider = _build_embedding_provider(settings)
    intake_extractor = _build_intake_extractor(settings)
    card_summarizer = _build_card_summarizer(settings)
    substack_discovery = _build_substack_discovery(settings)
    app_store_verifier = _build_app_store_verifier(settings)
    control_plane = ControlPlaneService(
        settings=settings,
        repository=control_repository,
        storage=storage,
        podcast_client=podcast_client,
        mailer=mailer or NoopMailer(),
        session_manager=session_manager,
        apple_identity_verifier=apple_verifier,
        firebase_identity_verifier=firebase_verifier,
        task_enqueuer=task_enqueuer,
        embedding_provider=embedding_provider,
        intake_extractor=intake_extractor,
        card_summarizer=card_summarizer,
        substack_discovery=substack_discovery,
        app_store_verifier=app_store_verifier,
    )
    return control_repository, control_plane


def _build_app_store_verifier(settings: Settings):
    """Construct the App Store Server Notification signed-payload verifier.

    Returns `None` when verification is disabled (e.g. `app_store_environment`
    is empty) so the legacy unsigned path stays open during dev. A
    production environment without an `app_store_app_apple_id` fails loudly
    rather than silently degrading to the legacy path.
    """
    from .app_store_verifier import AppStoreNotificationVerifier

    env = (settings.app_store_environment or "").strip().lower()
    if not env:
        return None
    try:
        return AppStoreNotificationVerifier(
            bundle_id=settings.app_store_bundle_id,
            environment=env,
            app_apple_id=settings.app_store_app_apple_id,
        )
    except Exception as exc:
        # Production must not silently fall through to the legacy unsigned
        # path; re-raise so the deploy aborts with a clear error. In any
        # non-production env we log and keep going so dev work isn't blocked.
        if env in {"production", "prod"} or settings.app_store_notifications_require_signed:
            raise
        logger.warning("App Store verifier disabled: %s", exc)
        return None


def _build_embedding_provider(settings: Settings) -> EmbeddingProvider | None:
    if not settings.source_item_embeddings_enabled:
        return None
    api_key = settings.openai_embedding_api_key
    if not api_key:
        logger.warning(
            "Source-item embeddings enabled but no OPENAI_EMBEDDING_API_KEY (or "
            "PODCAST_API_KEY fallback) is configured; persistence will run without embeddings"
        )
        return None
    return OpenAIEmbeddingProvider(
        api_key=api_key,
        model=settings.openai_embedding_model,
        endpoint=settings.openai_embedding_endpoint,
    )


def _build_intake_extractor(settings: Settings):
    """Voice-intake LLM extractor. Returns None when the OpenAI key isn't
    configured — in that case `submit_voice_intake` will reject calls with a
    clear error rather than silently dropping the transcript.
    """
    from .voice_intake import OpenAIIntakeExtractor

    api_key = settings.openai_embedding_api_key or settings.podcast_api_key
    if not api_key:
        return None
    return OpenAIIntakeExtractor(
        api_key=api_key,
        model=settings.voice_intake_model,
    )


def _build_card_summarizer(settings: Settings):
    """Swipe-deck card-summary LLM. Returns None when no OpenAI key is set;
    the CardSummaryService skips the pass and the iOS client falls back to
    cleaning the raw RSS summary on-device.
    """
    from .card_summary import OpenAICardSummarizer

    api_key = settings.openai_embedding_api_key or settings.podcast_api_key
    if not api_key:
        return None
    return OpenAICardSummarizer(
        api_key=api_key,
        model=settings.card_summary_model,
    )


def _build_substack_discovery(settings: Settings):
    """Substack-discovery service. Returns None when no OpenAI key is set;
    `discover_substacks` then rejects calls with a clear 400 instead of
    silently returning an empty list.
    """
    from .substack_discovery import OpenAISubstackSuggester, SubstackDiscoveryService

    api_key = settings.openai_embedding_api_key or settings.podcast_api_key
    if not api_key:
        return None
    return SubstackDiscoveryService(
        suggester=OpenAISubstackSuggester(
            api_key=api_key,
            model=settings.substack_discovery_model,
        )
    )


def _build_topic_picker(
    settings: Settings,
    broadcast_repository: BroadcastRepository,
) -> BroadcastTopicPicker:
    proposer = None
    if settings.podcast_api_key:
        proposer = OpenAITopicProposer(
            api_key=settings.podcast_api_key,
            model=settings.broadcast_llm_model,
        )
    return BroadcastTopicPicker(proposer=proposer, repository=broadcast_repository)


def _build_feedback_summarizer(settings: Settings):
    if not settings.podcast_api_key:
        return None
    return OpenAIFeedbackSummarizer(
        api_key=settings.podcast_api_key,
        model=settings.broadcast_llm_model,
    )


def _build_scheduled_runner(container: ServiceContainer, static_dir: Path) -> ScheduledBroadcastRunner:
    assert container.podcast_client is not None
    assert container.x_client is not None
    assert container.broadcast_repository is not None
    assert container.control_repository is not None

    broadcast_settings = BroadcastSettings(
        app_base_url=container.settings.app_base_url,
        primary_voice_id=container.settings.elevenlabs_voice_primary_id,
        secondary_voice_id=container.settings.elevenlabs_voice_secondary_id,
        primary_host_name=container.settings.podcast_host_primary_name,
        secondary_host_name=container.settings.podcast_host_secondary_name,
        cover_image_path=static_dir / "cover.png",
    )
    service = BroadcastService(
        settings=broadcast_settings,
        storage=container.storage,
        podcast_client=container.podcast_client,
    )
    publisher = BroadcastPublisher(storage=container.storage, x_client=container.x_client)
    topic_picker = _build_topic_picker(container.settings, container.broadcast_repository)

    # Bound the per-loop grounding fetch. Lookback covers a usual week of
    # newsletters; the cap stops a 90-source loop from pulling thousands
    # of items before the prompt builder dedupes per source.
    control_repository = container.control_repository
    def _source_item_provider(source_ids: list[str]) -> list[SourceItem]:
        if not source_ids:
            return []
        records = control_repository.list_recent_source_items_for_sources(
            source_ids=source_ids,
            lookback_days=7,
            limit=150,
        )
        # SourceItemRecord -> SourceItem so the broadcast pipeline only
        # depends on the lightweight read-only model.
        return [
            SourceItem(
                source_id=r.source_id,
                source_name=r.source_name,
                guid=r.guid,
                link=r.link,
                title=r.title,
                summary=r.summary,
                published_at=r.published_at,
                dedupe_key=r.dedupe_key,
            )
            for r in records
        ]

    return ScheduledBroadcastRunner(
        repository=container.broadcast_repository,
        topic_picker=topic_picker,
        broadcast_service=service,
        publisher=publisher,
        source_item_provider=_source_item_provider,
        # Auto-poll deps: both must be set for the runner to read replies
        # on yesterday's episode before picking today's topic. X client
        # is always present (raises XClientUnavailable when creds missing,
        # which the runner catches). Summarizer is None when no LLM key
        # is configured.
        x_client=container.x_client,
        feedback_summarizer=_build_feedback_summarizer(container.settings),
    )


def _resolve_feedback_prompt(value: Optional[str]) -> Optional[str]:
    """Decide what feedback-prompt reply (if any) to post under a broadcast
    tweet. The caller has three tri-state intents — fall back to default,
    use a custom prompt, or suppress entirely — collapsed onto a single
    Optional[str] body field:

    - None (field omitted): use the bundled default copy.
    - "" (explicit empty): suppress the reply entirely.
    - anything else: use it verbatim.
    """
    if value is None:
        return DEFAULT_FEEDBACK_PROMPT
    stripped = value.strip()
    if not stripped:
        return None
    return stripped


def _serve_broadcast_object(
    container: ServiceContainer,
    episode_id: str,
    *,
    suffix: str,
    media_type: str,
    request: Request,
) -> Response:
    if not _BROADCAST_EPISODE_ID_RE.fullmatch(episode_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    object_name = f"broadcast/{episode_id}.{suffix}"
    try:
        data = container.storage.get_object(object_name)
    except FileNotFoundError:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")
    # Serve with HTTP Range support so browsers and podcast players can seek
    # (scrub) the episode — a bare 200 with Accept-Ranges: none leaves the
    # website player unable to skip around. These are immutable public marketing
    # assets, so allow shared caches to keep them. Conditional headers are read
    # off the request rather than threaded through the route signature.
    return _build_media_response(
        audio_bytes=data,
        media_type=media_type,
        request=request,
        range_header=request.headers.get("range"),
        if_range_header=request.headers.get("if-range"),
        if_none_match_header=request.headers.get("if-none-match"),
        if_modified_since_header=request.headers.get("if-modified-since"),
        etag=_episode_etag(episode_id, len(data)),
        cache_control="public, max-age=31536000, immutable",
    )


def _validate_job_auth(
    settings: Settings,
    authorization: str | None,
    x_job_trigger_token: str | None,
) -> None:
    if not settings.job_trigger_token:
        return

    expected = f"Bearer {settings.job_trigger_token}"
    if authorization and secrets.compare_digest(expected, authorization):
        return
    if x_job_trigger_token and secrets.compare_digest(settings.job_trigger_token, x_job_trigger_token):
        return

    raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized")


def _require_session_user(container: ServiceContainer, authorization: str | None):
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing session token")
    token = authorization.removeprefix("Bearer ").strip()
    try:
        assert container.control_plane is not None
        return container.control_plane.get_authenticated_user(token)
    except (AuthError, ControlPlaneError) as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc))


# ElevenLabs renders broadcast MP3s at a constant 128 kbps, so we can derive a
# good-enough itunes:duration from the byte size without decoding the audio.
_BROADCAST_FEED_BITRATE_BPS = 128_000
_BROADCAST_FEED_DESCRIPTION = (
    "ClawCast's short daily show — the same episodes posted to X, generated "
    "and hosted by ClawCast from the feeds it follows."
)


@dataclass(frozen=True)
class _BroadcastFeedItem:
    """Adapter exposing just the attributes build_feed_xml reads, so the
    broadcast feed can reuse the user-feed XML builder without sharing the
    UserEpisodeRecord schema."""

    id: str
    title: str
    description: str
    published_at: datetime
    duration_seconds: int
    audio_size_bytes: int
    audio_mime_type: str


def _broadcast_feed_title(loop: BroadcastLoopRecord | None) -> str:
    # Loops carry a region but no human-facing show name; keep a stable title
    # and disambiguate by region when one is set.
    if loop and loop.region.strip():
        return f"ClawCast Daily — {loop.region.strip()}"
    return "ClawCast Daily"


def _broadcast_feed_item(
    episode: BroadcastEpisodeRecord, audio_size_bytes: int
) -> _BroadcastFeedItem:
    duration = max(1, round(audio_size_bytes * 8 / _BROADCAST_FEED_BITRATE_BPS))
    return _BroadcastFeedItem(
        id=episode.episode_id,
        title=episode.title,
        description=episode.show_notes or episode.title,
        published_at=episode.created_at,
        duration_seconds=duration,
        audio_size_bytes=audio_size_bytes,
        audio_mime_type="audio/mpeg",
    )


def _build_xml_response(xml_content: str, request: Request) -> Response:
    xml_bytes = xml_content.encode("utf-8")
    headers = {
        "Content-Length": str(len(xml_bytes)),
        "Accept-Ranges": "bytes",
    }
    if request.method == "HEAD":
        return Response(content=b"", media_type="application/rss+xml", headers=headers)
    return Response(content=xml_bytes, media_type="application/rss+xml", headers=headers)


def _episode_etag(episode_id: str, size: int) -> str:
    # Strong validator: episode_id is immutable and size pins the byte stream
    # the client is currently playing. Quoted per RFC 7232.
    return f'"{episode_id}-{size}"'


def _http_date(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return format_datetime(value.astimezone(timezone.utc), usegmt=True)


def _if_none_match_matches(header_value: str | None, etag: str) -> bool:
    if not header_value:
        return False
    for token in header_value.split(","):
        candidate = token.strip()
        if candidate == "*" or candidate == etag:
            return True
    return False


def _if_modified_since_satisfied(header_value: str | None, last_modified: datetime) -> bool:
    if not header_value:
        return False
    try:
        since = parsedate_to_datetime(header_value)
    except (TypeError, ValueError):
        return False
    if since.tzinfo is None:
        since = since.replace(tzinfo=timezone.utc)
    # Last-Modified granularity is one second; truncate to compare fairly.
    last_modified_utc = last_modified.astimezone(timezone.utc).replace(microsecond=0)
    return last_modified_utc <= since.astimezone(timezone.utc)


def _if_range_matches(
    header_value: str | None,
    etag: str,
    last_modified: datetime,
) -> bool:
    if not header_value:
        return True
    candidate = header_value.strip()
    if candidate.startswith('"') or candidate.startswith('W/'):
        return candidate == etag
    try:
        when = parsedate_to_datetime(candidate)
    except (TypeError, ValueError):
        return False
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return when.astimezone(timezone.utc).replace(microsecond=0) == last_modified.astimezone(
        timezone.utc
    ).replace(microsecond=0)


def _build_media_response(
    audio_bytes: bytes,
    media_type: str,
    request: Request,
    range_header: str | None,
    if_range_header: str | None = None,
    if_none_match_header: str | None = None,
    if_modified_since_header: str | None = None,
    etag: str | None = None,
    last_modified: datetime | None = None,
    cache_control: str | None = None,
) -> Response:
    total_length = len(audio_bytes)
    headers: dict[str, str] = {"Accept-Ranges": "bytes"}
    if etag is not None:
        headers["ETag"] = etag
    if last_modified is not None:
        headers["Last-Modified"] = _http_date(last_modified)
    # Episode bytes are immutable once published — let clients cache aggressively
    # so resumes after interruption don't have to re-download. Per-user media is
    # private; public marketing assets pass a `public` directive instead.
    headers["Cache-Control"] = cache_control or "private, max-age=31536000, immutable"

    if etag is not None and _if_none_match_matches(if_none_match_header, etag):
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers=headers)
    if (
        last_modified is not None
        and not if_none_match_header
        and _if_modified_since_satisfied(if_modified_since_header, last_modified)
    ):
        return Response(status_code=status.HTTP_304_NOT_MODIFIED, headers=headers)

    effective_range = range_header
    if effective_range is not None and etag is not None and last_modified is not None:
        if not _if_range_matches(if_range_header, etag, last_modified):
            effective_range = None

    range_spec = _parse_range_header(effective_range, total_length)

    if range_spec is None:
        headers["Content-Length"] = str(total_length)
        if request.method == "HEAD":
            return Response(content=b"", media_type=media_type, headers=headers)
        return Response(content=audio_bytes, media_type=media_type, headers=headers)

    start, end = range_spec
    chunk = audio_bytes[start : end + 1]
    headers["Content-Length"] = str(len(chunk))
    headers["Content-Range"] = f"bytes {start}-{end}/{total_length}"
    if request.method == "HEAD":
        return Response(
            content=b"",
            status_code=status.HTTP_206_PARTIAL_CONTENT,
            media_type=media_type,
            headers=headers,
        )
    return Response(
        content=chunk,
        status_code=status.HTTP_206_PARTIAL_CONTENT,
        media_type=media_type,
        headers=headers,
    )


# Audio is rendered at ~64 kbps mono (see ElevenLabs TTS settings), i.e. about
# 8 KB/s, so a Range request's start byte / this ≈ the playhead in seconds. The
# mapping is intentionally coarse — older episodes and any VBR drift make it
# approximate — and is only used to bucket the server-side /media listening
# pulse into "got past the intro" vs not. Never relied on for exact position.
_MEDIA_APPROX_BYTES_PER_SECOND = 8000


# Per-user stack (ios/android) cache for the /media listening pulse. A podcast
# app downloads an episode in a burst of Range requests, so cache the device-
# token lookup briefly to avoid a Firestore read per chunk. Bounded so a long-
# lived instance can't grow it without limit (cleared wholesale on overflow —
# entries are cheap to repopulate).
_user_platform_cache: dict[str, tuple[Optional[str], float]] = {}
_USER_PLATFORM_TTL_SECONDS = 300.0
_USER_PLATFORM_CACHE_MAX = 5000


def _user_device_platform(container, user_id: str) -> Optional[str]:
    """Best-effort platform for a user from their newest active device token.

    The /media attribution fallback: when the podcast client's User-Agent is a
    cross-platform one we can't resolve (e.g. Pocket Casts), we still know which
    stack the *user* is on from the device token they registered for push.
    Returns None if the user has no device token or on any lookup error — this
    must never break audio delivery.
    """
    now = time.monotonic()
    cached = _user_platform_cache.get(user_id)
    if cached is not None and cached[1] > now:
        return cached[0]
    platform: Optional[str] = None
    try:
        if container.control_repository is not None:
            tokens = container.control_repository.list_active_device_tokens(user_id)
            if tokens:
                platform = normalize_platform(tokens[0].platform)
    except Exception:  # pragma: no cover - never fail audio on a token read
        platform = None
    if len(_user_platform_cache) >= _USER_PLATFORM_CACHE_MAX:
        _user_platform_cache.clear()
    _user_platform_cache[user_id] = (platform, now + _USER_PLATFORM_TTL_SECONDS)
    return platform


def _range_start_bytes(range_header: str | None) -> int:
    """Best-effort start offset of a Range request, for the listening event
    only. Unlike _parse_range_header this never raises — malformed or absent
    ranges fall back to 0 so an analytics read can't break audio delivery."""
    if not range_header:
        return 0
    prefix = "bytes="
    if not range_header.startswith(prefix):
        return 0
    first = range_header[len(prefix):].strip().split(",")[0]
    start_text = first.partition("-")[0].strip()
    return int(start_text) if start_text.isdigit() else 0


def _parse_range_header(range_header: str | None, total_length: int) -> tuple[int, int] | None:
    if not range_header:
        return None

    prefix = "bytes="
    if not range_header.startswith(prefix):
        raise HTTPException(status_code=status.HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE, detail="Invalid range")

    value = range_header[len(prefix) :].strip()
    if "," in value:
        raise HTTPException(
            status_code=status.HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE,
            detail="Multiple ranges are not supported",
        )

    start_text, sep, end_text = value.partition("-")
    if not sep:
        raise HTTPException(status_code=status.HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE, detail="Invalid range")

    if start_text == "":
        if not end_text.isdigit():
            raise HTTPException(status_code=status.HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE, detail="Invalid range")
        suffix_length = int(end_text)
        if suffix_length <= 0:
            raise HTTPException(status_code=status.HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE, detail="Invalid range")
        start = max(total_length - suffix_length, 0)
        end = total_length - 1
        return start, end

    if not start_text.isdigit():
        raise HTTPException(status_code=status.HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE, detail="Invalid range")

    start = int(start_text)
    if start >= total_length:
        raise HTTPException(status_code=status.HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE, detail="Range out of bounds")

    if end_text == "":
        end = total_length - 1
    else:
        if not end_text.isdigit():
            raise HTTPException(status_code=status.HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE, detail="Invalid range")
        end = int(end_text)

    if end < start:
        raise HTTPException(status_code=status.HTTP_416_REQUESTED_RANGE_NOT_SATISFIABLE, detail="Invalid range")

    end = min(end, total_length - 1)
    return start, end
