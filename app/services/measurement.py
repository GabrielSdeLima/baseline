from sqlalchemy.ext.asyncio import AsyncSession

from app.models.measurement import Measurement
from app.repositories.lookup import LookupRepository
from app.repositories.measurement import MeasurementRepository
from app.schemas.measurement import MeasurementCreate, MeasurementQuery, MeasurementResponse


def _to_response(m: Measurement) -> MeasurementResponse:
    return MeasurementResponse(
        id=m.id,
        user_id=m.user_id,
        metric_type_id=m.metric_type_id,
        metric_type_slug=m.metric_type.slug if m.metric_type else None,
        metric_type_name=m.metric_type.name if m.metric_type else None,
        source_id=m.source_id,
        source_slug=m.source.slug if m.source else None,
        value_num=m.value_num,
        unit=m.unit,
        measured_at=m.measured_at,
        started_at=m.started_at,
        ended_at=m.ended_at,
        recorded_at=m.recorded_at,
        ingested_at=m.ingested_at,
        aggregation_level=m.aggregation_level,
        is_derived=m.is_derived,
        confidence=m.confidence,
        context=m.context,
        raw_payload_id=m.raw_payload_id,
    )


class MeasurementService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = MeasurementRepository(session)
        self.lookup = LookupRepository(session)

    async def create(self, data: MeasurementCreate) -> MeasurementResponse:
        metric_type = await self.lookup.get_metric_type_by_slug(data.metric_type_slug)
        if not metric_type:
            raise ValueError(f"Unknown metric type: {data.metric_type_slug}")

        source = await self.lookup.get_data_source_by_slug(data.source_slug)
        if not source:
            raise ValueError(f"Unknown data source: {data.source_slug}")

        measurement = Measurement(
            user_id=data.user_id,
            metric_type_id=metric_type.id,
            source_id=source.id,
            value_num=data.value_num,
            unit=data.unit,
            measured_at=data.measured_at,
            started_at=data.started_at,
            ended_at=data.ended_at,
            recorded_at=data.recorded_at,
            aggregation_level=data.aggregation_level,
            is_derived=data.is_derived,
            confidence=data.confidence,
            context=data.context,
            raw_payload_id=data.raw_payload_id,
        )
        await self.repo.create(measurement)
        await self.session.commit()
        # Reload with relationships
        loaded = await self.repo.get_by_id(measurement.id)
        return _to_response(loaded)

    async def list(self, query: MeasurementQuery) -> tuple[list[MeasurementResponse], int]:
        items = await self.repo.list_by_user(
            query.user_id,
            metric_type_slug=query.metric_type_slug,
            start=query.start,
            end=query.end,
            aggregation_level=query.aggregation_level,
            offset=query.offset,
            limit=query.limit,
        )
        total = await self.repo.count_by_user(
            query.user_id,
            metric_type_slug=query.metric_type_slug,
            start=query.start,
            end=query.end,
            aggregation_level=query.aggregation_level,
        )
        return [_to_response(m) for m in items], total
