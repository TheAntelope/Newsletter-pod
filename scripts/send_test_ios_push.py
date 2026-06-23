"""Send a single test pod-ready push to a user's ACTIVE iOS FCM token(s) only.

Isolates the Flutter iOS → FCM → APNs leg without generating an episode.
Reads the fcm-service-account from Secret Manager, builds the same FcmSender
the app uses, and prints the per-token FCM response.

Usage (PowerShell):
    $env:GOOGLE_CLOUD_PROJECT = "newsletter-pod"
    python scripts/send_test_ios_push.py --user-id 5c7ef3a8b9f14bf7a09a7db21b896d6d
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from google.cloud import firestore

from newsletter_pod.push import FcmSender

PREFIXES = ["newsletter_pod", "control_plane"]


def _service_account() -> dict:
    # Pass the fcm-service-account JSON in via env var to avoid spawning gcloud
    # from Python on Windows (gcloud is a .cmd, not found by subprocess):
    #   FCM_SERVICE_ACCOUNT_JSON=$(gcloud secrets versions access latest \
    #       --secret fcm-service-account) python scripts/send_test_ios_push.py ...
    raw = os.environ.get("FCM_SERVICE_ACCOUNT_JSON")
    if not raw:
        print(
            "Set FCM_SERVICE_ACCOUNT_JSON from the fcm-service-account secret first.",
            file=sys.stderr,
        )
        sys.exit(2)
    return json.loads(raw)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--user-id", required=True)
    ap.add_argument("--project", default="newsletter-pod")
    ap.add_argument("--firebase-project", default="theclawcast-9a045")
    args = ap.parse_args()

    db = firestore.Client(project=args.project)

    # device tokens live under whichever prefix actually has them
    tokens = []
    for p in PREFIXES:
        tokens = list(
            db.collection(f"{p}_device_tokens")
            .where("user_id", "==", args.user_id)
            .stream()
        )
        if tokens:
            break

    ios = [
        t.to_dict() for t in tokens
        if (t.to_dict().get("platform") == "ios"
            and t.to_dict().get("invalidated_at") is None)
    ]
    # de-dupe by token string (same device can have multiple docs)
    seen, ios_unique = set(), []
    for d in ios:
        tok = d.get("token")
        if tok and tok not in seen:
            seen.add(tok)
            ios_unique.append(d)

    if not ios_unique:
        print("No active iOS tokens for this user.", file=sys.stderr)
        sys.exit(1)

    print(f"Active iOS tokens: {len(ios_unique)}")
    sa = _service_account()
    sender = FcmSender(project_id=args.firebase_project, service_account_info=sa)

    for d in ios_unique:
        tok = d["token"]
        res = sender.send(
            device_token=tok,
            notification={
                "title": "Your briefing is ready",
                "body": "TEST push — confirming iOS delivery. Tap to open.",
            },
            data={"type": "pod_ready"},
            collapse_key=f"pod-ready-{args.user_id[:8]}",
        )
        print(
            f"  token=…{tok[-8:]} last_seen={d.get('last_seen_at')} "
            f"-> status={res.status_code} reason={res.reason} "
            f"token_invalid={res.token_invalid}"
        )


if __name__ == "__main__":
    main()
