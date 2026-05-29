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

import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Optional

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
) -> dict:
    """Send the Substack verification-code push to every active device the
    user has. No-ops with an INFO log when the sender is None (APNs disabled
    in this environment) so callers can invoke unconditionally.

    Returns a small dict useful for tests / logs:
      {"attempted": N, "delivered": K, "deregistered": M}
    """
    if sender is None:
        logger.info(
            "APNs sender unavailable; skipping verification-code push: user=%s",
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

    payload = build_substack_verification_payload(code=code, pub_title=pub_title)
    if pub_url:
        payload["pub_url"] = pub_url

    delivered = 0
    deregistered = 0
    # collapse_id ensures retry storms (e.g. user rapidly hitting Resend on
    # Substack) result in a single visible notification, replacing earlier
    # codes with the freshest one.
    collapse_id = f"substack-verify-{user_id[:8]}"
    for record in tokens:
        result = sender.send(
            device_token=record.token,
            payload=payload,
            push_type="alert",
            priority=10,
            collapse_id=collapse_id,
        )
        if result.status_code == 200:
            delivered += 1
            continue
        if result.token_invalid:
            invalidated = record.model_copy(update={"invalidated_at": utc_now()})
            repository.save_device_token(invalidated)
            deregistered += 1
            logger.info(
                "Deregistered APNs token after 410/BadDeviceToken: user=%s token_prefix=%s",
                user_id,
                record.token[:8],
            )

    return {"attempted": len(tokens), "delivered": delivered, "deregistered": deregistered}


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
