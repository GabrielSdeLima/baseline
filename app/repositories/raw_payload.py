import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.raw_payload import RawPayload
from app.repositories.base import BaseRepository


class RawPayloadRepository(BaseRepository):
    def __init__(self, session: AsyncSession):
        super().__init__(session)

    async def get_by_id(self, id: uuid.UUID) -> RawPayload | None:
        return await self._get_by_id(RawPayload, id)

    async def find_by_external_id(self, source_id: int, external_id: str) -> RawPayload | None:
        stmt = select(RawPayload).where(
            RawPayload.source_id == source_id,
            RawPayload.external_id == external_id,
        )
        return await self._get_one_or_none(stmt)

    async def list_pending(self, limit: int = 100) -> list[RawPayload]:
        stmt = (
            select(RawPayload)
            .where(RawPayload.processing_status == "pending")
            .order_by(RawPayload.ingested_at)
            .limit(limit)
        )
        return await self._get_all(stmt)

    async def list_by_user(
        self, user_id: uuid.UUID, offset: int = 0, limit: int = 50
    ) -> list[RawPayload]:
        stmt = (
            select(RawPayload)
            .where(RawPayload.user_id == user_id)
            .order_by(RawPayload.ingested_at.desc())
            .offset(offset)
            .limit(limit)
        )
        return await self._get_all(stmt)

    async def count_by_user(self, user_id: uuid.UUID) -> int:
        stmt = select(RawPayload).where(RawPayload.user_id == user_id)
        return await self._count(stmt)

    async def create(self, payload: RawPayload) -> RawPayload:
        return await self._add(payload)
