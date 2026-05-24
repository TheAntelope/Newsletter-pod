"""Wrap Apple's `SignedDataVerifier` to expose just what the billing
notification handler needs.

App Store Server Notifications V2 deliver `{"signedPayload": "<JWS>"}`.
The JWS payload (`ResponseBodyV2DecodedPayload`) contains a `data` block
whose `signedTransactionInfo` is *itself* another JWS that carries the
transaction details (`productId`, `appAccountToken`, expiry, etc.).
Both signatures must be verified against Apple's certificate chain
before any tier change can be trusted.

The verifier loads `AppleRootCA-G3.cer` from this package's `data/`
directory; it's bundled via setuptools `package-data`, so the file
ships inside the wheel + Docker image.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from appstoreserverlibrary.models.Environment import Environment
from appstoreserverlibrary.signed_data_verifier import (
    SignedDataVerifier,
    VerificationException,
)

logger = logging.getLogger(__name__)

_APPLE_ROOT_CA_G3_PATH = Path(__file__).resolve().parent / "data" / "AppleRootCA-G3.cer"


class AppStoreVerificationError(RuntimeError):
    """Raised when an App Store notification payload fails JWS verification.

    The handler turns this into an HTTP 400. Apple retries on non-2xx,
    so legitimate retries still land once the server is healthy and
    misconfigured ones surface in logs.
    """


@dataclass
class DecodedNotification:
    """The subset of a verified App Store notification the billing
    handler actually acts on. Everything here is sourced from a JWS
    payload Apple signed — caller can trust these values."""

    notification_type: str
    subtype: Optional[str]
    notification_uuid: Optional[str]
    bundle_id: Optional[str]
    environment: Optional[str]
    transaction_id: Optional[str]
    product_id: Optional[str]
    app_account_token: Optional[str]
    expires_date_ms: Optional[int]
    revocation_date_ms: Optional[int]


@dataclass
class DecodedTransaction:
    """A verified StoreKit2 transaction (Apple-signed). Returned by
    `verify_transaction` for the iOS client-push path."""

    transaction_id: Optional[str]
    product_id: Optional[str]
    app_account_token: Optional[str]
    expires_date_ms: Optional[int]
    revocation_date_ms: Optional[int]
    bundle_id: Optional[str]
    environment: Optional[str]


class AppStoreNotificationVerifier:
    """Lightweight wrapper around Apple's `SignedDataVerifier`.

    Construct one of these at app startup. The cert-chain parsing
    happens inside `SignedDataVerifier.__init__`, so reuse the instance
    across requests instead of building it per call.
    """

    def __init__(
        self,
        *,
        bundle_id: str,
        environment: str,
        app_apple_id: Optional[int],
        root_cert_path: Optional[Path] = None,
    ) -> None:
        env = _parse_environment(environment)
        if env is Environment.PRODUCTION and app_apple_id is None:
            raise RuntimeError(
                "APP_STORE_APP_APPLE_ID is required when "
                "APP_STORE_ENVIRONMENT='production'"
            )
        cert_path = root_cert_path or _APPLE_ROOT_CA_G3_PATH
        if not cert_path.exists():
            raise RuntimeError(
                f"Apple root CA cert missing at {cert_path}. "
                "Make sure newsletter_pod/data/AppleRootCA-G3.cer is bundled."
            )
        root_cert_bytes = cert_path.read_bytes()
        self._verifier = SignedDataVerifier(
            root_certificates=[root_cert_bytes],
            enable_online_checks=False,
            environment=env,
            bundle_id=bundle_id,
            app_apple_id=app_apple_id,
        )
        self._bundle_id = bundle_id
        self._environment = env

    @property
    def environment(self) -> Environment:
        return self._environment

    def verify(self, signed_payload: str) -> DecodedNotification:
        """Verify the outer notification JWS and (when present) the
        nested `signedTransactionInfo` JWS, then collapse the verified
        fields into a `DecodedNotification`. Raises
        `AppStoreVerificationError` on any signature failure."""
        if not signed_payload:
            raise AppStoreVerificationError("signedPayload is empty")
        try:
            notification = self._verifier.verify_and_decode_notification(signed_payload)
        except VerificationException as exc:
            raise AppStoreVerificationError(
                f"signedPayload verification failed: {exc}"
            ) from exc

        data = notification.data
        transaction = None
        if data and data.signedTransactionInfo:
            try:
                transaction = self._verifier.verify_and_decode_signed_transaction(
                    data.signedTransactionInfo
                )
            except VerificationException as exc:
                raise AppStoreVerificationError(
                    f"signedTransactionInfo verification failed: {exc}"
                ) from exc

        return DecodedNotification(
            notification_type=notification.rawNotificationType or "",
            subtype=notification.rawSubtype,
            notification_uuid=notification.notificationUUID,
            bundle_id=data.bundleId if data else None,
            environment=(data.rawEnvironment if data else None),
            transaction_id=transaction.transactionId if transaction else None,
            product_id=transaction.productId if transaction else None,
            app_account_token=transaction.appAccountToken if transaction else None,
            expires_date_ms=transaction.expiresDate if transaction else None,
            revocation_date_ms=transaction.revocationDate if transaction else None,
        )

    def verify_transaction(self, signed_transaction_info: str) -> DecodedTransaction:
        """Verify a StoreKit2 `Transaction.jwsRepresentation` and return
        the decoded fields. Sandbox ASN delivery is unreliable, so the
        iOS client pushes this JWS to the backend directly after a
        successful purchase as the source of truth for tier upgrades."""
        if not signed_transaction_info:
            raise AppStoreVerificationError("signed_transaction_info is empty")
        try:
            transaction = self._verifier.verify_and_decode_signed_transaction(
                signed_transaction_info
            )
        except VerificationException as exc:
            raise AppStoreVerificationError(
                f"signed_transaction_info verification failed: {exc}"
            ) from exc
        return DecodedTransaction(
            transaction_id=transaction.transactionId,
            product_id=transaction.productId,
            app_account_token=transaction.appAccountToken,
            expires_date_ms=transaction.expiresDate,
            revocation_date_ms=transaction.revocationDate,
            bundle_id=transaction.bundleId,
            environment=transaction.rawEnvironment,
        )


def _parse_environment(value: str) -> Environment:
    normalized = (value or "").strip().lower()
    if normalized in {"production", "prod"}:
        return Environment.PRODUCTION
    if normalized in {"sandbox", "dev", "test"}:
        return Environment.SANDBOX
    if normalized == "xcode":
        return Environment.XCODE
    if normalized in {"local", "local_testing"}:
        return Environment.LOCAL_TESTING
    raise RuntimeError(f"Unknown APP_STORE_ENVIRONMENT value: {value!r}")
