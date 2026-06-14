"""Daily Firestore -> BigQuery snapshot export.

Backs the subscription/tier/churn views (infra/bigquery_views.sql) — which read
`analytics.subscriptions_export` — and the per-user platform join in
`vw_engagement_by_platform`, which reads `analytics.device_tokens_export`.

Unlike the event stream (a Cloud Logging sink), these are point-in-time
snapshots of Firestore. `/jobs/export-analytics-snapshot` reads the relevant
collections via the repository and replaces each BigQuery table
(WRITE_TRUNCATE) once a day. Kept app-side — rather than a managed Firestore
export + Cloud Function — so the schema is explicit, the row-building is
unit-testable, and it reuses the existing /jobs auth + Cloud Scheduler pattern.

`google.cloud.bigquery` is imported lazily inside BigQueryTableWriter so that
importing this module (and running unit tests with a fake writer) never needs
the dependency.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any, Optional, Protocol

from .config import Settings
from .user_repository import ControlPlaneRepository

# Safety bound on a single snapshot scan — far above current scale, just so a
# runaway collection can't pull unbounded rows into memory.
_MAX_ROWS = 100_000


def _iso(value: Optional[datetime]) -> Optional[str]:
    """datetime -> RFC3339 string for a BigQuery TIMESTAMP column (or None)."""
    return value.isoformat() if value is not None else None


# Explicit schemas: the table is created with the right column types even when
# a snapshot is empty, and the views' column references never depend on a
# Firestore field happening to be present in the sampled documents.
SUBSCRIPTIONS_TABLE = "subscriptions_export"
SUBSCRIPTIONS_SCHEMA: list[tuple[str, str]] = [
    ("user_id", "STRING"),
    ("tier", "STRING"),
    ("status", "STRING"),
    ("product_id", "STRING"),
    ("started_at", "TIMESTAMP"),
    ("renewal_at", "TIMESTAMP"),
    ("expires_at", "TIMESTAMP"),
    ("updated_at", "TIMESTAMP"),
]

DEVICE_TOKENS_TABLE = "device_tokens_export"
DEVICE_TOKENS_SCHEMA: list[tuple[str, str]] = [
    ("user_id", "STRING"),
    ("platform", "STRING"),
    ("environment", "STRING"),
    ("last_seen_at", "TIMESTAMP"),
]


def build_subscription_rows(repo: ControlPlaneRepository) -> list[dict[str, Any]]:
    """One row per user subscription, shaped for SUBSCRIPTIONS_SCHEMA."""
    return [
        {
            "user_id": sub.user_id,
            "tier": sub.tier,
            "status": sub.status,
            "product_id": sub.product_id,
            "started_at": _iso(sub.started_at),
            "renewal_at": _iso(sub.renewal_at),
            "expires_at": _iso(sub.expires_at),
            "updated_at": _iso(sub.updated_at),
        }
        for sub in repo.list_all_subscriptions(limit=_MAX_ROWS)
    ]


def build_device_token_rows(repo: ControlPlaneRepository) -> list[dict[str, Any]]:
    """One row per active device token (the repo already drops invalidated
    ones), shaped for DEVICE_TOKENS_SCHEMA. The view reduces this to the
    newest platform per user."""
    return [
        {
            "user_id": tok.user_id,
            "platform": tok.platform,
            "environment": tok.environment,
            "last_seen_at": _iso(tok.last_seen_at),
        }
        for tok in repo.list_all_active_device_tokens(limit=_MAX_ROWS)
    ]


class TableWriter(Protocol):
    """Replaces a whole table from in-memory rows. The Protocol keeps run_export
    decoupled from BigQuery so tests can inject a fake."""

    def replace_table(
        self, table: str, schema: list[tuple[str, str]], rows: list[dict[str, Any]]
    ) -> None: ...


def run_export(repo: ControlPlaneRepository, writer: TableWriter) -> dict[str, int]:
    """Build every snapshot and replace its BigQuery table. Returns row counts."""
    subscriptions = build_subscription_rows(repo)
    device_tokens = build_device_token_rows(repo)
    writer.replace_table(SUBSCRIPTIONS_TABLE, SUBSCRIPTIONS_SCHEMA, subscriptions)
    writer.replace_table(DEVICE_TOKENS_TABLE, DEVICE_TOKENS_SCHEMA, device_tokens)
    return {
        SUBSCRIPTIONS_TABLE: len(subscriptions),
        DEVICE_TOKENS_TABLE: len(device_tokens),
    }


class BigQueryTableWriter:
    """Replaces a whole BigQuery table from in-memory rows (WRITE_TRUNCATE).

    Lazily imports google.cloud.bigquery so importing this module (and unit
    tests using a fake writer) never requires the dependency.
    """

    def __init__(self, settings: Settings) -> None:
        from google.cloud import bigquery  # lazy import

        self._bigquery = bigquery
        self._dataset = settings.bigquery_dataset_id
        self._location = settings.bigquery_location
        # project=None lets the client infer it from ADC / the Cloud Run
        # metadata server when google_cloud_project isn't set explicitly.
        self._client = bigquery.Client(
            project=settings.google_cloud_project or None,
            location=settings.bigquery_location,
        )

    def replace_table(
        self, table: str, schema: list[tuple[str, str]], rows: list[dict[str, Any]]
    ) -> None:
        bq = self._bigquery
        table_id = f"{self._client.project}.{self._dataset}.{table}"
        bq_schema = [bq.SchemaField(name, ftype) for name, ftype in schema]

        # Ensure the table exists with the right schema even on an empty
        # snapshot — load_table_from_json rejects an empty list, and we still
        # want the (now-empty) table present so the views don't break.
        self._client.create_table(bq.Table(table_id, schema=bq_schema), exists_ok=True)
        if not rows:
            self._client.query(
                f"TRUNCATE TABLE `{table_id}`", location=self._location
            ).result()
            return

        job = self._client.load_table_from_json(
            rows,
            table_id,
            job_config=bq.LoadJobConfig(
                schema=bq_schema,
                write_disposition=bq.WriteDisposition.WRITE_TRUNCATE,
            ),
        )
        job.result()
