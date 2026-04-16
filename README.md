# Baseline

A personal **longitudinal health data platform** that cross-references performance metrics (Garmin, wearables) with clinical state data (weight, temperature, symptoms, medication adherence) to enable health inference.

The value is in the **data architecture** — real foreign keys, triple temporal modelling, raw/curated layer separation, and cross-domain analytical capability — surfaced through a lightweight UI and a baseline-aware insight layer.

---

## What This Proves

| Concern | How Baseline Addresses It |
|---|---|
| **Relational rigor** | 14 tables, all FKs enforced at DB level, CHECK constraints on value domains, partial indexes for dedup and queue processing |
| **Temporal precision** | Triple-temporal model (`measured_at` / `recorded_at` / `ingested_at`) for measurements; domain-specific timestamps for workouts, medications, and symptoms |
| **Data lineage** | Raw payloads preserved as JSONB; curated records carry `raw_payload_id` FK for full traceability |
| **Ingestion safety** | Idempotent pipeline — duplicate external IDs are de-duped, failures preserve raw data, savepoint rollback prevents partial curated records |
| **Cross-domain analysis** | Single SQL query correlates HRV, training load, sleep quality, medication adherence, and symptom intensity across a 30-day timeline |
| **Baseline-aware insights** | Deviation from your individual 14-day rolling baseline (z-score), not fixed absolute thresholds |

## Architecture

```
React UI  (Today · Timeline · Quick Input)
    ↓  /api/v1/*
FastAPI  (async, OpenAPI at /docs)
    ↓
Service layer  (business rules, slug resolution, insight heuristics)
    ↓
Repository layer  (query encapsulation, eager loading)
    ↓
SQLAlchemy 2.0  (Mapped classes, async sessions)
    ↓
PostgreSQL 16  (TIMESTAMPTZ, JSONB, partial indexes)
```

See [docs/architecture.md](docs/architecture.md) for trade-off analysis and [docs/data-model.md](docs/data-model.md) for schema details.

## Quick Start

```bash
# Start PostgreSQL
docker compose up -d

# Install Python dependencies
python -m venv .venv
source .venv/bin/activate  # Windows: .venv\Scripts\activate
pip install -e ".[dev]"

# Run migrations (creates tables + analytical views + seeds lookup data)
alembic upgrade head

# Seed 30 days of realistic health data
python scripts/seed.py

# Build the UI (deploys to app/static/ui/ — served by FastAPI)
npm --prefix ui install
npm --prefix ui run build

# Start the API (serves UI + all endpoints)
uvicorn app.main:app --reload

# Visit the app
open http://localhost:8000
```

**First-time UI setup:** on first visit, you will be prompted to enter a user ID (UUID). Use the one seed.py printed, or any UUID from the `users` table:

```bash
psql -h localhost -p 5433 -U baseline -d baseline -c "SELECT id FROM users LIMIT 1;"
```

### Development mode (hot reload for UI)

```bash
# API on port 8001 (Vite dev proxy target)
uvicorn app.main:app --reload --port 8001

# In a second terminal: Vite dev server on port 5173
npm --prefix ui run dev

# Visit http://localhost:5173
```

### Run analytical queries (after seeding)

```bash
psql -h localhost -p 5433 -U baseline -d baseline -f scripts/analytics.sql
```

## UI

A minimal single-page application built to stay out of the way of the data.

**Tech stack:** React 19 · TypeScript · Vite · Tailwind CSS 3 · TanStack Query 5 · date-fns

**Three views:**

| View | Purpose |
|------|---------|
| **Today** | Daily summary — illness signal, recovery status, physiological deviations, symptom burden, medication adherence. FreshnessBar shows when each data source last reported. |
| **Timeline** | 7-day rolling table — HRV, illness signal, recovery status, symptoms, check-ins per day. |
| **Quick Input** | Modal for logging checkpoints (morning/night), symptoms, medication doses, and manual measurements (body temperature). |

**Key design decisions:**

- No auth — user ID lives in `localStorage`. Single-user by design in V1.
- Mutations invalidate the `['summary', userId]` cache key immediately; no manual refresh required.
- `FreshnessBar` makes three lightweight queries: Garmin (via `hrv_rmssd`), Scale (via `weight`), Manual (today's checkpoints). Each shows "today / yesterday / no data" independently.
- Deviations card shows **"Baseline forming"** when fewer than 3 HRV readings exist, rather than misleading zero-deviation state.
- Weight is intentionally absent from Quick Input — HC900 ingestion is automatic via `scripts/import_scale.py`.

## Testing

```bash
# Backend (requires PostgreSQL running)
pytest -v

# Frontend (no server needed)
npm --prefix ui test
```

**Total: 187 tests — 152 backend + 35 frontend. All green.**

**Backend tests:**

| File | Count | What it covers |
|---|---|---|
| `test_invariants.py` | 14 | FK violations, UNIQUE constraints, CHECK constraints — DB rejects bad data even if app is bypassed |
| `test_ingestion.py` | 8 | Pipeline idempotency, duplicate dedup, rollback on parser failure, raw→curated traceability |
| `test_domain_rules.py` | 11 | Slug resolution, medication authorization, checkpoint uniqueness, Pydantic schema validation |
| `test_api.py` | 8 | HTTP status codes, pagination, error propagation |
| `test_insights.py` | 63 | Classification functions, view contracts, insufficient_data semantics, stable vs experimental separation, filter/range tests, heuristic regression, feature engineering math, service-level, API |
| `test_scale_integration.py` | 23 | Full HC900 pipeline (weight + body_fat_pct), payload audit fields, deduplication, missing-source error, malformed-payload rollback, profile helpers |
| `test_garmin_integration.py` | 25 | Parser (10 metrics), timezone semantics (measured_at = noon local), null-safety, deduplication, error paths, sync helpers |

**Frontend tests:**

| File | Count | What it covers |
|---|---|---|
| `today.test.tsx` | 11 | Symptom burden type coercion, medication no-regimens vs 0% adherence, baseline forming state, FreshnessBar rendering, insufficient_data notes |
| `freshness-bar.test.tsx` | 7 | Per-source chips (Garmin, Scale, Manual), today/yesterday/no-data labels |
| `quick-input.test.tsx` | 14 | No weight in Measure tab, started_at collapsible, morning/night ScoreRow order, med log empty state, cache invalidation after each mutation type |
| `timeline.test.tsx` | 5 | Legend, column headers, 7-row count, today marker |

## Seed Scenario

`scripts/seed.py` generates 30 days (March 2026) of physiologically correlated data:

| Phase | Days | Pattern |
|---|---|---|
| **Baseline** | 1–7 | Good sleep, stable HRV (~48 ms), regular training, no symptoms |
| **Overreach** | 8–14 | Increased volume, HRV dipping (~42 ms), knee pain after long runs |
| **Illness** | 15–21 | HRV crash (~33 ms), elevated temperature, headache + fatigue, training paused |
| **Recovery** | 22–30 | Gradual HRV recovery, residual fatigue, return to training |

## Insight Layer

Baseline computes **baseline-aware insights** from the data it tracks.

> **Baseline-first principle:** insights are based on deviation from the user's own 14-day rolling baseline (z-score), not fixed absolute thresholds. What matters is whether a value is unusual *for this person*.

> **Pattern detection for personal health tracking, NOT clinical diagnosis.**

### Two-tier architecture

| Tier | Role | Location |
|------|------|----------|
| Tier 1 — Analytical Views | Feature engineering in SQL (no labels, no thresholds) | `view_definitions/insight_views_a1b2c3d4e5f6.py` |
| Tier 2 — Insight Services | Classification heuristics in Python | `app/services/insights.py` |

### Endpoints

| Endpoint | Stability | Notes |
|----------|-----------|-------|
| `GET /api/v1/insights/medication-adherence` | **Stable** | Adherence per regimen, overall % |
| `GET /api/v1/insights/physiological-deviations` | **Stable** | Metrics where \|z_score\| > threshold |
| `GET /api/v1/insights/symptom-burden` | **Stable** | Daily symptom burden, peak date |
| `GET /api/v1/insights/illness-signal` | **Experimental V1** | `method: baseline_deviation_v1` |
| `GET /api/v1/insights/recovery-status` | **Experimental V1** | `method: load_hrv_heuristic_v1` |
| `GET /api/v1/insights/summary` | — | Aggregates all insights for today |

Experimental endpoints include a `method` field identifying the heuristic version.

**`insufficient_data`**: when the baseline window has fewer than 3 data points, the signal is explicitly `"insufficient_data"` — not `"low"` or `"recovered"`. Absence of evidence ≠ all clear.

## Garmin Connect Integration

Baseline syncs daily health summaries from Garmin Connect via `python-garminconnect`.

```bash
# Install Garmin extras
pip install -e ".[garmin]"

# Configure credentials
cp scripts/garmin_config.json.example scripts/garmin_config.json
# edit email, password, token_store, user_timezone

# Sync last 7 days (first run prompts for MFA if enabled, then saves tokens)
python scripts/sync_garmin.py --user-id <UUID>

# Backfill a specific date range
python scripts/sync_garmin.py --user-id <UUID> --start-date 2026-03-01 --end-date 2026-04-15

# Dry-run: fetch and decode without submitting
python scripts/sync_garmin.py --user-id <UUID> --dry-run
```

**10 metrics imported per day:**

| Metric | Garmin API field | Unit |
|---|---|---|
| `resting_hr` | `restingHeartRate` | bpm |
| `steps` | `totalSteps` | steps |
| `active_calories` | `activeKilocalories` | kcal |
| `stress_level` | `averageStressLevel` | score |
| `spo2` | `averageSpo2` | % |
| `respiratory_rate` | `avgWakingRespirationValue` | brpm |
| `body_battery` | `bodyBatteryMostRecentValue` | score |
| `hrv_rmssd` | `hrvSummary.lastNightAvg` | ms |
| `sleep_duration` | `sleepTimeSeconds / 60` | min |
| `sleep_score` | `sleepScores.overall.value` | score |

**`measured_at` semantics:** Daily aggregates use **noon in the user's local timezone** (from `user_timezone` in `garmin_config.json`). This avoids UTC-day-boundary ambiguity regardless of sync time.

**Deduplication:** `garmin_connect_{YYYY-MM-DD}` — one payload per calendar date. Re-syncing the same day is always safe.

**HRV note:** `lastNightAvg` is real overnight RMSSD (ms), not Garmin's categorical status. Requires a compatible device (Fenix 6 Pro+, Fenix 7, Forerunner 955/265, Venu 2 Plus+, etc.).

## Real Scale Integration (HC900 BLE)

Baseline ingests real measurements from an HC900/FG260RB BLE smart scale.

```bash
# Prerequisites: PostgreSQL + API running, Pulso app at C:/src/pulso/pulso-app
cp scripts/scale_profile.json.example scripts/scale_profile.json
# edit height_cm, birth_date, sex

# Step on the scale and run (discovers via BLE, imports automatically)
python scripts/import_scale.py --user-id <UUID>

# Dry-run: scan and decode but don't submit
python scripts/import_scale.py --user-id <UUID> --dry-run

# Filter by MAC address (if multiple scales nearby)
python scripts/import_scale.py --user-id <UUID> --mac A0:91:5C:92:CF:17
```

**How it works:**
1. `scan_scale.py` passively scans BLE for HC900 advertisements (company ID `0xA0AC`)
2. `import_scale.py` calls `dart run tools/decode_scale.dart` (Pulso project) via subprocess — Pulso is the authoritative decode source
3. The normalised payload is POSTed to `/api/v1/raw-payloads/ingest` with a deterministic `external_id` for deduplication
4. The `_parse_hc900_scale` parser extracts `weight` and `body_fat_pct` into the curated layer

**Deduplication key:** `hc900_{mac}_{YYYYmmddTHHMM}_{weight_grams}_{impedance_adc|x}`

## Analytical Queries

`scripts/analytics.sql` contains 7 cross-domain queries:

1. **HRV 7-day rolling average** — trend analysis with window functions
2. **Training load vs next-day HRV** — workout RPE × duration correlated with recovery
3. **Medication adherence rate** — taken/skipped/delayed breakdown per regimen
4. **Sleep quality → next-morning energy** — checkpoint self-join across types
5. **Symptom-workout correlation** — symptoms preceded by workouts within 48 h
6. **Multi-domain daily dashboard** — one query, 6 tables, complete daily picture
7. **Illness detection signal** — multi-signal pattern matching (temp + HRV + symptoms)

## Stack

| Component | Choice |
|---|---|
| Runtime | Python 3.12+ |
| Framework | FastAPI |
| ORM | SQLAlchemy 2.0 (async) |
| Migrations | Alembic |
| Validation | Pydantic v2 |
| Database | PostgreSQL 16 |
| Driver | asyncpg |
| Backend tests | pytest + httpx |
| Linting | Ruff |
| IDs | UUIDv7 (time-sortable) |
| UI framework | React 19 + TypeScript |
| UI build | Vite 8 |
| UI styling | Tailwind CSS 3 |
| UI state | TanStack Query 5 |
| UI dates | date-fns 4 |
| Frontend tests | Vitest + Testing Library |

## V1 Boundaries

Explicit about what's **not** included and why:

- **No authentication** — user ID is stored in localStorage. Single-user personal use only; not designed for sharing or multi-user access.
- **No TimescaleDB** — pure PostgreSQL handles the scale (personal health data = millions of rows, not billions)
- **No derived metrics** — `is_derived` and `confidence` columns exist as extension points but no pipeline populates them
- **No unit conversion** — measurements store the unit as-received
- **No soft-delete** — append-only by design; corrections are new records
- **No real-time push** — the UI polls via TanStack Query stale-time; no WebSocket or SSE

---

Built as a professional portfolio case demonstrating data platform thinking, relational modelling rigour, and full-stack backend engineering quality.
