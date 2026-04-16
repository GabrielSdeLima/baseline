-- ============================================================================
-- Baseline — Analytical Queries
-- ============================================================================
-- Run after seeding (python scripts/seed.py).
-- These queries prove the cross-domain value of the relational schema:
-- joins that would be impossible with siloed data stores.
--
-- Replace :user_id with the actual UUID from the seed, or wrap in a CTE:
--   WITH u AS (SELECT id FROM users WHERE email = 'lucas@baseline.dev')
-- ============================================================================


-- ─── 1. HRV trend with 7-day rolling average ──────────────────────────────
-- Demonstrates: metric_type normalization, window functions on measured_at.

SELECT
    m.measured_at::date            AS day,
    m.value_num                    AS hrv,
    ROUND(AVG(m.value_num) OVER (
        ORDER BY m.measured_at::date
        ROWS BETWEEN 6 PRECEDING AND CURRENT ROW
    ), 1)                          AS hrv_7d_avg
FROM measurements m
JOIN metric_types mt ON m.metric_type_id = mt.id
JOIN users u ON m.user_id = u.id
WHERE mt.slug = 'hrv_rmssd'
  AND u.email = 'lucas@baseline.dev'
ORDER BY day;


-- ─── 2. Training load vs next-day HRV ─────────────────────────────────────
-- Demonstrates: cross-domain join (workouts × measurements).
-- Training load = RPE × duration. Next-day HRV signals recovery.

WITH daily_load AS (
    SELECT
        ws.started_at::date                              AS day,
        SUM(ws.duration_seconds * ws.perceived_effort)
            / 60.0                                       AS load_score
    FROM workout_sessions ws
    JOIN users u ON ws.user_id = u.id
    WHERE u.email = 'lucas@baseline.dev'
    GROUP BY ws.started_at::date
),
daily_hrv AS (
    SELECT
        m.measured_at::date AS day,
        m.value_num         AS hrv
    FROM measurements m
    JOIN metric_types mt ON m.metric_type_id = mt.id
    JOIN users u ON m.user_id = u.id
    WHERE mt.slug = 'hrv_rmssd'
      AND u.email = 'lucas@baseline.dev'
)
SELECT
    dl.day              AS training_day,
    ROUND(dl.load_score)AS load,
    dh.hrv              AS next_day_hrv
FROM daily_load dl
JOIN daily_hrv dh ON dh.day = dl.day + 1
ORDER BY dl.day;


-- ─── 3. Medication adherence rate ──────────────────────────────────────────
-- Demonstrates: medication domain model (definition → regimen → log).

SELECT
    md.name                                                     AS medication,
    mr.frequency,
    COUNT(*) FILTER (WHERE ml.status = 'taken')                 AS taken,
    COUNT(*) FILTER (WHERE ml.status = 'skipped')               AS skipped,
    COUNT(*) FILTER (WHERE ml.status = 'delayed')               AS delayed,
    COUNT(*)                                                    AS total_logs,
    ROUND(
        100.0 * COUNT(*) FILTER (WHERE ml.status = 'taken')
        / NULLIF(COUNT(*), 0), 1
    )                                                           AS adherence_pct
FROM medication_logs ml
JOIN medication_regimens mr ON ml.regimen_id = mr.id
JOIN medication_definitions md ON mr.medication_id = md.id
JOIN users u ON ml.user_id = u.id
WHERE u.email = 'lucas@baseline.dev'
GROUP BY md.name, mr.frequency
ORDER BY md.name;


-- ─── 4. Sleep quality → next-morning energy ────────────────────────────────
-- Demonstrates: daily_checkpoints unique constraint (morning/night per day),
-- self-join across checkpoint types.

SELECT
    night.checkpoint_date       AS night_of,
    night.sleep_quality,
    morning.energy              AS next_am_energy,
    morning.mood                AS next_am_mood
FROM daily_checkpoints night
JOIN daily_checkpoints morning
    ON  morning.user_id         = night.user_id
    AND morning.checkpoint_type = 'morning'
    AND morning.checkpoint_date = night.checkpoint_date + 1
JOIN users u ON night.user_id = u.id
WHERE night.checkpoint_type = 'night'
  AND u.email = 'lucas@baseline.dev'
  AND night.sleep_quality IS NOT NULL
ORDER BY night.checkpoint_date;


-- ─── 5. Symptom frequency with preceding workout correlation ───────────────
-- Demonstrates: cross-domain correlation (symptoms × workouts within 48h).

WITH pairs AS (
    SELECT
        sl.id            AS log_id,
        s.name           AS symptom,
        sl.intensity,
        sl.started_at,
        ws.workout_type,
        ws.perceived_effort,
        ws.started_at    AS workout_at
    FROM symptom_logs sl
    JOIN symptoms s ON sl.symptom_id = s.id
    JOIN users u ON sl.user_id = u.id
    LEFT JOIN workout_sessions ws
        ON  ws.user_id   = sl.user_id
        AND ws.started_at BETWEEN sl.started_at - INTERVAL '48 hours'
                          AND     sl.started_at
    WHERE u.email = 'lucas@baseline.dev'
)
SELECT
    symptom,
    COUNT(DISTINCT log_id)                                       AS occurrences,
    ROUND(AVG(intensity), 1)                                     AS avg_intensity,
    COUNT(DISTINCT log_id) FILTER (WHERE workout_type IS NOT NULL) AS preceded_by_workout,
    MODE() WITHIN GROUP (ORDER BY workout_type)                  AS most_common_trigger_workout
FROM pairs
GROUP BY symptom
ORDER BY occurrences DESC;


-- ─── 6. Multi-domain daily dashboard ───────────────────────────────────────
-- Demonstrates: the schema's power — one query assembles a complete health picture
-- from 6 tables (measurements, checkpoints, workouts, symptoms).

WITH u AS (SELECT id FROM users WHERE email = 'lucas@baseline.dev')
SELECT
    d.day::date,
    -- Vitals (from measurements)
    MAX(m.value_num) FILTER (WHERE mt.slug = 'resting_hr')       AS resting_hr,
    MAX(m.value_num) FILTER (WHERE mt.slug = 'hrv_rmssd')        AS hrv,
    MAX(m.value_num) FILTER (WHERE mt.slug = 'weight')           AS weight_kg,
    MAX(m.value_num) FILTER (WHERE mt.slug = 'body_temperature') AS temp_c,
    MAX(m.value_num) FILTER (WHERE mt.slug = 'steps')            AS steps,
    MAX(m.value_num) FILTER (WHERE mt.slug = 'sleep_score')      AS sleep_score,
    -- Subjective (from checkpoints)
    MAX(dc.mood)   FILTER (WHERE dc.checkpoint_type = 'morning') AS am_mood,
    MAX(dc.energy) FILTER (WHERE dc.checkpoint_type = 'morning') AS am_energy,
    -- Training
    COUNT(DISTINCT ws.id)                                        AS workouts,
    MAX(ws.perceived_effort)                                     AS max_rpe,
    -- Symptoms
    COUNT(DISTINCT sl.id)                                        AS symptom_count,
    MAX(sl.intensity)                                            AS max_symptom_intensity
FROM generate_series('2026-03-01'::date, '2026-03-30'::date, '1 day') AS d(day)
CROSS JOIN u
LEFT JOIN measurements m   ON m.measured_at::date = d.day AND m.user_id = u.id
LEFT JOIN metric_types mt  ON m.metric_type_id = mt.id
LEFT JOIN daily_checkpoints dc ON dc.checkpoint_date = d.day AND dc.user_id = u.id
LEFT JOIN workout_sessions ws  ON ws.started_at::date = d.day AND ws.user_id = u.id
LEFT JOIN symptom_logs sl      ON sl.started_at::date = d.day AND sl.user_id = u.id
GROUP BY d.day
ORDER BY d.day;


-- ─── 7. Illness detection signal ──────────────────────────────────────────
-- Demonstrates: multi-signal pattern matching across domains.
-- Flags days where elevated temperature + low HRV + active symptoms converge.

WITH u AS (SELECT id FROM users WHERE email = 'lucas@baseline.dev'),
signals AS (
    SELECT
        d.day::date,
        MAX(m.value_num) FILTER (WHERE mt.slug = 'body_temperature') AS temp_c,
        MAX(m.value_num) FILTER (WHERE mt.slug = 'hrv_rmssd')        AS hrv,
        MAX(m.value_num) FILTER (WHERE mt.slug = 'resting_hr')       AS resting_hr,
        COUNT(DISTINCT sl.id)                                        AS active_symptoms,
        MAX(dc.energy) FILTER (WHERE dc.checkpoint_type = 'morning') AS energy
    FROM generate_series('2026-03-01'::date, '2026-03-30'::date, '1 day') AS d(day)
    CROSS JOIN u
    LEFT JOIN measurements m  ON m.measured_at::date = d.day AND m.user_id = u.id
    LEFT JOIN metric_types mt ON m.metric_type_id = mt.id
    LEFT JOIN symptom_logs sl ON d.day BETWEEN sl.started_at::date
                                 AND COALESCE(sl.ended_at::date, d.day)
                                 AND sl.user_id = u.id
    LEFT JOIN daily_checkpoints dc ON dc.checkpoint_date = d.day AND dc.user_id = u.id
    GROUP BY d.day
)
SELECT
    day,
    temp_c,
    hrv,
    resting_hr,
    active_symptoms,
    energy,
    CASE
        WHEN temp_c > 37.2 AND hrv < 38 AND active_symptoms >= 2 THEN 'HIGH'
        WHEN temp_c > 37.0 AND (hrv < 40 OR active_symptoms >= 1) THEN 'MODERATE'
        ELSE 'LOW'
    END AS illness_signal
FROM signals
WHERE active_symptoms > 0 OR temp_c > 37.0
ORDER BY day;
