import uuid
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.medication import MedicationDefinition, MedicationLog, MedicationRegimen
from app.repositories.base import BaseRepository


class MedicationRepository(BaseRepository):
    def __init__(self, session: AsyncSession):
        super().__init__(session)

    # --- Definitions ---

    async def get_definition_by_id(self, id: int) -> MedicationDefinition | None:
        return await self._get_by_id(MedicationDefinition, id)

    async def list_definitions(self) -> list[MedicationDefinition]:
        return await self._get_all(select(MedicationDefinition).order_by(MedicationDefinition.name))

    async def create_definition(self, definition: MedicationDefinition) -> MedicationDefinition:
        return await self._add(definition)

    # --- Regimens ---

    async def get_regimen_by_id(self, id: uuid.UUID) -> MedicationRegimen | None:
        stmt = (
            select(MedicationRegimen)
            .options(selectinload(MedicationRegimen.medication))
            .where(MedicationRegimen.id == id)
        )
        return await self._get_one_or_none(stmt)

    async def list_regimens_by_user(
        self,
        user_id: uuid.UUID,
        *,
        active_only: bool = False,
        offset: int = 0,
        limit: int = 50,
    ) -> list[MedicationRegimen]:
        stmt = (
            select(MedicationRegimen)
            .options(selectinload(MedicationRegimen.medication))
            .where(MedicationRegimen.user_id == user_id)
        )
        if active_only:
            stmt = stmt.where(MedicationRegimen.is_active.is_(True))
        stmt = stmt.order_by(MedicationRegimen.started_at.desc()).offset(offset).limit(limit)
        return await self._get_all(stmt)

    async def count_regimens_by_user(self, user_id: uuid.UUID, *, active_only: bool = False) -> int:
        stmt = select(MedicationRegimen).where(MedicationRegimen.user_id == user_id)
        if active_only:
            stmt = stmt.where(MedicationRegimen.is_active.is_(True))
        return await self._count(stmt)

    async def create_regimen(self, regimen: MedicationRegimen) -> MedicationRegimen:
        return await self._add(regimen)

    # --- Logs ---

    async def list_logs_by_user(
        self, user_id: uuid.UUID, offset: int = 0, limit: int = 50
    ) -> list[MedicationLog]:
        stmt = (
            select(MedicationLog)
            .where(MedicationLog.user_id == user_id)
            .order_by(MedicationLog.scheduled_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return await self._get_all(stmt)

    async def count_logs_by_user(self, user_id: uuid.UUID) -> int:
        stmt = select(MedicationLog).where(MedicationLog.user_id == user_id)
        return await self._count(stmt)

    async def list_logs_by_user_date_range(
        self,
        user_id: uuid.UUID,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> list[MedicationLog]:
        stmt = select(MedicationLog).where(MedicationLog.user_id == user_id)
        if start_date is not None:
            start_dt = datetime.combine(start_date, time.min, tzinfo=timezone.utc)
            stmt = stmt.where(MedicationLog.scheduled_at >= start_dt)
        if end_date is not None:
            end_dt = datetime.combine(end_date + timedelta(days=1), time.min, tzinfo=timezone.utc)
            stmt = stmt.where(MedicationLog.scheduled_at < end_dt)
        stmt = stmt.order_by(MedicationLog.scheduled_at.desc()).offset(offset).limit(limit)
        return await self._get_all(stmt)

    async def count_logs_by_user_date_range(
        self,
        user_id: uuid.UUID,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> int:
        stmt = select(MedicationLog).where(MedicationLog.user_id == user_id)
        if start_date is not None:
            start_dt = datetime.combine(start_date, time.min, tzinfo=timezone.utc)
            stmt = stmt.where(MedicationLog.scheduled_at >= start_dt)
        if end_date is not None:
            end_dt = datetime.combine(end_date + timedelta(days=1), time.min, tzinfo=timezone.utc)
            stmt = stmt.where(MedicationLog.scheduled_at < end_dt)
        return await self._count(stmt)

    async def create_log(self, log: MedicationLog) -> MedicationLog:
        return await self._add(log)
