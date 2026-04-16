# Architecture — Trade-offs & Decisions

## Layer Architecture

```
API  (thin: validation + routing)
 ↓
Service  (business logic, slug resolution, authorization)
 ↓
Repository  (query encapsulation, eager loading strategy)
 ↓
Model  (SQLAlchemy 2.0 Mapped classes, CHECK/FK/UNIQUE constraints)
 ↓
PostgreSQL 16  (real FKs, partial indexes, JSONB)
```

**Why this and not Clean Architecture / Hexagonal?**
Ports-and-adapters adds indirection that's only justified when you have multiple concrete adapters (e.g., swap Postgres for Dynamo). Baseline has one database and no plans to change it. A pragmatic layered approach gives the same testability (DI via `Depends()`) without abstract interfaces that nobody implements twice.

**Why Repository pattern on top of SQLAlchemy?**
SQLAlchemy's `Session` already abstracts SQL. Repositories add value here because:
1. They centralise eager-loading strategy (`selectinload`) — the service never decides join depth.
2. They keep filter logic (slug joins, date ranges) out of services.
3. They provide a natural boundary for unit-testing with a real DB.

## Temporal Model

| Table type | Timestamps | Rationale |
|---|---|---|
| Measurements | `measured_at`, `recorded_at`, `ingested_at` | Classic triple-temporal: when the value *was* (measured), when the user *said* (recorded), when the system *received* (ingested). |
| Workouts, Symptom logs | domain-specific (`started_at`/`ended_at`) + `recorded_at` + `ingested_at` | `measured_at` doesn't make semantic sense for a workout — `started_at` *is* the timestamp of observation. |
| Medication logs | `scheduled_at`, `taken_at`, `recorded_at`, `ingested_at` | Four-temporal: prescription time, action time, observation time, system time. |
| Lookup tables | `created_at` only | Reference data. Immutable by design. |

**Why not a single `event_at` column?**
Because temporal precision is the entire point of a longitudinal health platform. A weight measured at 7:30, recorded in the app at 8:00, and synced at 8:15 has three semantically different timestamps. Collapsing them destroys analytical value (e.g., "how much recording lag does this user have?").

## Raw vs Curated Separation

Every external data point enters through `raw_payloads` first:

1. The **raw layer** preserves the original JSON exactly as received. Append-only, never mutated (except `processing_status`).
2. The **ingestion pipeline** parses and normalises into the curated layer (measurements, workouts, etc.) with FK traceability (`raw_payload_id`).
3. If parsing fails, the raw payload survives with `status='failed'` and an error message. The curated layer is not contaminated (savepoint rollback).

**Trade-off accepted:** Storing both raw and curated means ~2× storage for externally-sourced data. This is acceptable because:
- Raw payloads enable reprocessing when parsers improve.
- Audit trail is non-negotiable for health data.
- Storage is cheap; lost data is irreplaceable.

## Idempotency & Deduplication

- **External dedup:** `UNIQUE(source_id, external_id) WHERE external_id IS NOT NULL` prevents duplicate ingestion of the same Garmin/Withings record. The partial index avoids bloating the index with manual entries that have no external ID.
- **Ingestion idempotency:** Re-ingesting the same `external_id` returns the existing record without side effects.
- **Reprocess safety:** Re-processing a payload that already has curated data marks it `skipped` instead of creating duplicates.
- **Daily checkpoint uniqueness:** `UNIQUE(user_id, checkpoint_type, checkpoint_date)` enforced at DB level, with a friendlier service-level check that runs first.

## Index Strategy

| Index | Purpose |
|---|---|
| `(user_id, measured_at)` | Default query: "my data in a time range" |
| `(user_id, metric_type_id, measured_at)` | Filtered query: "my weight over 30 days" |
| `(raw_payload_id)` | Traceability: raw → curated lookup |
| `(processing_status) WHERE 'pending'` | Partial index for the processing queue — only indexes pending rows, not the 99% that are processed |
| `(source_id, external_id) WHERE NOT NULL` | Partial unique index for dedup — excludes manual entries |

**Why partial indexes?** They keep the index small and writes fast. The pending-queue index only tracks the tiny fraction of payloads awaiting processing, not the entire history.

## Insight Layer: Two-Tier Design

Phase 5 transforms analytical views into consumable, baseline-aware insights.

```
Tier 1 — Analytical Views (feature engineering, no labels)
 ↓
Tier 2 — Insight Services (classification heuristics in Python)
 ↓
API endpoints (6 GET-only routes under /api/v1/insights)
```

### Tier 1 — Analytical Views

Five regular PostgreSQL views (not materialized) in `v_daily_metric`, `v_metric_baseline`, `v_daily_training_load`, `v_daily_symptom_burden`, `v_medication_adherence`.

**Design rules, strictly enforced:**
- No classification labels in SQL (`'high'`, `'strained'`, etc.)
- No absolute thresholds (`WHERE temp > 37.2`, etc.)
- All features are relative to the individual user's data
- `v_metric_baseline` is the core: 14-day rolling avg, stddev, z-score, delta — all personal

View SQL is the single source of truth in `view_definitions/insight_views_a1b2c3d4e5f6.py` (revision-tagged, treated as immutable once shipped). Both the Alembic migration and test setup import from the same module.

### Tier 2 — Insight Services

Python classification heuristics over view features. Classification lives in Python (not SQL) so it's easy to iterate, testable in isolation, and clearly separated from the stable feature layer.

| Insight | Stability | Method identifier |
|---------|-----------|-------------------|
| `medication_adherence` | **Stable** | — |
| `physiological_deviations` | **Stable** | — |
| `symptom_burden` | **Stable** | — |
| `illness_signal` | **Experimental V1** | `baseline_deviation_v1` |
| `recovery_status` | **Experimental V1** | `load_hrv_heuristic_v1` |

Experimental insights expose a `method` field so consumers know the classification version.

### Baseline-First Principle

The primary signal is **deviation from the user's individual 14-day rolling baseline** (z-score), not fixed absolute thresholds. Absolute values are irrelevant — what matters is whether a metric is unusual *for this person*.

- z-score NULL when fewer than 3 baseline data points → `"insufficient_data"`
- `"insufficient_data"` ≠ `"low"` or `"recovered"` — it means no evidence, not normality
- When some z-scores are available and some are NULL (partial baseline), available signals are used and missing ones treated as neutral

### Important Disclaimer

**This is pattern detection for personal health tracking, NOT clinical diagnosis.** The heuristics are V1 approximations designed to surface anomalies relative to your own baseline. No medical decisions should be based on these signals.

## HC900 Scale Integration — Dart Subprocess Bridge

Phase 6 adds real device data ingestion from the HC900/FG260RB BLE smart scale.

### Why a Dart subprocess instead of a Python port

The HC900 decode algorithm (XOR cipher + body composition formulas) already exists in the Pulso project (`C:/src/pulso/pulso-app`) as Dart. Re-implementing it in Python would create two diverging sources of truth. Instead:

1. **`tools/decode_scale.dart`** (Pulso project) is the single decode authority — it reads raw bytes from stdin, returns normalised JSON to stdout.
2. **`scripts/import_scale.py`** calls `dart run tools/decode_scale.dart` as a subprocess.
3. **`scripts/scan_scale.py`** handles BLE scanning via `bleak` — pure Python, no decode logic.

If the decode algorithm is ever corrected in Pulso, Baseline automatically benefits at the next run — no duplicate fix.

### Stdin/stdout contract

```
# Input (JSON, one line):
{"mfr_weight": [...14 ints...], "mfr_impedance": [...14 ints...],
 "height_cm": 180, "age": 34, "sex": 1, "captured_at": "2026-04-15T07:30:00+00:00"}

# Output (JSON, one line):
{"weight_kg": 75.84, "body_fat_pct": 24.4, "impedance_adc": 527,
 "decoder_version": "hc900_ble_v1", ...optional body comp fields...}
```

`mfr_impedance` is optional. When absent, the decoder returns weight only (no body composition).

### Raw bytes preservation

The full 14-byte manufacturer arrays are stored as hex strings in `raw_payloads.payload_json`:

```json
{
  "raw_mfr_weight_hex":    "aca017cf925c91a0202d88e00da2",
  "raw_mfr_impedance_hex": "aca017cf925c91a0a2afa0a206b9"
}
```

This enables offline reprocessing: if the Dart decoder is improved, historical raw payloads can be re-decoded without ever re-scanning the physical device.

### Deduplication key

The HC900 has no native measurement IDs. The deterministic external ID encodes enough context to make collisions physically impossible:

```
hc900_{mac_no_colon}_{YYYYmmddTHHMM}_{weight_grams}_{impedance_adc|x}
Example: hc900_a0915c92cf17_20260415T0730_75840_527
```

- **MAC** — isolates readings from different physical devices
- **Minute precision** — absorbs BLE timestamp jitter between scan sessions
- **weight_grams** — distinguishes different weights within the same minute
- **impedance_adc** — eliminates residual collision risk; `x` when no impedance

### Temporal semantics (V1)

`captured_at` (when `bleak` captured the advertisement) equals `measured_at` (effective measurement time) in V1. They are stored separately with an explicit `_measured_at_note` in the payload JSON. Future versions may allow manual time override (e.g., user steps on scale at 07:30 but opens the app at 08:00).

### Known limitations (V1)

- **Idle-phase impedance**: the btsnoop-derived test data captures a BLE advertisement during the idle/reference phase (~ADC 527), not the active BIA measurement phase (~ADC 30,000–48,000). Body composition values computed from idle-phase impedance are not clinically accurate. A live `scan_scale.py` session captures the correct active-phase packet.
- **Dart runtime required**: `dart` must be on PATH and `pulso-app` must be at `C:/src/pulso/pulso-app`. The import script fails with a clear `FileNotFoundError` if either is missing.
- **BLE on Windows**: `bleak` on Windows requires the WinRT Bluetooth API. The BLE scanner runs correctly but may need elevated permissions on some systems.

## Garmin Connect Integration — Architectural Decisions

### Why `python-garminconnect` and not the official API

Garmin's developer API requires a verified partnership application. `python-garminconnect` reverse-engineers the same SSO flow used by the Garmin Connect web app. For personal use this is appropriate; for a production SaaS product it would not be.

### Daily metric mapping

`sync_garmin.py` calls two Garmin Connect endpoints per day: `get_stats()` (activity + vitals) and `get_hrv_data()` (overnight RMSSD). Each synced day produces a single `raw_payload` with `payload_type = "garmin_connect_daily"` and is then parsed into up to 10 individual `measurements` rows:

```
resting_hr · steps · active_calories · stress_level · spo2
respiratory_rate · body_battery · hrv_rmssd · sleep_duration · sleep_score
```

Fields absent from the Garmin response (e.g., `hrv_rmssd` on incompatible devices) are silently skipped — the partial payload is still ingested; only the available metrics are written to `measurements`.

### `measured_at` timezone semantics

Daily aggregates from Garmin are inherently timezone-dependent (a "day" in Tokyo ≠ a "day" in Lisbon). The sync script uses **noon in the user's local timezone** (configured in `garmin_config.json` as IANA timezone string) as the canonical `measured_at`:

```python
noon_local = datetime(year, month, day, 12, 0, 0, tzinfo=user_tz)
measured_at = noon_local.astimezone(timezone.utc)
```

Why noon? It avoids UTC-midnight ambiguity regardless of the user's UTC offset (UTC±12 covers all real timezones; noon local never crosses a UTC day boundary for offsets ≤ UTC+12).

### Deduplication and idempotency

`external_id = "garmin_connect_{YYYY-MM-DD}"` — one raw payload per calendar day per user. Re-syncing the same date is always safe (the existing record is returned, no duplicate created, curated measurements are not re-inserted).

### Token persistence

First-run authentication writes OAuth2 tokens to the path specified in `garmin_config.json` as `token_store`. Subsequent runs reload the token file. If MFA is enabled, the interactive prompt fires only on first run. Tokens expire after several weeks; the script will re-prompt at that point.

---

## UI Minimal Surface

### Design constraints

The UI follows a deliberate "minimal surface" philosophy:

- No state management library beyond TanStack Query's server state cache
- No routing library — three views handled with a single `useState`
- No UI component library — Tailwind utility classes only
- No auth — single-user personal tool, user ID in `localStorage`

The entire frontend is ~1,000 lines of TypeScript across 10 files. Complexity lives in the backend; the UI's job is to display it without introducing its own.

### Build and serving

```
npm run build  →  tsc + Vite  →  app/static/ui/
```

FastAPI serves the compiled assets directly:

```python
app.mount("/assets", StaticFiles(directory=_UI_DIR / "assets"))
@app.get("/{full_path:path}", response_model=None)  # catch-all SPA route
async def serve_ui(full_path: str) -> FileResponse | PlainTextResponse: ...
```

No separate web server, no CORS configuration, no reverse proxy needed in production. The API and UI share the same origin.

### Query cache strategy

TanStack Query v5 with `staleTime = 5 minutes` for all read queries. After a successful mutation the affected query keys are invalidated immediately:

| Mutation | Invalidated keys |
|----------|-----------------|
| `POST /checkpoints/` | `['checkpoints']`, `['summary', userId]` |
| `POST /symptoms/logs` | `['symptomLogs']`, `['summary', userId]` |
| `POST /medications/logs` | `['medLogs']`, `['summary', userId]`, `['adherence', userId]` |
| `POST /measurements/` | `['measurements']`, `['summary', userId]` |

The summary card always reflects the current state of the data without a manual page refresh.

### FreshnessBar — per-source data staleness

Rather than a single "data as of" timestamp, the FreshnessBar makes three lightweight queries (`limit=1`) to show independently when each source last reported:

- **Garmin** — most recent `hrv_rmssd` measurement (Garmin is the only source for this metric)
- **Scale** — most recent `weight` measurement (HC900 is the only source in practice)
- **Manual** — whether a morning or night checkpoint exists for today

Green dot = today, amber = yesterday, grey = no data.

---

## What We Chose NOT To Do

- **No soft-delete.** V1 is append-only. Records are never logically deleted. This simplifies queries (no `WHERE deleted_at IS NULL` everywhere) and matches the health-data semantics (a measurement happened; you can add a correction, but the original observation stands).
- **No authentication.** The `users` table exists for multi-tenancy and FK integrity, not for auth. V1 focuses on the data model, not access control.
- **No TimescaleDB.** Pure PostgreSQL handles the expected data volume (years of personal health data = millions of rows at most). Hypertables add operational complexity without measurable benefit at this scale.
- **No event sourcing.** Append-only + raw payload preservation gives most of the audit benefits without the complexity of an event store, projections, and eventual consistency.
- **No async lazy loading.** All relationships use explicit `selectinload` in repositories. SQLAlchemy's async driver doesn't support implicit lazy loading — and we wouldn't want it anyway (N+1 queries are a bug, not a feature).
