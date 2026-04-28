#!/usr/bin/env bash
# Trigger a forced podcast generation against a deployed instance.
# Used as a post-deploy smoke test in Cloud Build, and locally for ad-hoc runs.
#
# Usage:
#   APP_BASE_URL=https://newsletter-pod-... \
#   SMOKE_USER_ID=<user-id> \
#   JOB_TRIGGER_TOKEN=<token> \
#   scripts/post_deploy_smoke.sh
#
# Prints the JSON response from /jobs/process-user-podcast and exits non-zero
# on HTTP failure or if the run did not publish an episode.
set -euo pipefail

: "${APP_BASE_URL:?APP_BASE_URL is required}"
: "${SMOKE_USER_ID:?SMOKE_USER_ID is required}"
: "${JOB_TRIGGER_TOKEN:?JOB_TRIGGER_TOKEN is required}"

echo "Triggering smoke episode for user ${SMOKE_USER_ID} on ${APP_BASE_URL}" >&2

response="$(curl --silent --show-error --fail \
  --max-time 600 \
  --request POST "${APP_BASE_URL%/}/jobs/process-user-podcast" \
  --header "Authorization: Bearer ${JOB_TRIGGER_TOKEN}" \
  --header "Content-Type: application/json" \
  --data "{\"user_id\":\"${SMOKE_USER_ID}\",\"force\":true}")"

echo "$response"

status="$(echo "$response" | jq -r '.run.status // .status // "unknown"')"
case "$status" in
  published)
    episode_id="$(echo "$response" | jq -r '.episode.id // .run.published_episode_id // ""')"
    echo "Smoke episode published: ${episode_id}" >&2
    ;;
  no_content)
    echo "Smoke run completed but no new content was available; not a failure." >&2
    ;;
  *)
    echo "Smoke run did not publish (status=${status}); failing build." >&2
    exit 1
    ;;
esac
