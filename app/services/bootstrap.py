"""Operational bootstrap: create per-user integrations, register agents, migrate devices."""

import logging
import uuid
from datetime import UTC, datetime

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_instance import AgentInstance
from app.models.data_source import DataSource
from app.models.raw_payload import RawPayload
from app.models.user_device import UserDevice
from app.models.user_integration import UserIntegration

logger = logging.getLogger(__name__)

_INTEGRATION_CONFIGS: dict[str, dict] = {
    "garmin_connect": {
        "username_env": "GARMIN_USERNAME",
        "timezone": "America/Sao_Paulo",
    },
    "hc900_ble": {
        "scan_duration_s": 15,
        "company_id": "0xA0AC",
        "xor_keys": [44, 160, 160],
    },
}


class BootstrapService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    # ------------------------------------------------------------------ #
    # Public API                                                           #
    # ------------------------------------------------------------------ #

    async def ensure_user_integrations(
        self, user_id: uuid.UUID
    ) -> dict[str, UserIntegration]:
        """Create user_integrations for garmin_connect and hc900_ble if absent.

        Idempotent — returns existing row unchanged if already present.
        """
        results: dict[str, UserIntegration] = {}
        for slug, config in _INTEGRATION_CONFIGS.items():
            source = await self._get_source(slug)
            if source is None:
                logger.warning("Data source %r not found — skipping integration", slug)
                continue
            integ = await self._upsert_integration(user_id, source.id, config)
            results[slug] = integ
        return results

    async def register_agent(
        self,
        user_id: uuid.UUID,
        install_id: str,
        *,
        display_name: str = "",
        platform: str = "",
        agent_version: str = "",
    ) -> AgentInstance:
        """Register or refresh the local agent instance.

        Idempotent — if ``install_id`` already exists, updates last_seen_at.
        """
        result = await self.session.execute(
            select(AgentInstance).where(AgentInstance.install_id == install_id)
        )
        existing = result.scalar_one_or_none()

        if existing is not None:
            existing.last_seen_at = datetime.now(UTC)
            existing.updated_at = datetime.now(UTC)
            existing.is_active = True
            if display_name:
                existing.display_name = display_name
            if platform:
                existing.platform = platform
            if agent_version:
                existing.agent_version = agent_version
            await self.session.flush()
            return existing

        agent = AgentInstance(
            user_id=user_id,
            install_id=install_id,
            agent_type="local_pc",
            display_name=display_name,
            platform=platform,
            agent_version=agent_version,
        )
        self.session.add(agent)
        await self.session.flush()
        return agent

    async def migrate_hc900_device(
        self,
        user_id: uuid.UUID,
        integration_id: uuid.UUID,
    ) -> UserDevice | None:
        """Migrate the HC900 MAC address from raw_payloads history to user_devices.

        Finds the most recently ingested hc900_scale payload, extracts
        device_mac, and upserts a UserDevice row linked to the given
        integration.  Also back-fills user_device_id on all historical
        payloads from that MAC.

        Returns the UserDevice, or None when no HC900 history exists.
        """
        mac = await self._latest_hc900_mac(user_id)
        if mac is None:
            logger.info("No HC900 payloads found for user %s — skipping device migration", user_id)
            return None

        hc900_source = await self._get_source("hc900_ble")
        if hc900_source is None:
            raise ValueError("Data source 'hc900_ble' not found — run: alembic upgrade head")

        device = await self._upsert_device(user_id, hc900_source.id, integration_id, mac)
        await self._backfill_raw_payload_device_id(user_id, mac, device.id)
        return device

    # ------------------------------------------------------------------ #
    # Private helpers                                                      #
    # ------------------------------------------------------------------ #

    async def _get_source(self, slug: str) -> DataSource | None:
        result = await self.session.execute(
            select(DataSource).where(DataSource.slug == slug)
        )
        return result.scalar_one_or_none()

    async def _upsert_integration(
        self,
        user_id: uuid.UUID,
        source_id: int,
        config: dict,
    ) -> UserIntegration:
        result = await self.session.execute(
            select(UserIntegration).where(
                UserIntegration.user_id == user_id,
                UserIntegration.source_id == source_id,
            )
        )
        existing = result.scalar_one_or_none()
        if existing is not None:
            return existing

        integ = UserIntegration(
            user_id=user_id,
            source_id=source_id,
            config_json=config,
        )
        self.session.add(integ)
        await self.session.flush()
        return integ

    async def _upsert_device(
        self,
        user_id: uuid.UUID,
        source_id: int,
        integration_id: uuid.UUID,
        mac: str,
    ) -> UserDevice:
        # Normalize to lowercase no-colon form to match the scan_scale endpoint
        mac = mac.replace(":", "").lower()

        result = await self.session.execute(
            select(UserDevice).where(
                UserDevice.user_id == user_id,
                UserDevice.source_id == source_id,
                UserDevice.identifier == mac,
            )
        )
        existing = result.scalar_one_or_none()

        # Legacy: device may exist with un-normalized MAC (e.g. "A0:91:5C:92:CF:17")
        if existing is None:
            result = await self.session.execute(
                select(UserDevice).where(
                    UserDevice.user_id == user_id,
                    UserDevice.source_id == source_id,
                    UserDevice.identifier_type == "mac",
                )
            )
            for candidate in result.scalars():
                if candidate.identifier.replace(":", "").lower() == mac:
                    candidate.identifier = mac  # migrate to normalized form
                    existing = candidate
                    await self.session.flush()
                    break

        if existing is not None:
            if existing.integration_id is None:
                existing.integration_id = integration_id
                await self.session.flush()
            return existing

        device = UserDevice(
            user_id=user_id,
            source_id=source_id,
            integration_id=integration_id,
            device_type="scale",
            identifier=mac,
            identifier_type="mac",
            display_name="HC900/FG260RB",
        )
        self.session.add(device)
        await self.session.flush()
        return device

    async def _latest_hc900_mac(self, user_id: uuid.UUID) -> str | None:
        result = await self.session.execute(
            select(RawPayload.payload_json["device_mac"].astext)
            .where(
                RawPayload.user_id == user_id,
                RawPayload.payload_type == "hc900_scale",
                RawPayload.payload_json["device_mac"].astext.isnot(None),
            )
            .order_by(RawPayload.ingested_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def _backfill_raw_payload_device_id(
        self,
        user_id: uuid.UUID,
        mac: str,
        device_id: uuid.UUID,
    ) -> int:
        result = await self.session.execute(
            update(RawPayload)
            .where(
                RawPayload.user_id == user_id,
                RawPayload.payload_type == "hc900_scale",
                RawPayload.payload_json["device_mac"].astext == mac,
                RawPayload.user_device_id.is_(None),
            )
            .values(user_device_id=device_id)
            .execution_options(synchronize_session="fetch")
        )
        updated = result.rowcount
        if updated:
            logger.info("Backfilled user_device_id on %d raw_payload(s)", updated)
        return updated
