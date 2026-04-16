import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.symptom import SymptomLog
from app.repositories.base import BaseRepository


class SymptomRepository(BaseRepository):
    def __init__(self, session: AsyncSession):
        super().__init__(session)

    async def get_log_by_id(self, id: uuid.UUID) -> SymptomLog | None:
        stmt = (
            select(SymptomLog).options(selectinload(SymptomLog.symptom)).where(SymptomLog.id == id)
        )
        return await self._get_one_or_none(stmt)

    async def list_logs_by_user(
        self,
        user_id: uuid.UUID,
        *,
        active_only: bool = False,
        offset: int = 0,
        limit: int = 50,
    ) -> list[SymptomLog]:
        stmt = (
            select(SymptomLog)
            .options(selectinload(SymptomLog.symptom))
            .where(SymptomLog.user_id == user_id)
        )
        if active_only:
            stmt = stmt.where(SymptomLog.status == "active")
        stmt = stmt.order_by(SymptomLog.started_at.desc()).offset(offset).limit(limit)
        return await self._get_all(stmt)

    async def count_logs_by_user(self, user_id: uuid.UUID, *, active_only: bool = False) -> int:
        stmt = select(SymptomLog).where(SymptomLog.user_id == user_id)
        if active_only:
            stmt = stmt.where(SymptomLog.status == "active")
        return await self._count(stmt)

    async def create_log(self, log: SymptomLog) -> SymptomLog:
        return await self._add(log)
