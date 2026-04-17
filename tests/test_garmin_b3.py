"""B3 — Garmin operational runs: versioned snapshots, run linking, source cursors.

Covers:
  A. Versioned snapshots — each re-sync creates a new raw_payload, measurements
     are replaced for the logical date, other sources/dates are not touched.
  B. IngestionRun linking — new snapshots link as 'created', counters increment,
     null idempotency_key allows multiple completed runs for refresh triggers.
  C. SourceCursor semantics — cursor is created on first success, advances on
     subsequent runs, and points to the correct logical date.
"""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import uuid7
from app.models.data_source import DataSource
from app.models.ingestion_run import IngestionRun
from app.models.ingestion_run_payload import IngestionRunPayload
from app.models.measurement import Measurement
from app.models.raw_payload import RawPayload
from app.models.source_cursor import SourceCursor
from app.models.user import User
from app.schemas.raw_payload import RawPayloadIngest
from app.services.ingestion import IngestionService


# ── Shared fixtures / helpers ─────────────────────────────────────────────────

_STATS = {
    "restingHeartRate": 58,
    "totalSteps": 9000,
    "activeKilocalories": 480,
    "averageStressLevel": 32,
    "averageSpo2": 97,
    "avgWakingRespirationValue": 14.5,
    "bodyBatteryMostRecentValue": 42,
}
_HRV = {"hrvSummary": {"lastNightAvg": 46}}
_SLEEP = {
    "dailySleepDTO": {
        "sleepTimeSeconds": 25200,
        "sleepScores": {"overall": {"value": 74}},
    }
}

_GARMIN_PAYLOAD: dict = {
    "format_version": "garmin_connect_v1",
    "date": "2026-04-17",
    "user_timezone": "America/Sao_Paulo",
    "fetch_method": "garminconnect_api",
    "stats": _STATS,
    "hrv": _HRV,
    "sleep": _SLEEP,
}


def _garmin_req(
    user: User,
    payload_json: dict,
    *,
    external_id: str,
    run_id: uuid.UUID | None = None,
) -> RawPayloadIngest:
    return RawPayloadIngest(
        user_id=user.id,
        source_slug="garmin_connect",
        external_id=external_id,
        payload_type="garmin_connect_daily",
        payload_json=payload_json,
        ingestion_run_id=run_id,
    )


async def _make_garmin_run(db: AsyncSession, user: User) -> IngestionRun:
    """Create a minimal running IngestionRun for garmin_connect in the test session."""
    result = await db.execute(
        select(DataSource.id).where(DataSource.slug == "garmin_connect")
    )
    source_id = result.scalar_one()
    run = IngestionRun(
        user_id=user.id,
        source_id=source_id,
        operation_type="cloud_sync",
        trigger_type="scheduled",
    )
    db.add(run)
    await db.flush()
    return run


# ── A. Versioned snapshots ────────────────────────────────────────────────────


class TestGarminVersionedSnapshotsB3:
    async def test_resync_creates_new_raw_payload(self, db: AsyncSession, user: User):
        """Two fetches of the same date with different timestamps → two distinct raw_payloads."""
        svc = IngestionService(db)
        p1 = await svc.ingest(_garmin_req(
            user, _GARMIN_PAYLOAD, external_id="garmin_connect_2026-04-17_20260417T080000Z",
        ))
        p2 = await svc.ingest(_garmin_req(
            user, _GARMIN_PAYLOAD, external_id="garmin_connect_2026-04-17_20260417T200000Z",
        ))
        assert p1.id != p2.id

    async def test_new_snapshot_measurements_replace_old(self, db: AsyncSession, user: User):
        """After re-sync, the 10 curated measurements all belong to the latest snapshot."""
        svc = IngestionService(db)
        p1 = await svc.ingest(_garmin_req(
            user, _GARMIN_PAYLOAD, external_id="garmin_connect_2026-04-17_20260417T080000Z",
        ))
        p2 = await svc.ingest(_garmin_req(
            user, _GARMIN_PAYLOAD, external_id="garmin_connect_2026-04-17_20260417T200000Z",
        ))
        # p1's measurements are gone
        old_count = await db.scalar(
            select(func.count()).select_from(Measurement)
            .where(Measurement.raw_payload_id == p1.id)
        )
        # p2's measurements are present
        new_count = await db.scalar(
            select(func.count()).select_from(Measurement)
            .where(Measurement.raw_payload_id == p2.id)
        )
        assert old_count == 0
        assert new_count == 10

    async def test_old_raw_payload_preserved(self, db: AsyncSession, user: User):
        """raw_payload from the first sync is NOT deleted — append-only audit trail."""
        svc = IngestionService(db)
        p1 = await svc.ingest(_garmin_req(
            user, _GARMIN_PAYLOAD, external_id="garmin_connect_2026-04-17_20260417T080000Z",
        ))
        await svc.ingest(_garmin_req(
            user, _GARMIN_PAYLOAD, external_id="garmin_connect_2026-04-17_20260417T200000Z",
        ))
        raw = await db.get(RawPayload, p1.id)
        assert raw is not None

    async def test_other_source_measurements_not_touched(
        self, db: AsyncSession, user: User
    ):
        """HC900 and manual measurements for the same date are never deleted by Garmin re-sync."""
        svc = IngestionService(db)
        # Manual measurement for the same date
        manual = RawPayload(
            user_id=user.id,
            source_id=(await db.scalar(select(DataSource.id).where(DataSource.slug == "manual"))),
            payload_type="manual_measurement",
            payload_json={
                "metric_type_slug": "weight",
                "value": 82.5,
                "unit": "kg",
                "measured_at": "2026-04-17T07:00:00Z",
            },
        )
        db.add(manual)
        await db.flush()
        await svc._process(manual)

        manual_m_count_before = await db.scalar(
            select(func.count()).select_from(Measurement)
            .where(Measurement.raw_payload_id == manual.id)
        )
        assert manual_m_count_before == 1

        # Garmin re-sync for the same date
        await svc.ingest(_garmin_req(
            user, _GARMIN_PAYLOAD, external_id="garmin_connect_2026-04-17_20260417T080000Z",
        ))
        await svc.ingest(_garmin_req(
            user, _GARMIN_PAYLOAD, external_id="garmin_connect_2026-04-17_20260417T200000Z",
        ))

        manual_m_count_after = await db.scalar(
            select(func.count()).select_from(Measurement)
            .where(Measurement.raw_payload_id == manual.id)
        )
        assert manual_m_count_after == 1, "Manual measurements must survive Garmin re-sync"

    async def test_other_date_garmin_measurements_not_touched(
        self, db: AsyncSession, user: User
    ):
        """Re-sync of 2026-04-17 does not delete measurements for 2026-04-16."""
        svc = IngestionService(db)
        yesterday = await svc.ingest(_garmin_req(
            user, {**_GARMIN_PAYLOAD, "date": "2026-04-16"},
            external_id="garmin_connect_2026-04-16_20260417T080000Z",
        ))
        # First sync of today
        await svc.ingest(_garmin_req(
            user, _GARMIN_PAYLOAD, external_id="garmin_connect_2026-04-17_20260417T080000Z",
        ))
        # Re-sync of today
        await svc.ingest(_garmin_req(
            user, _GARMIN_PAYLOAD, external_id="garmin_connect_2026-04-17_20260417T200000Z",
        ))

        yesterday_count = await db.scalar(
            select(func.count()).select_from(Measurement)
            .where(Measurement.raw_payload_id == yesterday.id)
        )
        assert yesterday_count == 10, "Yesterday's measurements must not be touched"


# ── B. IngestionRun linking ───────────────────────────────────────────────────


class TestIngestionRunLinkingB3:
    async def test_new_snapshot_linked_as_created(self, db: AsyncSession, user: User):
        """A fresh versioned snapshot is linked to the run with role='created'."""
        svc = IngestionService(db)
        run = await _make_garmin_run(db, user)
        payload = await svc.ingest(_garmin_req(
            user, _GARMIN_PAYLOAD,
            external_id="garmin_connect_2026-04-17_20260417T080000Z",
            run_id=run.id,
        ))
        link = await db.get(IngestionRunPayload, (run.id, payload.id))
        assert link is not None
        assert link.role == "created"

    async def test_resync_snapshot_also_linked_as_created(self, db: AsyncSession, user: User):
        """Re-sync creates a NEW raw_payload → links as 'created', not 'reused'."""
        svc = IngestionService(db)
        run = await _make_garmin_run(db, user)
        await svc.ingest(_garmin_req(
            user, _GARMIN_PAYLOAD,
            external_id="garmin_connect_2026-04-17_20260417T080000Z",
            run_id=run.id,
        ))
        p2 = await svc.ingest(_garmin_req(
            user, _GARMIN_PAYLOAD,
            external_id="garmin_connect_2026-04-17_20260417T200000Z",
            run_id=run.id,
        ))
        link2 = await db.get(IngestionRunPayload, (run.id, p2.id))
        assert link2 is not None
        assert link2.role == "created"

    async def test_run_counter_increments_per_new_snapshot(self, db: AsyncSession, user: User):
        """raw_payloads_created increments for each distinct versioned snapshot."""
        svc = IngestionService(db)
        run = await _make_garmin_run(db, user)
        await svc.ingest(_garmin_req(
            user, _GARMIN_PAYLOAD,
            external_id="garmin_connect_2026-04-17_20260417T080000Z",
            run_id=run.id,
        ))
        await svc.ingest(_garmin_req(
            user, _GARMIN_PAYLOAD,
            external_id="garmin_connect_2026-04-17_20260417T200000Z",
            run_id=run.id,
        ))
        await db.refresh(run)
        assert run.raw_payloads_created == 2

    async def test_null_idempotency_key_allows_multiple_completed_runs(
        self, db: AsyncSession, user: User
    ):
        """Startup/scheduled runs use key=None, so a completed run never blocks a new refresh."""
        result = await db.execute(
            select(DataSource.id).where(DataSource.slug == "garmin_connect")
        )
        source_id = result.scalar_one()

        # First run completes
        run1 = IngestionRun(
            user_id=user.id,
            source_id=source_id,
            operation_type="cloud_sync",
            trigger_type="startup",
            idempotency_key=None,
            status="completed",
        )
        db.add(run1)

        # Second run for same user/source with null key — must not raise
        run2 = IngestionRun(
            user_id=user.id,
            source_id=source_id,
            operation_type="cloud_sync",
            trigger_type="scheduled",
            idempotency_key=None,
            status="running",
        )
        db.add(run2)
        await db.flush()

        r1 = await db.get(IngestionRun, run1.id)
        r2 = await db.get(IngestionRun, run2.id)
        assert r1 is not None
        assert r2 is not None
        assert r1.id != r2.id


# ── C. SourceCursor semantics ─────────────────────────────────────────────────


class TestSourceCursorB3:
    async def test_cursor_initial_creation(self, db: AsyncSession, user: User):
        """SourceCursor is created with the correct date and linked run on first insert."""
        result = await db.execute(
            select(DataSource.id).where(DataSource.slug == "garmin_connect")
        )
        source_id = result.scalar_one()
        run = await _make_garmin_run(db, user)
        run.status = "completed"
        run.finished_at = datetime.now(UTC)

        today = date(2026, 4, 17)
        cursor = SourceCursor(
            user_id=user.id,
            source_id=source_id,
            cursor_name="daily_summary",
            cursor_scope_key="",
            cursor_value_json={"date": today.isoformat()},
            last_successful_run_id=run.id,
            last_advanced_at=datetime.now(UTC),
        )
        db.add(cursor)
        await db.flush()

        saved = await db.scalar(
            select(SourceCursor).where(
                SourceCursor.user_id == user.id,
                SourceCursor.cursor_name == "daily_summary",
            )
        )
        assert saved is not None
        assert saved.cursor_value_json == {"date": "2026-04-17"}
        assert saved.last_successful_run_id == run.id

    async def test_cursor_date_advances(self, db: AsyncSession, user: User):
        """Updating the cursor advances cursor_value_json to the new date."""
        result = await db.execute(
            select(DataSource.id).where(DataSource.slug == "garmin_connect")
        )
        source_id = result.scalar_one()
        run1 = await _make_garmin_run(db, user)
        run2 = await _make_garmin_run(db, user)

        cursor = SourceCursor(
            user_id=user.id,
            source_id=source_id,
            cursor_name="daily_summary",
            cursor_scope_key="",
            cursor_value_json={"date": "2026-04-16"},
            last_successful_run_id=run1.id,
            last_advanced_at=datetime.now(UTC),
        )
        db.add(cursor)
        await db.flush()

        # Advance to next day
        cursor.cursor_value_json = {"date": "2026-04-17"}
        cursor.last_successful_run_id = run2.id
        cursor.last_advanced_at = datetime.now(UTC)
        cursor.updated_at = datetime.now(UTC)
        await db.flush()

        saved = await db.scalar(
            select(SourceCursor).where(SourceCursor.id == cursor.id)
        )
        assert saved.cursor_value_json["date"] == "2026-04-17"
        assert saved.last_successful_run_id == run2.id

    async def test_cursor_scope_key_default_is_empty_string(
        self, db: AsyncSession, user: User
    ):
        """Garmin daily_summary cursor uses cursor_scope_key='' (not NULL)."""
        result = await db.execute(
            select(DataSource.id).where(DataSource.slug == "garmin_connect")
        )
        source_id = result.scalar_one()

        cursor = SourceCursor(
            user_id=user.id,
            source_id=source_id,
            cursor_name="daily_summary",
            cursor_value_json={"date": "2026-04-17"},
        )
        db.add(cursor)
        await db.flush()

        saved = await db.get(SourceCursor, cursor.id)
        assert saved.cursor_scope_key == ""
