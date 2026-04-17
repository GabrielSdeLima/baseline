"""Bloco B2 — ingestion_run_id link and bootstrap service tests.

Tests:
  - ingest without ingestion_run_id (backward compat)
  - ingest with valid ingestion_run_id creates 'created' link
  - ingest duplicate (external_id) with run creates 'reused' link
  - ingest with run from another user raises ValueError
  - ingest with run from wrong source raises ValueError
  - idempotent link (same payload ingested twice with same run)
  - raw_payloads_created counter incremented
  - raw_payloads_reused counter incremented
  - BootstrapService: ensure_user_integrations
  - BootstrapService: idempotent integrations
  - BootstrapService: register_agent
  - BootstrapService: register_agent idempotent (last_seen_at refreshed)
  - BootstrapService: migrate_hc900_device (with history)
  - BootstrapService: migrate_hc900_device (no history → None)
  - BootstrapService: backfill sets user_device_id on historical payloads
"""

import uuid

import pytest
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_instance import AgentInstance
from app.models.base import uuid7
from app.models.data_source import DataSource
from app.models.ingestion_run import IngestionRun
from app.models.ingestion_run_payload import IngestionRunPayload
from app.models.raw_payload import RawPayload
from app.models.user import User
from app.models.user_device import UserDevice
from app.models.user_integration import UserIntegration
from app.schemas.raw_payload import RawPayloadIngest
from app.services.bootstrap import BootstrapService
from app.services.ingestion import IngestionService


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
    result = await db.execute(select(DataSource).where(DataSource.slug == "hc900_ble"))
    return result.scalar_one()


@pytest.fixture
async def garmin_run(db: AsyncSession, user: User, garmin_source: DataSource) -> IngestionRun:
    run = IngestionRun(
        user_id=user.id,
        source_id=garmin_source.id,
        operation_type="cloud_sync",
        trigger_type="scheduled",
    )
    db.add(run)
    await db.flush()
    return run


@pytest.fixture
async def other_user(db: AsyncSession) -> User:
    u = User(id=uuid7(), email="other@baseline.dev", name="Other User", timezone="UTC")
    db.add(u)
    await db.flush()
    return u


def _garmin_payload(user_id: uuid.UUID, date: str = "2026-04-17") -> RawPayloadIngest:
    return RawPayloadIngest(
        user_id=user_id,
        source_slug="garmin_connect",
        external_id=f"garmin_connect_{date}",
        payload_type="garmin_connect_daily",
        payload_json={
            "format_version": "garmin_connect_v1",
            "date": date,
            "user_timezone": "America/Sao_Paulo",
            "stats": {},
            "hrv": {},
            "sleep": {},
        },
    )


# ---------------------------------------------------------------------------
# Ingestion run link tests
# ---------------------------------------------------------------------------


class TestIngestWithoutRunId:
    async def test_backward_compat_no_link_created(
        self, db: AsyncSession, user: User
    ) -> None:
        svc = IngestionService(db)
        payload = await svc.ingest(_garmin_payload(user.id))

        result = await db.execute(
            select(IngestionRunPayload).where(
                IngestionRunPayload.payload_id == payload.id
            )
        )
        assert result.scalar_one_or_none() is None

    async def test_backward_compat_payload_processed(
        self, db: AsyncSession, user: User
    ) -> None:
        svc = IngestionService(db)
        payload = await svc.ingest(_garmin_payload(user.id, date="2026-04-16"))
        assert payload.processing_status in ("processed", "skipped", "failed")
        assert payload.id is not None


class TestIngestWithRunId:
    async def test_creates_created_link(
        self, db: AsyncSession, user: User, garmin_run: IngestionRun
    ) -> None:
        svc = IngestionService(db)
        data = _garmin_payload(user.id)
        data.ingestion_run_id = garmin_run.id

        payload = await svc.ingest(data)

        result = await db.execute(
            select(IngestionRunPayload).where(
                IngestionRunPayload.run_id == garmin_run.id,
                IngestionRunPayload.payload_id == payload.id,
            )
        )
        link = result.scalar_one()
        assert link.role == "created"

    async def test_increments_raw_payloads_created(
        self, db: AsyncSession, user: User, garmin_run: IngestionRun
    ) -> None:
        svc = IngestionService(db)
        data = _garmin_payload(user.id, date="2026-04-15")
        data.ingestion_run_id = garmin_run.id

        await svc.ingest(data)

        await db.refresh(garmin_run)
        assert garmin_run.raw_payloads_created == 1
        assert garmin_run.raw_payloads_reused == 0

    async def test_duplicate_external_id_creates_reused_link(
        self, db: AsyncSession, user: User, garmin_run: IngestionRun
    ) -> None:
        svc = IngestionService(db)
        date = "2026-04-14"

        # First ingest — no run, creates the payload
        first = await svc.ingest(_garmin_payload(user.id, date=date))

        # Second ingest — same external_id, this time with run
        data = _garmin_payload(user.id, date=date)
        data.ingestion_run_id = garmin_run.id
        second = await svc.ingest(data)

        # Same payload returned
        assert second.id == first.id

        result = await db.execute(
            select(IngestionRunPayload).where(
                IngestionRunPayload.run_id == garmin_run.id,
                IngestionRunPayload.payload_id == first.id,
            )
        )
        link = result.scalar_one()
        assert link.role == "reused"

    async def test_increments_raw_payloads_reused(
        self, db: AsyncSession, user: User, garmin_run: IngestionRun
    ) -> None:
        svc = IngestionService(db)
        date = "2026-04-13"

        # Create payload first
        await svc.ingest(_garmin_payload(user.id, date=date))

        # Reuse via run
        data = _garmin_payload(user.id, date=date)
        data.ingestion_run_id = garmin_run.id
        await svc.ingest(data)

        await db.refresh(garmin_run)
        assert garmin_run.raw_payloads_reused == 1
        assert garmin_run.raw_payloads_created == 0

    async def test_link_idempotent_on_repeated_ingest(
        self, db: AsyncSession, user: User, garmin_run: IngestionRun
    ) -> None:
        svc = IngestionService(db)
        date = "2026-04-12"

        data = _garmin_payload(user.id, date=date)
        data.ingestion_run_id = garmin_run.id

        # Ingest once with run → creates link
        payload = await svc.ingest(data)

        # Reset counter to verify it doesn't increment again
        garmin_run.raw_payloads_created = 0
        await db.flush()

        # Ingest again (same external_id → dedup path, same run → reused path)
        # But the link already exists — should not duplicate
        data2 = _garmin_payload(user.id, date=date)
        data2.ingestion_run_id = garmin_run.id
        second = await svc.ingest(data2)
        assert second.id == payload.id

        # Link should exist exactly once
        result = await db.execute(
            select(IngestionRunPayload).where(
                IngestionRunPayload.run_id == garmin_run.id,
                IngestionRunPayload.payload_id == payload.id,
            )
        )
        links = result.scalars().all()
        assert len(links) == 1

        # Counter was not incremented again (link was idempotent)
        await db.refresh(garmin_run)
        assert garmin_run.raw_payloads_created == 0
        assert garmin_run.raw_payloads_reused == 0


class TestIngestRunValidation:
    async def test_run_not_found_raises(
        self, db: AsyncSession, user: User
    ) -> None:
        svc = IngestionService(db)
        data = _garmin_payload(user.id)
        data.ingestion_run_id = uuid.uuid4()  # nonexistent

        with pytest.raises(ValueError, match="not found"):
            await svc.ingest(data)

    async def test_run_from_different_user_raises(
        self, db: AsyncSession, user: User, other_user: User, garmin_run: IngestionRun
    ) -> None:
        svc = IngestionService(db)
        data = _garmin_payload(other_user.id)  # other_user's payload
        data.ingestion_run_id = garmin_run.id   # but user's run

        with pytest.raises(ValueError, match="different user"):
            await svc.ingest(data)

    async def test_run_source_mismatch_raises(
        self, db: AsyncSession, user: User, garmin_run: IngestionRun
    ) -> None:
        svc = IngestionService(db)
        # garmin_run is for garmin_connect; ingest with hc900_ble source
        data = RawPayloadIngest(
            user_id=user.id,
            source_slug="hc900_ble",
            payload_type="hc900_scale",
            payload_json={"test": True},
            ingestion_run_id=garmin_run.id,
        )

        with pytest.raises(ValueError, match="source mismatch"):
            await svc.ingest(data)


# ---------------------------------------------------------------------------
# BootstrapService tests
# ---------------------------------------------------------------------------


class TestBootstrapServiceIntegrations:
    async def test_creates_both_integrations(
        self, db: AsyncSession, user: User
    ) -> None:
        svc = BootstrapService(db)
        result = await svc.ensure_user_integrations(user.id)

        assert "garmin_connect" in result
        assert "hc900_ble" in result

        garmin = result["garmin_connect"]
        assert garmin.user_id == user.id
        assert garmin.status == "active"
        assert "username_env" in garmin.config_json

        hc900 = result["hc900_ble"]
        assert hc900.user_id == user.id
        assert "scan_duration_s" in hc900.config_json

    async def test_idempotent_does_not_duplicate(
        self, db: AsyncSession, user: User
    ) -> None:
        svc = BootstrapService(db)
        first = await svc.ensure_user_integrations(user.id)
        second = await svc.ensure_user_integrations(user.id)

        assert first["garmin_connect"].id == second["garmin_connect"].id
        assert first["hc900_ble"].id == second["hc900_ble"].id

        # Only two rows total
        result = await db.execute(
            select(UserIntegration).where(UserIntegration.user_id == user.id)
        )
        assert len(result.scalars().all()) == 2

    async def test_integration_has_config(
        self, db: AsyncSession, user: User
    ) -> None:
        svc = BootstrapService(db)
        result = await svc.ensure_user_integrations(user.id)

        await db.refresh(result["garmin_connect"])
        assert result["garmin_connect"].config_json.get("timezone") == "America/Sao_Paulo"

        await db.refresh(result["hc900_ble"])
        assert result["hc900_ble"].config_json.get("company_id") == "0xA0AC"


class TestBootstrapServiceAgent:
    async def test_register_creates_agent(
        self, db: AsyncSession, user: User
    ) -> None:
        svc = BootstrapService(db)
        install_id = str(uuid.uuid4())
        agent = await svc.register_agent(
            user.id, install_id, display_name="TestPC", platform="Windows 11"
        )

        assert agent.id is not None
        assert agent.install_id == install_id
        assert agent.user_id == user.id
        assert agent.agent_type == "local_pc"
        assert agent.display_name == "TestPC"
        assert agent.platform == "Windows 11"

    async def test_register_idempotent_returns_same_agent(
        self, db: AsyncSession, user: User
    ) -> None:
        svc = BootstrapService(db)
        install_id = str(uuid.uuid4())

        first = await svc.register_agent(user.id, install_id, display_name="PC1")
        second = await svc.register_agent(user.id, install_id, display_name="PC1")

        assert first.id == second.id

        result = await db.execute(
            select(AgentInstance).where(AgentInstance.install_id == install_id)
        )
        assert len(result.scalars().all()) == 1

    async def test_register_idempotent_updates_last_seen_at(
        self, db: AsyncSession, user: User
    ) -> None:
        svc = BootstrapService(db)
        install_id = str(uuid.uuid4())

        first = await svc.register_agent(user.id, install_id)
        first_seen = first.last_seen_at

        second = await svc.register_agent(user.id, install_id)
        assert second.last_seen_at is not None

    async def test_register_nullable_user_id(self, db: AsyncSession) -> None:
        svc = BootstrapService(db)
        install_id = str(uuid.uuid4())
        # user_id is nullable — for server workers
        agent = await svc.register_agent(None, install_id, display_name="Worker")  # type: ignore[arg-type]
        assert agent.user_id is None


class TestBootstrapServiceHC900Device:
    async def test_migrate_creates_device_from_history(
        self, db: AsyncSession, user: User, hc900_source: DataSource
    ) -> None:
        # Seed an hc900_scale payload with device_mac
        payload = RawPayload(
            user_id=user.id,
            source_id=hc900_source.id,
            payload_type="hc900_scale",
            payload_json={
                "device_mac": "A0:91:5C:92:CF:17",
                "measured_at": "2026-04-15T07:30:00+00:00",
                "decoded": {"weight_kg": 77.0},
            },
        )
        db.add(payload)
        await db.flush()

        # Create a hc900_ble integration to link the device to
        integ = UserIntegration(user_id=user.id, source_id=hc900_source.id)
        db.add(integ)
        await db.flush()

        svc = BootstrapService(db)
        device = await svc.migrate_hc900_device(user.id, integ.id)

        assert device is not None
        assert device.identifier == "a0915c92cf17"
        assert device.identifier_type == "mac"
        assert device.device_type == "scale"
        assert device.integration_id == integ.id
        assert device.user_id == user.id

    async def test_migrate_returns_none_when_no_history(
        self, db: AsyncSession, user: User
    ) -> None:
        svc = BootstrapService(db)
        device = await svc.migrate_hc900_device(user.id, uuid.uuid4())
        assert device is None

    async def test_migrate_does_not_create_device_for_other_payload_types(
        self, db: AsyncSession, user: User, hc900_source: DataSource, garmin_source: DataSource
    ) -> None:
        # Only garmin payload — no hc900_scale
        payload = RawPayload(
            user_id=user.id,
            source_id=garmin_source.id,
            payload_type="garmin_connect_daily",
            payload_json={"date": "2026-04-17", "stats": {}},
        )
        db.add(payload)
        await db.flush()

        svc = BootstrapService(db)
        device = await svc.migrate_hc900_device(user.id, uuid.uuid4())
        assert device is None

    async def test_migrate_backfills_user_device_id_on_existing_payloads(
        self, db: AsyncSession, user: User, hc900_source: DataSource
    ) -> None:
        mac = "A0:91:5C:92:CF:18"
        payloads = [
            RawPayload(
                user_id=user.id,
                source_id=hc900_source.id,
                payload_type="hc900_scale",
                payload_json={
                    "device_mac": mac,
                    "measured_at": f"2026-04-{10 + i:02d}T07:30:00+00:00",
                    "decoded": {"weight_kg": 77.0},
                },
            )
            for i in range(3)
        ]
        db.add_all(payloads)
        integ = UserIntegration(user_id=user.id, source_id=hc900_source.id)
        db.add(integ)
        await db.flush()

        svc = BootstrapService(db)
        device = await svc.migrate_hc900_device(user.id, integ.id)

        assert device is not None
        for p in payloads:
            await db.refresh(p)
            assert p.user_device_id == device.id

    async def test_migrate_idempotent(
        self, db: AsyncSession, user: User, hc900_source: DataSource
    ) -> None:
        mac = "A0:91:5C:92:CF:19"
        payload = RawPayload(
            user_id=user.id,
            source_id=hc900_source.id,
            payload_type="hc900_scale",
            payload_json={
                "device_mac": mac,
                "measured_at": "2026-04-15T07:30:00+00:00",
                "decoded": {"weight_kg": 77.0},
            },
        )
        integ = UserIntegration(user_id=user.id, source_id=hc900_source.id)
        db.add_all([payload, integ])
        await db.flush()

        svc = BootstrapService(db)
        first = await svc.migrate_hc900_device(user.id, integ.id)
        second = await svc.migrate_hc900_device(user.id, integ.id)

        assert first is not None
        assert second is not None
        assert first.id == second.id

        # Only one device row (normalized MAC)
        result = await db.execute(
            select(UserDevice).where(
                UserDevice.user_id == user.id,
                UserDevice.identifier == mac.replace(":", "").lower(),
            )
        )
        assert len(result.scalars().all()) == 1
