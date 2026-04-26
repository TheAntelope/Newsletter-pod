from __future__ import annotations

import logging
import secrets
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, Header, HTTPException, Request, Response, status
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from .auth import AppleIdentityVerifier, AuthError, SessionManager
from .config import Settings, load_sources
from .control_plane import ControlPlaneError, ControlPlaneService, build_task_enqueuer
from .feed import build_feed_xml
from .ingestion import RSSIngestionService
from .legal import PRIVACY_HTML, TERMS_HTML
from .mailer import NoopMailer, SMTPMailer
from .pipeline import DigestPipeline
from .podcast_api import PodcastApiClient
from .repository import FirestoreRepository, InMemoryRepository, Repository
from .retry_policy import RetryPolicy
from .storage import AudioStorage, GCSAudioStorage, InMemoryAudioStorage
from .user_repository import ControlPlaneRepository, FirestoreControlPlaneRepository, InMemoryControlPlaneRepository

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


class RunDigestRequest(BaseModel):
    force: bool = False


class AppleAuthRequest(BaseModel):
    identity_token: str
    given_name: Optional[str] = None


class UpdateMeRequest(BaseModel):
    display_name: Optional[str] = None
    timezone: Optional[str] = None


class ValidateSourceRequest(BaseModel):
    rss_url: str


class ReplaceSourcesRequest(BaseModel):
    sources: list[dict]


class UpdatePodcastConfigRequest(BaseModel):
    title: Optional[str] = None
    format_preset: Optional[str] = None
    host_primary_name: Optional[str] = None
    host_secondary_name: Optional[str] = None
    guest_names: Optional[list[str]] = None
    desired_duration_minutes: Optional[int] = None


class UpdateScheduleRequest(BaseModel):
    timezone: Optional[str] = None
    weekdays: Optional[list[str]] = None


class BillingNotificationRequest(BaseModel):
    notification_type: Optional[str] = None
    notificationType: Optional[str] = None
    subtype: Optional[str] = None
    user_id: Optional[str] = None
    app_account_token: Optional[str] = None
    product_id: Optional[str] = None
    productId: Optional[str] = None
    status: Optional[str] = None
    expires_at: Optional[str] = None
    signed_payload: Optional[str] = None


class ProcessUserRequest(BaseModel):
    user_id: str
    force: bool = False


@dataclass
class ServiceContainer:
    settings: Settings
    repository: Repository
    storage: AudioStorage
    pipeline: DigestPipeline
    control_repository: ControlPlaneRepository | None = None
    control_plane: ControlPlaneService | None = None


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

    @app.post("/jobs/run-digest")
    def run_digest(
        request_payload: RunDigestRequest,
        authorization: str | None = Header(default=None),
        x_job_trigger_token: str | None = Header(default=None),
    ) -> dict:
        _validate_job_auth(container.settings, authorization, x_job_trigger_token)
        result = container.pipeline.run_daily_digest(force=request_payload.force)
        return result.model_dump(mode="json")

    @app.post("/jobs/dispatch-weekly-podcasts")
    def dispatch_weekly_podcasts(
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
        return container.control_plane.process_user_generation(
            user_id=request_payload.user_id,
            force=request_payload.force,
        )

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

    @app.get("/v1/sources/catalog")
    def get_source_catalog() -> dict:
        assert container.control_plane is not None
        return {"sources": container.control_plane.get_source_catalog()}

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
        authorization: str | None = Header(default=None),
    ) -> dict:
        user = _require_session_user(container, authorization)
        assert container.control_plane is not None
        try:
            return container.control_plane.replace_user_sources(user.id, request_payload.sources)
        except Exception as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

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
            )
        except ControlPlaneError as exc:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))

    @app.get("/v1/me/feed")
    def get_feed_details(authorization: str | None = Header(default=None)) -> dict:
        user = _require_session_user(container, authorization)
        assert container.control_plane is not None
        return container.control_plane.get_feed_details(user.id)

    @app.post("/v1/me/generate")
    def generate_episode_now(authorization: str | None = Header(default=None)) -> dict:
        user = _require_session_user(container, authorization)
        assert container.control_plane is not None
        return container.control_plane.process_user_generation(user_id=user.id, force=True)

    @app.post("/v1/billing/app-store/notifications")
    def receive_billing_notification(request_payload: BillingNotificationRequest) -> dict:
        assert container.control_plane is not None
        return container.control_plane.apply_app_store_notification(request_payload.model_dump(exclude_none=True))

    @app.api_route("/feed/{secret_token}.xml", methods=["GET", "HEAD"], response_class=Response)
    def get_private_feed(secret_token: str, request: Request) -> Response:
        _validate_feed_token_or_404(container.settings.feed_token, secret_token)

        episodes = container.repository.list_recent_episodes(container.settings.max_feed_episodes)
        base_url = container.settings.app_base_url.rstrip("/")
        feed_url = f"{base_url}/feed/{secret_token}.xml"

        xml_content = build_feed_xml(
            title=container.settings.podcast_title,
            description=container.settings.podcast_description,
            author=container.settings.podcast_author,
            language=container.settings.podcast_language,
            feed_url=feed_url,
            image_url=container.settings.podcast_image_url,
            episodes=episodes,
            media_url_builder=lambda episode: (
                f"{base_url}/media/{secret_token}/{episode.id}.mp3"
            ),
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
    ) -> Response:
        episode = None
        if secrets.compare_digest(container.settings.feed_token, secret_token):
            episode = container.repository.get_episode(episode_id)
        else:
            assert container.control_repository is not None
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

        return _build_media_response(
            audio_bytes=audio_bytes,
            media_type=episode.audio_mime_type,
            request=request,
            range_header=range_header,
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
        repository = InMemoryRepository()
        storage: AudioStorage = InMemoryAudioStorage()
    else:
        repository = FirestoreRepository(settings.firestore_collection_prefix)
        if not settings.gcs_bucket_name:
            raise RuntimeError("GCS_BUCKET_NAME is required when USE_INMEMORY_ADAPTERS=false")
        storage = GCSAudioStorage(settings.gcs_bucket_name, prefix=settings.gcs_prefix)

    sources = load_sources(settings.sources_file)
    ingestion = RSSIngestionService(
        repository=repository,
        bootstrap_max_items_per_source=settings.podcast_bootstrap_max_items_per_source,
    )
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
    )

    mailer_required = settings.alert_email_enabled or settings.publish_summary_email_enabled
    if mailer_required:
        required = [
            settings.smtp_host,
            settings.alert_email_from,
            settings.alert_email_to,
        ]
        if not all(required):
            raise RuntimeError("Email delivery is enabled but SMTP or email addresses are missing")
        mailer = SMTPMailer(
            host=settings.smtp_host or "",
            port=settings.smtp_port,
            username=settings.smtp_username,
            password=settings.smtp_password,
            sender=settings.alert_email_from or "",
            recipient=settings.alert_email_to or "",
            use_tls=settings.smtp_use_tls,
        )
    else:
        mailer = NoopMailer()

    retry_policy = RetryPolicy(
        timezone_name=settings.app_timezone,
        start_local=settings.schedule_start_local,
        target_local=settings.schedule_target_local,
        cutoff_local=settings.schedule_cutoff_local,
        rapid_retry_minutes=settings.rapid_retry_minutes,
        periodic_retry_minutes=settings.periodic_retry_minutes,
    )

    pipeline = DigestPipeline(
        sources=sources,
        repository=repository,
        ingestion_service=ingestion,
        podcast_client=podcast_client,
        storage=storage,
        mailer=mailer,
        retry_policy=retry_policy,
        podcast_ux=settings.podcast_ux_config(),
        app_base_url=settings.app_base_url,
        feed_token=settings.feed_token,
        publish_summary_email_enabled=settings.publish_summary_email_enabled,
    )

    control_repository, control_plane = _build_control_plane(
        settings=settings,
        storage=storage,
        podcast_client=podcast_client,
        mailer=mailer,
    )

    return ServiceContainer(
        settings=settings,
        repository=repository,
        storage=storage,
        pipeline=pipeline,
        control_repository=control_repository,
        control_plane=control_plane,
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

    podcast_client = podcast_client or PodcastApiClient(
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
    )
    session_manager = SessionManager(
        signing_secret=settings.session_signing_secret,
        ttl_hours=settings.session_ttl_hours,
    )
    apple_verifier = AppleIdentityVerifier(settings.apple_client_id)
    task_enqueuer = build_task_enqueuer(settings)
    control_plane = ControlPlaneService(
        settings=settings,
        repository=control_repository,
        storage=storage,
        podcast_client=podcast_client,
        mailer=mailer or NoopMailer(),
        session_manager=session_manager,
        apple_identity_verifier=apple_verifier,
        task_enqueuer=task_enqueuer,
    )
    return control_repository, control_plane


def _validate_feed_token_or_404(expected: str, provided: str) -> None:
    if not secrets.compare_digest(expected, provided):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Not found")


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


def _build_xml_response(xml_content: str, request: Request) -> Response:
    xml_bytes = xml_content.encode("utf-8")
    headers = {
        "Content-Length": str(len(xml_bytes)),
        "Accept-Ranges": "bytes",
    }
    if request.method == "HEAD":
        return Response(content=b"", media_type="application/rss+xml", headers=headers)
    return Response(content=xml_bytes, media_type="application/rss+xml", headers=headers)


def _build_media_response(
    audio_bytes: bytes,
    media_type: str,
    request: Request,
    range_header: str | None,
) -> Response:
    total_length = len(audio_bytes)
    headers = {"Accept-Ranges": "bytes"}
    range_spec = _parse_range_header(range_header, total_length)

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
