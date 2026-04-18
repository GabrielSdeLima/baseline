from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_instance import AgentInstance
from app.models.data_source import DataSource
from app.models.ingestion_run import IngestionRun
from app.models.source_cursor import SourceCursor
from app.models.user_device import UserDevice
from app.models.user_integration import UserIntegration
from app.schemas.common import utcnow
from app.schemas.status import AgentStatus, AgentSummary, SourceStatus, SystemStatusResponse

_TRACKED_SOURCES = ("garmin_connect", "hc900_ble")
_DEVICE_SOURCES = frozenset({"hc900_ble"})  # sources where device_paired is meaningful

_ACTIVE_THRESHOLD = timedelta(hours=24)
_STALE_THRESHOLD = timedelta(days=7)


def _agent_status(a: AgentInstance, now: datetime) -> AgentStatus:
    if not a.is_active or a.last_seen_at is None:
        return "unknown"
    last = a.last_seen_at
    if last.tzinfo is None:
        last = last.replace(tzinfo=UTC)
    delta = now - last
    if delta <= _ACTIVE_THRESHOLD:
        return "active"
    if delta <= _STALE_THRESHOLD:
        return "stale"
    return "unknown"


class StatusRepository:
    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def build_system_status(self, user_id: uuid.UUID) -> SystemStatusResponse:
        now = utcnow()

        # 1. Source ID map for tracked slugs
        ds_rows = await self.db.execute(
            select(DataSource.id, DataSource.slug).where(DataSource.slug.in_(_TRACKED_SOURCES))
        )
        source_map: dict[str, int] = {r.slug: r.id for r in ds_rows}
        source_ids = list(source_map.values())

        # 2. Active integrations per source
        integ_rows = await self.db.execute(
            select(UserIntegration).where(
                UserIntegration.user_id == user_id,
                UserIntegration.source_id.in_(source_ids),
            )
        )
        integrations: dict[int, UserIntegration] = {r.source_id: r for r in integ_rows.scalars()}

        # 3. Latest cursor advancement per source (max across all cursor names)
        cursor_rows = await self.db.execute(
            select(SourceCursor.source_id, func.max(SourceCursor.last_advanced_at).label("adv"))
            .where(
                SourceCursor.user_id == user_id,
                SourceCursor.source_id.in_(source_ids),
            )
            .group_by(SourceCursor.source_id)
        )
        cursors: dict[int, datetime | None] = {r.source_id: r.adv for r in cursor_rows}

        # 4. Active devices per source (only queried for _DEVICE_SOURCES semantics)
        dev_rows = await self.db.execute(
            select(UserDevice.source_id).where(
                UserDevice.user_id == user_id,
                UserDevice.source_id.in_(source_ids),
                UserDevice.is_active.is_(True),
            )
        )
        active_device_sources: set[int] = {r.source_id for r in dev_rows}

        # 5. Latest ingestion run per source via correlated subquery (max started_at)
        latest_subq = (
            select(IngestionRun.source_id, func.max(IngestionRun.started_at).label("max_start"))
            .where(
                IngestionRun.user_id == user_id,
                IngestionRun.source_id.in_(source_ids),
            )
            .group_by(IngestionRun.source_id)
            .subquery()
        )
        run_rows = await self.db.execute(
            select(IngestionRun)
            .join(
                latest_subq,
                (IngestionRun.source_id == latest_subq.c.source_id)
                & (IngestionRun.started_at == latest_subq.c.max_start),
            )
            .where(IngestionRun.user_id == user_id)
        )
        latest_runs: dict[int, IngestionRun] = {r.source_id: r for r in run_rows.scalars()}

        # Build SourceStatus in canonical order
        sources: list[SourceStatus] = []
        for slug in _TRACKED_SOURCES:
            src_id = source_map.get(slug)
            if src_id is None:
                continue
            integ = integrations.get(src_id)
            run = latest_runs.get(src_id)
            sources.append(
                SourceStatus(
                    source_slug=slug,
                    integration_configured=integ is not None and integ.status == "active",
                    device_paired=(
                        (src_id in active_device_sources) if slug in _DEVICE_SOURCES else None
                    ),
                    last_sync_at=integ.last_sync_at if integ else None,
                    last_advanced_at=cursors.get(src_id),
                    last_run_status=run.status if run else None,
                    last_run_at=run.finished_at if run else None,
                )
            )

        # 6. All agents for user, most-recently-seen first
        agent_rows = await self.db.execute(
            select(AgentInstance)
            .where(AgentInstance.user_id == user_id)
            .order_by(AgentInstance.last_seen_at.desc().nullslast())
        )
        agents: list[AgentSummary] = [
            AgentSummary(
                agent_type=a.agent_type,
                display_name=a.display_name,
                status=_agent_status(a, now),
                last_seen_at=a.last_seen_at,
            )
            for a in agent_rows.scalars()
        ]

        return SystemStatusResponse(user_id=user_id, sources=sources, agents=agents, as_of=now)
