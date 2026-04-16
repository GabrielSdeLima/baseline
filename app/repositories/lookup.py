from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.data_source import DataSource
from app.models.exercise import Exercise
from app.models.metric_type import MetricType
from app.models.symptom import Symptom
from app.repositories.base import BaseRepository


class LookupRepository(BaseRepository):
    """Repository for all lookup/reference tables."""

    def __init__(self, session: AsyncSession):
        super().__init__(session)

    async def get_data_source_by_slug(self, slug: str) -> DataSource | None:
        stmt = select(DataSource).where(DataSource.slug == slug)
        return await self._get_one_or_none(stmt)

    async def get_metric_type_by_slug(self, slug: str) -> MetricType | None:
        stmt = select(MetricType).where(MetricType.slug == slug)
        return await self._get_one_or_none(stmt)

    async def get_exercise_by_slug(self, slug: str) -> Exercise | None:
        stmt = select(Exercise).where(Exercise.slug == slug)
        return await self._get_one_or_none(stmt)

    async def get_symptom_by_slug(self, slug: str) -> Symptom | None:
        stmt = select(Symptom).where(Symptom.slug == slug)
        return await self._get_one_or_none(stmt)

    async def list_data_sources(self) -> list[DataSource]:
        return await self._get_all(select(DataSource).order_by(DataSource.slug))

    async def list_metric_types(self) -> list[MetricType]:
        return await self._get_all(select(MetricType).order_by(MetricType.slug))

    async def list_exercises(self) -> list[Exercise]:
        return await self._get_all(select(Exercise).order_by(Exercise.slug))

    async def list_symptoms(self) -> list[Symptom]:
        return await self._get_all(select(Symptom).order_by(Symptom.slug))
