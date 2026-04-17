import uuid
from datetime import datetime

from sqlalchemy import delete as sa_delete
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.measurement import Measurement
from app.models.metric_type import MetricType
from app.models.raw_payload import RawPayload
from app.repositories.base import BaseRepository


class MeasurementRepository(BaseRepository):
    def __init__(self, session: AsyncSession):
        super().__init__(session)

    async def get_by_id(self, id: uuid.UUID) -> Measurement | None:
        stmt = (
            select(Measurement)
            .options(selectinload(Measurement.metric_type), selectinload(Measurement.source))
            .where(Measurement.id == id)
        )
        return await self._get_one_or_none(stmt)

    async def list_by_user(
        self,
        user_id: uuid.UUID,
        *,
        metric_type_slug: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        aggregation_level: str | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> list[Measurement]:
        stmt = (
            select(Measurement)
            .options(selectinload(Measurement.metric_type), selectinload(Measurement.source))
            .where(Measurement.user_id == user_id)
        )
        if metric_type_slug:
            stmt = stmt.join(MetricType).where(MetricType.slug == metric_type_slug)
        if start:
            stmt = stmt.where(Measurement.measured_at >= start)
        if end:
            stmt = stmt.where(Measurement.measured_at <= end)
        if aggregation_level:
            stmt = stmt.where(Measurement.aggregation_level == aggregation_level)
        stmt = stmt.order_by(Measurement.measured_at.desc()).offset(offset).limit(limit)
        return await self._get_all(stmt)

    async def count_by_user(
        self,
        user_id: uuid.UUID,
        *,
        metric_type_slug: str | None = None,
        start: datetime | None = None,
        end: datetime | None = None,
        aggregation_level: str | None = None,
    ) -> int:
        stmt = select(Measurement).where(Measurement.user_id == user_id)
        if metric_type_slug:
            stmt = stmt.join(MetricType).where(MetricType.slug == metric_type_slug)
        if start:
            stmt = stmt.where(Measurement.measured_at >= start)
        if end:
            stmt = stmt.where(Measurement.measured_at <= end)
        if aggregation_level:
            stmt = stmt.where(Measurement.aggregation_level == aggregation_level)
        return await self._count(stmt)

    async def exists_for_raw_payload(self, raw_payload_id: uuid.UUID) -> bool:
        stmt = select(Measurement).where(Measurement.raw_payload_id == raw_payload_id).limit(1)
        result = await self._get_one_or_none(stmt)
        return result is not None

    async def create(self, measurement: Measurement) -> Measurement:
        return await self._add(measurement)

    async def create_many(self, measurements: list[Measurement]) -> list[Measurement]:
        return await self._add_all(measurements)

    async def delete_for_garmin_daily_snapshot(
        self,
        user_id: uuid.UUID,
        source_id: int,
        logical_date: str,
        current_raw_payload_id: uuid.UUID,
    ) -> int:
        """Delete measurements from prior garmin_connect_daily snapshots for a logical date.

        Targets only garmin_connect_daily payloads for the given user, source, and date,
        excluding the current (newest) raw_payload. HC900, manual, and other payload
        types are never touched.
        """
        prior_ids_subq = (
            select(RawPayload.id)
            .where(
                RawPayload.user_id == user_id,
                RawPayload.source_id == source_id,
                RawPayload.payload_type == "garmin_connect_daily",
                RawPayload.payload_json["date"].astext == logical_date,
                RawPayload.id != current_raw_payload_id,
            )
        )
        result = await self.session.execute(
            sa_delete(Measurement)
            .where(Measurement.raw_payload_id.in_(prior_ids_subq))
            .execution_options(synchronize_session="fetch")
        )
        return result.rowcount
