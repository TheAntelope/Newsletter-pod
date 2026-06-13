-- ClawCast analytics views (Phase 2)
--
-- All views live in dataset `analytics` (see infra/bigquery_setup.md for
-- creation). They read from:
--   * analytics.events_raw         — Cloud Logging sink, app_event lines
--                                    partitioned by `timestamp` (== entry time).
--                                    Defined below as a proxy view over the
--                                    sink-created `run_googleapis_com_stdout`
--                                    table — Cloud Logging names BigQuery
--                                    tables after the source log name
--                                    (sanitized), not arbitrary aliases.
--   * analytics.subscriptions_export — daily Firestore snapshot.
--   * analytics.users_export        — daily Firestore snapshot.
--
-- Cost discipline:
--   The brief constrains every view that scans events_raw to filter on
--   the partition column so BigQuery prunes partitions and we never pay
--   for a full-table scan. The Cloud Logging sink partitions by the log
--   `timestamp` column (which is the event time within a few ms), so
--   every events_raw CTE below opens with
--       WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL N DAY)
--   matched to the view's lookback window.
--
-- jsonPayload extraction style:
--   We deliberately read every field via JSON_VALUE / JSON_VALUE_ARRAY
--   against TO_JSON_STRING(jsonPayload) rather than dotted STRUCT access.
--   The reason is that the Cloud Logging sink only adds a STRUCT field
--   to events_raw the first time it sees that field in a log line —
--   so a brand-new properties key wouldn't be queryable until the sink
--   had backfilled. JSON_VALUE never errors on a missing path and
--   keeps the views forward-compatible as we add event properties.

-- Proxy view: every downstream view reads from `analytics.events_raw`,
-- but the Cloud Logging sink actually writes to a table named after the
-- source log (`run.googleapis.com/stdout` → sanitized
-- `run_googleapis_com_stdout`). Wrapping it in a stable alias lets the
-- downstream views stay readable and survive any future log-routing
-- rename without rewriting every CTE.
CREATE OR REPLACE VIEW `analytics.events_raw` AS
SELECT * FROM `analytics.run_googleapis_com_stdout`;


CREATE OR REPLACE VIEW `analytics.vw_dau_wau_mau` AS
WITH events AS (
  SELECT
    SAFE.PARSE_TIMESTAMP('%Y-%m-%dT%H:%M:%E*S%Ez',
      JSON_VALUE(TO_JSON_STRING(jsonPayload), '$.ts')) AS ts,
    JSON_VALUE(TO_JSON_STRING(jsonPayload), '$.user_id') AS user_id
  FROM `analytics.events_raw`
  WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 60 DAY)
    AND JSON_VALUE(TO_JSON_STRING(jsonPayload), '$.user_id') IS NOT NULL
),
daily AS (
  SELECT DATE(ts) AS event_date, user_id
  FROM events
  WHERE ts IS NOT NULL
  GROUP BY event_date, user_id
),
day_axis AS (
  SELECT day FROM UNNEST(GENERATE_DATE_ARRAY(
    DATE_SUB(CURRENT_DATE(), INTERVAL 30 DAY), CURRENT_DATE()
  )) AS day
)
SELECT
  day AS event_date,
  (SELECT COUNT(DISTINCT user_id) FROM daily WHERE event_date = day)
    AS dau,
  (SELECT COUNT(DISTINCT user_id) FROM daily
    WHERE event_date BETWEEN DATE_SUB(day, INTERVAL 6 DAY) AND day)
    AS wau,
  (SELECT COUNT(DISTINCT user_id) FROM daily
    WHERE event_date BETWEEN DATE_SUB(day, INTERVAL 29 DAY) AND day)
    AS mau
FROM day_axis
ORDER BY event_date DESC;


CREATE OR REPLACE VIEW `analytics.vw_activation_funnel` AS
-- Funnel: sign_in → onboarding_done → first_episode → first_play_30s.
-- "onboarding_done" maps to the first SOURCES_SAVED event for the user —
-- that's the last must-do step in the iOS wizard; without sources, no
-- episode can generate. "first_play_30s" is the first EPISODE_PLAY_PULSE
-- whose position_bucket is past 0-30 (so the listener got past the
-- intro). Conversion is reported both step-over-previous and from the
-- top of the funnel.
WITH events AS (
  SELECT
    SAFE.PARSE_TIMESTAMP('%Y-%m-%dT%H:%M:%E*S%Ez',
      JSON_VALUE(TO_JSON_STRING(jsonPayload), '$.ts')) AS ts,
    JSON_VALUE(TO_JSON_STRING(jsonPayload), '$.user_id') AS user_id,
    JSON_VALUE(TO_JSON_STRING(jsonPayload), '$.event_name') AS event_name,
    JSON_VALUE(TO_JSON_STRING(jsonPayload), '$.properties.position_bucket')
      AS position_bucket
  FROM `analytics.events_raw`
  WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 90 DAY)
    AND JSON_VALUE(TO_JSON_STRING(jsonPayload), '$.user_id') IS NOT NULL
),
per_user AS (
  SELECT
    user_id,
    MIN(IF(event_name = 'sign_in', ts, NULL)) AS sign_in_at,
    MIN(IF(event_name = 'sources_saved', ts, NULL)) AS onboarding_done_at,
    MIN(IF(event_name = 'episode_generated', ts, NULL)) AS first_episode_at,
    MIN(IF(event_name = 'episode_play_pulse'
           AND position_bucket IS NOT NULL
           AND position_bucket != '0-30', ts, NULL)) AS first_play_30s_at
  FROM events
  WHERE ts IS NOT NULL
  GROUP BY user_id
),
counts AS (
  SELECT
    COUNTIF(sign_in_at IS NOT NULL) AS step_sign_in,
    COUNTIF(onboarding_done_at IS NOT NULL) AS step_onboarding_done,
    COUNTIF(first_episode_at IS NOT NULL) AS step_first_episode,
    COUNTIF(first_play_30s_at IS NOT NULL) AS step_first_play_30s
  FROM per_user
),
steps AS (
  SELECT 1 AS step_order, 'sign_in' AS step, step_sign_in AS user_count
    FROM counts
  UNION ALL
  SELECT 2, 'onboarding_done', step_onboarding_done FROM counts
  UNION ALL
  SELECT 3, 'first_episode', step_first_episode FROM counts
  UNION ALL
  SELECT 4, 'first_play_30s', step_first_play_30s FROM counts
)
SELECT
  step_order,
  step,
  user_count,
  SAFE_DIVIDE(
    user_count,
    NULLIF(LAG(user_count) OVER (ORDER BY step_order), 0)
  ) AS conversion_from_previous,
  SAFE_DIVIDE(
    user_count,
    NULLIF(FIRST_VALUE(user_count) OVER (ORDER BY step_order), 0)
  ) AS conversion_from_first
FROM steps
ORDER BY step_order;


CREATE OR REPLACE VIEW `analytics.vw_cohort_retention` AS
-- Each user is anchored to the ISO week of their first sign_in event.
-- For every subsequent ISO week we count how many of that cohort had
-- ANY event in the week. week_n = 0 is the cohort's signup week.
WITH events AS (
  SELECT
    SAFE.PARSE_TIMESTAMP('%Y-%m-%dT%H:%M:%E*S%Ez',
      JSON_VALUE(TO_JSON_STRING(jsonPayload), '$.ts')) AS ts,
    JSON_VALUE(TO_JSON_STRING(jsonPayload), '$.user_id') AS user_id,
    JSON_VALUE(TO_JSON_STRING(jsonPayload), '$.event_name') AS event_name
  FROM `analytics.events_raw`
  WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 180 DAY)
    AND JSON_VALUE(TO_JSON_STRING(jsonPayload), '$.user_id') IS NOT NULL
),
cohorts AS (
  SELECT
    user_id,
    DATE_TRUNC(DATE(MIN(ts)), WEEK(MONDAY)) AS cohort_week
  FROM events
  WHERE event_name = 'sign_in' AND ts IS NOT NULL
  GROUP BY user_id
),
cohort_sizes AS (
  SELECT cohort_week, COUNT(*) AS cohort_size
  FROM cohorts
  GROUP BY cohort_week
),
weekly_activity AS (
  SELECT
    user_id,
    DATE_TRUNC(DATE(ts), WEEK(MONDAY)) AS activity_week
  FROM events
  WHERE ts IS NOT NULL
  GROUP BY user_id, activity_week
)
SELECT
  c.cohort_week,
  DATE_DIFF(a.activity_week, c.cohort_week, WEEK) AS week_n,
  s.cohort_size,
  COUNT(DISTINCT a.user_id) AS active_users,
  SAFE_DIVIDE(COUNT(DISTINCT a.user_id), NULLIF(s.cohort_size, 0))
    AS retention_rate
FROM cohorts c
JOIN cohort_sizes s USING (cohort_week)
JOIN weekly_activity a USING (user_id)
WHERE a.activity_week >= c.cohort_week
GROUP BY c.cohort_week, week_n, s.cohort_size
ORDER BY c.cohort_week DESC, week_n;


CREATE OR REPLACE VIEW `analytics.vw_tier_breakdown` AS
-- Snapshot-only view: reads the daily Firestore export, not events_raw.
-- No ts filter is needed; the export table is small (one row per user).
-- MRR maps each product_id to its monthly equivalent (annual / 12).
-- Source of truth for pricing: billing_model_2026_05.md.
WITH active_subs AS (
  SELECT user_id, tier, status, product_id
  FROM `analytics.subscriptions_export`
  WHERE LOWER(IFNULL(status, 'unknown')) = 'active'
),
priced AS (
  SELECT
    user_id,
    LOWER(IFNULL(tier, 'free')) AS tier,
    product_id,
    CASE product_id
      WHEN 'com.newsletterpod.pro.monthly' THEN 19.99
      WHEN 'com.newsletterpod.pro.annual'  THEN 179.99 / 12.0
      WHEN 'com.newsletterpod.max.monthly' THEN 29.99
      WHEN 'com.newsletterpod.max.annual'  THEN 269.99 / 12.0
      ELSE 0.0
    END AS monthly_revenue_usd
  FROM active_subs
)
SELECT
  tier,
  COUNT(*) AS user_count,
  ROUND(SUM(monthly_revenue_usd), 2) AS mrr_usd
FROM priced
GROUP BY tier
ORDER BY mrr_usd DESC, user_count DESC;


CREATE OR REPLACE VIEW `analytics.vw_episode_completion` AS
-- plays_30s / episodes_delivered, weekly.
--   episodes_delivered = COUNT(DISTINCT episode_id) per ISO week from
--                        EPISODE_GENERATED events.
--   plays_30s          = COUNT(DISTINCT user_id × episode_id) per ISO
--                        week from EPISODE_PLAY_PULSE events whose
--                        position_bucket is past '0-30' (i.e. they got
--                        past the intro). This undercounts users who
--                        listen in Apple Podcasts but never hit our
--                        play-pulse endpoint — that gap closes when an
--                        in-app player ships or the /media route emits
--                        server-side pulses.
WITH events AS (
  SELECT
    SAFE.PARSE_TIMESTAMP('%Y-%m-%dT%H:%M:%E*S%Ez',
      JSON_VALUE(TO_JSON_STRING(jsonPayload), '$.ts')) AS ts,
    JSON_VALUE(TO_JSON_STRING(jsonPayload), '$.user_id') AS user_id,
    JSON_VALUE(TO_JSON_STRING(jsonPayload), '$.event_name') AS event_name,
    JSON_VALUE(TO_JSON_STRING(jsonPayload), '$.properties.episode_id')
      AS episode_id,
    JSON_VALUE(TO_JSON_STRING(jsonPayload), '$.properties.position_bucket')
      AS position_bucket
  FROM `analytics.events_raw`
  WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 90 DAY)
),
gens AS (
  SELECT
    DATE_TRUNC(DATE(ts), WEEK(MONDAY)) AS iso_week,
    COUNT(DISTINCT episode_id) AS episodes_delivered
  FROM events
  WHERE event_name = 'episode_generated'
    AND ts IS NOT NULL
    AND episode_id IS NOT NULL
  GROUP BY iso_week
),
plays AS (
  SELECT
    DATE_TRUNC(DATE(ts), WEEK(MONDAY)) AS iso_week,
    COUNT(DISTINCT CONCAT(user_id, '|', episode_id)) AS plays_30s
  FROM events
  WHERE event_name = 'episode_play_pulse'
    AND ts IS NOT NULL
    AND position_bucket IS NOT NULL
    AND position_bucket != '0-30'
    AND episode_id IS NOT NULL
  GROUP BY iso_week
)
SELECT
  COALESCE(g.iso_week, p.iso_week) AS iso_week,
  IFNULL(g.episodes_delivered, 0) AS episodes_delivered,
  IFNULL(p.plays_30s, 0) AS plays_30s,
  SAFE_DIVIDE(p.plays_30s, NULLIF(g.episodes_delivered, 0))
    AS completion_rate
FROM gens g
FULL OUTER JOIN plays p USING (iso_week)
ORDER BY iso_week DESC;


CREATE OR REPLACE VIEW `analytics.vw_churn_risk_users` AS
-- Heuristic: on a paid tier, no episode play in the last 7 days, and
-- zero swipes in the last 14 days. Filter parameters mirror the Phase 3
-- churn-risk scoring job that will read this view; tweak both together.
WITH events AS (
  SELECT
    SAFE.PARSE_TIMESTAMP('%Y-%m-%dT%H:%M:%E*S%Ez',
      JSON_VALUE(TO_JSON_STRING(jsonPayload), '$.ts')) AS ts,
    JSON_VALUE(TO_JSON_STRING(jsonPayload), '$.user_id') AS user_id,
    JSON_VALUE(TO_JSON_STRING(jsonPayload), '$.event_name') AS event_name
  FROM `analytics.events_raw`
  WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 30 DAY)
    AND JSON_VALUE(TO_JSON_STRING(jsonPayload), '$.user_id') IS NOT NULL
),
last_play_per_user AS (
  SELECT user_id, MAX(ts) AS last_play_at
  FROM events
  WHERE event_name = 'episode_play_pulse' AND ts IS NOT NULL
  GROUP BY user_id
),
swipes_14d AS (
  SELECT user_id, COUNT(*) AS swipes_14d
  FROM events
  WHERE event_name = 'swipe_recorded'
    AND ts IS NOT NULL
    AND ts >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 14 DAY)
  GROUP BY user_id
),
active_paid_subs AS (
  SELECT user_id, tier, product_id
  FROM `analytics.subscriptions_export`
  WHERE LOWER(IFNULL(status, 'unknown')) = 'active'
    AND LOWER(IFNULL(tier, 'free')) IN ('pro', 'max')
)
SELECT
  s.user_id,
  s.tier,
  s.product_id,
  lp.last_play_at,
  IFNULL(sw.swipes_14d, 0) AS swipes_14d
FROM active_paid_subs s
LEFT JOIN last_play_per_user lp USING (user_id)
LEFT JOIN swipes_14d sw USING (user_id)
WHERE (lp.last_play_at IS NULL
       OR lp.last_play_at < TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 7 DAY))
  AND IFNULL(sw.swipes_14d, 0) = 0
ORDER BY lp.last_play_at NULLS FIRST;


CREATE OR REPLACE VIEW `analytics.vw_engagement_by_platform` AS
-- Single pane for comparing the iOS and Flutter/Android stacks side by side.
-- Every event now carries a top-level `platform` field:
--   * iOS / Android / web for first-party API calls — stamped from the
--     X-Client-Platform header by the backend middleware.
--   * iOS / Android for server-side episode_play_pulse events emitted by the
--     /media route, derived from the podcast client's User-Agent (Apple
--     Podcasts ~= iOS, Podcast Addict ~= Android). These carry
--     properties.source = 'media_fetch' to distinguish them from in-app
--     client play-pulses.
-- Events with no resolvable platform (server jobs, webhooks, legacy rows
-- logged before this field shipped) bucket as 'unknown'.
WITH events AS (
  SELECT
    SAFE.PARSE_TIMESTAMP('%Y-%m-%dT%H:%M:%E*S%Ez',
      JSON_VALUE(TO_JSON_STRING(jsonPayload), '$.ts')) AS ts,
    JSON_VALUE(TO_JSON_STRING(jsonPayload), '$.user_id') AS user_id,
    JSON_VALUE(TO_JSON_STRING(jsonPayload), '$.event_name') AS event_name,
    LOWER(IFNULL(
      JSON_VALUE(TO_JSON_STRING(jsonPayload), '$.platform'), 'unknown'
    )) AS platform,
    JSON_VALUE(TO_JSON_STRING(jsonPayload), '$.properties.episode_id')
      AS episode_id,
    JSON_VALUE(TO_JSON_STRING(jsonPayload), '$.properties.position_bucket')
      AS position_bucket
  FROM `analytics.events_raw`
  WHERE timestamp >= TIMESTAMP_SUB(CURRENT_TIMESTAMP(), INTERVAL 60 DAY)
    AND JSON_VALUE(TO_JSON_STRING(jsonPayload), '$.user_id') IS NOT NULL
)
SELECT
  DATE(ts) AS event_date,
  platform,
  COUNT(DISTINCT user_id) AS active_users,
  COUNT(DISTINCT IF(event_name = 'sign_in', user_id, NULL)) AS signed_in_users,
  -- Distinct user×episode that got past the intro, on this platform/day.
  COUNT(DISTINCT IF(
    event_name = 'episode_play_pulse'
      AND position_bucket IS NOT NULL
      AND position_bucket != '0-30',
    CONCAT(user_id, '|', episode_id), NULL)) AS episodes_played_30s,
  COUNT(*) AS events
FROM events
WHERE ts IS NOT NULL
GROUP BY event_date, platform
ORDER BY event_date DESC, platform;
