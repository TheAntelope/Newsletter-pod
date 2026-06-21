#!/usr/bin/env bash
# One-shot, idempotent setup for the stale-run reaper.
#
# Creates (or updates) a Cloud Scheduler job that POSTs to /jobs/reap-stale-runs
# on the deployed Cloud Run service. The endpoint marks any user podcast run
# stuck `in_progress` past STALE_RUN_TIMEOUT_MINUTES as failed. These are runs
# whose in-process generation task was abandoned (instance recycled / OOM-killed
# / request timed out) before it could finalize the run — without this sweep
# they wedge the user's interactive "Generate now" and leave the client progress
# bar stuck at 95%. The endpoint is idempotent (the flip is conditional on the
# row still being in_progress), so reruns and overlapping invocations are safe.
#
# Cadence is FREQUENT (every 15 min) because an orphaned run blocks the user's
# next pod until it is reaped; start_user_generation also self-heals on the
# user's next attempt, so this job is the no-user-action backstop.
#
# Required env:
#   GCP_PROJECT          GCP project ID (e.g. clawcast-prod)
#   SERVICE_URL          Cloud Run base URL (e.g. https://newsletter-pod-xxx.run.app)
#   JOB_TRIGGER_TOKEN    Same token configured on the Cloud Run service
#
# Optional env:
#   REGION               Scheduler region (default: europe-west1)
#   JOB_NAME             Scheduler job ID (default: reap-stale-runs)
#   SCHEDULE             cron expression (default: "*/15 * * * *" — every 15 min)
#   TIME_ZONE            IANA tz (default: Europe/Amsterdam)
#
# Usage:
#   GCP_PROJECT=clawcast-prod \
#   SERVICE_URL=https://newsletter-pod-xxx.run.app \
#   JOB_TRIGGER_TOKEN=... \
#   ./scripts/schedule_reap_stale_runs.sh

set -euo pipefail

: "${GCP_PROJECT:?GCP_PROJECT is required}"
: "${SERVICE_URL:?SERVICE_URL is required}"
: "${JOB_TRIGGER_TOKEN:?JOB_TRIGGER_TOKEN is required}"

REGION="${REGION:-europe-west1}"
JOB_NAME="${JOB_NAME:-reap-stale-runs}"
SCHEDULE="${SCHEDULE:-*/15 * * * *}"
TIME_ZONE="${TIME_ZONE:-Europe/Amsterdam}"
URI="${SERVICE_URL%/}/jobs/reap-stale-runs"

common_args=(
  --location="$REGION"
  --project="$GCP_PROJECT"
  --schedule="$SCHEDULE"
  --time-zone="$TIME_ZONE"
  --uri="$URI"
  --http-method=POST
  --headers="X-Job-Trigger-Token=${JOB_TRIGGER_TOKEN},Content-Type=application/json"
  --description="Every 15 min: fail user podcast runs orphaned in_progress past STALE_RUN_TIMEOUT_MINUTES so they stop wedging generation."
  --attempt-deadline=120s
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
