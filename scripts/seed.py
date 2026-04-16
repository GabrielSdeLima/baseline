"""Seed: 30-day realistic health scenario.

Creates a complete user timeline (March 1-30, 2026) with physiological
correlations across every domain.  Designed to feed the analytical queries
in ``scripts/analytics.sql``.

Phases
------
  baseline  (days 0-6)   — good health, consistent training
  overreach (days 7-13)  — increased volume, early fatigue signals
  illness   (days 14-20) — mild viral illness, reduced training
  recovery  (days 21-29) — gradual return to normal

Run: python scripts/seed.py
Requires: PostgreSQL running, migration applied.
"""
import asyncio
import random
import sys
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

# Allow direct execution (python scripts/seed.py)
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import (  # noqa: E402
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.core.config import settings  # noqa: E402
from app.models.base import uuid7  # noqa: E402
from app.models.daily_checkpoint import DailyCheckpoint  # noqa: E402
from app.models.data_source import DataSource  # noqa: E402
from app.models.exercise import Exercise  # noqa: E402
from app.models.measurement import Measurement  # noqa: E402
from app.models.medication import (  # noqa: E402
    MedicationDefinition,
    MedicationLog,
    MedicationRegimen,
)
from app.models.metric_type import MetricType  # noqa: E402
from app.models.raw_payload import RawPayload  # noqa: E402
from app.models.symptom import Symptom, SymptomLog  # noqa: E402
from app.models.user import User  # noqa: E402
from app.models.workout import WorkoutSession, WorkoutSet  # noqa: E402

random.seed(42)
BRT = timezone(timedelta(hours=-3))
START_DATE = date(2026, 3, 1)


# ── Helpers ────────────────────────────────────────────────────────────────


def phase(day: int) -> str:
    if day < 7:
        return "baseline"
    if day < 14:
        return "overreach"
    if day < 21:
        return "illness"
    return "recovery"


def dt(d: date, hour: int = 7, minute: int = 0) -> datetime:
    """Build a timezone-aware datetime in BRT."""
    return datetime(d.year, d.month, d.day, hour, minute, tzinfo=BRT)


def jitter(base: float, amplitude: float) -> float:
    return round(base + random.uniform(-amplitude, amplitude), 1)


async def get_or_none(session: AsyncSession, model, **kw):
    stmt = select(model)
    for k, v in kw.items():
        stmt = stmt.where(getattr(model, k) == v)
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


# ── Lookup seeding ─────────────────────────────────────────────────────────


async def ensure_lookups(s: AsyncSession) -> dict:
    """Insert lookups if missing; return slug→model maps."""
    sources_data = [
        ("manual", "Manual Entry", "manual"),
        ("garmin", "Garmin", "device"),
        ("withings", "Withings", "device"),
        ("apple_health", "Apple Health", "app"),
    ]
    for slug, name, stype in sources_data:
        if not await get_or_none(s, DataSource, slug=slug):
            s.add(DataSource(slug=slug, name=name, source_type=stype))

    metrics_data = [
        ("weight", "Weight", "body_composition", "kg", 2),
        ("body_fat_pct", "Body Fat %", "body_composition", "%", 1),
        ("body_temperature", "Body Temperature", "vitals", "°C", 1),
        ("resting_hr", "Resting Heart Rate", "cardiovascular", "bpm", 0),
        ("hrv_rmssd", "HRV (RMSSD)", "cardiovascular", "ms", 1),
        ("spo2", "SpO2", "respiratory", "%", 0),
        ("steps", "Steps", "activity", "steps", 0),
        ("active_calories", "Active Calories", "activity", "kcal", 0),
        ("sleep_duration", "Sleep Duration", "sleep", "min", 0),
        ("sleep_score", "Sleep Score", "sleep", "score", 0),
        ("stress_level", "Stress Level", "cardiovascular", "score", 0),
        ("respiratory_rate", "Respiratory Rate", "respiratory", "brpm", 1),
    ]
    for slug, name, cat, unit, prec in metrics_data:
        if not await get_or_none(s, MetricType, slug=slug):
            s.add(MetricType(
                slug=slug, name=name, category=cat,
                default_unit=unit, value_precision=prec,
            ))

    exercises_data = [
        ("bench_press", "Bench Press", "strength", "chest", "barbell"),
        ("squat", "Squat", "strength", "legs", "barbell"),
        ("deadlift", "Deadlift", "strength", "back", "barbell"),
        ("running", "Running", "cardio", "legs", None),
        ("pull_up", "Pull Up", "strength", "back", "bodyweight"),
        ("plank", "Plank", "strength", "core", "bodyweight"),
    ]
    for slug, name, cat, mg, eq in exercises_data:
        if not await get_or_none(s, Exercise, slug=slug):
            s.add(Exercise(slug=slug, name=name, category=cat, muscle_group=mg, equipment=eq))

    symptoms_data = [
        ("headache", "Headache", "neurological"),
        ("fatigue", "Fatigue", "systemic"),
        ("knee_pain", "Knee Pain", "musculoskeletal"),
        ("lower_back_pain", "Lower Back Pain", "musculoskeletal"),
        ("nausea", "Nausea", "digestive"),
        ("insomnia", "Insomnia", "neurological"),
    ]
    for slug, name, cat in symptoms_data:
        if not await get_or_none(s, Symptom, slug=slug):
            s.add(Symptom(slug=slug, name=name, category=cat))

    await s.flush()

    # Build lookup dicts
    src = {ds.slug: ds for ds in (await s.execute(select(DataSource))).scalars()}
    met = {mt.slug: mt for mt in (await s.execute(select(MetricType))).scalars()}
    exe = {e.slug: e for e in (await s.execute(select(Exercise))).scalars()}
    sym = {sy.slug: sy for sy in (await s.execute(select(Symptom))).scalars()}
    return {"sources": src, "metrics": met, "exercises": exe, "symptoms": sym}


# ── Garmin daily summaries (Raw → Curated) ─────────────────────────────────


GARMIN_PROFILES = {
    #                 rhr   hrv   steps  stress spo2  rr    kcal  sleep_m score
    "baseline":     (59,   48,   9000,  28,    97,   15.5, 450,  465,    82),
    "overreach":    (62,   42,   11000, 38,    96,   15.8, 520,  420,    74),
    "illness":      (68,   33,   4500,  50,    95,   17.0, 200,  390,    60),
    "recovery":     (63,   41,   7500,  34,    97,   15.6, 380,  445,    76),
}


async def seed_garmin(
    s: AsyncSession, user: User, d: date, ph: str, lk: dict
) -> None:
    base = GARMIN_PROFILES[ph]
    payload_json = {
        "date": d.isoformat(),
        "resting_hr": int(jitter(base[0], 3)),
        "hrv_rmssd": round(jitter(base[1], 5), 1),
        "steps": int(jitter(base[2], 2000)),
        "stress_level": int(jitter(base[3], 8)),
        "spo2": int(jitter(base[4], 1)),
        "respiratory_rate": round(jitter(base[5], 0.8), 1),
        "active_calories": int(jitter(base[6], 80)),
        "sleep_duration_min": int(jitter(base[7], 30)),
        "sleep_score": int(jitter(base[8], 8)),
    }

    garmin = lk["sources"]["garmin"]
    raw = RawPayload(
        id=uuid7(),
        user_id=user.id,
        source_id=garmin.id,
        external_id=f"garmin_{d.isoformat()}",
        payload_type="garmin_daily_summary",
        payload_json=payload_json,
        processing_status="processed",
        processed_at=dt(d, 6, 0),
    )
    s.add(raw)
    await s.flush()

    mapping = {
        "resting_hr": ("resting_hr", "bpm"),
        "hrv_rmssd": ("hrv_rmssd", "ms"),
        "steps": ("steps", "steps"),
        "stress_level": ("stress_level", "score"),
        "spo2": ("spo2", "%"),
        "respiratory_rate": ("respiratory_rate", "brpm"),
        "active_calories": ("active_calories", "kcal"),
        "sleep_duration_min": ("sleep_duration", "min"),
        "sleep_score": ("sleep_score", "score"),
    }
    for json_key, (slug, unit) in mapping.items():
        mt = lk["metrics"].get(slug)
        if not mt:
            continue
        s.add(
            Measurement(
                id=uuid7(),
                user_id=user.id,
                metric_type_id=mt.id,
                source_id=garmin.id,
                value_num=Decimal(str(payload_json[json_key])),
                unit=unit,
                measured_at=dt(d, 6),
                recorded_at=dt(d, 6),
                aggregation_level="daily",
                raw_payload_id=raw.id,
            )
        )


# ── Manual measurements (weight + temperature) ────────────────────────────

WEIGHT_PROFILES = {"baseline": 81.5, "overreach": 81.0, "illness": 81.8, "recovery": 80.6}
TEMP_PROFILES = {"baseline": 36.4, "overreach": 36.5, "illness": 37.4, "recovery": 36.5}


async def seed_manual(
    s: AsyncSession, user: User, d: date, ph: str, lk: dict
) -> None:
    manual = lk["sources"]["manual"]
    # Weight (morning)
    wt = lk["metrics"]["weight"]
    s.add(
        Measurement(
            id=uuid7(),
            user_id=user.id,
            metric_type_id=wt.id,
            source_id=manual.id,
            value_num=Decimal(str(round(jitter(WEIGHT_PROFILES[ph], 0.4), 1))),
            unit="kg",
            measured_at=dt(d, 7, 15),
            recorded_at=dt(d, 7, 20),
            aggregation_level="spot",
        )
    )
    # Temperature (morning)
    bt = lk["metrics"]["body_temperature"]
    s.add(
        Measurement(
            id=uuid7(),
            user_id=user.id,
            metric_type_id=bt.id,
            source_id=manual.id,
            value_num=Decimal(str(round(jitter(TEMP_PROFILES[ph], 0.2), 1))),
            unit="°C",
            measured_at=dt(d, 7, 20),
            recorded_at=dt(d, 7, 25),
            aggregation_level="spot",
        )
    )


# ── Workouts ───────────────────────────────────────────────────────────────


async def seed_workout(
    s: AsyncSession, user: User, d: date, ph: str, day_offset: int, lk: dict
) -> None:
    wd = d.weekday()  # 0=Mon … 6=Sun

    if ph == "illness":
        # Only one light walk mid-week
        if wd != 2:
            return
        session = WorkoutSession(
            id=uuid7(), user_id=user.id, source_id=lk["sources"]["manual"].id,
            title="Light walk", workout_type="cardio",
            started_at=dt(d, 10), ended_at=dt(d, 10, 30), duration_seconds=1800,
            perceived_effort=3, recorded_at=dt(d, 11),
        )
        s.add(session)
        return

    if ph == "recovery" and day_offset < 23:
        # First 2 days of recovery are rest
        return

    if wd == 0 or wd == 2:
        # Running days (Mon, Wed)
        dist = jitter(6000 if ph == "baseline" else 7500, 1000)
        dur = int(dist / 2.5)  # ~2.5 m/s
        session = WorkoutSession(
            id=uuid7(), user_id=user.id, source_id=lk["sources"]["garmin"].id,
            title="Easy run" if wd == 0 else "Tempo run", workout_type="cardio",
            started_at=dt(d, 6, 30), ended_at=dt(d, 6, 30) + timedelta(seconds=dur),
            duration_seconds=dur,
            perceived_effort=random.randint(5, 7),
            recorded_at=dt(d, 8),
        )
        s.add(session)
        await s.flush()
        s.add(WorkoutSet(
            id=uuid7(), workout_session_id=session.id,
            exercise_id=lk["exercises"]["running"].id, set_number=1,
            duration_seconds=dur, distance_meters=Decimal(str(int(dist))),
        ))

    elif wd == 1 or wd == 3:
        # Strength days (Tue, Thu)
        effort = random.randint(7, 9)
        session = WorkoutSession(
            id=uuid7(), user_id=user.id, source_id=lk["sources"]["manual"].id,
            title="Upper body" if wd == 1 else "Lower body", workout_type="strength",
            started_at=dt(d, 17, 0), ended_at=dt(d, 18, 15),
            duration_seconds=4500, perceived_effort=effort,
            recorded_at=dt(d, 18, 30),
        )
        s.add(session)
        await s.flush()

        exercises = (
            [("bench_press", 3), ("pull_up", 3), ("plank", 2)]
            if wd == 1
            else [("squat", 4), ("deadlift", 3)]
        )
        set_num = 1
        for slug, n_sets in exercises:
            for _ in range(n_sets):
                s.add(WorkoutSet(
                    id=uuid7(), workout_session_id=session.id,
                    exercise_id=lk["exercises"][slug].id, set_number=set_num,
                    reps=random.randint(6, 12),
                    weight_kg=Decimal(str(random.randint(40, 100))),
                    rest_seconds=random.choice([60, 90, 120]),
                ))
                set_num += 1

    elif wd == 5:
        # Saturday long run
        dist = jitter(12000 if ph != "overreach" else 15000, 1500)
        dur = int(dist / 2.4)
        session = WorkoutSession(
            id=uuid7(), user_id=user.id, source_id=lk["sources"]["garmin"].id,
            title="Long run", workout_type="cardio",
            started_at=dt(d, 7), ended_at=dt(d, 7) + timedelta(seconds=dur),
            duration_seconds=dur,
            perceived_effort=random.randint(7, 9),
            recorded_at=dt(d, 10),
        )
        s.add(session)
        await s.flush()
        s.add(WorkoutSet(
            id=uuid7(), workout_session_id=session.id,
            exercise_id=lk["exercises"]["running"].id, set_number=1,
            duration_seconds=dur, distance_meters=Decimal(str(int(dist))),
        ))


# ── Medications ────────────────────────────────────────────────────────────


async def seed_medications(
    s: AsyncSession, user: User
) -> dict:
    multi = MedicationDefinition(name="Daily Multivitamin", dosage_form="tablet")
    ibu = MedicationDefinition(
        name="Ibuprofen 400mg", dosage_form="tablet", active_ingredient="Ibuprofen"
    )
    s.add_all([multi, ibu])
    await s.flush()

    reg_multi = MedicationRegimen(
        id=uuid7(), user_id=user.id, medication_id=multi.id,
        dosage_amount=Decimal("1"), dosage_unit="tablet",
        frequency="daily", instructions="Take with breakfast",
        started_at=START_DATE,
    )
    reg_ibu = MedicationRegimen(
        id=uuid7(), user_id=user.id, medication_id=ibu.id,
        dosage_amount=Decimal("400"), dosage_unit="mg",
        frequency="as_needed", instructions="Take with food after intense exercise or for pain",
        started_at=START_DATE,
    )
    s.add_all([reg_multi, reg_ibu])
    await s.flush()
    return {"multivitamin": reg_multi, "ibuprofen": reg_ibu}


async def seed_med_logs(
    s: AsyncSession, user: User, d: date, ph: str, day_offset: int, meds: dict
) -> None:
    now = dt(d, 8)
    # Daily multivitamin — sometimes skipped during illness
    if ph == "illness" and random.random() < 0.3:
        status = "skipped"
        taken_at = None
    else:
        status = "taken"
        taken_at = now
    s.add(MedicationLog(
        id=uuid7(), user_id=user.id,
        regimen_id=meds["multivitamin"].id,
        status=status, scheduled_at=dt(d, 8),
        taken_at=taken_at, recorded_at=now,
    ))

    # Ibuprofen: after Saturday long run, or during illness headache days
    take_ibu = (d.weekday() == 5 and ph in ("baseline", "overreach")) or (
        ph == "illness" and random.random() < 0.5
    )
    if take_ibu:
        s.add(MedicationLog(
            id=uuid7(), user_id=user.id,
            regimen_id=meds["ibuprofen"].id,
            status="taken", scheduled_at=dt(d, 12),
            taken_at=dt(d, 12, random.randint(0, 30)),
            recorded_at=dt(d, 13),
        ))


# ── Symptoms ───────────────────────────────────────────────────────────────


async def seed_symptoms(
    s: AsyncSession, user: User, d: date, ph: str, day_offset: int, lk: dict
) -> None:
    # Knee pain after Saturday long run (Sun/Mon following)
    if d.weekday() in (6, 0) and ph in ("baseline", "overreach"):
        s.add(SymptomLog(
            id=uuid7(), user_id=user.id,
            symptom_id=lk["symptoms"]["knee_pain"].id,
            intensity=random.randint(3, 5) if ph == "baseline" else random.randint(5, 7),
            status="active", trigger="long run",
            functional_impact="mild" if ph == "baseline" else "moderate",
            started_at=dt(d, 9), ended_at=dt(d, 18),
            recorded_at=dt(d, 9, 15),
        ))

    # Illness symptoms
    if ph == "illness":
        if day_offset < 18:  # headache in first half of illness
            s.add(SymptomLog(
                id=uuid7(), user_id=user.id,
                symptom_id=lk["symptoms"]["headache"].id,
                intensity=random.randint(4, 7),
                status="active", functional_impact="moderate",
                started_at=dt(d, 8), ended_at=dt(d, 20),
                recorded_at=dt(d, 8, 30),
            ))
        # Fatigue through entire illness
        s.add(SymptomLog(
            id=uuid7(), user_id=user.id,
            symptom_id=lk["symptoms"]["fatigue"].id,
            intensity=random.randint(5, 8),
            status="active", functional_impact="moderate",
            started_at=dt(d, 7), ended_at=dt(d, 22),
            recorded_at=dt(d, 7, 30),
        ))

    # Residual fatigue in early recovery
    if ph == "recovery" and day_offset < 23:
        s.add(SymptomLog(
            id=uuid7(), user_id=user.id,
            symptom_id=lk["symptoms"]["fatigue"].id,
            intensity=random.randint(2, 4),
            status="improving", functional_impact="mild",
            started_at=dt(d, 7), ended_at=dt(d, 15),
            recorded_at=dt(d, 7, 30),
        ))


# ── Daily checkpoints ─────────────────────────────────────────────────────

CHECKPOINT_PROFILES = {
    #              mood  energy  sleep_q  body
    "baseline":   (7.5,  7.5,   7.0,     7.5),
    "overreach":  (6.5,  6.0,   6.0,     6.0),
    "illness":    (4.0,  3.5,   4.5,     3.5),
    "recovery":   (6.5,  6.0,   6.5,     6.0),
}


async def seed_checkpoints(
    s: AsyncSession, user: User, d: date, ph: str
) -> None:
    mp = CHECKPOINT_PROFILES[ph]
    # Morning
    s.add(DailyCheckpoint(
        id=uuid7(), user_id=user.id,
        checkpoint_type="morning", checkpoint_date=d,
        checkpoint_at=dt(d, 7, 30), recorded_at=dt(d, 7, 35),
        mood=max(1, min(10, int(jitter(mp[0], 1.2)))),
        energy=max(1, min(10, int(jitter(mp[1], 1.2)))),
        sleep_quality=max(1, min(10, int(jitter(mp[2], 1.5)))),
        body_state_score=max(1, min(10, int(jitter(mp[3], 1.2)))),
    ))
    # Night
    s.add(DailyCheckpoint(
        id=uuid7(), user_id=user.id,
        checkpoint_type="night", checkpoint_date=d,
        checkpoint_at=dt(d, 22, 30), recorded_at=dt(d, 22, 35),
        mood=max(1, min(10, int(jitter(mp[0] - 0.5, 1.0)))),
        sleep_quality=max(1, min(10, int(jitter(mp[2], 1.0)))),
        body_state_score=max(1, min(10, int(jitter(mp[3] - 0.3, 1.0)))),
    ))


# ── Main ───────────────────────────────────────────────────────────────────


async def main() -> None:
    engine = create_async_engine(settings.database_url, echo=False)
    session_factory = async_sessionmaker(
        engine, class_=AsyncSession, expire_on_commit=False
    )

    async with session_factory() as s:
        lk = await ensure_lookups(s)
        await s.commit()

        # User (idempotent: skip if already seeded)
        user = await get_or_none(s, User, email="lucas@baseline.dev")
        if user:
            print("User already exists — re-run with a clean DB to re-seed.")
            await engine.dispose()
            return
        user = User(
            id=uuid7(),
            email="lucas@baseline.dev",
            name="Lucas Mendes",
            timezone="America/Sao_Paulo",
        )
        s.add(user)
        await s.flush()

        meds = await seed_medications(s, user)
        await s.commit()

        for day_offset in range(30):
            d = START_DATE + timedelta(days=day_offset)
            ph = phase(day_offset)

            await seed_garmin(s, user, d, ph, lk)
            await seed_manual(s, user, d, ph, lk)
            await seed_workout(s, user, d, ph, day_offset, lk)
            await seed_med_logs(s, user, d, ph, day_offset, meds)
            await seed_symptoms(s, user, d, ph, day_offset, lk)
            await seed_checkpoints(s, user, d, ph)

            await s.commit()
            print(f"  {d} ({ph})")

    await engine.dispose()
    print("\nSeed complete — 30 days for lucas@baseline.dev")


if __name__ == "__main__":
    asyncio.run(main())
