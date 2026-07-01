# Looker Studio dashboard setup

Step-by-step build of a 6-tile dashboard backed by the BigQuery views in
`infra/bigquery_views.sql`. Assumes you have:

- The `analytics` dataset in `europe-west1` (see
  `infra/bigquery_setup.md`).
- The 6 `vw_*` views created and at least one day of data in
  `events_raw` (otherwise the funnel / retention tiles will render with
  zeroes — that's expected, not broken).
- A Google account with at least `BigQuery Data Viewer` and `BigQuery
  Job User` on the project.

Looker Studio is free; no licence to configure.

## 1. Create the report shell

1. Open <https://lookerstudio.google.com/> and click **Create → Report**.
2. Skip the "Add data" dialog for now (close it) so the empty page
   gives you control over canvas size before the first data source is
   added.
3. **File → Report settings → Date range**: set the default to "Last
   28 days" so every tile lands on a sensible window when the report
   opens.
4. **Resource → Manage report URL parameters**: leave default. We won't
   parameterise the project id; the report is hard-bound to the
   `analytics` dataset.

## 2. Connect the six views as data sources

Add each view as its own BigQuery data source so each tile only scans
the view it needs. **Resource → Manage added data sources → Add a data
source → BigQuery → Custom query**.

For each view, use a one-line wrapper query so Looker Studio gets a
clean schema and the partition filter inside the view does the real
work:

| Data source name      | Custom query                                     |
|-----------------------|--------------------------------------------------|
| `dau_wau_mau`         | `SELECT * FROM \`analytics.vw_dau_wau_mau\``     |
| `activation_funnel`   | `SELECT * FROM \`analytics.vw_activation_funnel\`` |
| `cohort_retention`    | `SELECT * FROM \`analytics.vw_cohort_retention\`` |
| `tier_breakdown`      | `SELECT * FROM \`analytics.vw_tier_breakdown\`` |
| `episode_completion`  | `SELECT * FROM \`analytics.vw_episode_completion\`` |
| `churn_risk_users`    | `SELECT * FROM \`analytics.vw_churn_risk_users\`` |
| `activity_windows`    | `SELECT * FROM \`analytics.vw_activity_windows\`` |

For every source, set **Data freshness** to **15 minutes** (the
`events_raw` partition is updated continuously by the log sink, so
fresher than 15m is wasted query cost; less fresh and morning
sessions show stale data).

## 3. Build the tiles

The dashboard is intentionally one page, 6 tiles, no drilldowns. Add
each tile via **Insert → <chart>** and bind it to the listed data
source.

### Tile 1 — DAU / WAU / MAU (time-series)

- Data source: `dau_wau_mau`
- Chart: **Time series**
- Date dimension: `event_date`
- Metrics: `dau`, `wau`, `mau` (all SUM, but each row already has the
  pre-computed values so the SUM is a no-op)
- Style: line chart, three series, smooth lines off, point markers on
- Range: rolling 30 days

### Tile 2 — Activation funnel

- Data source: `activation_funnel`
- Chart: **Bar chart** (horizontal)
- Dimension: `step` (sort by `step_order` ascending — set under "Sort"
  in the chart panel)
- Metric: `user_count`
- Conditional formatting: colour bars by `conversion_from_first` —
  red < 0.25, amber < 0.5, green ≥ 0.5
- Show `conversion_from_previous` as a tooltip / data label

### Tile 3 — Cohort retention (heatmap)

- Data source: `cohort_retention`
- Chart: **Pivot table with heatmap**
- Row dimension: `cohort_week` (descending, so newest cohorts on top)
- Column dimension: `week_n` (ascending, capped at week 12)
- Metric: `retention_rate` (format as percent)
- Heatmap: green at 1.0, red at 0
- Add a tooltip showing `active_users / cohort_size`

### Tile 4 — Tier breakdown + MRR

- Data source: `tier_breakdown`
- Chart: **Scorecards + table combo**
  - Three scorecards: MRR (sum of `mrr_usd`), paid users
    (count where `tier IN ('pro','max')`), free users
    (count where `tier = 'free'`)
  - Table below: tier, user_count, mrr_usd — sorted by mrr_usd desc

### Tile 5 — Episode completion (weekly)

- Data source: `episode_completion`
- Chart: **Combo chart**
- Date dimension: `iso_week`
- Bar metrics: `episodes_delivered`, `plays_30s`
- Line metric: `completion_rate` (right axis, format as percent)
- Annotation: add a note explaining that completion is undercounted
  while episode playback happens in Apple Podcasts (the
  EPISODE_PLAY_PULSE endpoint is only hit by an in-app player; see
  `newsletter_pod/events.py`).

### Tile 6 — Churn-risk users

- Data source: `churn_risk_users`
- Chart: **Table**
- Columns: `tier`, `user_id`, `last_play_at`, `swipes_14d`
- Sort: `last_play_at` ascending, NULLs first (i.e. never-played users
  surface at the top)
- Row limit: 50
- Add a filter control: dropdown on `tier` so the operator can scope
  to Pro vs Max while triaging

### Tile 7 — Activity & feature usage (rolling 7d / 30d)

- Data source: `activity_windows`
- Chart: **Table** — one compact tile covering every feature
  - Dimension: `event_name`
  - Metrics: `users_7d`, `events_7d`, `users_30d`, `events_30d`
  - Sort: `events_30d` descending
- What each `event_name` row means:
  - `episode_play_pulse` — **listeners** (distinct users who pulled audio);
    `users_7d` / `users_30d` are your headline listener counts.
  - `episode_generated` — **podcasts created** (`events_*` = total pods;
    `users_*` = distinct users who received one).
  - `sources_saved` — **source adjustments** (fires on the onboarding save
    too, so read it as "set or changed sources", not purely later edits).
  - `inbound_email_received` — **ClawCast-email usage** (a newsletter landed
    at the user's alias). Absent until the `INBOUND_EMAIL_RECEIVED`
    instrumentation deploys — see `newsletter_pod/inbound.py`.
  - `shared_item_received` — **share-sheet usage**.
- Optional headline **scorecards** above the table (each is the same data
  source with a filter):
  - "Listeners (7d)" — metric `users_7d`, filter `event_name =
    episode_play_pulse`; "Listeners (30d)" — metric `users_30d`, same filter.
  - "Podcasts created (7d)" — metric `events_7d`, filter `event_name =
    episode_generated`.
- Caveat: the listening `users_*` is the podcast-app *download-fetch* signal —
  trustworthy for presence, but do **not** use `position_bucket` for listen
  depth (it's a byte-range artifact; see `newsletter_pod/events.py`).

## 4. Share and link from the runbook

1. **Share → Get link** → "Restricted, anyone with access can view"
2. **Schedule email delivery**: weekly, Mondays 09:00 Europe/Copenhagen
   to `vincemartin1991@gmail.com`. PDF format, default page only.
3. Drop the report URL into the project root README's "Operations"
   section so it's discoverable from CLAUDE.md → README → here.

## 5. When tiles render zero

A fresh deploy of Phase 1 + Phase 2 will produce a dashboard with:

- Tile 4 (tier breakdown) — populated from the daily Firestore export.
- Tile 1 (DAU/WAU/MAU) — populated within ~5m of the first sign-in
  after the log sink is live.
- Tiles 2, 3, 5, 6 — empty for the first few days until users
  accumulate enough event history.

If a tile is zero AND you expect data, check in this order:

1. **Cloud Logging**: search `jsonPayload.event="app_event"` for the
   relevant time window. If absent → the app didn't emit the event;
   check `newsletter_pod/events.py` wiring.
2. **`analytics.events_raw`**: `SELECT COUNT(*) FROM
   analytics.events_raw WHERE DATE(timestamp) = CURRENT_DATE()`. If
   zero → the sink isn't writing; re-check
   `infra/bigquery_setup.md` step 2.
3. **The view directly**: `bq query --use_legacy_sql=false 'SELECT *
   FROM analytics.vw_dau_wau_mau LIMIT 5'`. If empty, the view is
   filtering everything out — most likely the lookback window in the
   view is shorter than the gap to the most recent event.
4. **Looker Studio cache**: force a refresh with
   **View → Refresh data**. Cache TTL is 15 minutes per step 2.
