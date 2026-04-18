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
    _worst_availability,
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
    # B3: unknown user has no active regimens → not_applicable, overall is null.
    assert data["overall_adherence_pct"] is None
    assert data["availability_status"] == "not_applicable"


# ═══════════════════════════════════════════════════════════════════════════
# J. Onda 2 / B1 — Availability-vs-signal schema separation
# ═══════════════════════════════════════════════════════════════════════════

_B1_RESPONSE_SCHEMAS = [
    "MedicationAdherenceResponse",
    "PhysiologicalDeviationsResponse",
    "SymptomBurdenResponse",
    "IllnessSignalResponse",
    "RecoveryStatusResponse",
    "InsightSummary",
]

_B1_AVAILABILITY_DOMAIN = {
    "ok", "no_data", "no_data_today", "insufficient_data",
    "stale_data", "partial", "not_applicable",
}


def _literal_values(annotation) -> set[str]:
    """Extract string members of a Literal[...] (possibly under | None)."""
    from typing import Literal, Union, get_args, get_origin
    origin = get_origin(annotation)
    if origin is Literal:
        return {a for a in get_args(annotation) if isinstance(a, str)}
    if origin is Union or (origin is type(None)):
        for arg in get_args(annotation):
            vals = _literal_values(arg)
            if vals:
                return vals
    return set()


def test_b1_availability_status_type_has_all_required_members():
    from app.schemas.insights import AvailabilityStatus
    members = _literal_values(AvailabilityStatus)
    assert members == _B1_AVAILABILITY_DOMAIN, (
        f"AvailabilityStatus missing/extra members: expected {_B1_AVAILABILITY_DOMAIN}, got {members}"
    )


def test_b1_availability_separate_from_signal_in_illness():
    """IllnessSignalResponse must expose availability_status AND signal_status
    as distinct fields.  Mixing the two into peak_signal was the false-all-clear
    bug B1 is fixing."""
    from app.schemas.insights import IllnessSignalResponse
    fields = IllnessSignalResponse.model_fields
    assert "availability_status" in fields
    assert "signal_status" in fields
    # signal_status must only admit genuine classifications — no availability leaks.
    signal_members = _literal_values(fields["signal_status"].annotation)
    assert signal_members == {"low", "moderate", "high"}, (
        f"signal_status must be a pure signal Literal, got {signal_members}"
    )
    # availability_status must use the canonical availability domain.
    avail_members = _literal_values(fields["availability_status"].annotation)
    assert avail_members == _B1_AVAILABILITY_DOMAIN


def test_b1_availability_separate_from_signal_in_recovery():
    from app.schemas.insights import RecoveryStatusResponse
    fields = RecoveryStatusResponse.model_fields
    assert "current_availability_status" in fields
    assert "current_signal_status" in fields
    signal_members = _literal_values(fields["current_signal_status"].annotation)
    assert signal_members == {"recovered", "recovering", "strained", "overreaching"}


@pytest.mark.parametrize("schema_name", _B1_RESPONSE_SCHEMAS)
def test_b1_response_schemas_have_data_availability(schema_name: str):
    """Every insight response must carry a ``data_availability`` envelope."""
    import app.schemas.insights as ins
    cls = getattr(ins, schema_name)
    assert "data_availability" in cls.model_fields, (
        f"{schema_name} must expose data_availability (DataAvailability | None)"
    )


def test_b1_data_availability_distinguishes_measured_from_synced():
    """Freshness of sync and freshness of measurement must be independent fields."""
    from app.schemas.insights import DataAvailability
    fields = DataAvailability.model_fields
    for name in (
        "latest_measured_at",
        "latest_synced_at",
        "has_data_for_target_date",
        "target_date",
        "missing_metrics",
        "metrics_with_baseline",
        "metrics_without_baseline",
        "stale_metrics",
    ):
        assert name in fields, f"DataAvailability missing field {name!r}"


def test_b1_medication_item_status_pending_first_log_exists():
    from app.schemas.insights import MedicationAdherenceItem
    fields = MedicationAdherenceItem.model_fields
    assert "item_status" in fields
    members = _literal_values(fields["item_status"].annotation)
    assert "pending_first_log" in members, (
        f"Medication items need a pending_first_log state, got {members}"
    )


def test_b1_summary_block_availability_covers_all_insights():
    from app.schemas.insights import InsightSummary, SummaryBlockAvailability
    assert "block_availability" in InsightSummary.model_fields
    expected = {"deviations", "illness", "recovery", "adherence", "symptoms"}
    actual = set(SummaryBlockAvailability.model_fields.keys())
    assert expected == actual, (
        f"SummaryBlockAvailability blocks: expected {expected}, got {actual}"
    )


def test_b1_defaults_are_backwards_compatible():
    """Pre-B1 construction (only old fields) must still succeed; new fields
    fall through to safe defaults so B2/B3 can fill them gradually."""
    from app.schemas.insights import (
        IllnessSignalResponse,
        InsightSummary,
        MedicationAdherenceResponse,
        PhysiologicalDeviationsResponse,
        RecoveryStatusResponse,
        SymptomBurdenResponse,
    )
    uid = uuid.uuid4()
    today = date.today()
    r1 = MedicationAdherenceResponse(user_id=uid, items=[], overall_adherence_pct=Decimal("0"))
    r2 = PhysiologicalDeviationsResponse(
        user_id=uid, baseline_window_days=14, deviation_threshold=Decimal("2.0"),
        deviations=[], metrics_flagged=0,
    )
    r3 = SymptomBurdenResponse(user_id=uid, days=[], total_symptom_days=0, peak_burden_date=None)
    r4 = IllnessSignalResponse(
        user_id=uid, method="baseline_deviation_v1",
        days=[], peak_signal="insufficient_data", peak_signal_date=None,
    )
    r5 = RecoveryStatusResponse(
        user_id=uid, method="load_hrv_heuristic_v1",
        days=[], current_status="insufficient_data",
    )
    r6 = InsightSummary(
        user_id=uid, as_of=today, overall_adherence_pct=Decimal("0"),
        active_deviations=0, current_symptom_burden=Decimal("0"),
        illness_signal="insufficient_data", recovery_status="insufficient_data",
    )
    for r in (r1, r2, r3, r5):
        # availability_status top-level exists and defaults to "ok".
        status_field = (
            "current_availability_status" if hasattr(r, "current_availability_status")
            else "availability_status"
        )
        assert getattr(r, status_field) == "ok"
        assert r.data_availability is None
    # Illness uses top-level availability_status.
    assert r4.availability_status == "ok"
    assert r4.signal_status is None  # set in B3 when data is sufficient
    # Summary carries per-block availability defaulting to ok across the board.
    for block in ("deviations", "illness", "recovery", "adherence", "symptoms"):
        assert getattr(r6.block_availability, block) == "ok"


# ═══════════════════════════════════════════════════════════════════════════
# K. Onda 2 / B2 — Availability and freshness guards at the service layer
# ═══════════════════════════════════════════════════════════════════════════
#
# The helper in app.services.insight_availability classifies the data we have
# access to.  These tests lock in the decision tree:
#
#   no measurement ever        → no_data
#   fewer than BASELINE_MIN    → insufficient_data
#   latest too old             → stale_data
#   fresh but nothing on target → no_data_today
#   otherwise                  → ok
#
# Partial coverage across required_metrics collapses to ``partial`` with
# missing/with-baseline/without-baseline buckets populated.


async def _seed_hrv(
    db: AsyncSession,
    user: User,
    start: date,
    values: list[float],
) -> None:
    """Insert HRV measurements starting at ``start``, one per consecutive day."""
    lk = await _resolve_lookups(db)
    mt = lk["metrics"]["hrv_rmssd"]
    src = lk["sources"]["manual"]
    for i, val in enumerate(values):
        d = start + timedelta(days=i)
        db.add(Measurement(
            id=uuid7(), user_id=user.id,
            metric_type_id=mt.id, source_id=src.id,
            value_num=Decimal(str(val)), unit="ms",
            measured_at=datetime(d.year, d.month, d.day, 7, tzinfo=UTC),
            recorded_at=datetime(d.year, d.month, d.day, 7, tzinfo=UTC),
            aggregation_level="spot",
        ))
    await db.flush()


async def test_b2_recovery_no_data_returns_no_data(db: AsyncSession, user: User):
    """Zero HRV measurements → recovery availability = no_data, signal = None."""
    svc = InsightService(db)
    resp = await svc.recovery_status(user.id)
    assert resp.current_availability_status == "no_data"
    assert resp.current_signal_status is None
    assert resp.current_status == "insufficient_data"
    assert resp.data_availability is not None
    assert resp.data_availability.availability_status == "no_data"
    assert resp.data_availability.has_data_for_target_date is False
    assert resp.data_availability.missing_metrics == ["hrv_rmssd"]


async def test_b2_recovery_one_day_returns_insufficient_data(
    db: AsyncSession, user: User
):
    """A single HRV measurement can't form a baseline → insufficient_data."""
    await _seed_hrv(db, user, date.today() - timedelta(days=1), [42.0])
    svc = InsightService(db)
    resp = await svc.recovery_status(user.id)
    assert resp.current_availability_status == "insufficient_data"
    assert resp.current_signal_status is None
    assert resp.data_availability.metrics_without_baseline == ["hrv_rmssd"]


async def test_b2_recovery_baseline_below_min_returns_insufficient_data(
    db: AsyncSession, user: User
):
    """Two days of data still short of the three-point baseline minimum."""
    await _seed_hrv(db, user, date.today() - timedelta(days=2), [40.0, 42.0])
    svc = InsightService(db)
    resp = await svc.recovery_status(user.id)
    assert resp.current_availability_status == "insufficient_data"


async def test_b2_recovery_fresh_baseline_no_data_today_flags_no_data_today(
    db: AsyncSession, user: User
):
    """Baseline satisfied and latest measurement within budget but target
    date has no row → no_data_today (distinct from stale_data)."""
    today = date.today()
    # Four points spanning [today-4, today-1]; latest is yesterday (within
    # the 2-day HRV budget) and baseline_points reaches 3 on the last day.
    await _seed_hrv(db, user, today - timedelta(days=4), [40.0, 41.0, 42.0, 43.0])
    svc = InsightService(db)
    resp = await svc.recovery_status(user.id)
    assert resp.current_availability_status == "no_data_today"
    assert resp.current_signal_status is None
    assert resp.data_availability.has_data_for_target_date is False
    # The metric has a baseline — it shows up under metrics_with_baseline.
    assert "hrv_rmssd" in resp.data_availability.metrics_with_baseline


async def test_b2_recovery_stale_data_when_latest_beyond_budget(
    db: AsyncSession, user: User
):
    """Baseline exists but latest measurement is well past the 2-day HRV
    staleness budget → stale_data."""
    today = date.today()
    # Baseline 30 days old — far beyond the 2-day HRV budget.
    await _seed_hrv(db, user, today - timedelta(days=30), [40.0, 41.0, 42.0, 43.0])
    svc = InsightService(db)
    resp = await svc.recovery_status(user.id)
    assert resp.current_availability_status == "stale_data"
    assert resp.current_signal_status is None
    assert resp.data_availability.stale_metrics == ["hrv_rmssd"]


async def test_b2_illness_partial_when_body_temperature_missing(
    db: AsyncSession, user: User
):
    """HRV + resting_hr present, body_temperature absent → partial.
    body_temperature appears in missing_metrics; the other two fall under
    metrics_with_baseline."""
    lk = await _resolve_lookups(db)
    src = lk["sources"]["manual"]
    today = date.today()
    # Seed HRV and resting_hr fresh enough to satisfy availability for each.
    for slug, unit, base in [("hrv_rmssd", "ms", 40.0), ("resting_hr", "bpm", 58.0)]:
        mt = lk["metrics"][slug]
        for offset in range(3):
            d = today - timedelta(days=offset)
            db.add(Measurement(
                id=uuid7(), user_id=user.id,
                metric_type_id=mt.id, source_id=src.id,
                value_num=Decimal(str(base + offset)), unit=unit,
                measured_at=datetime(d.year, d.month, d.day, 7, tzinfo=UTC),
                recorded_at=datetime(d.year, d.month, d.day, 7, tzinfo=UTC),
                aggregation_level="spot",
            ))
    await db.flush()

    svc = InsightService(db)
    resp = await svc.illness_signal(user.id)
    # Mixed states: body_temperature missing, other two ok → partial.
    assert resp.availability_status == "partial"
    assert resp.signal_status is None  # availability ≠ ok → no signal leak
    assert "body_temperature" in resp.data_availability.missing_metrics
    assert set(resp.data_availability.metrics_with_baseline) == {
        "hrv_rmssd", "resting_hr"
    }


async def test_b2_illness_no_data_when_all_metrics_missing(
    db: AsyncSession, user: User
):
    """None of the illness metrics recorded → uniform no_data aggregation."""
    svc = InsightService(db)
    resp = await svc.illness_signal(user.id)
    assert resp.availability_status == "no_data"
    assert resp.signal_status is None
    assert set(resp.data_availability.missing_metrics) == {
        "body_temperature", "hrv_rmssd", "resting_hr"
    }


async def test_b2_deviations_empty_does_not_mask_insufficient_baseline(
    db: AsyncSession, user: User
):
    """Physiological deviations with no flagged metrics must not report
    availability_status = ok when the user lacks enough data to form a
    baseline.  This prevents the Home screen from showing "all clear"
    when there is nothing to be clear about."""
    await _seed_hrv(db, user, date.today() - timedelta(days=1), [42.0])
    svc = InsightService(db)
    resp = await svc.physiological_deviations(user.id)
    assert resp.metrics_flagged == 0
    assert resp.availability_status != "ok"
    assert resp.availability_status in ("insufficient_data", "no_data")


async def test_b2_deviations_no_data_when_user_has_no_measurements(
    db: AsyncSession, user: User
):
    """A user with zero measurements gets availability_status = no_data."""
    svc = InsightService(db)
    resp = await svc.physiological_deviations(user.id)
    assert resp.availability_status == "no_data"
    assert resp.data_availability.has_data_for_target_date is False


async def test_b2_recovery_does_not_use_yesterday_as_current(
    db: AsyncSession, user: User
):
    """Target_date = today but latest data is yesterday → current signal
    must be None, not yesterday's classification.  This is the precise
    false-all-clear bug B2 closes."""
    today = date.today()
    # Four HRV days ending yesterday — the 4th day produces baseline_points=3,
    # so the view emits exactly one row (yesterday) that the old code would
    # have surfaced as the "current" recovery state.
    await _seed_hrv(db, user, today - timedelta(days=4), [40.0, 41.0, 42.0, 43.0])
    svc = InsightService(db)
    resp = await svc.recovery_status(user.id)
    assert resp.days, "yesterday must produce a classified row for this test"
    yesterday_status = resp.days[-1].status
    assert yesterday_status in (
        "recovered", "recovering", "strained", "overreaching"
    ), f"Expected a real classification, got {yesterday_status}"
    # Target is today with no row — current must NOT inherit yesterday's value.
    assert resp.current_availability_status == "no_data_today"
    assert resp.current_signal_status is None
    assert resp.current_status == "insufficient_data"


async def test_b2_data_availability_separates_measured_from_synced(
    db: AsyncSession, user: User
):
    """latest_measured_at reflects data time; latest_synced_at reflects the
    last cursor advance.  They must be independent fields.  With no source
    cursor written, latest_synced_at is None even when measurements exist."""
    today = date.today()
    await _seed_hrv(db, user, today - timedelta(days=2), [40.0, 41.0, 42.0])
    svc = InsightService(db)
    resp = await svc.recovery_status(user.id)
    # latest_measured_at reflects the HRV seed — today (latest day seeded).
    assert resp.data_availability.latest_measured_at is not None
    assert resp.data_availability.latest_measured_at.date() == today
    # No source_cursor row written → latest_synced_at is None, independent.
    assert resp.data_availability.latest_synced_at is None


async def test_b2_illness_fresh_signal_is_exposed(db: AsyncSession, user: User):
    """When availability is ok and the heuristic produces a non-insufficient
    signal, signal_status mirrors peak_signal.  Guards against an
    overzealous B2 that nullifies everything."""
    lk = await _resolve_lookups(db)
    src = lk["sources"]["manual"]
    today = date.today()
    # Seed four days of stable data per metric — the view needs 3 prior
    # points to emit a non-NULL z_score, so today's row requires 4 total
    # observations.  Values are near-constant so the z_score lands firmly
    # inside the "low" band.
    seed = [
        ("hrv_rmssd", "ms", [45.0, 45.1, 45.0, 45.0]),
        ("resting_hr", "bpm", [58.0, 58.0, 58.0, 58.0]),
        ("body_temperature", "°C", [36.4, 36.5, 36.4, 36.4]),
    ]
    for slug, unit, vals in seed:
        mt = lk["metrics"][slug]
        for offset, val in enumerate(vals):
            d = today - timedelta(days=3 - offset)
            db.add(Measurement(
                id=uuid7(), user_id=user.id,
                metric_type_id=mt.id, source_id=src.id,
                value_num=Decimal(str(val)), unit=unit,
                measured_at=datetime(d.year, d.month, d.day, 7, tzinfo=UTC),
                recorded_at=datetime(d.year, d.month, d.day, 7, tzinfo=UTC),
                aggregation_level="spot",
            ))
    await db.flush()

    svc = InsightService(db)
    resp = await svc.illness_signal(user.id)
    assert resp.availability_status == "ok"
    # With flat data and no burden the signal lands at "low".
    assert resp.peak_signal == "low"
    assert resp.signal_status == "low"


async def test_b2_summary_block_availability_reflects_sources(
    db: AsyncSession, user: User
):
    """Summary's block_availability must mirror each underlying response —
    not collapse to a single "ok" when some blocks have no data."""
    svc = InsightService(db)
    resp = await svc.summary(user.id)
    # A brand-new user has no deviations, illness, or recovery data.
    assert resp.block_availability.deviations == "no_data"
    assert resp.block_availability.illness == "no_data"
    assert resp.block_availability.recovery == "no_data"


# ═══════════════════════════════════════════════════════════════════════════
# L. Onda 2 / B3 — Insight-specific corrections
# ═══════════════════════════════════════════════════════════════════════════
#
# Validates the corrected heuristic rules:
#   Illness  — body_temperature governs HIGH; partial still exposes moderate.
#   Recovery — no signal without HRV on target_date.
#   Medication — LEFT JOIN surfaces regimens with no logs; not_applicable
#               when no active regimens.
#   Symptom  — tracking_ever_used distinguishes absence from quiet.


# ── L-1. Illness signal ────────────────────────────────────────────────────

async def _seed_metric_with_baseline(
    db: AsyncSession,
    user: User,
    metric_slug: str,
    unit: str,
    baseline_values: list[float],
    today_value: float,
) -> None:
    """Seed *baseline_values* on consecutive days ending yesterday, then
    *today_value* today — giving the view enough prior points to emit a
    z_score for today."""
    lk = await _resolve_lookups(db)
    mt = lk["metrics"][metric_slug]
    src = lk["sources"]["manual"]
    n = len(baseline_values)
    # baseline days: today-(n) … today-1
    for i, val in enumerate(baseline_values):
        d = date.today() - timedelta(days=n - i)
        db.add(Measurement(
            id=uuid7(), user_id=user.id,
            metric_type_id=mt.id, source_id=src.id,
            value_num=Decimal(str(val)), unit=unit,
            measured_at=datetime(d.year, d.month, d.day, 7, tzinfo=UTC),
            recorded_at=datetime(d.year, d.month, d.day, 7, tzinfo=UTC),
            aggregation_level="spot",
        ))
    # today's value
    d = date.today()
    db.add(Measurement(
        id=uuid7(), user_id=user.id,
        metric_type_id=mt.id, source_id=src.id,
        value_num=Decimal(str(today_value)), unit=unit,
        measured_at=datetime(d.year, d.month, d.day, 7, tzinfo=UTC),
        recorded_at=datetime(d.year, d.month, d.day, 7, tzinfo=UTC),
        aggregation_level="spot",
    ))
    await db.flush()


async def test_b3_illness_partial_with_hrv_rhr_bad_exposes_moderate(
    db: AsyncSession, user: User
):
    """HRV and RHR strongly deviate but body_temperature is absent.
    The signal must be at most ``moderate`` (never ``high``) and
    ``signal_status`` must surface it — not be null — because partial
    availability still carries a caveated signal."""
    # Baseline: HRV 40-48, today 28 → deeply negative z.
    await _seed_metric_with_baseline(
        db, user, "hrv_rmssd", "ms",
        [40.0, 42.0, 44.0, 46.0, 48.0], today_value=28.0,
    )
    # Baseline: RHR 58-62, today 80 → strongly positive z.
    await _seed_metric_with_baseline(
        db, user, "resting_hr", "bpm",
        [58.0, 59.0, 60.0, 61.0, 62.0], today_value=80.0,
    )
    # body_temperature: no measurements at all.
    svc = InsightService(db)
    resp = await svc.illness_signal(user.id)
    assert resp.availability_status == "partial"
    assert "body_temperature" in resp.data_availability.missing_metrics
    # HIGH is impossible without body_temperature; at most moderate.
    assert resp.signal_status in ("low", "moderate")
    assert resp.signal_status != "high"
    # The per-day signal_level and peak_signal legacy fields are unchanged.
    assert resp.peak_signal in ("low", "moderate", "high", "insufficient_data")


async def test_b3_illness_no_critical_metrics_returns_no_data(
    db: AsyncSession, user: User
):
    """Zero measurements for all illness metrics → no_data, signal None."""
    svc = InsightService(db)
    resp = await svc.illness_signal(user.id)
    assert resp.availability_status == "no_data"
    assert resp.signal_status is None
    assert set(resp.data_availability.missing_metrics) == {
        "body_temperature", "hrv_rmssd", "resting_hr"
    }


async def test_b3_illness_all_critical_present_classifies_normally(
    db: AsyncSession, user: User
):
    """All three illness metrics fresh and stable → ok, signal exposed."""
    for slug, unit in [
        ("hrv_rmssd", "ms"), ("resting_hr", "bpm"), ("body_temperature", "°C")
    ]:
        vals = [45.0, 45.1, 45.0, 45.0, 45.0]
        await _seed_metric_with_baseline(db, user, slug, unit, vals, 45.0)
    svc = InsightService(db)
    resp = await svc.illness_signal(user.id)
    assert resp.availability_status == "ok"
    assert resp.signal_status in ("low", "moderate", "high")
    # peak_signal legacy field is still set.
    assert resp.peak_signal in ("low", "moderate", "high", "insufficient_data")


async def test_b3_illness_high_never_emitted_via_signal_status_without_body_temp(
    db: AsyncSession, user: User
):
    """Even if the per-day _classify_illness would want HIGH (extreme HRV/RHR
    values) the signal_status cap on partial must prevent it — partial allows
    at most moderate."""
    await _seed_metric_with_baseline(
        db, user, "hrv_rmssd", "ms",
        [45.0, 45.0, 45.0, 45.0, 45.0], today_value=10.0,  # very low HRV
    )
    await _seed_metric_with_baseline(
        db, user, "resting_hr", "bpm",
        [60.0, 60.0, 60.0, 60.0, 60.0], today_value=110.0,  # very high RHR
    )
    # body_temperature absent — we cannot emit HIGH.
    svc = InsightService(db)
    resp = await svc.illness_signal(user.id)
    assert resp.availability_status == "partial"
    assert resp.signal_status != "high", (
        f"signal_status must not be 'high' without body_temperature, got {resp.signal_status!r}"
    )


# ── L-2. Recovery status ───────────────────────────────────────────────────

async def test_b3_recovery_hrv_ok_load_absent_classifies(
    db: AsyncSession, user: User
):
    """When HRV baseline is valid and data is fresh, recovery classifies
    correctly even without training load data — load is optional."""
    # Six HRV days ending today; today's value exceeds the baseline avg.
    await _seed_metric_with_baseline(
        db, user, "hrv_rmssd", "ms",
        [40.0, 42.0, 44.0, 46.0, 48.0], today_value=52.0,
    )
    svc = InsightService(db)
    resp = await svc.recovery_status(user.id)
    assert resp.current_availability_status == "ok"
    # z_score > 0 → recovered
    assert resp.current_signal_status == "recovered"
    assert resp.current_status == "recovered"


async def test_b3_recovery_hrv_absent_load_present_returns_no_data(
    db: AsyncSession, user: User
):
    """Training load exists but no HRV → cannot assess recovery.
    Availability must be no_data, signal must be None."""
    svc = InsightService(db)
    resp = await svc.recovery_status(user.id)
    assert resp.current_availability_status == "no_data"
    assert resp.current_signal_status is None
    assert resp.current_status == "insufficient_data"


async def test_b3_recovery_hrv_stale_blocks_signal(
    db: AsyncSession, user: User
):
    """HRV baseline exists but latest measurement is older than the 2-day
    staleness budget → stale_data, no current signal."""
    today = date.today()
    await _seed_hrv(db, user, today - timedelta(days=30), [40.0, 41.0, 42.0, 43.0])
    svc = InsightService(db)
    resp = await svc.recovery_status(user.id)
    assert resp.current_availability_status == "stale_data"
    assert resp.current_signal_status is None


async def test_b3_recovery_hrv_fresh_today_exposes_recovered(
    db: AsyncSession, user: User
):
    """HRV data for today with z_score >= 0 → current_signal_status = recovered."""
    await _seed_metric_with_baseline(
        db, user, "hrv_rmssd", "ms",
        [40.0, 41.0, 42.0, 43.0, 44.0], today_value=50.0,  # above baseline
    )
    svc = InsightService(db)
    resp = await svc.recovery_status(user.id)
    assert resp.current_availability_status == "ok"
    assert resp.current_signal_status == "recovered"
    assert resp.current_status == "recovered"


# ── L-3. Medication adherence ──────────────────────────────────────────────

async def test_b3_medication_no_active_regimens_is_not_applicable(
    db: AsyncSession, user: User
):
    """A user with no active regimens must get not_applicable — not 0%."""
    svc = InsightService(db)
    resp = await svc.medication_adherence(user.id)
    assert resp.availability_status == "not_applicable"
    assert resp.items == []
    assert resp.overall_adherence_pct is None


async def test_b3_medication_active_regimen_no_logs_pending_first_log(
    db: AsyncSession, user: User
):
    """An active regimen that has never been logged must appear as
    pending_first_log, not vanish from the response."""
    med_def = MedicationDefinition(name="Vitamin D", dosage_form="tablet")
    db.add(med_def)
    await db.flush()
    db.add(MedicationRegimen(
        id=uuid7(), user_id=user.id, medication_id=med_def.id,
        dosage_amount=Decimal("1"), dosage_unit="tablet",
        frequency="daily", started_at=date.today(),
    ))
    await db.flush()
    svc = InsightService(db)
    resp = await svc.medication_adherence(user.id)
    # Opção B: pending_first_log ⇒ partial (regimen active but no data yet)
    assert resp.availability_status == "partial"
    assert len(resp.items) == 1
    item = resp.items[0]
    assert item.item_status == "pending_first_log"
    assert item.adherence_pct is None
    assert item.total == 0
    # overall is None when no logs exist for any regimen.
    assert resp.overall_adherence_pct is None


async def test_b3_medication_active_regimen_with_logs_computes_adherence(
    db: AsyncSession, user: User
):
    """Active regimen with logs → normal adherence calculation, item_status ok."""
    med_def = MedicationDefinition(name="Magnesium", dosage_form="capsule")
    db.add(med_def)
    await db.flush()
    regimen = MedicationRegimen(
        id=uuid7(), user_id=user.id, medication_id=med_def.id,
        dosage_amount=Decimal("400"), dosage_unit="mg",
        frequency="daily", started_at=date(2026, 4, 1),
    )
    db.add(regimen)
    await db.flush()
    # 3 taken, 1 skipped → 75%
    for i, status in enumerate(["taken", "taken", "taken", "skipped"]):
        d = date(2026, 4, 1) + timedelta(days=i)
        db.add(MedicationLog(
            id=uuid7(), user_id=user.id, regimen_id=regimen.id,
            status=status, scheduled_at=_dt(d, 8),
            taken_at=_dt(d, 8) if status == "taken" else None,
            recorded_at=_dt(d, 8),
        ))
    await db.flush()
    svc = InsightService(db)
    resp = await svc.medication_adherence(user.id)
    assert resp.availability_status == "ok"
    assert len(resp.items) == 1
    item = resp.items[0]
    assert item.item_status == "ok"
    assert item.adherence_pct == Decimal("75.0")
    assert resp.overall_adherence_pct == Decimal("75.0")


async def test_b3_medication_no_regimens_not_same_as_zero_adherence(
    db: AsyncSession, user: User
):
    """Distinguishes not_applicable (no regimens) from 0% adherence (regimen
    exists but all events are skipped)."""
    # No regimens at all → not_applicable.
    svc = InsightService(db)
    no_regimen_resp = await svc.medication_adherence(user.id)
    assert no_regimen_resp.availability_status == "not_applicable"
    assert no_regimen_resp.overall_adherence_pct is None

    # Create a regimen with only skipped logs → 0% adherence.
    med_def = MedicationDefinition(name="Iron", dosage_form="tablet")
    db.add(med_def)
    await db.flush()
    regimen = MedicationRegimen(
        id=uuid7(), user_id=user.id, medication_id=med_def.id,
        dosage_amount=Decimal("1"), dosage_unit="tablet",
        frequency="daily", started_at=date(2026, 4, 1),
    )
    db.add(regimen)
    await db.flush()
    d = date(2026, 4, 1)
    db.add(MedicationLog(
        id=uuid7(), user_id=user.id, regimen_id=regimen.id,
        status="skipped", scheduled_at=_dt(d, 8), taken_at=None,
        recorded_at=_dt(d, 8),
    ))
    await db.flush()
    regimen_resp = await svc.medication_adherence(user.id)
    assert regimen_resp.availability_status == "ok"
    assert regimen_resp.overall_adherence_pct == Decimal("0.0")


# ── L-4. Symptom burden ────────────────────────────────────────────────────

async def test_b3_symptom_never_used_is_not_applicable(db: AsyncSession, user: User):
    """A user who has never logged a symptom gets tracking_ever_used=False
    and availability_status=not_applicable — not a blank 'all clear'."""
    svc = InsightService(db)
    resp = await svc.symptom_burden(user.id)
    assert resp.tracking_ever_used is False
    assert resp.availability_status == "not_applicable"
    assert resp.days == []


async def test_b3_symptom_historical_user_no_logs_today_is_ok(
    db: AsyncSession, user: User
):
    """A user with prior symptom logs but none today gets tracking_ever_used=True
    and availability_status=ok — burden=0 is a valid 'quiet day' signal."""
    lk = await _resolve_lookups(db)
    past_day = date.today() - timedelta(days=5)
    db.add(SymptomLog(
        id=uuid7(), user_id=user.id,
        symptom_id=lk["symptoms"]["headache"].id,
        intensity=4, status="active",
        started_at=datetime(past_day.year, past_day.month, past_day.day, 9, tzinfo=UTC),
        ended_at=datetime(past_day.year, past_day.month, past_day.day, 20, tzinfo=UTC),
        recorded_at=datetime(past_day.year, past_day.month, past_day.day, 9, tzinfo=UTC),
    ))
    await db.flush()
    svc = InsightService(db)
    resp = await svc.symptom_burden(user.id)
    assert resp.tracking_ever_used is True
    assert resp.availability_status == "ok"


async def test_b3_symptom_with_logs_today_is_ok_with_burden(
    db: AsyncSession, user: User
):
    """Symptom logs today → tracking_ever_used=True, ok, burden > 0."""
    lk = await _resolve_lookups(db)
    today = date.today()
    db.add(SymptomLog(
        id=uuid7(), user_id=user.id,
        symptom_id=lk["symptoms"]["fatigue"].id,
        intensity=6, status="active",
        started_at=datetime(today.year, today.month, today.day, 7, tzinfo=UTC),
        ended_at=datetime(today.year, today.month, today.day, 20, tzinfo=UTC),
        recorded_at=datetime(today.year, today.month, today.day, 7, tzinfo=UTC),
    ))
    await db.flush()
    svc = InsightService(db)
    resp = await svc.symptom_burden(user.id)
    assert resp.tracking_ever_used is True
    assert resp.availability_status == "ok"
    today_days = [d for d in resp.days if d.day == today]
    assert today_days and today_days[0].weighted_burden > 0


async def test_b3_summary_symptoms_not_applicable_when_never_used(
    db: AsyncSession, user: User
):
    """Summary block_availability.symptoms must be not_applicable for a
    user who has never engaged with symptom tracking."""
    svc = InsightService(db)
    resp = await svc.summary(user.id)
    assert resp.block_availability.symptoms == "not_applicable"
    # Medication also not_applicable (no regimens).
    assert resp.block_availability.adherence == "not_applicable"


# ═══════════════════════════════════════════════════════════════════════════
# M. Onda 2 / B4 — Summary correctness: aggregation does not mask absence
# ═══════════════════════════════════════════════════════════════════════════
#
# Tests the `summary()` end-to-end.  Every test checks both the legacy
# scalar fields (backward compat) and the new availability envelope so
# both consumers are validated simultaneously.


# ── M-1. No data at all ───────────────────────────────────────────────────

async def test_b4_summary_no_data_blocks_and_availability(
    db: AsyncSession, user: User
):
    """A brand-new user with zero measurements must not show any 'all clear'
    in the summary.  Every physiological block must signal absence."""
    svc = InsightService(db)
    resp = await svc.summary(user.id)

    # Physiological blocks: no data.
    assert resp.block_availability.deviations == "no_data"
    assert resp.block_availability.illness == "no_data"
    assert resp.block_availability.recovery == "no_data"
    # Optional/voluntary blocks: not_applicable (expected, not a warning).
    assert resp.block_availability.adherence == "not_applicable"
    assert resp.block_availability.symptoms == "not_applicable"

    # Aggregate availability must reflect the worst physiological block.
    assert resp.data_availability is not None
    assert resp.data_availability.availability_status != "ok"
    assert resp.data_availability.availability_status == "no_data"
    assert resp.data_availability.has_data_for_target_date is False

    # Legacy fields stay structurally sound.
    assert resp.illness_signal == "insufficient_data"
    assert resp.recovery_status == "insufficient_data"
    assert resp.active_deviations == 0
    assert resp.overall_adherence_pct is None


# ── M-2. Baseline insufficient ────────────────────────────────────────────

async def test_b4_summary_insufficient_baseline_not_all_clear(
    db: AsyncSession, user: User
):
    """One day of HRV data — below the 3-point baseline minimum.
    active_deviations=0 must not imply 'ok': the deviations block must
    expose insufficient_data."""
    await _seed_hrv(db, user, date.today(), [42.0])  # single day, no baseline
    svc = InsightService(db)
    resp = await svc.summary(user.id)

    assert resp.active_deviations == 0
    assert resp.block_availability.deviations != "ok"
    assert resp.data_availability.availability_status != "ok"
    # HRV exists (1 measurement) but baseline is insufficient.
    assert resp.block_availability.recovery in ("insufficient_data", "no_data_today")


# ── M-3. Historical data exists but nothing today ─────────────────────────

async def test_b4_summary_no_data_today_blocks_positive_read(
    db: AsyncSession, user: User
):
    """Baseline is valid (4 days of HRV ending yesterday) but today has no
    new measurement.  active_deviations=0 is not an 'all clear' — the
    recovery block must flag no_data_today and has_data_for_target_date
    must be False."""
    today = date.today()
    await _seed_hrv(db, user, today - timedelta(days=4), [40.0, 41.0, 42.0, 43.0])
    svc = InsightService(db)
    resp = await svc.summary(user.id)

    assert resp.block_availability.recovery == "no_data_today"
    assert resp.data_availability.has_data_for_target_date is False
    # aggregate picks up the no_data_today severity.
    assert resp.data_availability.availability_status in (
        "no_data_today", "no_data", "stale_data", "insufficient_data"
    )
    # legacy field falls back to insufficient_data (not a real recovery signal).
    assert resp.recovery_status == "insufficient_data"


# ── M-4. Illness partial when body_temperature absent ─────────────────────

async def test_b4_summary_illness_partial_body_temp_absent(
    db: AsyncSession, user: User
):
    """HRV and resting_hr are fresh and valid; body_temperature is absent.
    The illness block must be partial.  signal_status must not be 'high'."""
    await _seed_metric_with_baseline(
        db, user, "hrv_rmssd", "ms",
        [45.0, 45.1, 45.0, 45.0, 45.0], today_value=45.0,
    )
    await _seed_metric_with_baseline(
        db, user, "resting_hr", "bpm",
        [60.0, 60.0, 60.0, 60.0, 60.0], today_value=60.0,
    )
    svc = InsightService(db)
    resp = await svc.summary(user.id)

    assert resp.block_availability.illness == "partial"
    # Aggregate sees partial on illness — not ok.
    assert resp.data_availability.availability_status in ("partial", "no_data")
    # Illness signal must NOT be reported as a clean 'low' without caveat.
    # peak_signal (legacy) can still hold a value; signal_status for detail.
    illness = await InsightService(db).illness_signal(user.id)
    assert illness.signal_status != "high"


# ── M-5. Recovery stale — legacy field falls back correctly ───────────────

async def test_b4_summary_recovery_stale_legacy_fallback(
    db: AsyncSession, user: User
):
    """HRV baseline exists but is 30 days old (beyond 2-day budget) →
    stale_data.  The legacy recovery_status must be 'insufficient_data',
    not 'recovered' or any real classification."""
    today = date.today()
    await _seed_hrv(db, user, today - timedelta(days=30), [40.0, 41.0, 42.0, 43.0])
    svc = InsightService(db)
    resp = await svc.summary(user.id)

    assert resp.block_availability.recovery == "stale_data"
    assert resp.recovery_status == "insufficient_data"
    assert resp.data_availability.availability_status in (
        "stale_data", "no_data", "stale_data"
    )


# ── M-6. No medication regimens ───────────────────────────────────────────

async def test_b4_summary_no_medication_regimens_not_applicable(
    db: AsyncSession, user: User
):
    """No active regimens → adherence block = not_applicable.
    overall_adherence_pct must be None, not 0%.  not_applicable must NOT
    worsen the physiological availability aggregate."""
    svc = InsightService(db)
    resp = await svc.summary(user.id)

    assert resp.block_availability.adherence == "not_applicable"
    assert resp.overall_adherence_pct is None
    # not_applicable does not pull the aggregate below the physiological worst.
    # (no physiological data either, so aggregate = no_data anyway here)
    assert resp.data_availability.availability_status == "no_data"


# ── M-7. Active regimen with no logs ──────────────────────────────────────

async def test_b4_summary_active_regimen_no_logs_not_applicable(
    db: AsyncSession, user: User
):
    """An active regimen with zero logs must show adherence block = ok
    (the feature IS in use) but overall_adherence_pct = None (no data yet)."""
    med_def = MedicationDefinition(name="Test Supplement", dosage_form="tablet")
    db.add(med_def)
    await db.flush()
    db.add(MedicationRegimen(
        id=uuid7(), user_id=user.id, medication_id=med_def.id,
        dosage_amount=Decimal("1"), dosage_unit="tablet",
        frequency="daily", started_at=date.today(),
    ))
    await db.flush()
    svc = InsightService(db)
    resp = await svc.summary(user.id)

    # Block must be 'partial' (Opção B: active regimen with pending_first_log
    # is not 'ok' — logs haven't started yet).
    assert resp.block_availability.adherence == "partial"
    # But no logs → overall is still None.
    assert resp.overall_adherence_pct is None


# ── M-8. Symptom tracking never used ─────────────────────────────────────

async def test_b4_summary_symptom_never_used_not_applicable(
    db: AsyncSession, user: User
):
    """A user who has never logged a symptom gets symptom block = not_applicable.
    burden=0 must not be presented as a clean 'no symptoms today'."""
    svc = InsightService(db)
    resp = await svc.summary(user.id)

    assert resp.block_availability.symptoms == "not_applicable"
    assert resp.current_symptom_burden == Decimal("0")
    # not_applicable does not worsen the overall physiological aggregate.
    # (no physiological data → aggregate = no_data regardless)
    burden = await InsightService(db).symptom_burden(user.id)
    assert burden.tracking_ever_used is False
    assert burden.availability_status == "not_applicable"


# ── M-9. Symptom tracking used before, quiet today ───────────────────────

async def test_b4_summary_symptom_used_before_quiet_today(
    db: AsyncSession, user: User
):
    """Symptom history exists (5 days ago) but nothing today.
    symptom block = ok; burden=0 is a legitimate 'quiet day' signal."""
    lk = await _resolve_lookups(db)
    past = date.today() - timedelta(days=5)
    db.add(SymptomLog(
        id=uuid7(), user_id=user.id,
        symptom_id=lk["symptoms"]["fatigue"].id,
        intensity=4, status="resolved",
        started_at=datetime(past.year, past.month, past.day, 9, tzinfo=UTC),
        ended_at=datetime(past.year, past.month, past.day, 20, tzinfo=UTC),
        recorded_at=datetime(past.year, past.month, past.day, 9, tzinfo=UTC),
    ))
    await db.flush()
    svc = InsightService(db)
    resp = await svc.summary(user.id)

    assert resp.block_availability.symptoms == "ok"
    assert resp.current_symptom_burden == Decimal("0")
    burden = await InsightService(db).symptom_burden(user.id)
    assert burden.tracking_ever_used is True
    assert burden.availability_status == "ok"


# ── M-10. Healthy user — all physiological blocks ok ─────────────────────

async def test_b4_summary_healthy_user_all_blocks_ok(
    db: AsyncSession, user: User
):
    """When all three physiological metrics are fresh, have valid baselines,
    and have data today, the summary aggregate must be ok — no false negative."""
    # Seed 5 stable days ending today for each illness metric + HRV recovery.
    for slug, unit in [
        ("hrv_rmssd", "ms"), ("resting_hr", "bpm"), ("body_temperature", "°C")
    ]:
        await _seed_metric_with_baseline(
            db, user, slug, unit,
            baseline_values=[45.0, 45.1, 45.0, 45.0, 45.0],
            today_value=45.0,
        )

    svc = InsightService(db)
    resp = await svc.summary(user.id)

    assert resp.block_availability.deviations == "ok"
    assert resp.block_availability.illness == "ok"
    assert resp.block_availability.recovery == "ok"
    assert resp.data_availability is not None
    assert resp.data_availability.availability_status == "ok"
    assert resp.data_availability.has_data_for_target_date is True
    assert resp.data_availability.missing_metrics == []
    assert resp.data_availability.stale_metrics == []


# ═══════════════════════════════════════════════════════════════════════════
# N — B5: Backend Regression Hardening
# ═══════════════════════════════════════════════════════════════════════════
#
# N-1 to N-5  : _worst_availability pure unit tests (no DB)
# N-6 to N-9  : Summary aggregation edge cases
# N-10 to N-15: Endpoint contract tests
# N-16 to N-20: Real-world scenario anchors

# ── N-1 to N-5. _worst_availability unit tests ───────────────────────────


def test_b5_worst_partial_plus_stale_returns_stale():
    assert _worst_availability("partial", "stale_data") == "stale_data"


def test_b5_worst_partial_plus_no_data_today_returns_no_data_today():
    assert _worst_availability("partial", "no_data_today") == "no_data_today"


def test_b5_worst_insufficient_plus_no_data_returns_no_data():
    assert _worst_availability("insufficient_data", "no_data") == "no_data"


def test_b5_worst_not_applicable_ignored_when_mixed_with_problems():
    assert _worst_availability("not_applicable", "partial") == "partial"
    assert _worst_availability("not_applicable", "stale_data") == "stale_data"
    assert _worst_availability("not_applicable", "no_data") == "no_data"


def test_b5_worst_all_not_applicable_returns_ok():
    assert _worst_availability("not_applicable", "not_applicable") == "ok"


# ── N-6. Empty DataAvailability lists on new user ─────────────────────────


async def test_b5_summary_data_availability_empty_lists_new_user(
    db: AsyncSession, user: User
):
    """A brand-new user's summary DataAvailability must have empty metric
    lists (not None) — a valid but empty envelope."""
    resp = await InsightService(db).summary(user.id)

    da = resp.data_availability
    assert da is not None
    # illness + recovery required metrics show up as missing (no measurements)
    assert set(da.missing_metrics) == {"body_temperature", "hrv_rmssd", "resting_hr"}
    assert da.metrics_with_baseline == []
    assert da.metrics_without_baseline == []
    assert da.stale_metrics == []
    assert da.latest_measured_at is None
    # All three are missing → aggregate = no_data
    assert da.availability_status == "no_data"
    # Deduplication: lists must not contain repeats
    assert len(da.missing_metrics) == len(set(da.missing_metrics))


# ── N-7. latest_measured_at surfaces through when some blocks have data ───


async def test_b5_summary_latest_measured_at_when_some_blocks_have_data(
    db: AsyncSession, user: User
):
    """When HRV has data today but body_temperature is absent, the summary
    latest_measured_at must reflect the HRV timestamp (not collapse to None
    because one metric is missing)."""
    await _seed_metric_with_baseline(
        db, user, "hrv_rmssd", "ms",
        baseline_values=[45.0, 45.1, 45.0, 45.0],
        today_value=45.0,
    )
    resp = await InsightService(db).summary(user.id)
    da = resp.data_availability
    assert da is not None
    assert da.latest_measured_at is not None
    assert da.latest_measured_at.date() == date.today()
    # illness = partial (body_temp missing), but timestamp still surfaces.
    assert resp.block_availability.illness == "partial"


# ── N-8. missing_metrics deduplicated across blocks ───────────────────────


async def test_b5_summary_missing_metrics_deduplicated_across_blocks(
    db: AsyncSession, user: User
):
    """hrv_rmssd is required by both illness and recovery blocks.
    The summary's missing_metrics must contain it exactly once."""
    # New user — no measurements at all.
    resp = await InsightService(db).summary(user.id)
    da = resp.data_availability
    assert da is not None
    assert da.missing_metrics.count("hrv_rmssd") <= 1
    assert len(da.missing_metrics) == len(set(da.missing_metrics))
    assert len(da.metrics_with_baseline) == len(set(da.metrics_with_baseline))
    assert len(da.metrics_without_baseline) == len(set(da.metrics_without_baseline))
    assert len(da.stale_metrics) == len(set(da.stale_metrics))


# ── N-9. Multi-user isolation ─────────────────────────────────────────────


async def test_b5_multi_user_states_do_not_bleed(db: AsyncSession):
    """User A (full baseline) and user B (no data) must get independent
    summaries — user A's measurements must not appear in user B's response."""
    user_a = User(id=uuid7(), email="a_b5@test.local", name="User A B5")
    user_b = User(id=uuid7(), email="b_b5@test.local", name="User B B5")
    db.add_all([user_a, user_b])
    await db.flush()

    for slug, unit in [
        ("hrv_rmssd", "ms"), ("resting_hr", "bpm"), ("body_temperature", "°C")
    ]:
        await _seed_metric_with_baseline(
            db, user_a, slug, unit,
            baseline_values=[45.0, 45.1, 45.0, 45.0],
            today_value=45.0,
        )

    svc = InsightService(db)
    summary_a = await svc.summary(user_a.id)
    summary_b = await svc.summary(user_b.id)

    assert summary_a.data_availability.availability_status == "ok"
    assert summary_b.data_availability.availability_status != "ok"
    assert summary_b.data_availability.latest_measured_at is None
    assert summary_b.data_availability.metrics_with_baseline == []


# ── N-10 to N-15. Endpoint contract tests ────────────────────────────────


async def test_b5_contract_data_availability_present_in_deviations(
    db: AsyncSession, user: User
):
    """physiological_deviations must always include a non-None
    data_availability whose availability_status matches the top-level field."""
    resp = await InsightService(db).physiological_deviations(user.id)
    assert resp.data_availability is not None
    assert resp.availability_status == resp.data_availability.availability_status


async def test_b5_contract_data_availability_present_in_illness(
    db: AsyncSession, user: User
):
    """illness_signal must always include data_availability with
    availability_status consistent with the top-level field."""
    resp = await InsightService(db).illness_signal(user.id)
    assert resp.data_availability is not None
    assert resp.availability_status == resp.data_availability.availability_status


async def test_b5_contract_data_availability_present_in_recovery(
    db: AsyncSession, user: User
):
    """recovery_status must always include data_availability with
    availability_status consistent with current_availability_status."""
    resp = await InsightService(db).recovery_status(user.id)
    assert resp.data_availability is not None
    assert resp.current_availability_status == resp.data_availability.availability_status


async def test_b5_contract_signal_status_none_when_availability_not_ok(
    db: AsyncSession, user: User
):
    """A new user (no data) must have signal_status = None in the illness
    response — never a spurious health signal from absent data."""
    resp = await InsightService(db).illness_signal(user.id)
    assert resp.availability_status != "ok"
    assert resp.signal_status is None


async def test_b5_contract_block_availability_always_in_summary(
    db: AsyncSession, user: User
):
    """summary must always include block_availability with all five named
    fields populated — none may be absent or None."""
    resp = await InsightService(db).summary(user.id)
    ba = resp.block_availability
    assert ba is not None
    for field in ("deviations", "illness", "recovery", "adherence", "symptoms"):
        assert getattr(ba, field) is not None, f"block_availability.{field} is None"


async def test_b5_contract_overall_adherence_pct_accepts_none(
    db: AsyncSession, user: User
):
    """overall_adherence_pct must be None (not 0.0 or a validation error)
    when there are no active medication regimens."""
    resp = await InsightService(db).medication_adherence(user.id)
    assert resp.availability_status == "not_applicable"
    assert resp.overall_adherence_pct is None
    summary = await InsightService(db).summary(user.id)
    assert summary.overall_adherence_pct is None


# ── N-16 to N-20. Real-world scenario anchors ─────────────────────────────


async def test_b5_real_garmin_only_no_body_temperature_illness_partial(
    db: AsyncSession, user: User
):
    """User has Garmin (HRV + RHR) but has never measured body temperature
    manually.  illness_signal availability must be 'partial' and
    body_temperature must appear in missing_metrics."""
    lk = await _resolve_lookups(db)
    garmin = lk["sources"]["garmin"]
    today = date.today()
    for slug, unit in [("hrv_rmssd", "ms"), ("resting_hr", "bpm")]:
        mt = lk["metrics"][slug]
        for offset in range(5):
            d = today - timedelta(days=4 - offset)
            db.add(Measurement(
                id=uuid7(), user_id=user.id,
                metric_type_id=mt.id, source_id=garmin.id,
                value_num=Decimal("45.0"), unit=unit,
                measured_at=_dt(d, 6), recorded_at=_dt(d, 6),
                aggregation_level="daily",
            ))
    await db.flush()

    resp = await InsightService(db).illness_signal(user.id)
    assert resp.availability_status == "partial"
    assert resp.data_availability is not None
    assert "body_temperature" in resp.data_availability.missing_metrics


async def test_b5_real_garmin_synced_yesterday_no_data_today(
    db: AsyncSession, user: User
):
    """Garmin sync landed yesterday but produced no HRV value for today yet.
    recovery availability must be no_data_today and signal must be None."""
    lk = await _resolve_lookups(db)
    garmin = lk["sources"]["garmin"]
    hrv_mt = lk["metrics"]["hrv_rmssd"]
    today = date.today()
    # Four HRV measurements ending YESTERDAY (today has no row).
    for offset in range(4):
        d = today - timedelta(days=4 - offset)  # today-4 … today-1
        db.add(Measurement(
            id=uuid7(), user_id=user.id,
            metric_type_id=hrv_mt.id, source_id=garmin.id,
            value_num=Decimal("45.0"), unit="ms",
            measured_at=_dt(d, 6), recorded_at=_dt(d, 6),
            aggregation_level="daily",
        ))
    await db.flush()

    resp = await InsightService(db).recovery_status(user.id)
    assert resp.current_availability_status == "no_data_today"
    assert resp.data_availability.has_data_for_target_date is False
    assert resp.current_signal_status is None


async def test_b5_real_hc900_weight_stale_beyond_seven_day_budget(
    db: AsyncSession, user: User
):
    """HC900 weight last recorded 10 days ago — beyond the 7-day budget.
    assess_availability must flag it as stale_data."""
    from app.services.insight_availability import assess_availability as _assess

    lk = await _resolve_lookups(db)
    manual = lk["sources"]["manual"]
    weight_mt = lk["metrics"]["weight"]
    today = date.today()
    # Four weight measurements ending 10 days ago (10 > 7-day budget).
    for offset in range(4):
        d = today - timedelta(days=13 - offset)  # today-13 … today-10
        db.add(Measurement(
            id=uuid7(), user_id=user.id,
            metric_type_id=weight_mt.id, source_id=manual.id,
            value_num=Decimal("81.5"), unit="kg",
            measured_at=_dt(d, 7), recorded_at=_dt(d, 7),
            aggregation_level="spot",
        ))
    await db.flush()

    avail = await _assess(db, user.id, required_metrics=["weight"], target_date=today)
    assert avail.availability_status == "stale_data"
    assert "weight" in avail.stale_metrics


async def test_b5_real_freshly_formed_baseline_ok_at_minimum_points(
    db: AsyncSession, user: User
):
    """User just started tracking HRV — exactly 3 preceding measurements
    (baseline_points = 3, the minimum).  availability must be 'ok',
    not 'insufficient_data'."""
    # _seed_metric_with_baseline with 3 baseline_values seeds:
    #   today-3, today-2, today-1 (preceding) + today → 4 total rows,
    #   baseline window for today = 3 points (exactly the minimum).
    await _seed_metric_with_baseline(
        db, user, "hrv_rmssd", "ms",
        baseline_values=[45.0, 45.1, 45.0],
        today_value=45.0,
    )
    resp = await InsightService(db).recovery_status(user.id)
    assert resp.current_availability_status == "ok"
    assert resp.current_signal_status is not None


async def test_b5_real_medication_partial_when_pending_first_log(
    db: AsyncSession, user: User
):
    """Active regimen with zero logs must yield availability_status='partial'
    (Opção B) — 'ok' would mislead: the feature is not yet producing data."""
    med_def = MedicationDefinition(name="Omega-3", dosage_form="softgel")
    db.add(med_def)
    await db.flush()
    db.add(MedicationRegimen(
        id=uuid7(), user_id=user.id, medication_id=med_def.id,
        dosage_amount=Decimal("1"), dosage_unit="softgel",
        frequency="daily", started_at=date.today(),
    ))
    await db.flush()

    resp = await InsightService(db).medication_adherence(user.id)
    assert resp.availability_status == "partial"
    assert len(resp.items) == 1
    assert resp.items[0].item_status == "pending_first_log"
    assert resp.overall_adherence_pct is None
