#!/usr/bin/env bash
# One-shot, idempotent setup for the weekly cold-start swipe-deck refresh.
#
# Creates (or updates) a Cloud Scheduler job that POSTs to
# /jobs/refresh-cold-start-deck on the deployed Cloud Run service. The
# endpoint is idempotent and returns either {status: refreshed, ...} or
# {status: skipped, reason: empty_corpus} so reruns are safe.
#
# Required env:
#   GCP_PROJECT          GCP project ID (e.g. clawcast-prod)
#   SERVICE_URL          Cloud Run base URL (e.g. https://newsletter-pod-xxx.run.app)
#   JOB_TRIGGER_TOKEN    Same token configured on the Cloud Run service
#
# Optional env:
#   REGION               Scheduler region (default: europe-west1)
#   JOB_NAME             Scheduler job ID (default: newsletter-pod-cold-start-refresh)
#   SCHEDULE             cron expression (default: "0 3 * * 0" — Sundays 03:00)
#   TIME_ZONE            IANA tz (default: Europe/Copenhagen)
#
# Usage:
#   GCP_PROJECT=clawcast-prod \
#   SERVICE_URL=https://newsletter-pod-xxx.run.app \
#   JOB_TRIGGER_TOKEN=... \
#   ./scripts/schedule_cold_start_refresh.sh

set -euo pipefail

: "${GCP_PROJECT:?GCP_PROJECT is required}"
: "${SERVICE_URL:?SERVICE_URL is required}"
: "${JOB_TRIGGER_TOKEN:?JOB_TRIGGER_TOKEN is required}"

# Strip CRLF defensively — Secret Manager values uploaded from Windows often
# carry a trailing \r, and gcloud will faithfully pass that into the header,
# causing the receiving FastAPI handler to 401 on a token mismatch.
JOB_TRIGGER_TOKEN="${JOB_TRIGGER_TOKEN//$'\r'/}"
JOB_TRIGGER_TOKEN="${JOB_TRIGGER_TOKEN//$'\n'/}"

REGION="${REGION:-europe-west1}"
JOB_NAME="${JOB_NAME:-newsletter-pod-cold-start-refresh}"
SCHEDULE="${SCHEDULE:-0 3 * * 0}"
TIME_ZONE="${TIME_ZONE:-Europe/Copenhagen}"
URI="${SERVICE_URL%/}/jobs/refresh-cold-start-deck"

common_args=(
  --location="$REGION"
  --project="$GCP_PROJECT"
  --schedule="$SCHEDULE"
  --time-zone="$TIME_ZONE"
  --uri="$URI"
  --http-method=POST
  --headers="X-Job-Trigger-Token=${JOB_TRIGGER_TOKEN},Content-Type=application/json"
  --description="Weekly recompute of the global cold-start swipe deck (k-means over source_items embeddings)."
  --attempt-deadline=300s
)

if gcloud scheduler jobs describe "$JOB_NAME" \
      --location="$REGION" \
      --project="$GCP_PROJECT" >/dev/null 2>&1; then
  echo "Updating existing scheduler job '$JOB_NAME'..."
  gcloud scheduler jobs update http "$JOB_NAME" "${common_args[@]}"
else
  echo "Creating scheduler job '$JOB_NAME'..."
  gcloud scheduler jobs create http "$JOB_NAME" "${common_args[@]}"
fi

echo
echo "Done. Verify with:"
echo "  gcloud scheduler jobs describe $JOB_NAME --location=$REGION --project=$GCP_PROJECT"
echo "Trigger manually with:"
echo "  gcloud scheduler jobs run $JOB_NAME --location=$REGION --project=$GCP_PROJECT"
