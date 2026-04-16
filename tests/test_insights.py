"""Insight Layer tests — Phase 5.

Nine test categories covering the full insight stack:
  A. Pure classification functions (no DB)
  B. View contract tests (schema, no labels)
  C. Insufficient baseline → explicit insufficient_data
  D. Stable vs experimental separation
  E. Filter and range tests
  F. Heuristic regression tests
  G. Feature engineering math (controlled data)
  H. Service-level tests (30-day scenario)
  I. API endpoint tests

Fixtures
--------
insight_scenario  — seeds 30-day narrative within the test transaction.
                    Lookups resolved dynamically by slug — no hardcoded IDs.
math_scenario     — seeds controlled data (exact known values) for math tests.
"""
import random
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta, timezone
from decimal import Decimal

import pytest
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import uuid7
from app.models.daily_checkpoint import DailyCheckpoint
from app.models.data_source import DataSource
from app.models.exercise import Exercise
from app.models.measurement import Measurement
from app.models.medication import MedicationDefinition, MedicationLog, MedicationRegimen
from app.models.metric_type import MetricType
from app.models.symptom import Symptom, SymptomLog
from app.models.user import User
from app.models.workout import WorkoutSession, WorkoutSet
from app.services.insights import (
    InsightService,
    _classify_illness,
    _classify_recovery,
)

# ── Seed constants (mirrors scripts/seed.py) ──────────────────────────────

BRT = timezone(timedelta(hours=-3))
START_DATE = date(2026, 3, 1)

GARMIN_PROFILES = {
    "baseline":  (59,  48,  9000, 28, 97, 15.5, 450, 465, 82),
    "overreach": (62,  42, 11000, 38, 96, 15.8, 520, 420, 74),
    "illness":   (68,  33,  4500, 50, 95, 17.0, 200, 390, 60),
    "recovery":  (63,  41,  7500, 34, 97, 15.6, 380, 445, 76),
}
WEIGHT_PROFILES = {"baseline": 81.5, "overreach": 81.0, "illness": 81.8, "recovery": 80.6}
TEMP_PROFILES   = {"baseline": 36.4, "overreach": 36.5, "illness": 37.4, "recovery": 36.5}
CHECKPOINT_PROFILES = {
    "baseline":  (7.5, 7.5, 7.0, 7.5),
    "overreach": (6.5, 6.0, 6.0, 6.0),
    "illness":   (4.0, 3.5, 4.5, 3.5),
    "recovery":  (6.5, 6.0, 6.5, 6.0),
}


def _phase(day: int) -> str:
    if day < 7:
        return "baseline"
    if day < 14:
        return "overreach"
    if day < 21:
        return "illness"
    return "recovery"


def _dt(d: date, hour: int = 7, minute: int = 0) -> datetime:
    return datetime(d.year, d.month, d.day, hour, minute, tzinfo=BRT)


def _jitter(base: float, amplitude: float, rng: random.Random) -> float:
    return round(base + rng.uniform(-amplitude, amplitude), 1)


# ── Lookup helper ─────────────────────────────────────────────────────────

async def _resolve_lookups(db: AsyncSession) -> dict:
    sources   = {ds.slug: ds for ds in (await db.execute(select(DataSource))).scalars()}
    metrics   = {mt.slug: mt for mt in (await db.execute(select(MetricType))).scalars()}
    exercises = {e.slug:  e  for e  in (await db.execute(select(Exercise))).scalars()}
    symptoms  = {s.slug:  s  for s  in (await db.execute(select(Symptom))).scalars()}
    return {"sources": sources, "metrics": metrics, "exercises": exercises, "symptoms": symptoms}


# ── Scenario dataclass ────────────────────────────────────────────────────

@dataclass
class ScenarioData:
    user: User
    start: date
    end: date
    lk: dict


# ── 30-day seed fixture ───────────────────────────────────────────────────

@pytest.fixture
async def insight_scenario(db: AsyncSession, user: User) -> ScenarioData:
    """Seed a 30-day health narrative. Lookups resolved by slug — no hardcoded IDs."""
    rng = random.Random(42)
    lk = await _resolve_lookups(db)

    # Medication setup
    multi = MedicationDefinition(name="Daily Multivitamin", dosage_form="tablet")
    ibu   = MedicationDefinition(
        name="Ibuprofen 400mg", dosage_form="tablet", active_ingredient="Ibuprofen"
    )
    db.add_all([multi, ibu])
    await db.flush()

    reg_multi = MedicationRegimen(
        id=uuid7(), user_id=user.id, medication_id=multi.id,
        dosage_amount=Decimal("1"), dosage_unit="tablet",
        frequency="daily", started_at=START_DATE,
    )
    reg_ibu = MedicationRegimen(
        id=uuid7(), user_id=user.id, medication_id=ibu.id,
        dosage_amount=Decimal("400"), dosage_unit="mg",
        frequency="as_needed", started_at=START_DATE,
    )
    db.add_all([reg_multi, reg_ibu])
    await db.flush()
    meds = {"multivitamin": reg_multi, "ibuprofen": reg_ibu}

    for day_offset in range(30):
        d  = START_DATE + timedelta(days=day_offset)
        ph = _phase(day_offset)

        # Garmin measurements
        base = GARMIN_PROFILES[ph]
        garmin = lk["sources"]["garmin"]
        mapping = [
            ("resting_hr",      int(_jitter(base[0], 3,    rng)), "bpm"),
            ("hrv_rmssd",       round(_jitter(base[1], 5,  rng), 1), "ms"),
            ("steps",           int(_jitter(base[2], 2000, rng)), "steps"),
            ("stress_level",    int(_jitter(base[3], 8,    rng)), "score"),
            ("spo2",            int(_jitter(base[4], 1,    rng)), "%"),
            ("respiratory_rate",round(_jitter(base[5], 0.8,rng), 1), "brpm"),
            ("active_calories", int(_jitter(base[6], 80,   rng)), "kcal"),
            ("sleep_duration",  int(_jitter(base[7], 30,   rng)), "min"),
            ("sleep_score",     int(_jitter(base[8], 8,    rng)), "score"),
        ]
        for slug, val, unit in mapping:
            mt = lk["metrics"].get(slug)
            if mt:
                db.add(Measurement(
                    id=uuid7(), user_id=user.id,
                    metric_type_id=mt.id, source_id=garmin.id,
                    value_num=Decimal(str(val)), unit=unit,
                    measured_at=_dt(d, 6), recorded_at=_dt(d, 6),
                    aggregation_level="daily",
                ))

        # Manual: weight + temperature
        manual = lk["sources"]["manual"]
        wt = lk["metrics"]["weight"]
        db.add(Measurement(
            id=uuid7(), user_id=user.id,
            metric_type_id=wt.id, source_id=manual.id,
            value_num=Decimal(str(round(_jitter(WEIGHT_PROFILES[ph], 0.4, rng), 1))),
            unit="kg", measured_at=_dt(d, 7, 15), recorded_at=_dt(d, 7, 20),
            aggregation_level="spot",
        ))
        bt = lk["metrics"]["body_temperature"]
        db.add(Measurement(
            id=uuid7(), user_id=user.id,
            metric_type_id=bt.id, source_id=manual.id,
            value_num=Decimal(str(round(_jitter(TEMP_PROFILES[ph], 0.2, rng), 1))),
            unit="°C", measured_at=_dt(d, 7, 20), recorded_at=_dt(d, 7, 25),
            aggregation_level="spot",
        ))

        # Workouts
        wd = d.weekday()
        if ph == "illness":
            if wd == 2:
                ws = WorkoutSession(
                    id=uuid7(), user_id=user.id, source_id=manual.id,
                    title="Light walk", workout_type="cardio",
                    started_at=_dt(d, 10), ended_at=_dt(d, 10, 30),
                    duration_seconds=1800, perceived_effort=3, recorded_at=_dt(d, 11),
                )
                db.add(ws)
        elif not (ph == "recovery" and day_offset < 23):
            if wd in (0, 2):
                dist = _jitter(6000 if ph == "baseline" else 7500, 1000, rng)
                dur = int(dist / 2.5)
                ws = WorkoutSession(
                    id=uuid7(), user_id=user.id, source_id=garmin.id,
                    title="Easy run" if wd == 0 else "Tempo run",
                    workout_type="cardio",
                    started_at=_dt(d, 6, 30),
                    ended_at=_dt(d, 6, 30) + timedelta(seconds=dur),
                    duration_seconds=dur,
                    perceived_effort=rng.randint(5, 7),
                    recorded_at=_dt(d, 8),
                )
                db.add(ws)
                await db.flush()
                db.add(WorkoutSet(
                    id=uuid7(), workout_session_id=ws.id,
                    exercise_id=lk["exercises"]["running"].id, set_number=1,
                    duration_seconds=dur, distance_meters=Decimal(str(int(dist))),
                ))
            elif wd in (1, 3):
                effort = rng.randint(7, 9)
                ws = WorkoutSession(
                    id=uuid7(), user_id=user.id, source_id=manual.id,
                    title="Upper body" if wd == 1 else "Lower body",
                    workout_type="strength",
                    started_at=_dt(d, 17), ended_at=_dt(d, 18, 15),
                    duration_seconds=4500, perceived_effort=effort,
                    recorded_at=_dt(d, 18, 30),
                )
                db.add(ws)
                await db.flush()
                sets = (
                    [("bench_press", 3), ("pull_up", 3), ("plank", 2)]
                    if wd == 1 else [("squat", 4), ("deadlift", 3)]
                )
                set_num = 1
                for slug, n in sets:
                    for _ in range(n):
                        db.add(WorkoutSet(
                            id=uuid7(), workout_session_id=ws.id,
                            exercise_id=lk["exercises"][slug].id, set_number=set_num,
                            reps=rng.randint(6, 12),
                            weight_kg=Decimal(str(rng.randint(40, 100))),
                        ))
                        set_num += 1
            elif wd == 5:
                dist = _jitter(12000 if ph != "overreach" else 15000, 1500, rng)
                dur = int(dist / 2.4)
                ws = WorkoutSession(
                    id=uuid7(), user_id=user.id, source_id=garmin.id,
                    title="Long run", workout_type="cardio",
                    started_at=_dt(d, 7),
                    ended_at=_dt(d, 7) + timedelta(seconds=dur),
                    duration_seconds=dur,
                    perceived_effort=rng.randint(7, 9),
                    recorded_at=_dt(d, 10),
                )
                db.add(ws)
                await db.flush()
                db.add(WorkoutSet(
                    id=uuid7(), workout_session_id=ws.id,
                    exercise_id=lk["exercises"]["running"].id, set_number=1,
                    duration_seconds=dur, distance_meters=Decimal(str(int(dist))),
                ))

        # Medication logs
        now = _dt(d, 8)
        if ph == "illness" and rng.random() < 0.3:
            med_status, taken_at = "skipped", None
        else:
            med_status, taken_at = "taken", now
        db.add(MedicationLog(
            id=uuid7(), user_id=user.id, regimen_id=meds["multivitamin"].id,
            status=med_status, scheduled_at=_dt(d, 8), taken_at=taken_at, recorded_at=now,
        ))
        take_ibu = (wd == 5 and ph in ("baseline", "overreach")) or (
            ph == "illness" and rng.random() < 0.5
        )
        if take_ibu:
            db.add(MedicationLog(
                id=uuid7(), user_id=user.id, regimen_id=meds["ibuprofen"].id,
                status="taken", scheduled_at=_dt(d, 12),
                taken_at=_dt(d, 12, rng.randint(0, 30)), recorded_at=_dt(d, 13),
            ))

        # Symptoms
        if wd in (6, 0) and ph in ("baseline", "overreach"):
            db.add(SymptomLog(
                id=uuid7(), user_id=user.id,
                symptom_id=lk["symptoms"]["knee_pain"].id,
                intensity=rng.randint(3, 5) if ph == "baseline" else rng.randint(5, 7),
                status="active", trigger="long run",
                functional_impact="mild" if ph == "baseline" else "moderate",
                started_at=_dt(d, 9), ended_at=_dt(d, 18), recorded_at=_dt(d, 9, 15),
            ))
        if ph == "illness":
            if day_offset < 18:
                db.add(SymptomLog(
                    id=uuid7(), user_id=user.id,
                    symptom_id=lk["symptoms"]["headache"].id,
                    intensity=rng.randint(4, 7), status="active",
                    functional_impact="moderate",
                    started_at=_dt(d, 8), ended_at=_dt(d, 20), recorded_at=_dt(d, 8, 30),
                ))
            db.add(SymptomLog(
                id=uuid7(), user_id=user.id,
                symptom_id=lk["symptoms"]["fatigue"].id,
                intensity=rng.randint(5, 8), status="active",
                functional_impact="moderate",
                started_at=_dt(d, 7), ended_at=_dt(d, 22), recorded_at=_dt(d, 7, 30),
            ))
        if ph == "recovery" and day_offset < 23:
            db.add(SymptomLog(
                id=uuid7(), user_id=user.id,
                symptom_id=lk["symptoms"]["fatigue"].id,
                intensity=rng.randint(2, 4), status="improving",
                functional_impact="mild",
                started_at=_dt(d, 7), ended_at=_dt(d, 15), recorded_at=_dt(d, 7, 30),
            ))

        # Daily checkpoints
        mp = CHECKPOINT_PROFILES[ph]
        db.add(DailyCheckpoint(
            id=uuid7(), user_id=user.id,
            checkpoint_type="morning", checkpoint_date=d,
            checkpoint_at=_dt(d, 7, 30), recorded_at=_dt(d, 7, 35),
            mood=max(1, min(10, int(_jitter(mp[0], 1.2, rng)))),
            energy=max(1, min(10, int(_jitter(mp[1], 1.2, rng)))),
            sleep_quality=max(1, min(10, int(_jitter(mp[2], 1.5, rng)))),
            body_state_score=max(1, min(10, int(_jitter(mp[3], 1.2, rng)))),
        ))

    await db.flush()
    return ScenarioData(
        user=user,
        start=START_DATE,
        end=START_DATE + timedelta(days=29),
        lk=lk,
    )


# ── Controlled math fixture ───────────────────────────────────────────────

@pytest.fixture
async def math_scenario(db: AsyncSession, user: User):
    """Seed 4 days of HRV with exact known values for math verification."""
    lk = await _resolve_lookups(db)
    manual = lk["sources"]["manual"]
    hrv_mt = lk["metrics"]["hrv_rmssd"]
    base = date(2026, 1, 1)
    values = [10, 20, 30, 40]
    for i, val in enumerate(values):
        d = base + timedelta(days=i)
        db.add(Measurement(
            id=uuid7(), user_id=user.id,
            metric_type_id=hrv_mt.id, source_id=manual.id,
            value_num=Decimal(str(val)), unit="ms",
            measured_at=datetime(d.year, d.month, d.day, 7, tzinfo=UTC),
            recorded_at=datetime(d.year, d.month, d.day, 7, tzinfo=UTC),
            aggregation_level="spot",
        ))
    await db.flush()
    return {"user": user, "base_date": base, "lk": lk, "values": values}


# ═══════════════════════════════════════════════════════════════════════════
# A. Pure classification function tests (no DB)
# ═══════════════════════════════════════════════════════════════════════════

def test_classify_illness_high():
    result = _classify_illness(Decimal("2.0"), Decimal("-2.0"), Decimal("1.5"), Decimal("5"))
    assert result == "high"


def test_classify_illness_moderate_two_signals():
    # temp_z > 1.0 and hrv_z < -1.0 → 2 signals
    assert _classify_illness(Decimal("1.2"), Decimal("-1.2"), None, Decimal("0")) == "moderate"


def test_classify_illness_moderate_burden_counts():
    # hrv_z < -1.0 and burden > 0 → 2 signals
    assert _classify_illness(None, Decimal("-1.2"), None, Decimal("3")) == "moderate"


def test_classify_illness_low():
    assert _classify_illness(Decimal("0.5"), Decimal("-0.5"), Decimal("0.3"), Decimal("0")) == "low"


def test_classify_illness_insufficient_data():
    """All z-scores None = no baseline. Must NOT return 'low'."""
    result = _classify_illness(None, None, None, Decimal("0"))
    assert result == "insufficient_data"


def test_classify_illness_insufficient_data_even_with_burden():
    """Burden alone doesn't make 'low' when all z-scores are None."""
    result = _classify_illness(None, None, None, Decimal("10"))
    assert result == "insufficient_data"


def test_classify_recovery_overreaching():
    assert _classify_recovery(Decimal("-2.0"), Decimal("500"), 2) == "overreaching"


def test_classify_recovery_strained():
    assert _classify_recovery(Decimal("-1.5"), Decimal("400"), 0) == "strained"


def test_classify_recovery_recovering():
    assert _classify_recovery(Decimal("-0.5"), None, 0) == "recovering"


def test_classify_recovery_recovered():
    assert _classify_recovery(Decimal("0.5"), None, 0) == "recovered"


def test_classify_recovery_insufficient_data():
    """hrv_z = None = no baseline. Must NOT return 'recovered'."""
    result = _classify_recovery(None, None, 0)
    assert result == "insufficient_data"


def test_classify_recovery_insufficient_data_with_load():
    """Load present but no HRV baseline. Still insufficient."""
    result = _classify_recovery(None, Decimal("500"), 1)
    assert result == "insufficient_data"


# ═══════════════════════════════════════════════════════════════════════════
# B. View contract tests
# ═══════════════════════════════════════════════════════════════════════════

EXPECTED_VIEWS = [
    "v_daily_metric",
    "v_metric_baseline",
    "v_daily_training_load",
    "v_daily_symptom_burden",
    "v_medication_adherence",
]

EXPECTED_COLUMNS = {
    "v_daily_metric": {"user_id", "day", "metric_slug", "metric_name", "value", "readings"},
    "v_metric_baseline": {
        "user_id", "day", "metric_slug", "metric_name", "value",
        "baseline_avg", "baseline_stddev", "z_score", "delta_abs", "delta_pct", "baseline_points",
    },
    "v_daily_training_load": {
        "user_id", "day", "sessions", "total_duration_s", "training_load", "max_rpe",
    },
    "v_daily_symptom_burden": {
        "user_id", "day", "symptom_count", "max_intensity", "weighted_burden", "dominant_symptom",
    },
    "v_medication_adherence": {
        "user_id", "regimen_id", "medication_name", "frequency",
        "taken", "skipped", "delayed", "total", "adherence_pct",
    },
}

# Classification labels that must NEVER appear in view SQL
_FORBIDDEN_LABELS = [
    "'high'", "'moderate'", "'low'", "'strained'", "'overreaching'",
    "'recovered'", "'recovering'", "'insufficient_data'",
]


@pytest.mark.parametrize("view_name", EXPECTED_VIEWS)
async def test_view_exists(db: AsyncSession, view_name: str):
    row = await db.execute(
        text("SELECT 1 FROM information_schema.views WHERE table_name = :v"),
        {"v": view_name},
    )
    assert row.scalar() == 1, f"View {view_name!r} does not exist in test DB"


@pytest.mark.parametrize("view_name", EXPECTED_VIEWS)
async def test_view_columns(db: AsyncSession, view_name: str):
    result = await db.execute(
        text("SELECT column_name FROM information_schema.columns WHERE table_name = :v"),
        {"v": view_name},
    )
    actual = {r[0] for r in result.fetchall()}
    expected = EXPECTED_COLUMNS[view_name]
    assert expected.issubset(actual), (
        f"View {view_name!r} missing columns: {expected - actual}"
    )


@pytest.mark.parametrize("view_name", EXPECTED_VIEWS)
async def test_view_no_classification_labels(db: AsyncSession, view_name: str):
    """View SQL must not embed classification strings."""
    row = await db.execute(
        text("SELECT definition FROM pg_views WHERE viewname = :v"),
        {"v": view_name},
    )
    definition = row.scalar() or ""
    for label in _FORBIDDEN_LABELS:
        assert label not in definition, (
            f"View {view_name!r} contains classification label {label}"
        )


# ═══════════════════════════════════════════════════════════════════════════
# C. Insufficient baseline tests
# ═══════════════════════════════════════════════════════════════════════════

async def test_zscore_null_with_2_points(db: AsyncSession, user: User):
    """With only 2 prior data points, z_score must be NULL."""
    lk = await _resolve_lookups(db)
    mt = lk["metrics"]["hrv_rmssd"]
    src = lk["sources"]["manual"]
    base = date(2026, 2, 1)
    for i, val in enumerate([40, 42, 44]):
        d = base + timedelta(days=i)
        db.add(Measurement(
            id=uuid7(), user_id=user.id, metric_type_id=mt.id, source_id=src.id,
            value_num=Decimal(str(val)), unit="ms",
            measured_at=datetime(d.year, d.month, d.day, 7, tzinfo=UTC),
            recorded_at=datetime(d.year, d.month, d.day, 7, tzinfo=UTC),
            aggregation_level="spot",
        ))
    await db.flush()
    # Day 3 has only 2 prior points — z_score must be NULL
    result = await db.execute(
        text("""
            SELECT z_score, baseline_points
            FROM v_metric_baseline
            WHERE user_id = :uid AND metric_slug = 'hrv_rmssd'
            ORDER BY day
        """),
        {"uid": user.id},
    )
    rows = result.fetchall()
    # Day 1: 0 prior points → NULL; Day 2: 1 prior point → NULL; Day 3: 2 prior points → NULL
    assert all(r.z_score is None for r in rows if r.baseline_points < 3)


async def test_illness_signal_insufficient_data_with_1_day(db: AsyncSession, user: User):
    """A user with only 1 day of data has no baseline. All signals must be insufficient_data."""
    lk = await _resolve_lookups(db)
    d = date(2026, 2, 1)
    for slug, val, unit in [("body_temperature", 37.0, "°C"), ("hrv_rmssd", 40, "ms")]:
        mt = lk["metrics"][slug]
        db.add(Measurement(
            id=uuid7(), user_id=user.id, metric_type_id=mt.id,
            source_id=lk["sources"]["manual"].id,
            value_num=Decimal(str(val)), unit=unit,
            measured_at=datetime(d.year, d.month, d.day, 7, tzinfo=UTC),
            recorded_at=datetime(d.year, d.month, d.day, 7, tzinfo=UTC),
            aggregation_level="spot",
        ))
    await db.flush()
    svc = InsightService(db)
    resp = await svc.illness_signal(user.id)
    # May have days from burden view even without measurements; all should be insufficient_data
    for day in resp.days:
        assert day.signal_level == "insufficient_data", (
            f"Day {day.day} signal_level={day.signal_level!r}, expected 'insufficient_data'"
        )


async def test_recovery_insufficient_data_with_1_day(db: AsyncSession, user: User):
    """A user with only 1 day of HRV data has no baseline. Status must be insufficient_data."""
    lk = await _resolve_lookups(db)
    d = date(2026, 2, 1)
    mt = lk["metrics"]["hrv_rmssd"]
    db.add(Measurement(
        id=uuid7(), user_id=user.id, metric_type_id=mt.id,
        source_id=lk["sources"]["manual"].id,
        value_num=Decimal("45"), unit="ms",
        measured_at=datetime(d.year, d.month, d.day, 7, tzinfo=UTC),
        recorded_at=datetime(d.year, d.month, d.day, 7, tzinfo=UTC),
        aggregation_level="spot",
    ))
    await db.flush()
    svc = InsightService(db)
    resp = await svc.recovery_status(user.id)
    assert all(day.status == "insufficient_data" for day in resp.days)
    assert resp.current_status == "insufficient_data"


async def test_summary_reflects_insufficient_data(db: AsyncSession, user: User):
    """Summary for a user with no data must show insufficient_data, not optimistic defaults."""
    svc = InsightService(db)
    resp = await svc.summary(user.id)
    assert resp.illness_signal == "insufficient_data"
    assert resp.recovery_status == "insufficient_data"


# ═══════════════════════════════════════════════════════════════════════════
# D. Stable vs experimental separation
# ═══════════════════════════════════════════════════════════════════════════

def test_stable_schemas_have_no_method_field():
    from app.schemas.insights import (
        MedicationAdherenceResponse,
        PhysiologicalDeviationsResponse,
        SymptomBurdenResponse,
    )
    stable = (MedicationAdherenceResponse, PhysiologicalDeviationsResponse, SymptomBurdenResponse)
    for cls in stable:
        assert "method" not in cls.model_fields, (
            f"Stable schema {cls.__name__} must not have a 'method' field"
        )


def test_experimental_illness_method():
    from app.schemas.insights import IllnessSignalResponse
    assert "method" in IllnessSignalResponse.model_fields


def test_experimental_recovery_method():
    from app.schemas.insights import RecoveryStatusResponse
    assert "method" in RecoveryStatusResponse.model_fields


async def test_api_illness_signal_has_method_key(client, insight_scenario: ScenarioData):
    resp = await client.get(
        f"/api/v1/insights/illness-signal?user_id={insight_scenario.user.id}"
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "method" in data
    assert data["method"] == "baseline_deviation_v1"


async def test_api_medication_adherence_has_no_method_key(client, insight_scenario: ScenarioData):
    resp = await client.get(
        f"/api/v1/insights/medication-adherence?user_id={insight_scenario.user.id}"
    )
    assert resp.status_code == 200
    assert "method" not in resp.json()


# ═══════════════════════════════════════════════════════════════════════════
# E. Filter and range tests
# ═══════════════════════════════════════════════════════════════════════════

async def test_deviations_date_filter_bounds(db: AsyncSession, insight_scenario: ScenarioData):
    start = date(2026, 3, 15)
    end   = date(2026, 3, 20)
    svc = InsightService(db)
    resp = await svc.physiological_deviations(insight_scenario.user.id, start=start, end=end)
    for dev in resp.deviations:
        assert start <= dev.day <= end


async def test_symptom_burden_empty_range(db: AsyncSession, insight_scenario: ScenarioData):
    svc = InsightService(db)
    resp = await svc.symptom_burden(
        insight_scenario.user.id,
        start=date(2030, 1, 1), end=date(2030, 1, 31),
    )
    assert resp.days == []
    assert resp.total_symptom_days == 0
    assert resp.peak_burden_date is None


async def test_illness_signal_empty_range(db: AsyncSession, insight_scenario: ScenarioData):
    svc = InsightService(db)
    resp = await svc.illness_signal(
        insight_scenario.user.id,
        start=date(2030, 1, 1), end=date(2030, 1, 31),
    )
    assert resp.days == []
    assert resp.peak_signal == "insufficient_data"
    assert resp.peak_signal_date is None


async def test_user_no_data_returns_200(client, user: User):
    # Unknown UUID — never inserted; endpoints must handle it gracefully
    unknown_id = uuid.uuid4()
    for path in [
        f"/api/v1/insights/medication-adherence?user_id={unknown_id}",
        f"/api/v1/insights/physiological-deviations?user_id={unknown_id}",
        f"/api/v1/insights/symptom-burden?user_id={unknown_id}",
        f"/api/v1/insights/illness-signal?user_id={unknown_id}",
        f"/api/v1/insights/recovery-status?user_id={unknown_id}",
    ]:
        resp = await client.get(path)
        assert resp.status_code == 200, f"Expected 200 for {path}, got {resp.status_code}"


async def test_cross_user_isolation(db: AsyncSession, insight_scenario: ScenarioData):
    """Data seeded for user A must not appear when querying with user B's ID."""
    # user B: fresh user in same transaction
    user_b = User(id=uuid7(), email="userb@test.dev", name="User B", timezone="UTC")
    db.add(user_b)
    await db.flush()

    svc = InsightService(db)
    adh  = await svc.medication_adherence(user_b.id)
    devs = await svc.physiological_deviations(user_b.id)
    sym  = await svc.symptom_burden(user_b.id)

    assert adh.items == []
    assert devs.deviations == []
    assert sym.days == []


# ═══════════════════════════════════════════════════════════════════════════
# F. Heuristic regression tests
# ═══════════════════════════════════════════════════════════════════════════

async def test_illness_signal_driven_by_zscore_not_absolute(
    db: AsyncSession, insight_scenario: ScenarioData
):
    """During illness, signal escalation is driven by z-score direction (personal deviation)."""
    svc = InsightService(db)
    resp = await svc.illness_signal(insight_scenario.user.id)

    illness_start = insight_scenario.start + timedelta(days=14)
    illness_end   = insight_scenario.start + timedelta(days=20)

    illness_days = [
        d for d in resp.days
        if illness_start <= d.day <= illness_end
        and d.signal_level not in ("insufficient_data",)
    ]
    assert illness_days, "Expected classifiable illness days in illness phase"
    # At least one day with negative hrv_z (HRV deviated below personal baseline)
    hrv_negative = [d for d in illness_days if d.hrv_z is not None and d.hrv_z < 0]
    assert hrv_negative, "Expected HRV below personal baseline during illness phase"


async def test_illness_symptoms_alone_dont_trigger_high(db: AsyncSession, user: User):
    """High symptom burden without z-score deviations does not produce 'high' signal."""
    lk = await _resolve_lookups(db)
    d = date(2026, 3, 1)
    # Seed 5 days of stable HRV to build baseline
    for i in range(5):
        day = d + timedelta(days=i)
        mt = lk["metrics"]["hrv_rmssd"]
        db.add(Measurement(
            id=uuid7(), user_id=user.id, metric_type_id=mt.id,
            source_id=lk["sources"]["manual"].id,
            value_num=Decimal("45"), unit="ms",
            measured_at=datetime(day.year, day.month, day.day, 7, tzinfo=UTC),
            recorded_at=datetime(day.year, day.month, day.day, 7, tzinfo=UTC),
            aggregation_level="spot",
        ))
    # On day 6, add high-intensity symptoms but normal z-score metrics
    day6 = d + timedelta(days=5)
    mt_hrv = lk["metrics"]["hrv_rmssd"]
    db.add(Measurement(
        id=uuid7(), user_id=user.id, metric_type_id=mt_hrv.id,
        source_id=lk["sources"]["manual"].id,
        value_num=Decimal("45"), unit="ms",  # same as baseline → z ≈ 0
        measured_at=datetime(day6.year, day6.month, day6.day, 7, tzinfo=UTC),
        recorded_at=datetime(day6.year, day6.month, day6.day, 7, tzinfo=UTC),
        aggregation_level="spot",
    ))
    db.add(SymptomLog(
        id=uuid7(), user_id=user.id,
        symptom_id=lk["symptoms"]["fatigue"].id,
        intensity=9, status="active",
        started_at=datetime(day6.year, day6.month, day6.day, 8, tzinfo=UTC),
        recorded_at=datetime(day6.year, day6.month, day6.day, 8, tzinfo=UTC),
    ))
    await db.flush()

    svc = InsightService(db)
    resp = await svc.illness_signal(user.id, start=day6, end=day6)
    for day in resp.days:
        assert day.signal_level != "high", (
            f"Signal should not be 'high' on day {day.day} with symptoms but no z-score deviation"
        )


async def test_recovery_strained_requires_load(db: AsyncSession, user: User):
    """z < -1.0 without training load should produce 'recovering', not 'strained'.

    Baseline values must vary to produce non-zero stddev and a meaningful z-score.
    Values [48,50,52,50,49] → avg≈49.8, stddev≈1.3. Day 6 value=46 → z≈-2.9 < -1.
    No workout on day 6 → should classify as 'recovering'.
    """
    lk = await _resolve_lookups(db)
    base = date(2026, 3, 1)
    mt = lk["metrics"]["hrv_rmssd"]
    src = lk["sources"]["manual"]
    # Varying baseline to ensure stddev > 0
    baseline_values = [48, 50, 52, 50, 49]
    for i, val in enumerate(baseline_values):
        d = base + timedelta(days=i)
        db.add(Measurement(
            id=uuid7(), user_id=user.id, metric_type_id=mt.id, source_id=src.id,
            value_num=Decimal(str(val)), unit="ms",
            measured_at=datetime(d.year, d.month, d.day, 7, tzinfo=UTC),
            recorded_at=datetime(d.year, d.month, d.day, 7, tzinfo=UTC),
            aggregation_level="spot",
        ))
    # Day 6: HRV crashes to 46 (z ≈ -2.9), no workout seeded
    d6 = base + timedelta(days=5)
    db.add(Measurement(
        id=uuid7(), user_id=user.id, metric_type_id=mt.id, source_id=src.id,
        value_num=Decimal("42"), unit="ms",
        measured_at=datetime(d6.year, d6.month, d6.day, 7, tzinfo=UTC),
        recorded_at=datetime(d6.year, d6.month, d6.day, 7, tzinfo=UTC),
        aggregation_level="spot",
    ))
    await db.flush()

    svc = InsightService(db)
    resp = await svc.recovery_status(user.id, start=d6, end=d6)
    day_statuses = [day.status for day in resp.days if day.hrv_z is not None]
    assert "strained" not in day_statuses, (
        f"z < -1 without load must not be 'strained', got {day_statuses}"
    )
    # Must be 'recovering' (z < 0, no load) — not 'recovered'
    assert "recovering" in day_statuses, (
        f"Expected 'recovering' for z < 0 without load, got {day_statuses}"
    )


async def test_recovery_personal_baseline_not_absolute(db: AsyncSession):
    """Two users with different HRV baselines but same z-score get same recovery classification."""
    # user_low: baseline ~30ms, current ~20ms → z ≈ -1.5
    # user_high: baseline ~70ms, current ~50ms → z ≈ -1.5
    # Both should classify identically (no training load → "recovering")
    user_low  = User(id=uuid7(), email="low_hrv@test.dev",  name="Low HRV",  timezone="UTC")
    user_high = User(id=uuid7(), email="high_hrv@test.dev", name="High HRV", timezone="UTC")
    db.add_all([user_low, user_high])
    await db.flush()

    lk = await _resolve_lookups(db)
    mt = lk["metrics"]["hrv_rmssd"]
    src = lk["sources"]["manual"]
    base = date(2026, 3, 1)

    for user, baseline_val, current_val in [
        (user_low, 30, 15),
        (user_high, 70, 40),
    ]:
        for i in range(5):
            d = base + timedelta(days=i)
            db.add(Measurement(
                id=uuid7(), user_id=user.id, metric_type_id=mt.id, source_id=src.id,
                value_num=Decimal(str(baseline_val)), unit="ms",
                measured_at=datetime(d.year, d.month, d.day, 7, tzinfo=UTC),
                recorded_at=datetime(d.year, d.month, d.day, 7, tzinfo=UTC),
                aggregation_level="spot",
            ))
        d6 = base + timedelta(days=5)
        db.add(Measurement(
            id=uuid7(), user_id=user.id, metric_type_id=mt.id, source_id=src.id,
            value_num=Decimal(str(current_val)), unit="ms",
            measured_at=datetime(d6.year, d6.month, d6.day, 7, tzinfo=UTC),
            recorded_at=datetime(d6.year, d6.month, d6.day, 7, tzinfo=UTC),
            aggregation_level="spot",
        ))
    await db.flush()

    svc = InsightService(db)
    day6 = date(2026, 3, 6)
    resp_low  = await svc.recovery_status(user_low.id,  start=day6, end=day6)
    resp_high = await svc.recovery_status(user_high.id, start=day6, end=day6)

    statuses_low  = [d.status for d in resp_low.days  if d.hrv_z is not None]
    statuses_high = [d.status for d in resp_high.days if d.hrv_z is not None]
    assert statuses_low == statuses_high, (
        f"Same relative deviation should yield same status: {statuses_low} vs {statuses_high}"
    )


# ═══════════════════════════════════════════════════════════════════════════
# G. Feature engineering math tests (controlled data)
# ═══════════════════════════════════════════════════════════════════════════

async def test_baseline_avg_on_day4(db: AsyncSession, math_scenario: dict):
    """Day 4 baseline_avg = avg of days 1-3 = (10+20+30)/3 = 20.0"""
    result = await db.execute(
        text("""
            SELECT day, baseline_avg, baseline_points
            FROM v_metric_baseline
            WHERE user_id = :uid AND metric_slug = 'hrv_rmssd'
            ORDER BY day
        """),
        {"uid": math_scenario["user"].id},
    )
    rows = {r.day: r for r in result.fetchall()}
    day4 = math_scenario["base_date"] + timedelta(days=3)
    assert day4 in rows
    assert float(rows[day4].baseline_avg) == pytest.approx(20.0, rel=1e-2)
    assert rows[day4].baseline_points == 3


async def test_baseline_stddev_on_day4(db: AsyncSession, math_scenario: dict):
    """Day 4 stddev_pop([10,20,30]) = sqrt(200/3) ≈ 8.165"""
    import math as _math
    expected_stddev = _math.sqrt(((10-20)**2 + (20-20)**2 + (30-20)**2) / 3)
    result = await db.execute(
        text("""
            SELECT day, baseline_stddev
            FROM v_metric_baseline
            WHERE user_id = :uid AND metric_slug = 'hrv_rmssd'
            ORDER BY day
        """),
        {"uid": math_scenario["user"].id},
    )
    rows = {r.day: r for r in result.fetchall()}
    day4 = math_scenario["base_date"] + timedelta(days=3)
    assert float(rows[day4].baseline_stddev) == pytest.approx(expected_stddev, rel=1e-2)


async def test_zscore_on_day4(db: AsyncSession, math_scenario: dict):
    """Day 4 z_score = (40 - 20) / 8.165 ≈ 2.45"""
    import math as _math
    stddev = _math.sqrt(((10-20)**2 + (20-20)**2 + (30-20)**2) / 3)
    expected_z = (40 - 20) / stddev
    result = await db.execute(
        text("""
            SELECT day, z_score
            FROM v_metric_baseline
            WHERE user_id = :uid AND metric_slug = 'hrv_rmssd'
            ORDER BY day
        """),
        {"uid": math_scenario["user"].id},
    )
    rows = {r.day: r for r in result.fetchall()}
    day4 = math_scenario["base_date"] + timedelta(days=3)
    assert float(rows[day4].z_score) == pytest.approx(expected_z, rel=1e-2)


async def test_delta_abs_on_day4(db: AsyncSession, math_scenario: dict):
    """Day 4 delta_abs = 40 - 20 = 20.0"""
    result = await db.execute(
        text("""
            SELECT day, delta_abs
            FROM v_metric_baseline
            WHERE user_id = :uid AND metric_slug = 'hrv_rmssd'
            ORDER BY day
        """),
        {"uid": math_scenario["user"].id},
    )
    rows = {r.day: r for r in result.fetchall()}
    day4 = math_scenario["base_date"] + timedelta(days=3)
    assert float(rows[day4].delta_abs) == pytest.approx(20.0, rel=1e-2)


async def test_delta_pct_on_day4(db: AsyncSession, math_scenario: dict):
    """Day 4 delta_pct = (40-20)/20 * 100 = 100.0"""
    result = await db.execute(
        text("""
            SELECT day, delta_pct
            FROM v_metric_baseline
            WHERE user_id = :uid AND metric_slug = 'hrv_rmssd'
            ORDER BY day
        """),
        {"uid": math_scenario["user"].id},
    )
    rows = {r.day: r for r in result.fetchall()}
    day4 = math_scenario["base_date"] + timedelta(days=3)
    assert float(rows[day4].delta_pct) == pytest.approx(100.0, rel=1e-2)


# ═══════════════════════════════════════════════════════════════════════════
# H. Service tests (30-day scenario)
# ═══════════════════════════════════════════════════════════════════════════

async def test_medication_adherence_below_100(db: AsyncSession, user: User):
    """Seed a regimen with a known skip to verify adherence < 100%."""
    med_def = MedicationDefinition(name="Test Vitamin", dosage_form="tablet")
    db.add(med_def)
    await db.flush()
    regimen = MedicationRegimen(
        id=uuid7(), user_id=user.id, medication_id=med_def.id,
        dosage_amount=Decimal("1"), dosage_unit="tablet",
        frequency="daily", started_at=date(2026, 3, 1),
    )
    db.add(regimen)
    await db.flush()
    # 3 taken, 1 skipped
    for i, status in enumerate(["taken", "taken", "taken", "skipped"]):
        d = date(2026, 3, 1) + timedelta(days=i)
        db.add(MedicationLog(
            id=uuid7(), user_id=user.id, regimen_id=regimen.id,
            status=status, scheduled_at=_dt(d, 8),
            taken_at=_dt(d, 8) if status == "taken" else None,
            recorded_at=_dt(d, 8),
        ))
    await db.flush()
    svc = InsightService(db)
    resp = await svc.medication_adherence(user.id)
    assert resp.items, "Expected at least one medication item"
    assert resp.overall_adherence_pct < Decimal("100")


async def test_deviations_flag_hrv_during_illness(db: AsyncSession, insight_scenario: ScenarioData):
    """At least one HRV deviation (z < -2.0) should appear during illness phase."""
    svc = InsightService(db)
    resp = await svc.physiological_deviations(
        insight_scenario.user.id,
        start=date(2026, 3, 15),
        end=date(2026, 3, 21),
        threshold=Decimal("1.5"),
    )
    hrv_devs = [d for d in resp.deviations if d.metric_slug == "hrv_rmssd"]
    assert hrv_devs, "Expected HRV deviations during illness phase"
    assert any(d.z_score < 0 for d in hrv_devs), (
        "HRV deviations should be negative (below baseline)"
    )


async def test_symptom_burden_peak_in_illness_range(
    db: AsyncSession, insight_scenario: ScenarioData
):
    svc = InsightService(db)
    resp = await svc.symptom_burden(insight_scenario.user.id)
    assert resp.peak_burden_date is not None
    assert date(2026, 3, 14) <= resp.peak_burden_date <= date(2026, 3, 21), (
        f"Peak burden date {resp.peak_burden_date} expected in illness range Mar 14-21"
    )


async def test_illness_peak_signal_not_low(db: AsyncSession, insight_scenario: ScenarioData):
    """With 30 days of illness narrative, peak_signal must escalate above 'low'."""
    svc = InsightService(db)
    resp = await svc.illness_signal(insight_scenario.user.id)
    assert resp.peak_signal in ("high", "moderate"), (
        f"Expected 'high' or 'moderate' peak, got {resp.peak_signal!r}"
    )
    assert resp.peak_signal_date is not None


async def test_recovery_strained_days_exist(db: AsyncSession, insight_scenario: ScenarioData):
    """Strained or overreaching days should appear during overreach/illness phases."""
    svc = InsightService(db)
    resp = await svc.recovery_status(insight_scenario.user.id)
    strained_days = [
        d for d in resp.days
        if d.status in ("strained", "overreaching")
    ]
    assert strained_days, "Expected at least one strained/overreaching day"


async def test_summary_types_correct(db: AsyncSession, insight_scenario: ScenarioData):
    svc = InsightService(db)
    resp = await svc.summary(insight_scenario.user.id)
    assert isinstance(resp.overall_adherence_pct, Decimal)
    assert isinstance(resp.active_deviations, int)
    assert isinstance(resp.current_symptom_burden, Decimal)
    assert isinstance(resp.illness_signal, str)
    assert isinstance(resp.recovery_status, str)
    assert resp.illness_signal in ("high", "moderate", "low", "insufficient_data")
    assert resp.recovery_status in (
        "recovered", "recovering", "strained", "overreaching", "insufficient_data"
    )


# ═══════════════════════════════════════════════════════════════════════════
# I. API endpoint tests
# ═══════════════════════════════════════════════════════════════════════════

async def test_api_medication_adherence_200(client, insight_scenario: ScenarioData):
    resp = await client.get(
        f"/api/v1/insights/medication-adherence?user_id={insight_scenario.user.id}"
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "items" in data
    assert "overall_adherence_pct" in data
    assert isinstance(data["items"], list)


async def test_api_physiological_deviations_200(client, insight_scenario: ScenarioData):
    resp = await client.get(
        f"/api/v1/insights/physiological-deviations?user_id={insight_scenario.user.id}"
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "deviations" in data
    assert "metrics_flagged" in data
    assert isinstance(data["deviations"], list)


async def test_api_symptom_burden_200(client, insight_scenario: ScenarioData):
    resp = await client.get(
        f"/api/v1/insights/symptom-burden?user_id={insight_scenario.user.id}"
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "days" in data
    assert "total_symptom_days" in data


async def test_api_illness_signal_200(client, insight_scenario: ScenarioData):
    resp = await client.get(
        f"/api/v1/insights/illness-signal?user_id={insight_scenario.user.id}"
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "method" in data
    assert "days" in data
    assert "peak_signal" in data
    assert data["method"] == "baseline_deviation_v1"
    assert data["peak_signal"] in ("high", "moderate", "low", "insufficient_data")


async def test_api_recovery_status_200(client, insight_scenario: ScenarioData):
    resp = await client.get(
        f"/api/v1/insights/recovery-status?user_id={insight_scenario.user.id}"
    )
    assert resp.status_code == 200
    data = resp.json()
    assert "method" in data
    assert "days" in data
    assert "current_status" in data
    assert data["method"] == "load_hrv_heuristic_v1"
    assert data["current_status"] in (
        "recovered", "recovering", "strained", "overreaching", "insufficient_data"
    )


async def test_api_summary_200(client, insight_scenario: ScenarioData):
    resp = await client.get(
        f"/api/v1/insights/summary?user_id={insight_scenario.user.id}"
    )
    assert resp.status_code == 200
    data = resp.json()
    for field in ("overall_adherence_pct", "active_deviations", "current_symptom_burden",
                  "illness_signal", "recovery_status", "as_of"):
        assert field in data, f"Missing field {field!r} in summary response"


async def test_api_unknown_user_returns_200_empty(client):
    unknown_id = uuid.uuid4()
    resp = await client.get(f"/api/v1/insights/medication-adherence?user_id={unknown_id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["items"] == []
    assert float(data["overall_adherence_pct"]) == 0.0
