import uuid
from typing import Any, TypeVar

from sqlalchemy import Select, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import Base

ModelT = TypeVar("ModelT", bound=Base)


class BaseRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def _get_by_id(self, model: type[ModelT], id: uuid.UUID | int) -> ModelT | None:
        return await self.session.get(model, id)

    async def _get_one_or_none(self, stmt: Select) -> Any:
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def _get_all(self, stmt: Select) -> list[Any]:
        result = await self.session.execute(stmt)
        return list(result.scalars().all())

    async def _count(self, stmt: Select) -> int:
        count_stmt = select(func.count()).select_from(stmt.subquery())
        result = await self.session.execute(count_stmt)
        return result.scalar_one()

    async def _add(self, instance: Base) -> Base:
        self.session.add(instance)
        await self.session.flush()
        return instance

    async def _add_all(self, instances: list[Base]) -> list[Base]:
        self.session.add_all(instances)
        await self.session.flush()
        return instances
