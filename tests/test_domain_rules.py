"""Service-layer domain-rule tests.

Business logic that sits *above* the database but *below* the API:
  - Slug resolution (human-friendly slugs → FK IDs)
  - Authorization (medication log must match regimen owner)
  - Checkpoint uniqueness (service gives clear error before DB constraint)
  - Pydantic schema validation (naive datetimes, out-of-range values)
"""
import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from pydantic import ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.medication import MedicationDefinition, MedicationRegimen
from app.models.user import User
from app.schemas.daily_checkpoint import DailyCheckpointCreate
from app.schemas.measurement import MeasurementCreate
from app.schemas.medication import MedicationLogCreate
from app.schemas.symptom import SymptomLogCreate
from app.schemas.workout import WorkoutSessionCreate, WorkoutSetCreate
from app.services.daily_checkpoint import DailyCheckpointService
from app.services.measurement import MeasurementService
from app.services.medication import MedicationService
from app.services.symptom import SymptomService
from app.services.workout import WorkoutService

# ── Slug resolution ────────────────────────────────────────────────────────


class TestSlugResolution:
    async def test_measurement_resolves_slugs(self, db: AsyncSession, user: User):
        svc = MeasurementService(db)
        now = datetime.now(UTC)
        result = await svc.create(
            MeasurementCreate(
                user_id=user.id,
                metric_type_slug="weight",
                source_slug="manual",
                value_num=Decimal("81.5"),
                unit="kg",
                measured_at=now,
                recorded_at=now,
            )
        )
        assert result.metric_type_slug == "weight"
        assert result.source_slug == "manual"
        assert result.value_num == Decimal("81.5")

    async def test_measurement_rejects_unknown_metric(
        self, db: AsyncSession, user: User
    ):
        svc = MeasurementService(db)
        now = datetime.now(UTC)
        with pytest.raises(ValueError, match="Unknown metric type"):
            await svc.create(
                MeasurementCreate(
                    user_id=user.id,
                    metric_type_slug="nonexistent",
                    source_slug="manual",
                    value_num=Decimal("42"),
                    unit="?",
                    measured_at=now,
                    recorded_at=now,
                )
            )

    async def test_workout_resolves_exercise_slugs(
        self, db: AsyncSession, user: User
    ):
        svc = WorkoutService(db)
        now = datetime.now(UTC)
        result = await svc.create_session(
            WorkoutSessionCreate(
                user_id=user.id,
                source_slug="manual",
                workout_type="strength",
                started_at=now,
                recorded_at=now,
                sets=[
                    WorkoutSetCreate(
                        exercise_slug="bench_press", set_number=1,
                        reps=10, weight_kg=Decimal("80"),
                    ),
                    WorkoutSetCreate(
                        exercise_slug="squat", set_number=2,
                        reps=8, weight_kg=Decimal("100"),
                    ),
                ],
            )
        )
        assert len(result.sets) == 2
        assert result.sets[0].exercise_slug == "bench_press"
        assert result.sets[1].exercise_slug == "squat"

    async def test_symptom_resolves_slug(self, db: AsyncSession, user: User):
        svc = SymptomService(db)
        now = datetime.now(UTC)
        result = await svc.create_log(
            SymptomLogCreate(
                user_id=user.id,
                symptom_slug="knee_pain",
                intensity=6,
                started_at=now,
                recorded_at=now,
            )
        )
        assert result.symptom_slug == "knee_pain"


# ── Business rules ─────────────────────────────────────────────────────────


class TestCheckpointUniqueness:
    async def test_duplicate_rejected_with_clear_message(
        self, db: AsyncSession, user: User
    ):
        svc = DailyCheckpointService(db)
        now = datetime.now(UTC)
        today = date.today()
        data = DailyCheckpointCreate(
            user_id=user.id,
            checkpoint_type="morning",
            checkpoint_date=today,
            checkpoint_at=now,
            recorded_at=now,
            mood=7,
            energy=6,
        )
        await svc.create(data)
        with pytest.raises(ValueError, match="already exists"):
            await svc.create(data)


class TestMedicationAuthorization:
    async def test_log_rejects_other_users_regimen(
        self, db: AsyncSession, user: User
    ):
        # Setup: medication + regimen for `user`
        med = MedicationDefinition(name="Ibuprofen", dosage_form="tablet")
        db.add(med)
        await db.flush()

        regimen = MedicationRegimen(
            id=uuid.uuid4(),
            user_id=user.id,
            medication_id=med.id,
            dosage_amount=Decimal("400"),
            dosage_unit="mg",
            frequency="as_needed",
            started_at=date.today(),
        )
        db.add(regimen)
        await db.flush()

        # Another user tries to log against this regimen
        other = User(
            id=uuid.uuid4(),
            email="other@test.com",
            name="Other",
        )
        db.add(other)
        await db.flush()

        svc = MedicationService(db)
        now = datetime.now(UTC)
        with pytest.raises(ValueError, match="does not belong"):
            await svc.create_log(
                MedicationLogCreate(
                    user_id=other.id,
                    regimen_id=regimen.id,
                    status="taken",
                    scheduled_at=now,
                    taken_at=now,
                    recorded_at=now,
                )
            )


# ── Schema validation (Pydantic) ──────────────────────────────────────────


class TestSchemaValidation:
    def test_naive_datetime_rejected(self):
        with pytest.raises(ValidationError):
            MeasurementCreate(
                user_id=uuid.uuid4(),
                metric_type_slug="weight",
                source_slug="manual",
                value_num=Decimal("80"),
                unit="kg",
                measured_at=datetime(2026, 3, 15, 7, 30),  # naive
                recorded_at=datetime(2026, 3, 15, 7, 30),  # naive
            )

    def test_confidence_above_one_rejected(self):
        with pytest.raises(ValidationError):
            MeasurementCreate(
                user_id=uuid.uuid4(),
                metric_type_slug="weight",
                source_slug="manual",
                value_num=Decimal("80"),
                unit="kg",
                measured_at=datetime.now(UTC),
                recorded_at=datetime.now(UTC),
                confidence=Decimal("1.5"),
            )

    def test_perceived_effort_below_min(self):
        with pytest.raises(ValidationError):
            WorkoutSessionCreate(
                user_id=uuid.uuid4(),
                source_slug="manual",
                workout_type="strength",
                started_at=datetime.now(UTC),
                recorded_at=datetime.now(UTC),
                perceived_effort=0,
            )

    def test_checkpoint_mood_above_max(self):
        with pytest.raises(ValidationError):
            DailyCheckpointCreate(
                user_id=uuid.uuid4(),
                checkpoint_type="morning",
                checkpoint_date=date.today(),
                checkpoint_at=datetime.now(UTC),
                recorded_at=datetime.now(UTC),
                mood=11,
            )

    def test_symptom_intensity_below_min(self):
        with pytest.raises(ValidationError):
            SymptomLogCreate(
                user_id=uuid.uuid4(),
                symptom_slug="headache",
                intensity=0,
                started_at=datetime.now(UTC),
                recorded_at=datetime.now(UTC),
            )
