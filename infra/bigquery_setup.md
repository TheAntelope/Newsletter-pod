# BigQuery analytics setup

Phase 2 of the analytics rollout. This wires up the data path that
backs `infra/bigquery_views.sql` and `docs/looker_studio_setup.md`:

```
Cloud Run logger.info ─┐
                       ├─► Cloud Logging ──sink──► BigQuery analytics.events_raw
Firestore (daily)  ────┘                          analytics.users_export
                                                  analytics.subscriptions_export
                                                  analytics.user_episodes_export
                                                  analytics.swipes_export
                                                  analytics.user_runs_export
```

Phase 1 (`newsletter_pod/events.py`) is already emitting structured
`app_event` log lines. Until you run the commands below those lines are
just logs — nothing in BigQuery yet, so the `/admin/metrics` page
correctly shows placeholders for the event-driven tiles.

All commands assume:

```bash
export PROJECT_ID="newsletter-pod"   # adjust if different
export REGION="europe-west1"
export DATASET="analytics"
export CLOUD_RUN_LOG_NAME="run.googleapis.com%2Fstdout"
```

## 1. Create the BigQuery dataset

```bash
bq --project_id="$PROJECT_ID" --location="$REGION" mk \
   --dataset \
   --description "ClawCast analytics: event stream + daily Firestore exports" \
   "$PROJECT_ID:$DATASET"
```

The dataset and every table created in steps 2/3 must live in
`europe-west1` so the log sink (also in `europe-west1`) can write to it
without a cross-region transfer. BigQuery rejects writes from a sink in
a different region than the destination dataset.

## 2. Create the Cloud Logging sink → BigQuery

Sink filter pins to `jsonPayload.event = "app_event"` so we only export
the structured event lines `events.py` emits, not generic
application logs.

```bash
gcloud logging sinks create clawcast-app-events \
  "bigquery.googleapis.com/projects/$PROJECT_ID/datasets/$DATASET" \
  --project="$PROJECT_ID" \
  --log-filter='resource.type="cloud_run_revision"
                resource.labels.service_name="newsletter-pod"
                jsonPayload.event="app_event"' \
  --use-partitioned-tables \
  --description "ClawCast Phase 2 event sink → analytics.events_raw"
```

Grant the sink's service account write access to the dataset:

```bash
SINK_SA=$(gcloud logging sinks describe clawcast-app-events \
  --project="$PROJECT_ID" --format='value(writerIdentity)')

bq --project_id="$PROJECT_ID" add-iam-policy-binding \
   --member="$SINK_SA" \
   --role="roles/bigquery.dataEditor" \
   "$PROJECT_ID:$DATASET"
```

The sink creates `analytics.events_raw` automatically on the first
matching log line. The table is partitioned by `_PARTITIONTIME` (which
mirrors `timestamp`). The views in `bigquery_views.sql` query
`DATE(ts)` and filter on `ts >= ...` so partition pruning works.

A no-event smoke check after deploy:

```bash
bq query --project_id="$PROJECT_ID" --use_legacy_sql=false \
  "SELECT COUNT(*) AS n FROM \`$PROJECT_ID.$DATASET.events_raw\`
   WHERE DATE(timestamp) = CURRENT_DATE('UTC')"
```

If `n = 0` for more than ~5 minutes after a known event (e.g. you
just signed in via the iOS app), check:

1. The Cloud Run service is emitting the log line (search Cloud Logging
   for `jsonPayload.event="app_event"`).
2. The sink filter matches — `gcloud logging sinks describe
   clawcast-app-events`.
3. The sink's writer identity has BigQuery Data Editor on the dataset.

## 3. Daily Firestore → BigQuery export

The views in `bigquery_views.sql` join the event stream against five
Firestore collections. We snapshot them once a day at 06:00 UTC (well
clear of the European morning generation window).

### 3a. One-time IAM grants

The Firestore export needs Cloud Storage to stage the dump and BigQuery
permission to load it. We use the default Compute Engine service
account for simplicity — adjust if your project uses a dedicated one.

```bash
SA="${PROJECT_ID}-compute@developer.gserviceaccount.com"

# Permission to read Firestore + start exports.
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:$SA" --role="roles/datastore.importExportAdmin"

# Permission to write to the staging bucket and load into BigQuery.
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:$SA" --role="roles/storage.objectAdmin"
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:$SA" --role="roles/bigquery.dataEditor"
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
  --member="serviceAccount:$SA" --role="roles/bigquery.jobUser"
```

### 3b. Staging bucket

```bash
gcloud storage buckets create "gs://${PROJECT_ID}-firestore-export" \
  --project="$PROJECT_ID" \
  --location="$REGION" \
  --uniform-bucket-level-access

# Keep the bucket cheap — exports are reloaded each day so old dumps
# are dead weight after 7 days.
gcloud storage buckets update "gs://${PROJECT_ID}-firestore-export" \
  --lifecycle-file=<(cat <<'EOF'
{
  "lifecycle": {
    "rule": [
      {"action": {"type": "Delete"}, "condition": {"age": 7}}
    ]
  }
}
EOF
)
```

### 3c. Cloud Scheduler job (Firestore export)

Triggers a managed Firestore export of the five collections every day at
06:00 UTC. The collections are the ones referenced by the BigQuery
views — keep this list in sync with `infra/bigquery_views.sql`.

The deployed `firestore_collection_prefix` is `newsletter_pod` (see
`Settings.firestore_collection_prefix`), so the actual collection IDs
are `newsletter_pod_users`, `newsletter_pod_subscriptions`, etc. If
you've deployed with a different prefix, edit the `collectionIds` list
below before running.

```bash
DATABASE="(default)"
PREFIX="newsletter_pod"

gcloud scheduler jobs create http firestore-to-gcs-export \
  --project="$PROJECT_ID" \
  --location="$REGION" \
  --schedule="0 6 * * *" \
  --time-zone="UTC" \
  --uri="https://firestore.googleapis.com/v1/projects/$PROJECT_ID/databases/$DATABASE:exportDocuments" \
  --http-method=POST \
  --oauth-service-account-email="$SA" \
  --headers="Content-Type=application/json" \
  --message-body="{
    \"outputUriPrefix\": \"gs://${PROJECT_ID}-firestore-export/daily\",
    \"collectionIds\": [
      \"${PREFIX}_users\",
      \"${PREFIX}_subscriptions\",
      \"${PREFIX}_user_episodes\",
      \"${PREFIX}_swipes\",
      \"${PREFIX}_user_runs\"
    ]
  }"
```

### 3d. Cloud Scheduler job (GCS → BigQuery load)

The Firestore export writes one Avro file per collection under
`gs://.../daily/<timestamp>/all_namespaces/kind_<collection>/.../*.export_metadata`.
Loading those into BigQuery is a separate step. Use a Cloud Run Job (or
a small Cloud Function) triggered 30 minutes after the export job
fires:

```bash
gcloud scheduler jobs create http firestore-to-bq-load \
  --project="$PROJECT_ID" \
  --location="$REGION" \
  --schedule="30 6 * * *" \
  --time-zone="UTC" \
  --uri="https://${REGION}-${PROJECT_ID}.cloudfunctions.net/firestore-to-bq-load" \
  --http-method=POST \
  --oauth-service-account-email="$SA"
```

A minimal load script (Python) the function/job should run:

```python
from google.cloud import bigquery, storage
import os, re

PROJECT = os.environ["PROJECT_ID"]
DATASET = os.environ["DATASET"]
BUCKET = os.environ["EXPORT_BUCKET"]
PREFIX = os.environ.get("COLLECTION_PREFIX", "newsletter_pod")

COLLECTIONS = {
    f"{PREFIX}_users":          "users_export",
    f"{PREFIX}_subscriptions":  "subscriptions_export",
    f"{PREFIX}_user_episodes":  "user_episodes_export",
    f"{PREFIX}_swipes":         "swipes_export",
    f"{PREFIX}_user_runs":      "user_runs_export",
}

storage_client = storage.Client()
bq = bigquery.Client(project=PROJECT)

# Resolve the most recent export folder (the Firestore export job
# writes a timestamped prefix each run).
blobs = storage_client.list_blobs(BUCKET, prefix="daily/")
folders = sorted({b.name.split("/")[1] for b in blobs if "/" in b.name})
latest = folders[-1]

for collection, table in COLLECTIONS.items():
    uri = (
        f"gs://{BUCKET}/daily/{latest}/all_namespaces/kind_{collection}"
        f"/all_namespaces_kind_{collection}.export_metadata"
    )
    config = bigquery.LoadJobConfig(
        source_format=bigquery.SourceFormat.DATASTORE_BACKUP,
        write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
    )
    job = bq.load_table_from_uri(
        uri, f"{PROJECT}.{DATASET}.{table}", job_config=config
    )
    job.result()
    print(f"Loaded {collection} → {table} ({job.output_rows} rows)")
```

After the first successful run you'll have all five export tables
alongside `events_raw`. The views in `bigquery_views.sql` reference
them by these exact names.

## 4. Dry-run the views

Before the views actually exist in BigQuery, you can syntax-check the
SQL without scanning any bytes:

```bash
while read -r view; do
  echo "--- $view ---"
  bq query --project_id="$PROJECT_ID" --use_legacy_sql=false --dry_run \
    "$(sed -n "/CREATE OR REPLACE VIEW \`$view\`/,/;/p" infra/bigquery_views.sql)"
done <<EOF
$PROJECT_ID.$DATASET.vw_dau_wau_mau
$PROJECT_ID.$DATASET.vw_activation_funnel
$PROJECT_ID.$DATASET.vw_cohort_retention
$PROJECT_ID.$DATASET.vw_tier_breakdown
$PROJECT_ID.$DATASET.vw_episode_completion
$PROJECT_ID.$DATASET.vw_churn_risk_users
EOF
```

Apply the views once dry-runs pass:

```bash
bq query --project_id="$PROJECT_ID" --use_legacy_sql=false \
  < infra/bigquery_views.sql
```

## 5. Cost ceiling

Rough order-of-magnitude at current ClawCast scale (single-digit DAU):

| Item                              | Daily cost  |
|-----------------------------------|-------------|
| Log sink → BigQuery storage       | <$0.01      |
| Firestore export job (5 colls)    | <$0.01      |
| GCS staging (7d retention)        | <$0.01      |
| BigQuery storage (events + tables)| <$0.05      |
| Dashboard queries (Looker Studio) | <$0.10/day  |

Set a BigQuery billing alert at $5/day so a misbehaving dashboard
query (forgetting the `ts` filter on a 30-day-old view) doesn't run
unbounded. Every view in `bigquery_views.sql` filters on `ts` for
partition pruning; if you copy a view's body into Looker Studio as a
custom query, keep that filter.
