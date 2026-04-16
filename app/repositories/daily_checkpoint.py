import uuid
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.daily_checkpoint import DailyCheckpoint
from app.repositories.base import BaseRepository


class DailyCheckpointRepository(BaseRepository):
    def __init__(self, session: AsyncSession):
        super().__init__(session)

    async def get_by_id(self, id: uuid.UUID) -> DailyCheckpoint | None:
        return await self._get_by_id(DailyCheckpoint, id)

    async def find_existing(
        self, user_id: uuid.UUID, checkpoint_type: str, checkpoint_date: date
    ) -> DailyCheckpoint | None:
        stmt = select(DailyCheckpoint).where(
            DailyCheckpoint.user_id == user_id,
            DailyCheckpoint.checkpoint_type == checkpoint_type,
            DailyCheckpoint.checkpoint_date == checkpoint_date,
        )
        return await self._get_one_or_none(stmt)

    async def list_by_user(
        self,
        user_id: uuid.UUID,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> list[DailyCheckpoint]:
        stmt = select(DailyCheckpoint).where(DailyCheckpoint.user_id == user_id)
        if start_date:
            stmt = stmt.where(DailyCheckpoint.checkpoint_date >= start_date)
        if end_date:
            stmt = stmt.where(DailyCheckpoint.checkpoint_date <= end_date)
        stmt = stmt.order_by(DailyCheckpoint.checkpoint_date.desc()).offset(offset).limit(limit)
        return await self._get_all(stmt)

    async def count_by_user(
        self,
        user_id: uuid.UUID,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
    ) -> int:
        stmt = select(DailyCheckpoint).where(DailyCheckpoint.user_id == user_id)
        if start_date:
            stmt = stmt.where(DailyCheckpoint.checkpoint_date >= start_date)
        if end_date:
            stmt = stmt.where(DailyCheckpoint.checkpoint_date <= end_date)
        return await self._count(stmt)

    async def create(self, checkpoint: DailyCheckpoint) -> DailyCheckpoint:
        return await self._add(checkpoint)
