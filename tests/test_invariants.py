"""Database-level invariant tests.

These prove that the schema enforces integrity *independently of the
application layer* — a broken service cannot corrupt the data.

Invariants tested:
  - Foreign-key constraints (orphan prevention)
  - UNIQUE constraints (deduplication)
  - CHECK constraints (value-domain enforcement)
"""
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.daily_checkpoint import DailyCheckpoint
from app.models.data_source import DataSource
from app.models.measurement import Measurement
from app.models.symptom import SymptomLog
from app.models.user import User
from app.models.workout import WorkoutSession, WorkoutSet

# ── Foreign-key integrity ──────────────────────────────────────────────────


class TestForeignKeys:
    async def test_measurement_rejects_nonexistent_user(self, db: AsyncSession):
        m = Measurement(
            id=uuid.uuid4(),
            user_id=uuid.uuid4(),  # no such user
            metric_type_id=1,
            source_id=1,
            value_num=Decimal("80"),
            unit="kg",
            measured_at=datetime.now(UTC),
            recorded_at=datetime.now(UTC),
        )
        db.add(m)
        with pytest.raises(IntegrityError):
            await db.flush()

    async def test_measurement_rejects_nonexistent_metric_type(
        self, db: AsyncSession, user: User
    ):
        m = Measurement(
            id=uuid.uuid4(),
            user_id=user.id,
            metric_type_id=9999,
            source_id=1,
            value_num=Decimal("80"),
            unit="kg",
            measured_at=datetime.now(UTC),
            recorded_at=datetime.now(UTC),
        )
        db.add(m)
        with pytest.raises(IntegrityError):
            await db.flush()

    async def test_measurement_rejects_nonexistent_source(
        self, db: AsyncSession, user: User
    ):
        m = Measurement(
            id=uuid.uuid4(),
            user_id=user.id,
            metric_type_id=1,
            source_id=9999,
            value_num=Decimal("80"),
            unit="kg",
            measured_at=datetime.now(UTC),
            recorded_at=datetime.now(UTC),
        )
        db.add(m)
        with pytest.raises(IntegrityError):
            await db.flush()

    async def test_workout_set_rejects_nonexistent_session(self, db: AsyncSession):
        ws = WorkoutSet(
            id=uuid.uuid4(),
            workout_session_id=uuid.uuid4(),
            exercise_id=1,
            set_number=1,
            reps=10,
            weight_kg=Decimal("80"),
        )
        db.add(ws)
        with pytest.raises(IntegrityError):
            await db.flush()

    async def test_symptom_log_rejects_nonexistent_symptom(
        self, db: AsyncSession, user: User
    ):
        log = SymptomLog(
            id=uuid.uuid4(),
            user_id=user.id,
            symptom_id=9999,
            intensity=5,
            started_at=datetime.now(UTC),
            recorded_at=datetime.now(UTC),
        )
        db.add(log)
        with pytest.raises(IntegrityError):
            await db.flush()


# ── UNIQUE constraints ─────────────────────────────────────────────────────


class TestUniqueConstraints:
    async def test_daily_checkpoint_one_per_user_type_date(
        self, db: AsyncSession, user: User
    ):
        """Only one morning checkpoint per user per day."""
        now = datetime.now(UTC)
        today = date.today()
        base = dict(
            user_id=user.id,
            checkpoint_type="morning",
            checkpoint_date=today,
            checkpoint_at=now,
            recorded_at=now,
        )
        db.add(DailyCheckpoint(id=uuid.uuid4(), mood=7, **base))
        await db.flush()

        db.add(DailyCheckpoint(id=uuid.uuid4(), mood=8, **base))
        with pytest.raises(IntegrityError):
            await db.flush()

    async def test_daily_checkpoint_allows_different_types_same_day(
        self, db: AsyncSession, user: User
    ):
        """Morning + night on the same day is valid."""
        now = datetime.now(UTC)
        today = date.today()
        db.add_all(
            [
                DailyCheckpoint(
                    id=uuid.uuid4(),
                    user_id=user.id,
                    checkpoint_type="morning",
                    checkpoint_date=today,
                    checkpoint_at=now,
                    recorded_at=now,
                ),
                DailyCheckpoint(
                    id=uuid.uuid4(),
                    user_id=user.id,
                    checkpoint_type="night",
                    checkpoint_date=today,
                    checkpoint_at=now,
                    recorded_at=now,
                ),
            ]
        )
        await db.flush()  # must succeed

    async def test_user_email_unique(self, db: AsyncSession):
        db.add(User(id=uuid.uuid4(), email="dup@test.com", name="A"))
        await db.flush()
        db.add(User(id=uuid.uuid4(), email="dup@test.com", name="B"))
        with pytest.raises(IntegrityError):
            await db.flush()

    async def test_data_source_slug_unique(self, db: AsyncSession):
        """Seeded 'manual' slug must reject a duplicate."""
        db.add(DataSource(slug="manual", name="Dup", source_type="manual"))
        with pytest.raises(IntegrityError):
            await db.flush()


# ── CHECK constraints ──────────────────────────────────────────────────────


class TestCheckConstraints:
    async def test_symptom_intensity_below_min(self, db: AsyncSession, user: User):
        log = SymptomLog(
            id=uuid.uuid4(),
            user_id=user.id,
            symptom_id=1,
            intensity=0,
            started_at=datetime.now(UTC),
            recorded_at=datetime.now(UTC),
        )
        db.add(log)
        with pytest.raises(IntegrityError):
            await db.flush()

    async def test_symptom_intensity_above_max(self, db: AsyncSession, user: User):
        log = SymptomLog(
            id=uuid.uuid4(),
            user_id=user.id,
            symptom_id=1,
            intensity=11,
            started_at=datetime.now(UTC),
            recorded_at=datetime.now(UTC),
        )
        db.add(log)
        with pytest.raises(IntegrityError):
            await db.flush()

    async def test_perceived_effort_out_of_range(self, db: AsyncSession, user: User):
        ws = WorkoutSession(
            id=uuid.uuid4(),
            user_id=user.id,
            source_id=1,
            workout_type="strength",
            started_at=datetime.now(UTC),
            recorded_at=datetime.now(UTC),
            perceived_effort=11,
        )
        db.add(ws)
        with pytest.raises(IntegrityError):
            await db.flush()

    async def test_checkpoint_mood_below_min(self, db: AsyncSession, user: User):
        c = DailyCheckpoint(
            id=uuid.uuid4(),
            user_id=user.id,
            checkpoint_type="morning",
            checkpoint_date=date.today(),
            checkpoint_at=datetime.now(UTC),
            recorded_at=datetime.now(UTC),
            mood=0,
        )
        db.add(c)
        with pytest.raises(IntegrityError):
            await db.flush()

    async def test_checkpoint_energy_above_max(self, db: AsyncSession, user: User):
        c = DailyCheckpoint(
            id=uuid.uuid4(),
            user_id=user.id,
            checkpoint_type="night",
            checkpoint_date=date.today(),
            checkpoint_at=datetime.now(UTC),
            recorded_at=datetime.now(UTC),
            energy=11,
        )
        db.add(c)
        with pytest.raises(IntegrityError):
            await db.flush()
