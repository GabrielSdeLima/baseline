import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models.workout import WorkoutSession, WorkoutSet
from app.repositories.base import BaseRepository


class WorkoutRepository(BaseRepository):
    def __init__(self, session: AsyncSession):
        super().__init__(session)

    async def get_session_by_id(self, id: uuid.UUID) -> WorkoutSession | None:
        stmt = (
            select(WorkoutSession)
            .options(
                selectinload(WorkoutSession.sets).selectinload(WorkoutSet.exercise),
                selectinload(WorkoutSession.source),
            )
            .where(WorkoutSession.id == id)
        )
        return await self._get_one_or_none(stmt)

    async def list_sessions_by_user(
        self, user_id: uuid.UUID, offset: int = 0, limit: int = 50
    ) -> list[WorkoutSession]:
        stmt = (
            select(WorkoutSession)
            .options(
                selectinload(WorkoutSession.sets).selectinload(WorkoutSet.exercise),
                selectinload(WorkoutSession.source),
            )
            .where(WorkoutSession.user_id == user_id)
            .order_by(WorkoutSession.started_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return await self._get_all(stmt)

    async def count_sessions_by_user(self, user_id: uuid.UUID) -> int:
        stmt = select(WorkoutSession).where(WorkoutSession.user_id == user_id)
        return await self._count(stmt)

    async def create_session(self, session: WorkoutSession) -> WorkoutSession:
        return await self._add(session)

    async def create_sets(self, sets: list[WorkoutSet]) -> list[WorkoutSet]:
        return await self._add_all(sets)
