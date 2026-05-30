#!/usr/bin/env bash
# Idempotent setup for a daily broadcast-loop Cloud Scheduler job.
#
# One scheduler job per loop. Each fires at the loop's local post time
# and POSTs to /jobs/broadcast/loops/<loop_id>/run. Inactive loops
# return 200 with {status: skipped} so the scheduler stays green
# during pauses.
#
# Required env:
#   GCP_PROJECT          GCP project ID (e.g. clawcast-prod)
#   SERVICE_URL          Cloud Run base URL (e.g. https://newsletter-pod-xxx.run.app)
#   JOB_TRIGGER_TOKEN    Same token configured on the Cloud Run service
#   LOOP_ID              Loop id this scheduler entry should drive
#   LOCAL_HOUR           0-23, the local hour the run should fire
#   TIME_ZONE            IANA tz, e.g. America/Los_Angeles
#
# Optional env:
#   LOCAL_MINUTE         0-59 (default: 0)
#   REGION               Scheduler region (default: europe-west1)
#   JOB_NAME             Scheduler job ID (default: broadcast-loop-${LOOP_ID})
#   ATTEMPT_DEADLINE     gcloud --attempt-deadline (default: 900s)
#
# Usage:
#   GCP_PROJECT=clawcast-prod \
#   SERVICE_URL=https://newsletter-pod-xxx.run.app \
#   JOB_TRIGGER_TOKEN=... \
#   LOOP_ID=us-morning \
#   LOCAL_HOUR=8 \
#   TIME_ZONE=America/Los_Angeles \
#   ./scripts/schedule_broadcast_loop.sh

set -euo pipefail

: "${GCP_PROJECT:?GCP_PROJECT is required}"
: "${SERVICE_URL:?SERVICE_URL is required}"
: "${JOB_TRIGGER_TOKEN:?JOB_TRIGGER_TOKEN is required}"
: "${LOOP_ID:?LOOP_ID is required}"
: "${LOCAL_HOUR:?LOCAL_HOUR is required}"
: "${TIME_ZONE:?TIME_ZONE is required}"

LOCAL_MINUTE="${LOCAL_MINUTE:-0}"
REGION="${REGION:-europe-west1}"
JOB_NAME="${JOB_NAME:-broadcast-loop-${LOOP_ID}}"
ATTEMPT_DEADLINE="${ATTEMPT_DEADLINE:-900s}"
SCHEDULE="${LOCAL_MINUTE} ${LOCAL_HOUR} * * *"
URI="${SERVICE_URL%/}/jobs/broadcast/loops/${LOOP_ID}/run"

common_args=(
  --location="$REGION"
  --project="$GCP_PROJECT"
  --schedule="$SCHEDULE"
  --time-zone="$TIME_ZONE"
  --uri="$URI"
  --http-method=POST
  --headers="X-Job-Trigger-Token=${JOB_TRIGGER_TOKEN},Content-Type=application/json"
  --message-body='{"loop_id":"'"$LOOP_ID"'"}'
  --description="Daily broadcast-loop run for loop_id=${LOOP_ID}"
  --attempt-deadline="$ATTEMPT_DEADLINE"
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
