"""Insight view definitions — revision a1b2c3d4e5f6.

This module is IMMUTABLE. It is frozen to the Alembic revision that created
these views. Both the migration and test setup import from here so the SQL
exists in exactly one place.

DO NOT EDIT after the migration has shipped. If views need to change, create
a new revision with a new SQL module (e.g., insight_views_<new_rev>.py).
"""

VIEW_SQL: list[str] = [
    # ── 1. v_daily_metric ─────────────────────────────────────────────
    """
    CREATE OR REPLACE VIEW v_daily_metric AS
    SELECT
        m.user_id,
        m.measured_at::date                          AS day,
        mt.id                                        AS metric_type_id,
        mt.slug                                      AS metric_slug,
        mt.name                                      AS metric_name,
        ROUND(AVG(m.value_num), 2)                   AS value,
        COUNT(*)                                     AS readings
    FROM measurements m
    JOIN metric_types mt ON m.metric_type_id = mt.id
    GROUP BY m.user_id, m.measured_at::date, mt.id, mt.slug, mt.name
    """,

    # ── 2. v_metric_baseline ──────────────────────────────────────────
    """
    CREATE OR REPLACE VIEW v_metric_baseline AS
    SELECT
        dm.user_id,
        dm.day,
        dm.metric_slug,
        dm.metric_name,
        dm.value,
        ROUND(AVG(dm.value) OVER w_baseline, 2)     AS baseline_avg,
        ROUND(STDDEV_POP(dm.value) OVER w_baseline, 4)
                                                     AS baseline_stddev,
        CASE
            WHEN COUNT(*) OVER w_baseline < 3 THEN NULL
            WHEN STDDEV_POP(dm.value) OVER w_baseline = 0 THEN 0
            ELSE ROUND(
                (dm.value - AVG(dm.value) OVER w_baseline)
                / STDDEV_POP(dm.value) OVER w_baseline,
            2)
        END                                          AS z_score,
        ROUND(
            dm.value - AVG(dm.value) OVER w_baseline,
        2)                                           AS delta_abs,
        CASE
            WHEN AVG(dm.value) OVER w_baseline = 0 THEN NULL
            ELSE ROUND(
                (dm.value - AVG(dm.value) OVER w_baseline)
                / AVG(dm.value) OVER w_baseline * 100,
            2)
        END                                          AS delta_pct,
        COUNT(*) OVER w_baseline                     AS baseline_points
    FROM v_daily_metric dm
    WINDOW w_baseline AS (
        PARTITION BY dm.user_id, dm.metric_slug
        ORDER BY dm.day
        ROWS BETWEEN 14 PRECEDING AND 1 PRECEDING
    )
    """,

    # ── 3. v_daily_training_load ──────────────────────────────────────
    """
    CREATE OR REPLACE VIEW v_daily_training_load AS
    SELECT
        ws.user_id,
        ws.started_at::date                          AS day,
        COUNT(*)                                     AS sessions,
        COALESCE(SUM(ws.duration_seconds), 0)        AS total_duration_s,
        ROUND(
            COALESCE(
                SUM(ws.duration_seconds * ws.perceived_effort), 0
            ) / 60.0,
        1)                                           AS training_load,
        MAX(ws.perceived_effort)                     AS max_rpe
    FROM workout_sessions ws
    WHERE ws.perceived_effort IS NOT NULL
       OR ws.duration_seconds IS NOT NULL
    GROUP BY ws.user_id, ws.started_at::date
    """,

    # ── 4. v_daily_symptom_burden ─────────────────────────────────────
    """
    CREATE OR REPLACE VIEW v_daily_symptom_burden AS
    WITH agg AS (
        SELECT
            sl.user_id,
            sl.started_at::date                      AS day,
            COUNT(*)                                 AS symptom_count,
            MAX(sl.intensity)                        AS max_intensity,
            SUM(sl.intensity)                        AS weighted_burden
        FROM symptom_logs sl
        GROUP BY sl.user_id, sl.started_at::date
    ),
    dominant AS (
        SELECT DISTINCT ON (sl.user_id, sl.started_at::date)
            sl.user_id,
            sl.started_at::date                      AS day,
            s.name                                   AS dominant_symptom
        FROM symptom_logs sl
        JOIN symptoms s ON sl.symptom_id = s.id
        ORDER BY sl.user_id, sl.started_at::date, sl.intensity DESC, s.name
    )
    SELECT
        a.user_id,
        a.day,
        a.symptom_count,
        a.max_intensity,
        a.weighted_burden,
        d.dominant_symptom
    FROM agg a
    LEFT JOIN dominant d ON a.user_id = d.user_id AND a.day = d.day
    """,

    # ── 5. v_medication_adherence ─────────────────────────────────────
    """
    CREATE OR REPLACE VIEW v_medication_adherence AS
    SELECT
        ml.user_id,
        mr.id                                        AS regimen_id,
        md.name                                      AS medication_name,
        mr.frequency,
        COUNT(*) FILTER (WHERE ml.status = 'taken')  AS taken,
        COUNT(*) FILTER (WHERE ml.status = 'skipped') AS skipped,
        COUNT(*) FILTER (WHERE ml.status = 'delayed') AS delayed,
        COUNT(*)                                     AS total,
        ROUND(
            100.0 * COUNT(*) FILTER (WHERE ml.status = 'taken')
            / NULLIF(COUNT(*), 0),
        1)                                           AS adherence_pct
    FROM medication_logs ml
    JOIN medication_regimens mr ON ml.regimen_id = mr.id
    JOIN medication_definitions md ON mr.medication_id = md.id
    GROUP BY ml.user_id, mr.id, md.name, mr.frequency
    """,
]

DROP_VIEW_SQL: list[str] = [
    "DROP VIEW IF EXISTS v_medication_adherence",
    "DROP VIEW IF EXISTS v_daily_symptom_burden",
    "DROP VIEW IF EXISTS v_daily_training_load",
    "DROP VIEW IF EXISTS v_metric_baseline",
    "DROP VIEW IF EXISTS v_daily_metric",
]
