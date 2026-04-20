# Baseline

Personal longitudinal health data platform. Cross-references performance data (Garmin wearable) with clinical state data (weight, temperature, symptoms, medication adherence) to support health inference over time.

Built for daily personal use. Also a portfolio case for backend data platform engineering.

---

## The Problem

Garmin shows HRV trends. The smart scale shows weight. Nothing connects them. Over months, you have signals that should correlate — HRV dropping when you skip medication, weight drifting when sleep quality degrades — but no tool that tracks this longitudinally and computes it against your own baseline.

Baseline keeps everything in one relational schema, ingests from real devices, and computes signals against the individual — not a population average.

---

## Principles

**Honest semantics.** If data is missing, the system says so. `insufficient_data` is an explicit state throughout the stack. There are no defaults to "all clear" when the baseline window is thin.

**Individual baseline.** Deviation is z-scored against your own 14-day rolling average, not fixed population thresholds. What's a 3σ event for one person may be noise for another.

**Raw data preserved.** Device payloads are stored verbatim (JSONB) before parsing. The curated layer is derived and carries a `raw_payload_id` FK for full lineage. Parsers can be re-run against historical data.

**Operational traceability.** Every sync, scan, or replay creates an `IngestionRun` record with status, counters, and cursor. The system tracks what ran, when, and what it produced.

---

## Architecture

```
Browser (React + TypeScript)
    ↓  /api/v1/*
FastAPI (async — OpenAPI at /docs)
    ├── Garmin scheduler  (lifespan task: startup backfill + hourly sync)
    ├── Service layer     (ingestion pipeline, insight heuristics, operational state)
    └── SQLAlchemy 2.0 async → PostgreSQL 16
          ├── Raw         raw_payload (JSONB, append-only)
          ├── Curated     measurements · checkpoints · symptoms · medications
          └── Analytical  5 SQL views  (z-scores, deltas, burden, adherence)
```

**Data sources:**

| Source | Mechanism | Frequency |
|--------|-----------|-----------|
| Garmin Connect | `python-garminconnect`, 10 metrics/day | Automated hourly (lifespan scheduler) |
| HC900 BLE scale | BLE scan + Python-native decoder, 18 metrics | On-demand (UI button or CLI) |
| Manual | Check-ins, symptoms, medication doses via Log surface | User-triggered |

---

## Surfaces

### Today

Daily health snapshot. Four insight cards — illness signal, recovery status, physiological deviations, symptom burden — plus medication adherence and the latest scale reading.

Each signal uses the two-tier model: SQL views compute z-scores and deltas, Python services apply labels. A metric more than 2σ from your 14-day baseline is flagged. When the baseline has fewer than 3 data points, the card shows "Baseline forming" rather than false-confidence zero-deviation.

FreshnessBar shows per-source status (Garmin, Scale, check-ins) with last-seen timestamps. Refresh Garmin triggers an on-demand sync without leaving the page.

### Log

Full-screen overlay opened via `+ Log`. Five sections:

| Section | What it captures |
|---------|-----------------|
| Check-in | Mood, energy, sleep quality, body state (morning and night) |
| Symptoms | Slug from catalog, intensity 1–10, optional notes |
| Temperature | °C, with optional retroactive timestamp |
| Medication | Dose against an active regimen — taken / skipped / delayed |
| Scale | BLE scan for HC900 (same pipeline as Today's Scan button) |

### Progress

14-day retrospective. Four analytical blocks:

| Block | What it shows |
|-------|--------------|
| Protocol consistency | Check-in rate, check-out rate, medication adherence over the window |
| Signal direction | HRV and resting HR: recent 7-day mean vs prior 7-day mean, with neutral-zone filtering |
| Reported symptom burden | Recent vs prior 7-day symptom count, direction label, most frequent symptom |
| Data confidence | Garmin and scale freshness, analytical block coverage, check-in consistency |

When data is insufficient, the page shows an explicit empty state with directions — not an empty chart.

### Record

Chronological log of all entries, filterable by type: All · Check-ins · Symptoms · Temperature · Scale. Each entry shows a type badge, timestamp, and key values. No editing — the log is append-only.

---

## What Makes It Different

### Honest semantics

`insufficient_data` is not a missing value — it is a computed system state. The analytical views return `NULL` for z-score when the baseline window has fewer than 3 points. The service layer returns `"insufficient_data"` for the classification. The UI renders a distinct state at every level: Progress shows "Still collecting data", Today shows "Baseline forming", the insight summary preserves the count of signals in each state.

This is an explicit design choice: absence of data ≠ all clear.

### Individual baseline

Five SQL views compute per-user, per-metric rolling statistics over a 14-day window: `v_daily_metric`, `v_metric_baseline` (avg, stddev, z_score, delta_abs, delta_pct), `v_daily_training_load`, `v_daily_symptom_burden`, `v_medication_adherence`. The z-score is `(value - personal_avg) / personal_stddev`. Thresholds are relative, not absolute.

### Factual vs derived separation

| Layer | Role | Mutability |
|-------|------|-----------|
| `raw_payload` | Device data as received (JSONB) | Append-only |
| `measurements` | Parsed, typed values | Derived; FK to `raw_payload_id` |
| Analytical views | Feature engineering (z-scores, deltas) | Recomputable from curated layer |
| Insight services | Classification heuristics | Versioned via `method` field |

Re-running the HC900 decoder against historical payloads (`scripts/reprocess_hc900.py`) replaces the curated layer without re-fetching from the device. Garmin re-syncs follow the same pattern: new raw snapshot, delete-and-replace curated rows.

### Operational layer

Every sync or scan creates an `IngestionRun` record before the work starts:

- **Garmin sync** (`operation_type=cloud_sync`): cursor advances on success; versioned snapshots preserve every raw payload.
- **HC900 BLE scan** (`operation_type=ble_scan`): anti-overlap via 409 if a scan is already running; `X-Idempotency-Key` dedup (running → 409, completed → 200, failed → retry).
- **HC900 reprocess** (`operation_type=replay`): per-payload idempotency key; `--force` releases it.

`AgentInstance` registers the local machine. `UserDevice` stores the scale MAC (normalized to lowercase no-colons). `SourceCursor` tracks the last successful sync date per source.

---

## Stack

| Component | Choice |
|---|---|
| Runtime | Python 3.12+ |
| API framework | FastAPI |
| ORM | SQLAlchemy 2.0 (async) |
| Migrations | Alembic |
| Validation | Pydantic v2 |
| Database | PostgreSQL 16 |
| Driver | asyncpg |
| Linting | Ruff |
| Primary IDs | UUIDv7 (time-sortable) |
| UI framework | React 19 + TypeScript |
| Build | Vite |
| Styling | Tailwind CSS 3 |
| Data fetching | TanStack Query 5 |
| Backend tests | pytest + httpx |
| Frontend tests | Vitest + Testing Library |

---

## Tests

**707 total — 406 backend · 301 frontend. All green.**

### Backend (406)

| File | Tests | Coverage |
|---|---|---|
| `test_insights.py` | 118 | Classification functions, view contracts, `insufficient_data` semantics, stable vs experimental, feature math, heuristic regression, API |
| `test_operational_platform.py` | 40 | IngestionRun lifecycle, SourceCursor, AgentInstance, UserDevice |
| `test_ingestion_run_link.py` | 22 | IngestionRun ↔ raw_payload link table |
| `test_scale_scan_b4.py` | 19 | Scale scan endpoint — IngestionRun creation, idempotency, anti-overlap |
| `test_garmin_sync_endpoint.py` | 17 | Garmin sync trigger, status check, run history |
| `test_garmin_scheduler.py` | 14 | Lifespan scheduler — startup backfill, cursor advance, graceful degradation |
| `test_hc900_decoder.py` | 14 | Decoder paths: weight-only, full body-comp, profile validation |
| `test_invariants.py` | 14 | FK violations, UNIQUE constraints, CHECK constraints |
| `test_garmin_b3.py` | 12 | Versioned snapshots, delete-and-replace curated layer |
| `test_scale_latest.py` | 12 | `/scale/latest` — full_reading, weight_only, never_measured, multi-user isolation |
| `test_garmin_integration.py` | 28 | Parser (10 metrics), timezone semantics, null-safety, deduplication |
| `test_hc900_body_composition.py` | 28 | BIA formula accuracy — BMI, BMR, body fat, 14 derived metrics |
| `test_scale_integration.py` | 23 | Full HC900 pipeline (V2, 18 metrics), deduplication, rollback |
| `test_api.py` | 11 | HTTP status codes, pagination, error propagation |
| `test_domain_rules.py` | 11 | Slug resolution, medication authorization, checkpoint uniqueness |
| `test_status.py` | 10 | System status endpoint — source freshness, agent registration |
| `test_ingestion.py` | 8 | Idempotency, dedup, rollback on parser failure |
| `test_medication_b7.py` | 5 | Medication availability semantics (missing / partial / complete) |

### Frontend (301)

| File | Tests | Coverage |
|---|---|---|
| `progress-derivations.test.ts` | 57 | ProgressViewModel — all overallState paths, signal trends, consistency, symptom burden |
| `record-derivations.test.ts` | 57 | RecordViewModel — filter logic, type badges, sort order |
| `today-v2-derivations.test.ts` | 27 | TodayViewModel — action ranking, blocker logic, medication states |
| `freshness-bar.test.tsx` | 19 | Per-source chips, Scan button states (idle, scanning, success, error) |
| `capture-surface.test.tsx` | 14 | Five-section log surface — section switching, form submission, cache invalidation |
| `demo-mode.test.tsx` | 14 | Presentation mode: nav filtering, chrome reduction, URL detection |
| `medications.test.tsx` | 14 | Regimen list, log submission, empty state |
| `today-v2-home.test.tsx` | 12 | Today page — actions, blockers, completion card |
| `today-medication-b7.test.ts` | 12 | Medication availability states (missing / partial / complete) in Today |
| `progress-ui.test.tsx` | 12 | Progress rendering — no_data / limited / mixed / sufficient states |
| `quick-input.test.tsx` | 11 | Legacy quick input modal |
| `record-ui.test.tsx` | 10 | Record page — filter chips, entry rendering |
| `scale-reading-card.test.tsx` | 10 | Four scale states — full_reading V2, V1 partial, weight_only, never_measured |
| `timeline.test.tsx` | 10 | 7-day grid, column headers, week navigation |
| `garmin-sync-flow.test.tsx` | 7 | Garmin sync trigger → run status polling |
| `record-regression.test.tsx` | 6 | Edge cases — empty state, multi-type entries |
| `progress-regression.test.tsx` | 5 | Degraded states — partial fetch failures |
| `scale-scan-invalidation.test.tsx` | 1 | BLE scan → cache invalidation → card auto-update |

---

## Limitations

**No authentication.** User ID is self-selected and stored in `localStorage`. Single-user personal tool — not designed for multi-user access or sharing. UUID access provides no security boundary.

**No correlation analysis.** The analytical views and feature layer are built. Querying "does my HRV correlate with sleep quality?" or "does skipping medication affect next-day recovery?" requires a correlation service that doesn't exist yet. The raw material is there.

**Heuristics are experimental.** Illness signal (`method: baseline_deviation_v1`) and recovery status (`method: load_hrv_heuristic_v1`) are useful pattern detectors but aren't validated against clinical outcomes. They are explicitly labeled as experimental in API responses.

**HC900 body composition is estimated.** `impedance_adc` is a raw ADC integer, not ohms. Body fat, muscle, water, and all derived metrics are BIA regression estimates against population-level formulas. They track relative change reliably; absolute values are approximate.

**Local deployment only.** Runs on localhost. Auto-starts on Windows login via Task Scheduler. No TLS, no reverse proxy, no remote access.

**No automated alerts.** No notifications when the illness signal is high. The user checks the Today page.

---

## Next Steps

1. **Medications** — active regimens aren't entered yet; adherence insight shows N/A.
2. **Workout ingestion** — Garmin activity data exists in the API but isn't parsed or ingested.
3. **Correlation layer** — the main value proposition of the platform is cross-referencing; the foundation is built, the analysis isn't.
4. **Authentication** — prerequisite before this becomes shareable or multi-user.

---

See [`docs/architecture.md`](docs/architecture.md) for schema and trade-off detail, [`docs/data-model.md`](docs/data-model.md) for the full ERD, and [`docs/operations.md`](docs/operations.md) for the daily operations guide.
