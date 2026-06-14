#!/usr/bin/env bash
# One-shot, idempotent setup for the Phase 3 analytics jobs:
#   - export-analytics-snapshot  (daily 03:30 Europe/Amsterdam)
#   - score-churn-risk-daily     (daily 04:00 Europe/Amsterdam)
#   - weekly-cohort-report-mon   (Mondays 07:00 Europe/Amsterdam)
#
# The snapshot export runs first (before churn scoring) so
# analytics.subscriptions_export / device_tokens_export are fresh for the day.
#
# Both endpoints are idempotent (re-runs overwrite per-user state /
# resend the report) so retries from Cloud Scheduler are safe.
#
# Required env:
#   GCP_PROJECT          GCP project ID (e.g. clawcast-prod)
#   SERVICE_URL          Cloud Run base URL (e.g. https://newsletter-pod-xxx.run.app)
#   JOB_TRIGGER_TOKEN    Same token configured on the Cloud Run service
#
# Optional env:
#   REGION               Scheduler region (default: europe-west1)
#   TIME_ZONE            IANA tz (default: Europe/Amsterdam)
#   CHURN_JOB_NAME       Scheduler job ID for churn scoring
#                        (default: score-churn-risk-daily)
#   CHURN_SCHEDULE       cron for churn scoring (default: "0 4 * * *")
#   COHORT_JOB_NAME      Scheduler job ID for cohort report
#                        (default: weekly-cohort-report-mon)
#   COHORT_SCHEDULE      cron for cohort report (default: "0 7 * * 1")
#   DRY_RUN              If set to "1", prints the gcloud commands
#                        instead of running them. Useful for review
#                        before touching prod scheduler state.
#
# Usage:
#   GCP_PROJECT=clawcast-prod \
#   SERVICE_URL=https://newsletter-pod-xxx.run.app \
#   JOB_TRIGGER_TOKEN=... \
#   ./scripts/schedule_analytics_jobs.sh
#
# Dry-run:
#   DRY_RUN=1 GCP_PROJECT=clawcast-prod ... ./scripts/schedule_analytics_jobs.sh

set -euo pipefail

: "${GCP_PROJECT:?GCP_PROJECT is required}"
: "${SERVICE_URL:?SERVICE_URL is required}"
: "${JOB_TRIGGER_TOKEN:?JOB_TRIGGER_TOKEN is required}"

REGION="${REGION:-europe-west1}"
TIME_ZONE="${TIME_ZONE:-Europe/Amsterdam}"
EXPORT_JOB_NAME="${EXPORT_JOB_NAME:-export-analytics-snapshot}"
EXPORT_SCHEDULE="${EXPORT_SCHEDULE:-30 3 * * *}"
CHURN_JOB_NAME="${CHURN_JOB_NAME:-score-churn-risk-daily}"
CHURN_SCHEDULE="${CHURN_SCHEDULE:-0 4 * * *}"
COHORT_JOB_NAME="${COHORT_JOB_NAME:-weekly-cohort-report-mon}"
COHORT_SCHEDULE="${COHORT_SCHEDULE:-0 7 * * 1}"
DRY_RUN="${DRY_RUN:-0}"

run_gcloud() {
  if [[ "$DRY_RUN" == "1" ]]; then
    printf '[dry-run] gcloud'
    for arg in "$@"; do
      printf ' %q' "$arg"
    done
    printf '\n'
  else
    gcloud "$@"
  fi
}

apply_job() {
  local name="$1"
  local schedule="$2"
  local uri="$3"
  local description="$4"

  local common_args=(
    --location="$REGION"
    --project="$GCP_PROJECT"
    --schedule="$schedule"
    --time-zone="$TIME_ZONE"
    --uri="$uri"
    --http-method=POST
    --headers="X-Job-Trigger-Token=${JOB_TRIGGER_TOKEN},Content-Type=application/json"
    --description="$description"
    --attempt-deadline=300s
  )

  # `describe` is a read — always run it (even in DRY_RUN) so we know
  # whether the create vs update branch would fire.
  if gcloud scheduler jobs describe "$name" \
        --location="$REGION" \
        --project="$GCP_PROJECT" >/dev/null 2>&1; then
    echo "Updating existing scheduler job '$name'..."
    run_gcloud scheduler jobs update http "$name" "${common_args[@]}"
  else
    echo "Creating scheduler job '$name'..."
    run_gcloud scheduler jobs create http "$name" "${common_args[@]}"
  fi
}

apply_job \
  "$EXPORT_JOB_NAME" \
  "$EXPORT_SCHEDULE" \
  "${SERVICE_URL%/}/jobs/export-analytics-snapshot" \
  "Daily Firestore->BigQuery snapshot of subscriptions + device tokens (backs the tier/churn views and the per-user platform join). Idempotent: WRITE_TRUNCATE replace."

apply_job \
  "$CHURN_JOB_NAME" \
  "$CHURN_SCHEDULE" \
  "${SERVICE_URL%/}/jobs/score-churn-risk" \
  "Daily churn-risk scoring across active paid users (Phase 3). Idempotent: re-runs overwrite per-user state."

apply_job \
  "$COHORT_JOB_NAME" \
  "$COHORT_SCHEDULE" \
  "${SERVICE_URL%/}/jobs/weekly-cohort-report" \
  "Weekly Monday cohort report email — last-week signups, activation, paid conversion, top-3 churn risks (Phase 3)."

if [[ "$DRY_RUN" == "1" ]]; then
  echo
  echo "DRY_RUN=1 — no scheduler state was modified."
fi

echo
echo "Done. Verify with:"
echo "  gcloud scheduler jobs describe $EXPORT_JOB_NAME --location=$REGION --project=$GCP_PROJECT"
echo "  gcloud scheduler jobs describe $CHURN_JOB_NAME --location=$REGION --project=$GCP_PROJECT"
echo "  gcloud scheduler jobs describe $COHORT_JOB_NAME --location=$REGION --project=$GCP_PROJECT"
echo "Trigger manually with:"
echo "  gcloud scheduler jobs run $EXPORT_JOB_NAME --location=$REGION --project=$GCP_PROJECT"
echo "  gcloud scheduler jobs run $CHURN_JOB_NAME --location=$REGION --project=$GCP_PROJECT"
echo "  gcloud scheduler jobs run $COHORT_JOB_NAME --location=$REGION --project=$GCP_PROJECT"
