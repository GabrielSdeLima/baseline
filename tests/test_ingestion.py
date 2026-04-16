"""Ingestion pipeline tests.

Covers the Raw → Curated lifecycle:
  - Garmin parser extracts correct measurements
  - Manual parser creates a single record
  - Duplicate external_id is idempotent (returns existing, no new rows)
  - Malformed payloads preserve raw and mark 'failed'
  - Unknown payload_type is a no-op (not an error)
  - Raw → curated traceability via raw_payload_id FK
  - Reprocessing skips payloads that already have curated data
"""
from decimal import Decimal

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.measurement import Measurement
from app.models.raw_payload import RawPayload
from app.models.user import User
from app.schemas.raw_payload import RawPayloadIngest
from app.services.ingestion import IngestionService


@pytest.fixture
def garmin_payload(user: User) -> RawPayloadIngest:
    return RawPayloadIngest(
        user_id=user.id,
        source_slug="garmin",
        external_id="garmin_2026-03-15",
        payload_type="garmin_daily_summary",
        payload_json={
            "date": "2026-03-15",
            "resting_hr": 58,
            "hrv_rmssd": 42.5,
            "steps": 8500,
            "stress_level": 35,
            "spo2": 97,
            "respiratory_rate": 15.2,
            "active_calories": 420,
            "sleep_duration_min": 450,
            "sleep_score": 82,
        },
    )


# ── Pipeline core ──────────────────────────────────────────────────────────


class TestPipeline:
    async def test_garmin_daily_creates_measurements(
        self, db: AsyncSession, user: User, garmin_payload: RawPayloadIngest
    ):
        svc = IngestionService(db)
        payload = await svc.ingest(garmin_payload)

        assert payload.processing_status == "processed"
        assert payload.processed_at is not None

        result = await db.execute(
            select(Measurement).where(Measurement.raw_payload_id == payload.id)
        )
        measurements = list(result.scalars().all())
        assert len(measurements) == 9  # all 9 metrics present in the fixture

    async def test_raw_curated_traceability(
        self, db: AsyncSession, user: User, garmin_payload: RawPayloadIngest
    ):
        """Every curated measurement links back to its raw payload."""
        svc = IngestionService(db)
        payload = await svc.ingest(garmin_payload)

        result = await db.execute(
            select(Measurement).where(Measurement.raw_payload_id == payload.id)
        )
        for m in result.scalars():
            assert m.raw_payload_id == payload.id
            assert m.user_id == user.id

    async def test_manual_measurement_single_record(
        self, db: AsyncSession, user: User
    ):
        svc = IngestionService(db)
        data = RawPayloadIngest(
            user_id=user.id,
            source_slug="manual",
            payload_type="manual_measurement",
            payload_json={
                "metric_type_slug": "weight",
                "value": 81.5,
                "unit": "kg",
                "measured_at": "2026-03-15T07:30:00+00:00",
            },
        )
        payload = await svc.ingest(data)

        assert payload.processing_status == "processed"
        result = await db.execute(
            select(Measurement).where(Measurement.raw_payload_id == payload.id)
        )
        rows = list(result.scalars().all())
        assert len(rows) == 1
        assert rows[0].value_num == Decimal("81.5")
        assert rows[0].unit == "kg"


# ── Idempotency ────────────────────────────────────────────────────────────


class TestIdempotency:
    async def test_duplicate_external_id_returns_existing(
        self, db: AsyncSession, user: User, garmin_payload: RawPayloadIngest
    ):
        svc = IngestionService(db)
        first = await svc.ingest(garmin_payload)
        second = await svc.ingest(garmin_payload)

        assert first.id == second.id

        count = await db.scalar(
            select(func.count()).select_from(RawPayload).where(
                RawPayload.external_id == garmin_payload.external_id
            )
        )
        assert count == 1

    async def test_reprocess_skips_already_curated(
        self, db: AsyncSession, user: User, garmin_payload: RawPayloadIngest
    ):
        svc = IngestionService(db)
        payload = await svc.ingest(garmin_payload)
        assert payload.processing_status == "processed"

        # Simulate manual reset to "pending"
        payload.processing_status = "pending"
        payload.processed_at = None
        await db.flush()
        await db.commit()

        await svc.reprocess_pending()
        await db.refresh(payload)
        assert payload.processing_status == "skipped"


# ── Rollback / failure ─────────────────────────────────────────────────────


class TestRollback:
    async def test_bad_payload_preserves_raw_marks_failed(
        self, db: AsyncSession, user: User
    ):
        """Malformed data: raw survives, curated does not leak."""
        svc = IngestionService(db)
        data = RawPayloadIngest(
            user_id=user.id,
            source_slug="manual",
            payload_type="manual_measurement",
            payload_json={
                "metric_type_slug": "nonexistent_metric",
                "value": 42,
            },
        )
        payload = await svc.ingest(data)

        assert payload.processing_status == "failed"
        assert "nonexistent_metric" in payload.error_message

        # Raw is preserved
        raw = await db.get(RawPayload, payload.id)
        assert raw is not None

        # No curated records leaked
        count = await db.scalar(
            select(func.count()).select_from(Measurement).where(
                Measurement.raw_payload_id == payload.id
            )
        )
        assert count == 0

    async def test_unknown_payload_type_is_noop(
        self, db: AsyncSession, user: User
    ):
        """Unknown type: no parser, no crash — processed with zero curated rows."""
        svc = IngestionService(db)
        data = RawPayloadIngest(
            user_id=user.id,
            source_slug="garmin",
            payload_type="garmin_body_composition",  # no parser registered
            payload_json={"body_fat": 18.5},
        )
        payload = await svc.ingest(data)
        assert payload.processing_status == "processed"

    async def test_unknown_source_raises_before_persisting(
        self, db: AsyncSession, user: User
    ):
        svc = IngestionService(db)
        data = RawPayloadIngest(
            user_id=user.id,
            source_slug="totally_fake_source",
            payload_type="whatever",
            payload_json={"x": 1},
        )
        with pytest.raises(ValueError, match="Unknown data source"):
            await svc.ingest(data)
