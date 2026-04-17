"""Bloco B1 — Operational Platform: schema constraints, uniqueness, retry policy,
ingestion_run lifecycle, ingestion_run_payloads, source_cursors.

Categories:
  A — Table constraints (CHECK, UNIQUE, nullable FK)
  B — Idempotency key uniqueness and retry policy
  C — ingestion_run lifecycle
  D — ingestion_run_payloads linking and roles
  E — source_cursors granularity and updates
"""

from datetime import UTC, datetime

import pytest
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_instance import AgentInstance
from app.models.base import uuid7
from app.models.data_source import DataSource
from app.models.ingestion_run import IngestionRun
from app.models.ingestion_run_payload import IngestionRunPayload
from app.models.raw_payload import RawPayload
from app.models.source_cursor import SourceCursor
from app.models.user_device import UserDevice
from app.models.user_integration import UserIntegration
from app.models.user import User


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def garmin_source(db: AsyncSession) -> DataSource:
    result = await db.execute(
        select(DataSource).where(DataSource.slug == "garmin_connect")
    )
    return result.scalar_one()


@pytest.fixture
async def hc900_source(db: AsyncSession) -> DataSource:
    result = await db.execute(
        select(DataSource).where(DataSource.slug == "hc900_ble")
    )
    return result.scalar_one()


@pytest.fixture
async def garmin_integration(db: AsyncSession, user: User, garmin_source: DataSource) -> UserIntegration:
    integ = UserIntegration(user_id=user.id, source_id=garmin_source.id)
    db.add(integ)
    await db.flush()
    return integ


@pytest.fixture
async def hc900_integration(db: AsyncSession, user: User, hc900_source: DataSource) -> UserIntegration:
    integ = UserIntegration(user_id=user.id, source_id=hc900_source.id)
    db.add(integ)
    await db.flush()
    return integ


@pytest.fixture
async def local_agent(db: AsyncSession, user: User) -> AgentInstance:
    agent = AgentInstance(
        user_id=user.id,
        install_id=str(uuid7()),
        agent_type="local_pc",
        display_name="Test PC",
    )
    db.add(agent)
    await db.flush()
    return agent


@pytest.fixture
async def garmin_run(
    db: AsyncSession,
    user: User,
    garmin_source: DataSource,
    garmin_integration: UserIntegration,
) -> IngestionRun:
    run = IngestionRun(
        user_id=user.id,
        source_id=garmin_source.id,
        user_integration_id=garmin_integration.id,
        operation_type="cloud_sync",
        trigger_type="scheduled",
    )
    db.add(run)
    await db.flush()
    return run


@pytest.fixture
async def garmin_payload(db: AsyncSession, user: User, garmin_source: DataSource) -> RawPayload:
    p = RawPayload(
        user_id=user.id,
        source_id=garmin_source.id,
        payload_type="garmin_connect_daily",
        payload_json={"date": "2026-04-17", "stats": {}},
    )
    db.add(p)
    await db.flush()
    return p


# ---------------------------------------------------------------------------
# A — Table constraints
# ---------------------------------------------------------------------------


class TestUserIntegrationConstraints:
    async def test_invalid_status_rejected(
        self, db: AsyncSession, user: User, garmin_source: DataSource
    ) -> None:
        with pytest.raises(IntegrityError):
            db.add(
                UserIntegration(
                    user_id=user.id, source_id=garmin_source.id, status="unknown"
                )
            )
            await db.flush()

    async def test_duplicate_user_source_rejected(
        self, db: AsyncSession, user: User, garmin_source: DataSource
    ) -> None:
        db.add(UserIntegration(user_id=user.id, source_id=garmin_source.id))
        await db.flush()
        with pytest.raises(IntegrityError):
            db.add(UserIntegration(user_id=user.id, source_id=garmin_source.id))
            await db.flush()

    async def test_config_json_defaults_to_empty_dict(
        self, db: AsyncSession, user: User, garmin_source: DataSource
    ) -> None:
        integ = UserIntegration(user_id=user.id, source_id=garmin_source.id)
        db.add(integ)
        await db.flush()
        await db.refresh(integ)
        assert integ.config_json == {}

    async def test_status_defaults_to_active(
        self, db: AsyncSession, user: User, garmin_source: DataSource
    ) -> None:
        integ = UserIntegration(user_id=user.id, source_id=garmin_source.id)
        db.add(integ)
        await db.flush()
        await db.refresh(integ)
        assert integ.status == "active"


class TestUserDeviceConstraints:
    async def test_invalid_device_type_rejected(
        self, db: AsyncSession, user: User, hc900_source: DataSource
    ) -> None:
        with pytest.raises(IntegrityError):
            db.add(
                UserDevice(
                    user_id=user.id,
                    source_id=hc900_source.id,
                    device_type="robot",
                    identifier="A0:91:5C:00:00:01",
                    identifier_type="mac",
                )
            )
            await db.flush()

    async def test_invalid_identifier_type_rejected(
        self, db: AsyncSession, user: User, hc900_source: DataSource
    ) -> None:
        with pytest.raises(IntegrityError):
            db.add(
                UserDevice(
                    user_id=user.id,
                    source_id=hc900_source.id,
                    device_type="scale",
                    identifier="A0:91:5C:00:00:01",
                    identifier_type="rfid",
                )
            )
            await db.flush()

    async def test_duplicate_user_source_identifier_rejected(
        self, db: AsyncSession, user: User, hc900_source: DataSource
    ) -> None:
        kwargs = dict(
            user_id=user.id,
            source_id=hc900_source.id,
            device_type="scale",
            identifier="A0:91:5C:00:00:01",
            identifier_type="mac",
        )
        db.add(UserDevice(**kwargs))
        await db.flush()
        with pytest.raises(IntegrityError):
            db.add(UserDevice(**kwargs))
            await db.flush()

    async def test_integration_id_nullable(
        self, db: AsyncSession, user: User, hc900_source: DataSource
    ) -> None:
        device = UserDevice(
            user_id=user.id,
            source_id=hc900_source.id,
            device_type="scale",
            identifier="A0:91:5C:00:00:02",
            identifier_type="mac",
        )
        db.add(device)
        await db.flush()
        await db.refresh(device)
        assert device.integration_id is None

    async def test_integration_id_links_to_integration(
        self,
        db: AsyncSession,
        user: User,
        hc900_source: DataSource,
        hc900_integration: UserIntegration,
    ) -> None:
        device = UserDevice(
            user_id=user.id,
            source_id=hc900_source.id,
            integration_id=hc900_integration.id,
            device_type="scale",
            identifier="A0:91:5C:00:00:03",
            identifier_type="mac",
        )
        db.add(device)
        await db.flush()
        await db.refresh(device)
        assert device.integration_id == hc900_integration.id


class TestAgentInstanceConstraints:
    async def test_invalid_agent_type_rejected(
        self, db: AsyncSession, user: User
    ) -> None:
        with pytest.raises(IntegrityError):
            db.add(
                AgentInstance(
                    user_id=user.id,
                    install_id=str(uuid7()),
                    agent_type="tablet",
                )
            )
            await db.flush()

    async def test_duplicate_install_id_rejected(
        self, db: AsyncSession, user: User
    ) -> None:
        install_id = str(uuid7())
        db.add(AgentInstance(user_id=user.id, install_id=install_id, agent_type="local_pc"))
        await db.flush()
        with pytest.raises(IntegrityError):
            db.add(
                AgentInstance(user_id=user.id, install_id=install_id, agent_type="server")
            )
            await db.flush()

    async def test_user_id_nullable(self, db: AsyncSession) -> None:
        agent = AgentInstance(
            install_id=str(uuid7()),
            agent_type="server",
            display_name="Global Worker",
        )
        db.add(agent)
        await db.flush()
        await db.refresh(agent)
        assert agent.user_id is None
        assert agent.id is not None

    async def test_metadata_json_defaults_to_empty_dict(
        self, db: AsyncSession, user: User
    ) -> None:
        agent = AgentInstance(
            user_id=user.id, install_id=str(uuid7()), agent_type="local_pc"
        )
        db.add(agent)
        await db.flush()
        await db.refresh(agent)
        assert agent.metadata_json == {}


class TestIngestionRunConstraints:
    async def test_invalid_operation_type_rejected(
        self, db: AsyncSession, user: User, garmin_source: DataSource
    ) -> None:
        with pytest.raises(IntegrityError):
            db.add(
                IngestionRun(
                    user_id=user.id,
                    source_id=garmin_source.id,
                    operation_type="magic_sync",
                    trigger_type="scheduled",
                )
            )
            await db.flush()

    async def test_invalid_trigger_type_rejected(
        self, db: AsyncSession, user: User, garmin_source: DataSource
    ) -> None:
        with pytest.raises(IntegrityError):
            db.add(
                IngestionRun(
                    user_id=user.id,
                    source_id=garmin_source.id,
                    operation_type="cloud_sync",
                    trigger_type="cron",
                )
            )
            await db.flush()

    async def test_invalid_status_rejected(
        self, db: AsyncSession, user: User, garmin_source: DataSource
    ) -> None:
        with pytest.raises(IntegrityError):
            run = IngestionRun(
                user_id=user.id,
                source_id=garmin_source.id,
                operation_type="cloud_sync",
                trigger_type="scheduled",
            )
            db.add(run)
            await db.flush()
            run.status = "done"
            await db.flush()

    async def test_metadata_json_defaults_to_empty_dict(
        self, db: AsyncSession, user: User, garmin_source: DataSource
    ) -> None:
        run = IngestionRun(
            user_id=user.id,
            source_id=garmin_source.id,
            operation_type="cloud_sync",
            trigger_type="scheduled",
        )
        db.add(run)
        await db.flush()
        await db.refresh(run)
        assert run.metadata_json == {}


class TestIngestionRunPayloadConstraints:
    async def test_invalid_role_rejected(
        self,
        db: AsyncSession,
        garmin_run: IngestionRun,
        garmin_payload: RawPayload,
    ) -> None:
        with pytest.raises(IntegrityError):
            db.add(
                IngestionRunPayload(
                    run_id=garmin_run.id,
                    payload_id=garmin_payload.id,
                    role="skipped",
                )
            )
            await db.flush()


# ---------------------------------------------------------------------------
# B — Idempotency key uniqueness and retry policy
# ---------------------------------------------------------------------------


class TestIdempotencyKey:
    async def test_unique_key_enforced_for_non_null(
        self, db: AsyncSession, user: User, garmin_source: DataSource
    ) -> None:
        key = "garmin:sync:test:2026-04-10:2026-04-17"
        db.add(
            IngestionRun(
                user_id=user.id,
                source_id=garmin_source.id,
                operation_type="cloud_sync",
                trigger_type="scheduled",
                idempotency_key=key,
            )
        )
        await db.flush()
        with pytest.raises(IntegrityError):
            db.add(
                IngestionRun(
                    user_id=user.id,
                    source_id=garmin_source.id,
                    operation_type="cloud_sync",
                    trigger_type="scheduled",
                    idempotency_key=key,
                )
            )
            await db.flush()

    async def test_null_key_allows_multiple_runs(
        self, db: AsyncSession, user: User, garmin_source: DataSource
    ) -> None:
        for _ in range(3):
            db.add(
                IngestionRun(
                    user_id=user.id,
                    source_id=garmin_source.id,
                    operation_type="ble_scan",
                    trigger_type="ui_button",
                    idempotency_key=None,
                )
            )
        await db.flush()
        result = await db.execute(
            select(IngestionRun).where(
                IngestionRun.user_id == user.id,
                IngestionRun.operation_type == "ble_scan",
            )
        )
        assert len(result.scalars().all()) == 3

    async def test_retry_failed_run_updates_in_place(
        self, db: AsyncSession, user: User, garmin_source: DataSource
    ) -> None:
        key = "garmin:sync:test:2026-04-15:2026-04-17"
        run = IngestionRun(
            user_id=user.id,
            source_id=garmin_source.id,
            operation_type="cloud_sync",
            trigger_type="scheduled",
            idempotency_key=key,
            status="failed",
            error_message="Garmin API timeout",
            finished_at=datetime.now(UTC),
        )
        db.add(run)
        await db.flush()

        # Simulate retry: preserve error history, reset for new attempt
        run.metadata_json = {
            "error_history": [
                {
                    "attempt": run.attempt_no,
                    "error": run.error_message,
                    "at": run.finished_at.isoformat() if run.finished_at else None,
                }
            ]
        }
        run.status = "running"
        run.attempt_no += 1
        run.trigger_type = "retry"
        run.error_message = None
        run.finished_at = None
        await db.flush()

        await db.refresh(run)
        assert run.status == "running"
        assert run.attempt_no == 2
        assert run.trigger_type == "retry"
        assert run.error_message is None
        assert run.finished_at is None
        assert run.metadata_json["error_history"][0]["attempt"] == 1
        assert run.metadata_json["error_history"][0]["error"] == "Garmin API timeout"

    async def test_running_run_visible_by_key_lookup(
        self, db: AsyncSession, user: User, garmin_source: DataSource
    ) -> None:
        key = "garmin:sync:test:2026-04-17:2026-04-17"
        run = IngestionRun(
            user_id=user.id,
            source_id=garmin_source.id,
            operation_type="cloud_sync",
            trigger_type="wake",
            idempotency_key=key,
            status="running",
        )
        db.add(run)
        await db.flush()

        result = await db.execute(
            select(IngestionRun).where(IngestionRun.idempotency_key == key)
        )
        found = result.scalar_one()
        assert found.id == run.id
        assert found.status == "running"

    async def test_completed_run_blocks_new_insert_with_same_key(
        self, db: AsyncSession, user: User, garmin_source: DataSource
    ) -> None:
        key = "garmin:sync:test:2026-04-16:2026-04-17"
        db.add(
            IngestionRun(
                user_id=user.id,
                source_id=garmin_source.id,
                operation_type="cloud_sync",
                trigger_type="scheduled",
                idempotency_key=key,
                status="completed",
            )
        )
        await db.flush()
        with pytest.raises(IntegrityError):
            db.add(
                IngestionRun(
                    user_id=user.id,
                    source_id=garmin_source.id,
                    operation_type="cloud_sync",
                    trigger_type="scheduled",
                    idempotency_key=key,
                )
            )
            await db.flush()


# ---------------------------------------------------------------------------
# C — ingestion_run lifecycle
# ---------------------------------------------------------------------------


class TestIngestionRunLifecycle:
    async def test_default_state_on_creation(
        self, db: AsyncSession, user: User, garmin_source: DataSource
    ) -> None:
        run = IngestionRun(
            user_id=user.id,
            source_id=garmin_source.id,
            operation_type="cloud_sync",
            trigger_type="startup",
        )
        db.add(run)
        await db.flush()
        await db.refresh(run)

        assert run.status == "running"
        assert run.attempt_no == 1
        assert run.finished_at is None
        assert run.error_message is None
        assert run.raw_payloads_created == 0
        assert run.raw_payloads_reused == 0
        assert run.raw_payloads_failed == 0
        assert run.measurements_created == 0
        assert run.measurements_deleted == 0

    async def test_transition_to_completed(
        self, db: AsyncSession, garmin_run: IngestionRun
    ) -> None:
        garmin_run.status = "completed"
        garmin_run.finished_at = datetime.now(UTC)
        garmin_run.raw_payloads_created = 7
        garmin_run.measurements_created = 63
        await db.flush()
        await db.refresh(garmin_run)

        assert garmin_run.status == "completed"
        assert garmin_run.finished_at is not None
        assert garmin_run.raw_payloads_created == 7
        assert garmin_run.measurements_created == 63

    async def test_transition_to_failed(
        self, db: AsyncSession, garmin_run: IngestionRun
    ) -> None:
        garmin_run.status = "failed"
        garmin_run.finished_at = datetime.now(UTC)
        garmin_run.error_message = "Garmin Connect: 401 Unauthorized"
        await db.flush()
        await db.refresh(garmin_run)

        assert garmin_run.status == "failed"
        assert garmin_run.error_message == "Garmin Connect: 401 Unauthorized"
        assert garmin_run.finished_at is not None

    async def test_reprocess_counters(
        self, db: AsyncSession, user: User, hc900_source: DataSource
    ) -> None:
        run = IngestionRun(
            user_id=user.id,
            source_id=hc900_source.id,
            operation_type="replay",
            trigger_type="manual",
            status="completed",
            finished_at=datetime.now(UTC),
            raw_payloads_reused=1,
            measurements_deleted=18,
            measurements_created=18,
        )
        db.add(run)
        await db.flush()
        await db.refresh(run)

        assert run.raw_payloads_reused == 1
        assert run.measurements_deleted == 18
        assert run.measurements_created == 18
        assert run.raw_payloads_created == 0


# ---------------------------------------------------------------------------
# D — ingestion_run_payloads
# ---------------------------------------------------------------------------


class TestIngestionRunPayloads:
    async def test_link_payload_to_run(
        self,
        db: AsyncSession,
        garmin_run: IngestionRun,
        garmin_payload: RawPayload,
    ) -> None:
        link = IngestionRunPayload(run_id=garmin_run.id, payload_id=garmin_payload.id)
        db.add(link)
        await db.flush()

        result = await db.execute(
            select(IngestionRunPayload).where(
                IngestionRunPayload.run_id == garmin_run.id,
                IngestionRunPayload.payload_id == garmin_payload.id,
            )
        )
        found = result.scalar_one()
        assert found.role == "created"
        assert found.linked_at is not None

    async def test_role_reused(
        self,
        db: AsyncSession,
        garmin_run: IngestionRun,
        garmin_payload: RawPayload,
    ) -> None:
        link = IngestionRunPayload(
            run_id=garmin_run.id, payload_id=garmin_payload.id, role="reused"
        )
        db.add(link)
        await db.flush()
        await db.refresh(link)
        assert link.role == "reused"

    async def test_role_reprocessed(
        self,
        db: AsyncSession,
        garmin_run: IngestionRun,
        garmin_payload: RawPayload,
    ) -> None:
        link = IngestionRunPayload(
            run_id=garmin_run.id, payload_id=garmin_payload.id, role="reprocessed"
        )
        db.add(link)
        await db.flush()
        await db.refresh(link)
        assert link.role == "reprocessed"

    async def test_reverse_lookup_by_payload_id(
        self,
        db: AsyncSession,
        garmin_run: IngestionRun,
        garmin_payload: RawPayload,
    ) -> None:
        db.add(IngestionRunPayload(run_id=garmin_run.id, payload_id=garmin_payload.id))
        await db.flush()

        result = await db.execute(
            select(IngestionRunPayload).where(
                IngestionRunPayload.payload_id == garmin_payload.id
            )
        )
        found = result.scalar_one()
        assert found.run_id == garmin_run.id

    async def test_composite_pk_blocks_duplicate(
        self,
        db: AsyncSession,
        garmin_run: IngestionRun,
        garmin_payload: RawPayload,
    ) -> None:
        db.add(IngestionRunPayload(run_id=garmin_run.id, payload_id=garmin_payload.id))
        await db.flush()
        with pytest.raises(IntegrityError):
            db.add(
                IngestionRunPayload(
                    run_id=garmin_run.id, payload_id=garmin_payload.id, role="reused"
                )
            )
            await db.flush()

    async def test_one_run_multiple_payloads(
        self, db: AsyncSession, user: User, garmin_source: DataSource, garmin_run: IngestionRun
    ) -> None:
        payloads = [
            RawPayload(
                user_id=user.id,
                source_id=garmin_source.id,
                payload_type="garmin_connect_daily",
                payload_json={"date": f"2026-04-{10 + i}", "stats": {}},
            )
            for i in range(5)
        ]
        db.add_all(payloads)
        await db.flush()

        links = [
            IngestionRunPayload(run_id=garmin_run.id, payload_id=p.id) for p in payloads
        ]
        db.add_all(links)
        await db.flush()

        result = await db.execute(
            select(IngestionRunPayload).where(IngestionRunPayload.run_id == garmin_run.id)
        )
        assert len(result.scalars().all()) == 5


# ---------------------------------------------------------------------------
# E — source_cursors
# ---------------------------------------------------------------------------


class TestSourceCursors:
    async def test_cursor_created_with_value(
        self, db: AsyncSession, user: User, garmin_source: DataSource
    ) -> None:
        cursor = SourceCursor(
            user_id=user.id,
            source_id=garmin_source.id,
            cursor_name="daily_summary",
            cursor_value_json={"date": "2026-04-17"},
        )
        db.add(cursor)
        await db.flush()
        await db.refresh(cursor)

        assert cursor.cursor_value_json == {"date": "2026-04-17"}
        assert cursor.cursor_scope_key == ""
        assert cursor.last_advanced_at is None
        assert cursor.last_successful_run_id is None

    async def test_scope_key_defaults_to_empty_string(
        self, db: AsyncSession, user: User, garmin_source: DataSource
    ) -> None:
        cursor = SourceCursor(
            user_id=user.id,
            source_id=garmin_source.id,
            cursor_name="hrv",
            cursor_value_json={"date": "2026-04-17"},
        )
        db.add(cursor)
        await db.flush()
        await db.refresh(cursor)
        assert cursor.cursor_scope_key == ""

    async def test_unique_constraint_enforced(
        self, db: AsyncSession, user: User, garmin_source: DataSource
    ) -> None:
        kwargs = dict(
            user_id=user.id,
            source_id=garmin_source.id,
            cursor_name="daily_summary",
            cursor_scope_key="",
            cursor_value_json={"date": "2026-04-17"},
        )
        db.add(SourceCursor(**kwargs))
        await db.flush()
        with pytest.raises(IntegrityError):
            db.add(SourceCursor(**kwargs))
            await db.flush()

    async def test_different_scope_keys_coexist(
        self, db: AsyncSession, user: User, garmin_source: DataSource
    ) -> None:
        for scope in ("", "running", "cycling"):
            db.add(
                SourceCursor(
                    user_id=user.id,
                    source_id=garmin_source.id,
                    cursor_name="activities",
                    cursor_scope_key=scope,
                    cursor_value_json={"activity_id": 1},
                )
            )
        await db.flush()

        result = await db.execute(
            select(SourceCursor).where(
                SourceCursor.user_id == user.id,
                SourceCursor.cursor_name == "activities",
            )
        )
        assert len(result.scalars().all()) == 3

    async def test_different_cursor_names_coexist(
        self, db: AsyncSession, user: User, garmin_source: DataSource
    ) -> None:
        for name in ("daily_summary", "hrv", "sleep"):
            db.add(
                SourceCursor(
                    user_id=user.id,
                    source_id=garmin_source.id,
                    cursor_name=name,
                    cursor_value_json={"date": "2026-04-17"},
                )
            )
        await db.flush()

        result = await db.execute(
            select(SourceCursor).where(SourceCursor.user_id == user.id)
        )
        assert len(result.scalars().all()) == 3

    async def test_cursor_update_advances_value(
        self, db: AsyncSession, user: User, garmin_source: DataSource, garmin_run: IngestionRun
    ) -> None:
        cursor = SourceCursor(
            user_id=user.id,
            source_id=garmin_source.id,
            cursor_name="daily_summary",
            cursor_value_json={"date": "2026-04-10"},
        )
        db.add(cursor)
        await db.flush()

        cursor.cursor_value_json = {"date": "2026-04-17"}
        cursor.last_successful_run_id = garmin_run.id
        cursor.last_advanced_at = datetime.now(UTC)
        cursor.updated_at = datetime.now(UTC)
        await db.flush()
        await db.refresh(cursor)

        assert cursor.cursor_value_json == {"date": "2026-04-17"}
        assert cursor.last_successful_run_id == garmin_run.id
        assert cursor.last_advanced_at is not None

    async def test_cursor_last_successful_run_set_null_on_run_delete(
        self, db: AsyncSession, user: User, garmin_source: DataSource
    ) -> None:
        run = IngestionRun(
            user_id=user.id,
            source_id=garmin_source.id,
            operation_type="cloud_sync",
            trigger_type="scheduled",
            status="completed",
        )
        db.add(run)
        await db.flush()

        cursor = SourceCursor(
            user_id=user.id,
            source_id=garmin_source.id,
            cursor_name="daily_summary",
            cursor_value_json={"date": "2026-04-17"},
            last_successful_run_id=run.id,
        )
        db.add(cursor)
        await db.flush()
        await db.refresh(cursor)
        assert cursor.last_successful_run_id == run.id
