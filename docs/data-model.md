# Data Model

## Table Overview

14 tables across 3 conceptual layers:

### Reference / Lookup (SERIAL PKs, immutable)
| Table | Role |
|---|---|
| `data_sources` | Catalogue of data origins (garmin, manual, withings, …) |
| `metric_types` | Measurement type registry (weight, hrv_rmssd, steps, …) |
| `exercises` | Exercise catalogue (bench_press, squat, running, …) |
| `symptoms` | Symptom catalogue (headache, knee_pain, fatigue, …) |
| `medication_definitions` | Medication registry (name, form, active ingredient) |

### Entity / Configuration (UUID PKs, mutable)
| Table | Role |
|---|---|
| `users` | System users (multi-tenancy anchor) |
| `medication_regimens` | Active prescriptions (user × medication × dosage × schedule) |

### Event / Fact (UUID PKs, append-only)
| Table | Role |
|---|---|
| `raw_payloads` | Raw JSON from external sources (audit + reprocessing) |
| `measurements` | Normalised numeric metrics (the core curated table) |
| `workout_sessions` | Training sessions with timestamps and metadata |
| `workout_sets` | Individual sets within a session |
| `medication_logs` | Dose-level adherence tracking |
| `symptom_logs` | Symptom occurrences with intensity and duration |
| `daily_checkpoints` | Subjective daily self-assessments (morning/night) |

## Relationship Map

```
users
  ├──< raw_payloads          (user_id)
  ├──< measurements          (user_id)
  ├──< workout_sessions      (user_id)
  ├──< medication_regimens   (user_id)
  ├──< medication_logs       (user_id)
  ├──< symptom_logs          (user_id)
  └──< daily_checkpoints     (user_id)

data_sources
  ├──< raw_payloads          (source_id)
  ├──< measurements          (source_id)
  └──< workout_sessions      (source_id)

metric_types ──< measurements       (metric_type_id)
raw_payloads ──< measurements       (raw_payload_id)  ← traceability
exercises    ──< workout_sets       (exercise_id)
workout_sessions ──< workout_sets   (workout_session_id)
medication_definitions ──< medication_regimens (medication_id)
medication_regimens    ──< medication_logs     (regimen_id)
symptoms ──< symptom_logs           (symptom_id)
```

**All arrows are real foreign keys.** Integrity is enforced by the database, not the application layer.

## PK Strategy

| Volume | Type | Rationale |
|---|---|---|
| Low (lookups) | `SERIAL` (integer) | Small, fast joins, human-readable IDs |
| High (events) | `UUIDv7` | Time-sortable (B-tree friendly), no coordination needed for distributed inserts, no enumeration risk |

UUIDv7 is generated in the application via `uuid_utils.uuid7()`. Unlike UUIDv4, its time-ordered prefix means sequential inserts don't fragment B-tree indexes.

## Naming Conventions

- **Table names:** plural snake_case (`measurements`, `workout_sets`)
- **FK columns:** `{referenced_table_singular}_id` (`user_id`, `metric_type_id`)
- **Slugs:** lowercase with underscores (`hrv_rmssd`, `bench_press`) — used as stable identifiers in the API instead of integer IDs
- **Timestamps:** always `TIMESTAMPTZ` — the database stores UTC; the application or client converts to the user's timezone
- **Booleans:** `is_` prefix (`is_active`, `is_derived`)

## Temporal Semantics by Domain

| Domain | "When it happened" | "When user reported" | "When system received" |
|---|---|---|---|
| Measurements | `measured_at` | `recorded_at` | `ingested_at` |
| Workouts | `started_at` / `ended_at` | `recorded_at` | `ingested_at` |
| Medication logs | `scheduled_at` / `taken_at` | `recorded_at` | `ingested_at` |
| Symptom logs | `started_at` / `ended_at` | `recorded_at` | `ingested_at` |
| Checkpoints | `checkpoint_at` | `recorded_at` | `ingested_at` |

## Analytical Views (Tier 1)

Five read-only views for feature engineering. No classification logic, no absolute thresholds, no labels anywhere in the SQL.

| View | Source Tables | Key Features |
|------|--------------|--------------|
| `v_daily_metric` | `measurements`, `metric_types` | One row per user × metric × day (avg of intra-day readings) |
| `v_metric_baseline` | `v_daily_metric` | Rolling 14-day avg, stddev, z_score, delta_abs, delta_pct, baseline_points |
| `v_daily_training_load` | `workout_sessions` | Sessions, total_duration_s, training_load (RPE × duration / 60), max_rpe |
| `v_daily_symptom_burden` | `symptom_logs`, `symptoms` | symptom_count, max_intensity, weighted_burden (sum of intensities), dominant_symptom |
| `v_medication_adherence` | `medication_logs`, `medication_regimens`, `medication_definitions` | taken, skipped, delayed, total, adherence_pct per user × regimen |

**View on view:** `v_metric_baseline` depends on `v_daily_metric` (drop order matters).

**Baseline math** (`v_metric_baseline`):
```
window: ROWS BETWEEN 14 PRECEDING AND 1 PRECEDING (excludes current day)
baseline_avg    = AVG(value) OVER window
baseline_stddev = STDDEV_POP(value) OVER window
z_score         = (value - baseline_avg) / baseline_stddev
                  NULL  when baseline_points < 3
                  0     when baseline_stddev = 0
delta_abs       = value - baseline_avg
delta_pct       = delta_abs / baseline_avg * 100  (NULL when avg = 0)
```

`z_score = NULL` is a signal: fewer than 3 prior data points exist. The service layer surfaces this as `"insufficient_data"` — never silently as `"low"` or `"recovered"`.

**SQL source:** `view_definitions/insight_views_a1b2c3d4e5f6.py` — revision-tagged, treated as immutable once the migration ships.

## HC900 Scale Integration — Data Contracts

### DataSource bootstrap

`hc900_ble` is guaranteed by an Alembic data migration (`c9d0e1f2a3b4`) using `ON CONFLICT (slug) DO NOTHING`. Running `alembic upgrade head` is sufficient — `seed.py` is not required. The import script guards against a missing source and prints a clear error message with the remediation command.

### Raw payload structure (`payload_type = "hc900_scale"`)

```json
{
  "format_version": "hc900_ble_v1",
  "device_mac":     "A0:91:5C:92:CF:17",
  "captured_at":    "2026-04-15T07:30:00+00:00",
  "measured_at":    "2026-04-15T07:30:00+00:00",
  "capture_method": "bleak_scan",
  "raw_mfr_weight_hex":    "aca017cf925c91a0202d88e00da2",
  "raw_mfr_impedance_hex": "aca017cf925c91a0a2afa0a206b9",
  "decoded": {
    "weight_kg": 75.84,
    "decoder_version": "hc900_ble_v1",
    "impedance_adc": 527,
    "body_fat_pct": 24.4,
    "muscle_pct": 38.4,
    "bone_mass_kg": 3.2,
    "water_pct": 57.8,
    "bmr": 1889
  },
  "user_profile_snapshot": {
    "height_cm": 180, "birth_date": "1991-08-15", "age": 34, "sex": 1
  }
}
```

`mfr_impedance_hex` and all body composition fields in `decoded` are `null`/absent when the scale did not transmit an impedance packet before the 15-second fallback timer.

### Normalised output

The `_parse_hc900_scale` parser (V1 scope) extracts two measurements:

| `decoded` key | `metric_slug` | unit | condition |
|---|---|---|---|
| `weight_kg` | `weight` | `kg` | always |
| `body_fat_pct` | `body_fat_pct` | `%` | only when present |

`aggregation_level = "spot"`, `measured_at` taken from `payload_json.measured_at`.

## Garmin Connect Integration — Data Contracts

### DataSource bootstrap

`garmin_connect` is seeded by an Alembic data migration (`a1b2c3d4e5f6_add_insight_views` range; actual migration in the initial schema) using `ON CONFLICT (slug) DO NOTHING`. Running `alembic upgrade head` is sufficient.

### Raw payload structure (`payload_type = "garmin_connect_daily"`)

```json
{
  "format_version": "garmin_connect_v1",
  "sync_date":      "2026-04-15",
  "user_timezone":  "America/Sao_Paulo",
  "measured_at":    "2026-04-15T15:00:00+00:00",
  "stats": {
    "restingHeartRate":            52,
    "totalSteps":                  9842,
    "activeKilocalories":          423,
    "averageStressLevel":          28,
    "averageSpo2":                 97,
    "avgWakingRespirationValue":   14.2,
    "bodyBatteryMostRecentValue":  68
  },
  "hrv": {
    "hrvSummary": {
      "lastNightAvg": 48
    }
  },
  "sleep": {
    "sleepTimeSeconds": 26520,
    "sleepScores": {
      "overall": { "value": 74 }
    }
  }
}
```

`measured_at` is noon in the user's local timezone converted to UTC. All nested Garmin fields are stored verbatim; the parser reads specific keys. Fields absent from the Garmin response (e.g., `hrv` on incompatible devices) are `null` or absent — the ingestion pipeline skips those metrics gracefully.

### Normalised output

The `_parse_garmin_connect_daily` parser produces up to 10 measurements per payload:

| `stats` / `hrv` / `sleep` key | `metric_slug` | unit | null-safe |
|---|---|---|---|
| `restingHeartRate` | `resting_hr` | `bpm` | yes |
| `totalSteps` | `steps` | `steps` | yes |
| `activeKilocalories` | `active_calories` | `kcal` | yes |
| `averageStressLevel` | `stress_level` | `score` | yes |
| `averageSpo2` | `spo2` | `%` | yes |
| `avgWakingRespirationValue` | `respiratory_rate` | `brpm` | yes |
| `bodyBatteryMostRecentValue` | `body_battery` | `score` | yes |
| `hrvSummary.lastNightAvg` | `hrv_rmssd` | `ms` | yes — skipped on incompatible devices |
| `sleepTimeSeconds / 60` | `sleep_duration` | `min` | yes |
| `sleepScores.overall.value` | `sleep_score` | `score` | yes |

`aggregation_level = "daily"`, `source_slug = "garmin_connect"`, `measured_at` taken from `payload_json.measured_at`.

### Deduplication key

`garmin_connect_{YYYY-MM-DD}` — one payload per calendar date. Re-syncing the same day is idempotent.

---

## V1 Constraints (explicit limits)

- **Single user in practice.** The schema supports multi-tenancy (all event tables have `user_id` FK), but V1 doesn't implement authentication or authorization beyond "regimen belongs to user."
- **No derived metrics.** `is_derived` and `confidence` columns exist in the schema but no V1 pipeline populates them. They're placeholders for future calculated metrics (e.g., training load score).
- **No unit conversion.** Measurements store the unit as-is. A future normalisation layer could convert lbs→kg or °F→°C on ingestion.
- **No time-series aggregation.** `aggregation_level` (spot/hourly/daily) is stored but no V1 pipeline generates rollups. The column enables future pre-aggregation without schema changes.
- **Append-only, no corrections.** If a measurement is wrong, you insert a new one — there's no UPDATE/DELETE pattern defined.
