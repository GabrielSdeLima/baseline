# Operations Guide

Day-to-day reference for running Baseline as a personal health tracking system.

---

## Prerequisites

All operations below assume:

```bash
docker compose up -d          # PostgreSQL on port 5433
uvicorn app.main:app --reload  # API on port 8000 (or --port 8001 for dev with Vite proxy)
```

Scripts read `BASELINE_API_URL` from the environment (default: `http://localhost:8000`). Override per-invocation with `--api-url`, or export `BASELINE_API_URL=http://localhost:8001` when the API is running on the dev port.

Your user UUID is stored in the browser's `localStorage` under `baseline_user_id`. Retrieve it from the database if needed:

```bash
psql -h localhost -p 5433 -U baseline -d baseline -c "SELECT id, created_at FROM users;"
```

---

## Garmin Sync

### First run (one time)

```bash
pip install -e ".[garmin]"
cp scripts/garmin_config.json.example scripts/garmin_config.json
# edit: email, password, token_store path, user_timezone (IANA: "America/Sao_Paulo")
```

### Daily sync

```bash
# Last 7 days (safe to re-run; existing days are skipped)
python scripts/sync_garmin.py --user-id <UUID>

# A specific day only
python scripts/sync_garmin.py --user-id <UUID> --date 2026-04-15

# Backfill a range
python scripts/sync_garmin.py --user-id <UUID> --start-date 2026-03-01 --end-date 2026-04-15

# Preview without writing to the database
python scripts/sync_garmin.py --user-id <UUID> --dry-run
```

Tokens are persisted after the first authentication. If MFA is enabled on your Garmin account, you will be prompted once; subsequent runs skip MFA.

### What gets imported

10 metrics per synced day: `resting_hr`, `steps`, `active_calories`, `stress_level`, `spo2`, `respiratory_rate`, `body_battery`, `hrv_rmssd`, `sleep_duration`, `sleep_score`. Missing fields (e.g., HRV on incompatible devices) are silently skipped.

### Freshness check

The Today page's FreshnessBar shows when the most recent `hrv_rmssd` was recorded. If it says "yesterday" or older, run the sync.

### Auto-sync (built into the API)

The FastAPI lifespan runs a scheduler that keeps Garmin data current with zero manual intervention:

1. **Startup catch-up** — when the API boots, it looks up the most recent Garmin measurement for `BASELINE_USER_ID` and backfills every missed day up to today (7-day initial backfill for a fresh user). Garmin stores data in their cloud, so PC downtime never causes data loss.
2. **Recurring loop** — every `SYNC_INTERVAL_MIN` minutes (default 60) pulls the last day so intraday updates (sleep score, body battery) are captured as Garmin emits them.

Required env vars (see `.env.example`):

```bash
BASELINE_USER_ID=<your-uuid>
SYNC_INTERVAL_MIN=60        # set to 0 to disable the recurring loop (catch-up still runs)
```

If prerequisites are missing (`BASELINE_USER_ID` unset, `scripts/garmin_config.json` absent), the scheduler logs one info line and exits quietly — the API keeps serving normally.

### Auto-start on Windows log-on (optional)

To have the API start automatically whenever you log in to Windows — no terminal required:

```powershell
# One-time setup (per user, no admin rights needed)
powershell -ExecutionPolicy Bypass -File scripts\register_autostart.ps1
```

This registers a Task Scheduler entry named `BaselineAPI` with an `-AtLogOn` trigger. The task runs `scripts\start_api.ps1`, which activates the venv, loads `.env`, and launches `uvicorn`.

Useful commands:

```powershell
Start-ScheduledTask    -TaskName BaselineAPI               # run now (for testing)
Stop-ScheduledTask     -TaskName BaselineAPI               # stop the running instance
Get-ScheduledTaskInfo  -TaskName BaselineAPI               # last run time and result
Unregister-ScheduledTask -TaskName BaselineAPI -Confirm:$false   # remove
```

Combined with auto-sync, this means: **turn the PC on → API starts → Garmin backfills any gap → data stays fresh hourly** for as long as the machine is on.

---

## HC900 Scale Import

### Prerequisites

- Bluetooth available (Windows: WinRT Bluetooth API via `bleak` — no elevated permissions needed on Windows 11)
- No Dart runtime or external project required — the decoder is Python-native

```bash
cp scripts/scale_profile.json.example scripts/scale_profile.json
# edit: height_cm, birth_date (YYYY-MM-DD), sex (1 = male, 2 = female)
```

### Pairing / device targeting

The scale is identified by BLE company ID `0xA0AC`. If multiple HC900 units are in range, pass `--mac` to target a specific one:

```bash
python scripts/discover_scales.py   # list nearby HC900 MAC addresses
```

### Import a reading

```bash
# Step on the scale, wait for it to stabilise (green light), then:
python scripts/import_scale.py --user-id <UUID>

# Target a specific scale by MAC
python scripts/import_scale.py --user-id <UUID> --mac A0:91:5C:92:CF:17

# Override profile fields without editing the JSON file
python scripts/import_scale.py --user-id <UUID> --height-cm 180 --birth-date 1991-08-15 --sex 1

# Preview without writing to the database
python scripts/import_scale.py --user-id <UUID> --dry-run
```

The script scans BLE passively for up to 15 seconds, captures the stable weight packet (and impedance when available), decodes natively via `app.integrations.hc900`, and POSTs to the API. Re-running for the same measurement is safe (deduplication by `hc900_{mac}_{timestamp}_{weight_grams}_{impedance_adc}`).

### What gets imported

Up to 18 measurements per weighing, depending on what the scale transmitted:

| State | Metrics stored |
|---|---|
| `full_reading` — impedance captured | `weight`, `impedance_adc`, `bmi`, `bmr`, and all 14 impedance-dependent body-comp metrics |
| `weight_only` — no impedance packet | `weight`, `bmi`, `bmr` |
| `never_measured` — first run, no data | nothing stored yet |

The **Latest Scale Reading** card on the Today page shows which state the most recent weighing is in.

### Scan from the UI

The **Scan** button in the FreshnessBar triggers the same pipeline via `POST /api/v1/integrations/scale/scan`. The profile and MAC address come from the Settings page (`localStorage`). On success, the Latest Scale Reading card updates automatically — no page reload required.

### Reprocess historical readings

If the decoder is updated, apply it to all historical payloads without re-scanning the device:

```bash
# Reprocess all HC900 payloads for a user (date range optional)
python scripts/reprocess_hc900.py --user-id <UUID>
python scripts/reprocess_hc900.py --user-id <UUID> --start-date 2026-01-01 --end-date 2026-04-16

# Preview: show what would change without writing
python scripts/reprocess_hc900.py --user-id <UUID> --dry-run
```

This replaces existing curated measurements for each payload in scope using the current V2 decoder (`hc900_ble_v2`). The raw bytes in `raw_payloads.payload_json` are the source of truth — they are never modified.

Freshness is shown in the **Scale** chip in the FreshnessBar.

---

## Manual Inputs (UI)

Open the **Quick Input** modal (+ button) for manual data entry.

| Tab | What to log | When |
|-----|-------------|------|
| **Check-in** | Morning: sleep quality, energy, mood. Night: energy, mood. | Each morning and night |
| **Symptom** | Symptom type, intensity (1–10), optional time override | When a symptom occurs |
| **Med Log** | Which regimen, taken/skipped/delayed, timestamp | After taking (or skipping) medication |
| **Measure** | Body temperature (°C) | Any manual measurement |

Weight is intentionally absent — the scale import handles it automatically.

**Symptom time:** defaults to "now." Click "edit time" to record a symptom that started earlier.

**Checkpoint type:** morning check-in surfaces sleep quality as the first field. Night check-in shows only energy and mood (sleep quality is not relevant at night).

---

## Daily Workflow

A suggested routine that keeps the data complete:

1. **Step on the scale** (morning, before eating): `python scripts/import_scale.py --user-id <UUID>` or use the **Scan** button in the FreshnessBar
2. **Morning check-in** (UI, Check-in tab): log sleep quality, energy, mood
3. **Garmin sync** (can run at any time): `python scripts/sync_garmin.py --user-id <UUID>`
4. **Log symptoms** as they occur during the day
5. **Log medication doses** after taking them
6. **Night check-in** (UI, Check-in tab): log energy, mood

---

## Interpreting the UI

### Today page

| Card | What it shows | What "insufficient_data" / empty state means |
|------|--------------|-------------------------------|
| Illness Signal | Composite deviation signal (temp z-score, HRV z-score, resting HR z-score, symptom burden) | Fewer than 3 HRV readings — baseline not yet established |
| Recovery Status | HRV trend vs training load | Same as above |
| Physiological Deviations | Metrics where \|z-score\| > 2.0 vs your 14-day rolling average | Shows "Baseline forming" when HRV count < 3 |
| Symptom Burden | Sum of today's symptom intensities | — |
| Medication Adherence | Overall % across active regimens | "No active regimens" when none configured |
| Latest Scale Reading | Most recent weighing: weight, body-comp grid, BIA caveat | "No readings yet — use the Scan button" when `never_measured` |

**FreshnessBar interpretation:**

- Green dot = data from today
- Amber dot = data from yesterday (Garmin sync may be needed)
- Grey dot = no data yet

### Timeline page

7-day rolling table. `–` means no reading was recorded for that cell on that day (not zero; truly absent). HRV values shown in ms; illness and recovery signals shown as colour-coded badges.

### Insight signal values

| Value | Meaning |
|-------|---------|
| `high` | Strong deviation from baseline — warrants attention |
| `moderate` | Mild deviation — monitor |
| `low` | Within normal range for you |
| `recovered` | HRV at or above baseline, no active load |
| `recovering` | HRV below baseline, no training load |
| `strained` | HRV below baseline with training load |
| `overreaching` | HRV below baseline for 2+ consecutive days with load |
| `insufficient_data` | Fewer than 3 baseline data points — no reliable signal |

Experimental signals (`illness_signal`, `recovery_status`) show `[exp]` in the card header. Their classification method is visible on hover.

---

## Seed Data (development only)

To reset and reseed a development database:

```bash
# Drop and recreate the database
psql -h localhost -p 5433 -U baseline -d postgres -c "DROP DATABASE baseline;"
psql -h localhost -p 5433 -U baseline -d postgres -c "CREATE DATABASE baseline;"

# Re-run migrations and seed
alembic upgrade head
python scripts/seed.py
```

The seed script prints the created user's UUID. Use that UUID in the UI or when running scripts.

---

## Troubleshooting

| Symptom | Likely cause | Fix |
|---------|-------------|-----|
| API returns 503 on `/` | UI not built | `npm --prefix ui run build` |
| Garmin sync: `401 Unauthorized` | Token expired | Delete the `token_store` file, re-run sync to re-authenticate |
| Scale import: `Data source 'hc900_ble' not found` | Migration not run | `alembic upgrade head` |
| Scale import: `Impedance packet present but user profile … incomplete` | `scale_profile.json` missing height, birth_date, or sex | Edit `scripts/scale_profile.json` or pass `--height-cm`, `--birth-date`, `--sex` flags |
| Scale card shows `weight_only` unexpectedly | Impedance packet not captured (scale idle phase) | Step on the scale and wait for the stable green-light reading before scanning |
| Scale card still shows old data after Scan | Browser cache — stale `scale-latest` key | Hard-reload (Ctrl+Shift+R) once; if recurring, check that `onSuccess` invalidation fires in network tab |
| `insufficient_data` on all cards | Not enough data yet | Sync at least 3 days of Garmin data |
| FreshnessBar all grey | No data for any source | Run Garmin sync, log a checkpoint |
| Deviations never flag anything | Baseline too stable or threshold too high | Default threshold is `|z| > 2.0`; seed data has clear deviations in illness phase |
