"""APNs (Apple Push Notification service) sender.

Token-based authentication using an ES256-signed JWT (Apple's auth flow as
of 2024): we generate the JWT once per ~50 minutes (Apple caps the lifetime
at ~60 min) and reuse it across all sends in that window. Pushes go to
`api.push.apple.com` (production) or `api.sandbox.push.apple.com` (sandbox)
over HTTP/2.

The sender is intentionally narrow:
- One public entry point, `send_substack_verification_push`, that picks the
  user's active device tokens and pushes the verification-code payload.
- 410 Gone deregisters the token (Apple's way of saying "the user
  uninstalled / disabled notifications for your app"); other 4xx are logged
  but not retried — the next push attempt will try again.
- Disabled in tests / local dev unless `apns_enabled` is True AND
  `apns_auth_key` is set; otherwise the sender no-ops with a single
  INFO log so call sites can still invoke it unconditionally.

When we extend this to "your pod is ready" notifications, the JWT cache and
HTTP/2 client stay; a new payload helper plus a thin public function on top
of `_send_payload` is all that's needed.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Callable, Optional

import httpx
import jwt

from .user_models import DeviceTokenRecord
from .user_repository import ControlPlaneRepository
from .utils import utc_now

logger = logging.getLogger(__name__)

# Apple's docs say the JWT must be no older than 1 hour. We refresh at 50
# minutes to leave headroom for clock skew between us and Apple's edge.
_JWT_REFRESH_SECONDS = 50 * 60

_APNS_HOSTS = {
    "production": "https://api.push.apple.com",
    "sandbox": "https://api.sandbox.push.apple.com",
}

# Apple's recommended timeout for a single push: 10s is generous for the
# typical sub-second response and tight enough that a hung TCP connection
# can't stall the inbound webhook for long.
_PUSH_TIMEOUT_SECONDS = 10.0

# FCM HTTP v1 send endpoint + the OAuth scope a service account needs to call it.
_FCM_SEND_URL = "https://fcm.googleapis.com/v1/projects/{project_id}/messages:send"
_FCM_SCOPE = "https://www.googleapis.com/auth/firebase.messaging"


class PushConfigError(Exception):
    """Raised when send is attempted but APNs is not properly configured."""


@dataclass
class PushSender:
    """Thread-safe APNs sender with a cached JWT."""

    team_id: str
    key_id: str
    auth_key_pem: str
    bundle_id: str
    environment: str = "production"
    _jwt: Optional[str] = None
    _jwt_issued_at: float = 0.0
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _http_client: Optional[httpx.Client] = None

    @property
    def host(self) -> str:
        host = _APNS_HOSTS.get(self.environment)
        if host is None:
            raise PushConfigError(
                f"Unknown APNs environment {self.environment!r}; expected 'production' or 'sandbox'"
            )
        return host

    def _get_client(self) -> httpx.Client:
        if self._http_client is None:
            # APNs requires HTTP/2. http2=True forces the h2 library path.
            self._http_client = httpx.Client(http2=True, timeout=_PUSH_TIMEOUT_SECONDS)
        return self._http_client

    def _current_jwt(self) -> str:
        """Return a valid provider JWT, regenerating if cache is stale."""
        with self._lock:
            now = time.time()
            if self._jwt is None or (now - self._jwt_issued_at) >= _JWT_REFRESH_SECONDS:
                self._jwt = jwt.encode(
                    payload={"iss": self.team_id, "iat": int(now)},
                    key=self.auth_key_pem,
                    algorithm="ES256",
                    headers={"alg": "ES256", "kid": self.key_id},
                )
                self._jwt_issued_at = now
            return self._jwt

    def send(
        self,
        *,
        device_token: str,
        payload: dict,
        push_type: str = "alert",
        priority: int = 10,
        collapse_id: Optional[str] = None,
    ) -> "PushResult":
        url = f"{self.host}/3/device/{device_token}"
        headers = {
            "authorization": f"bearer {self._current_jwt()}",
            "apns-topic": self.bundle_id,
            "apns-push-type": push_type,
            "apns-priority": str(priority),
        }
        if collapse_id:
            headers["apns-collapse-id"] = collapse_id

        try:
            response = self._get_client().post(url, json=payload, headers=headers)
        except httpx.HTTPError as exc:
            logger.warning("APNs send raised: %s device_token_prefix=%s", exc, device_token[:8])
            return PushResult(status_code=0, reason="transport_error", token_invalid=False)

        # Apple returns 200 with empty body on success; 4xx/5xx returns JSON
        # `{"reason": "Reason"}`. 410 specifically means the token is no
        # longer valid for this app — we deregister it.
        if response.status_code == 200:
            return PushResult(status_code=200, reason=None, token_invalid=False)
        reason: Optional[str] = None
        try:
            reason = (response.json() or {}).get("reason")
        except Exception:
            reason = None
        token_invalid = response.status_code == 410 or reason in {"BadDeviceToken", "Unregistered"}
        if not token_invalid:
            logger.warning(
                "APNs send non-2xx: status=%s reason=%s device_token_prefix=%s",
                response.status_code,
                reason,
                device_token[:8],
            )
        return PushResult(status_code=response.status_code, reason=reason, token_invalid=token_invalid)


@dataclass
class PushResult:
    status_code: int
    reason: Optional[str]
    token_invalid: bool


class FcmConfigError(Exception):
    """Raised when an FCM send is attempted but FCM is not properly configured."""


@dataclass
class FcmSender:
    """Thread-safe FCM HTTP v1 sender (the Android counterpart to [PushSender]).

    Auth is an OAuth2 access token minted from the Firebase service account
    (scope ``firebase.messaging``); google-auth caches + refreshes it, so we
    just ask for ``credentials.token`` and refresh when it goes invalid. Tests
    inject [access_token_provider] to avoid needing real Google credentials.
    """

    project_id: str
    service_account_info: dict
    # Tests set this to bypass google-auth; production leaves it None and mints
    # a token from the service account.
    access_token_provider: Optional[Callable[[], str]] = None
    _credentials: Optional[object] = None
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _http_client: Optional[httpx.Client] = None

    def _get_client(self) -> httpx.Client:
        if self._http_client is None:
            self._http_client = httpx.Client(timeout=_PUSH_TIMEOUT_SECONDS)
        return self._http_client

    def _access_token(self) -> str:
        if self.access_token_provider is not None:
            return self.access_token_provider()
        # Imported lazily so the module loads even where google-auth isn't
        # present, and so the no-op (disabled) path never touches it.
        from google.auth.transport.requests import Request as GoogleAuthRequest
        from google.oauth2 import service_account

        with self._lock:
            creds = self._credentials
            if creds is None:
                creds = service_account.Credentials.from_service_account_info(
                    self.service_account_info, scopes=[_FCM_SCOPE]
                )
                self._credentials = creds
            if not creds.valid:
                creds.refresh(GoogleAuthRequest())
            return creds.token

    def send(
        self,
        *,
        device_token: str,
        notification: dict,
        data: Optional[dict] = None,
        collapse_key: Optional[str] = None,
    ) -> "PushResult":
        url = _FCM_SEND_URL.format(project_id=self.project_id)
        message: dict = {
            "token": device_token,
            "notification": notification,
            # FCM data values must be strings.
            "data": {k: str(v) for k, v in (data or {}).items()},
            "android": {"priority": "high"},
        }
        if collapse_key:
            message["android"]["collapse_key"] = collapse_key
        headers = {
            "Authorization": f"Bearer {self._access_token()}",
            "Content-Type": "application/json",
        }

        try:
            response = self._get_client().post(
                url, json={"message": message}, headers=headers
            )
        except httpx.HTTPError as exc:
            logger.warning("FCM send raised: %s token_prefix=%s", exc, device_token[:8])
            return PushResult(status_code=0, reason="transport_error", token_invalid=False)

        if response.status_code == 200:
            return PushResult(status_code=200, reason=None, token_invalid=False)

        # FCM v1 errors look like
        # {"error": {"status": "NOT_FOUND", "details": [{"errorCode": "UNREGISTERED"}]}}
        reason: Optional[str] = None
        error_codes: set[str] = set()
        try:
            body = response.json() or {}
            error = body.get("error") or {}
            reason = error.get("status")
            for detail in error.get("details") or []:
                if isinstance(detail, dict) and detail.get("errorCode"):
                    error_codes.add(detail["errorCode"])
        except Exception:
            reason = None
        # Only UNREGISTERED (or a bare 404) reliably means the token is dead.
        # INVALID_ARGUMENT can also mean a malformed message (our bug), so we
        # log it but do NOT deregister on it.
        token_invalid = response.status_code == 404 or "UNREGISTERED" in error_codes
        if not token_invalid:
            logger.warning(
                "FCM send non-2xx: status=%s reason=%s codes=%s token_prefix=%s",
                response.status_code,
                reason,
                error_codes or None,
                device_token[:8],
            )
        return PushResult(
            status_code=response.status_code, reason=reason, token_invalid=token_invalid
        )


def build_substack_verification_payload(*, code: str, pub_title: str) -> dict:
    """Construct the APNs JSON body for a Substack verification-code push.

    `category` is a string the iOS notification-handler matches on to know
    this is a Substack-code push (so a tap can copy + open the pub URL).
    Adding `mutable-content: 1` would let a Notification Service Extension
    rewrite the body — not used yet, but cheap to include for forward compat.
    """
    return {
        "aps": {
            "alert": {
                "title": "Substack verification code",
                "body": f"{code} for {pub_title} — expires in ~15 min. Tap to copy.",
            },
            "sound": "default",
            "category": "SUBSTACK_VERIFICATION",
            "mutable-content": 1,
        },
        "type": "substack_verification",
        "code": code,
        "pub_title": pub_title,
    }


def send_substack_verification_push(
    *,
    sender: Optional[PushSender],
    repository: ControlPlaneRepository,
    user_id: str,
    code: str,
    pub_title: str,
    pub_url: Optional[str] = None,
    fcm_sender: Optional["FcmSender"] = None,
) -> dict:
    """Send the Substack verification-code push to every active device the
    user has, routing iOS tokens through APNs ([sender]) and Android tokens
    through FCM ([fcm_sender]). No-ops with an INFO log when BOTH senders are
    None (push disabled in this environment) so callers can invoke
    unconditionally. A token whose platform has no configured sender is skipped.

    Returns a small dict useful for tests / logs (attempted counts only tokens
    we actually tried — i.e. had a sender for):
      {"attempted": N, "delivered": K, "deregistered": M}
    """
    if sender is None and fcm_sender is None:
        logger.info(
            "Push senders unavailable; skipping verification-code push: user=%s",
            user_id,
        )
        return {"attempted": 0, "delivered": 0, "deregistered": 0}

    tokens = repository.list_active_device_tokens(user_id)
    if not tokens:
        logger.info(
            "No active device tokens for verification-code push: user=%s",
            user_id,
        )
        return {"attempted": 0, "delivered": 0, "deregistered": 0}

    apns_payload = build_substack_verification_payload(code=code, pub_title=pub_title)
    if pub_url:
        apns_payload["pub_url"] = pub_url

    # FCM uses a notification block + a string-valued data map rather than the
    # APNs `aps` dict; the Android handler reads `data` to act on the tap.
    fcm_notification = {
        "title": "Substack verification code",
        "body": f"{code} for {pub_title} — expires in ~15 min. Tap to copy.",
    }
    fcm_data: dict = {
        "type": "substack_verification",
        "code": code,
        "pub_title": pub_title,
    }
    if pub_url:
        fcm_data["pub_url"] = pub_url

    attempted = 0
    delivered = 0
    deregistered = 0
    # A stable collapse id ensures retry storms (e.g. rapidly hitting Resend)
    # show a single notification with the freshest code, on both platforms.
    collapse_id = f"substack-verify-{user_id[:8]}"
    for record in tokens:
        platform = (record.platform or "ios").lower()
        if platform == "android":
            if fcm_sender is None:
                logger.info(
                    "FCM sender unavailable; skipping android token: user=%s token_prefix=%s",
                    user_id,
                    record.token[:8],
                )
                continue
            result = fcm_sender.send(
                device_token=record.token,
                notification=fcm_notification,
                data=fcm_data,
                collapse_key=collapse_id,
            )
        else:
            if sender is None:
                logger.info(
                    "APNs sender unavailable; skipping ios token: user=%s token_prefix=%s",
                    user_id,
                    record.token[:8],
                )
                continue
            result = sender.send(
                device_token=record.token,
                payload=apns_payload,
                push_type="alert",
                priority=10,
                collapse_id=collapse_id,
            )

        attempted += 1
        if result.status_code == 200:
            delivered += 1
            continue
        if result.token_invalid:
            invalidated = record.model_copy(update={"invalidated_at": utc_now()})
            repository.save_device_token(invalidated)
            deregistered += 1
            logger.info(
                "Deregistered device token after invalid response: user=%s platform=%s token_prefix=%s",
                user_id,
                platform,
                record.token[:8],
            )

    return {"attempted": attempted, "delivered": delivered, "deregistered": deregistered}


def build_push_sender_from_settings(
    *,
    enabled: bool,
    team_id: Optional[str],
    key_id: Optional[str],
    auth_key_pem: Optional[str],
    bundle_id: str,
    environment: str,
) -> Optional[PushSender]:
    """Factory that returns None when APNs isn't fully configured. Lets the
    container builder decide once at startup whether the sender is alive.
    """
    if not enabled:
        return None
    if not (team_id and key_id and auth_key_pem):
        logger.info(
            "APNs enabled but config incomplete (team_id=%s key_id=%s auth_key=%s); push sender disabled",
            bool(team_id),
            bool(key_id),
            bool(auth_key_pem),
        )
        return None
    return PushSender(
        team_id=team_id,
        key_id=key_id,
        auth_key_pem=auth_key_pem,
        bundle_id=bundle_id,
        environment=environment,
    )


def build_fcm_sender_from_settings(
    *,
    enabled: bool,
    service_account_json: Optional[str],
    project_id: Optional[str],
) -> Optional[FcmSender]:
    """Factory that returns None when FCM isn't fully configured (disabled, or
    no service-account JSON / project id), mirroring [build_push_sender_from_settings].
    The container builder decides once at startup whether the sender is alive.
    """
    if not enabled:
        return None
    if not (service_account_json and project_id):
        logger.info(
            "FCM enabled but config incomplete (service_account=%s project_id=%s); FCM sender disabled",
            bool(service_account_json),
            bool(project_id),
        )
        return None
    try:
        info = json.loads(service_account_json)
    except (ValueError, TypeError) as exc:
        logger.warning(
            "FCM service-account JSON is not valid JSON; FCM sender disabled: %s", exc
        )
        return None
    return FcmSender(project_id=project_id, service_account_info=info)
