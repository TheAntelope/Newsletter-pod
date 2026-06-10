#!/usr/bin/env bash
# One-shot, idempotent setup for the DAILY cold-start + per-topic swipe-deck
# refresh.
#
# Creates (or updates) a Cloud Scheduler job that POSTs to
# /jobs/refresh-cold-start-deck on the deployed Cloud Run service. The endpoint
# recomputes the global k-means cold-start deck, pre-bakes one cached deck per
# catalog topic (so the onboarding "Tune your pod" request serves cached keys
# instead of an unbounded live scan), and pre-warms card summaries for the
# baked items. It is idempotent — the summary pass only does LLM work on
# newly-ingested items — so reruns are safe and cheap in steady state.
#
# Cadence is DAILY because the onboarding deck must reflect fresh items and the
# topic_deck_ttl_hours staleness guard defaults to 24h.
#
# Required env:
#   GCP_PROJECT          GCP project ID (e.g. clawcast-prod)
#   SERVICE_URL          Cloud Run base URL (e.g. https://newsletter-pod-xxx.run.app)
#   JOB_TRIGGER_TOKEN    Same token configured on the Cloud Run service
#
# Optional env:
#   REGION               Scheduler region (default: europe-west1)
#   JOB_NAME             Scheduler job ID (default: refresh-cold-start-deck-daily)
#   SCHEDULE             cron expression (default: "0 3 * * *" — daily 03:00)
#   TIME_ZONE            IANA tz (default: Europe/Amsterdam)
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

REGION="${REGION:-europe-west1}"
JOB_NAME="${JOB_NAME:-refresh-cold-start-deck-daily}"
LEGACY_JOB_NAME="refresh-cold-start-deck-weekly"
SCHEDULE="${SCHEDULE:-0 3 * * *}"
TIME_ZONE="${TIME_ZONE:-Europe/Amsterdam}"
URI="${SERVICE_URL%/}/jobs/refresh-cold-start-deck"

common_args=(
  --location="$REGION"
  --project="$GCP_PROJECT"
  --schedule="$SCHEDULE"
  --time-zone="$TIME_ZONE"
  --uri="$URI"
  --http-method=POST
  --headers="X-Job-Trigger-Token=${JOB_TRIGGER_TOKEN},Content-Type=application/json"
  --description="Daily refresh of the global cold-start deck + per-topic onboarding decks + card-summary pre-warm."
  # Generous deadline: the first run warms summaries for the whole recent
  # corpus (later runs only touch new items). Raise the Cloud Run request
  # timeout too if that first warm exceeds the service default.
  --attempt-deadline=1800s
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

# Remove the superseded weekly job so the refresh doesn't run on two cadences.
if [[ "$JOB_NAME" != "$LEGACY_JOB_NAME" ]] && \
   gcloud scheduler jobs describe "$LEGACY_JOB_NAME" \
      --location="$REGION" \
      --project="$GCP_PROJECT" >/dev/null 2>&1; then
  echo "Deleting superseded weekly job '$LEGACY_JOB_NAME'..."
  gcloud scheduler jobs delete "$LEGACY_JOB_NAME" \
      --location="$REGION" \
      --project="$GCP_PROJECT" \
      --quiet
fi

echo
echo "Done. Verify with:"
echo "  gcloud scheduler jobs describe $JOB_NAME --location=$REGION --project=$GCP_PROJECT"
echo "Trigger manually with:"
echo "  gcloud scheduler jobs run $JOB_NAME --location=$REGION --project=$GCP_PROJECT"
