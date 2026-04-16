from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Optional

import jwt
import requests
from jwt import PyJWKClient

from .user_models import AppleIdentity, AuthenticatedSession


class AuthError(RuntimeError):
    pass


class AppleIdentityVerifier:
    _APPLE_JWKS_URL = "https://appleid.apple.com/auth/keys"
    _APPLE_ISSUER = "https://appleid.apple.com"

    def __init__(self, client_id: Optional[str]) -> None:
        self._client_id = client_id
        self._jwks_client = PyJWKClient(self._APPLE_JWKS_URL)

    def verify(self, identity_token: str) -> AppleIdentity:
        if not self._client_id:
            raise AuthError("APPLE_CLIENT_ID is not configured")

        try:
            signing_key = self._jwks_client.get_signing_key_from_jwt(identity_token)
            claims = jwt.decode(
                identity_token,
                signing_key.key,
                algorithms=["RS256"],
                audience=self._client_id,
                issuer=self._APPLE_ISSUER,
            )
        except (jwt.InvalidTokenError, requests.RequestException) as exc:
            raise AuthError("Invalid Apple identity token") from exc

        subject = claims.get("sub")
        if not subject:
            raise AuthError("Apple identity token missing subject")

        return AppleIdentity(
            subject=subject,
            email=claims.get("email"),
        )


class SessionManager:
    def __init__(
        self,
        signing_secret: str,
        ttl_hours: int = 720,
        issuer: str = "newsletter-pod",
    ) -> None:
        self._signing_secret = signing_secret
        self._ttl_hours = ttl_hours
        self._issuer = issuer

    def issue(self, user_id: str) -> tuple[str, AuthenticatedSession]:
        now = datetime.now(timezone.utc)
        expires_at = now + timedelta(hours=self._ttl_hours)
        token = jwt.encode(
            {
                "sub": user_id,
                "iss": self._issuer,
                "iat": int(now.timestamp()),
                "exp": int(expires_at.timestamp()),
            },
            self._signing_secret,
            algorithm="HS256",
        )
        return token, AuthenticatedSession(
            user_id=user_id,
            issued_at=now,
            expires_at=expires_at,
        )

    def verify(self, token: str) -> AuthenticatedSession:
        try:
            claims = jwt.decode(
                token,
                self._signing_secret,
                algorithms=["HS256"],
                issuer=self._issuer,
            )
        except jwt.InvalidTokenError as exc:
            raise AuthError("Invalid session token") from exc

        user_id = claims.get("sub")
        if not user_id:
            raise AuthError("Session token missing subject")

        issued_at = datetime.fromtimestamp(claims["iat"], tz=timezone.utc)
        expires_at = datetime.fromtimestamp(claims["exp"], tz=timezone.utc)
        return AuthenticatedSession(
            user_id=user_id,
            issued_at=issued_at,
            expires_at=expires_at,
        )
