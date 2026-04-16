import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.symptom import SymptomLog
from app.repositories.lookup import LookupRepository
from app.repositories.symptom import SymptomRepository
from app.schemas.symptom import SymptomLogCreate, SymptomLogResponse


def _to_response(log: SymptomLog) -> SymptomLogResponse:
    return SymptomLogResponse(
        id=log.id,
        user_id=log.user_id,
        symptom_id=log.symptom_id,
        symptom_slug=log.symptom.slug if log.symptom else None,
        symptom_name=log.symptom.name if log.symptom else None,
        intensity=log.intensity,
        status=log.status,
        trigger=log.trigger,
        functional_impact=log.functional_impact,
        started_at=log.started_at,
        ended_at=log.ended_at,
        notes=log.notes,
        recorded_at=log.recorded_at,
        ingested_at=log.ingested_at,
        context=log.context,
    )


class SymptomService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = SymptomRepository(session)
        self.lookup = LookupRepository(session)

    async def create_log(self, data: SymptomLogCreate) -> SymptomLogResponse:
        symptom = await self.lookup.get_symptom_by_slug(data.symptom_slug)
        if not symptom:
            raise ValueError(f"Unknown symptom: {data.symptom_slug}")

        log = SymptomLog(
            user_id=data.user_id,
            symptom_id=symptom.id,
            intensity=data.intensity,
            status=data.status,
            trigger=data.trigger,
            functional_impact=data.functional_impact,
            started_at=data.started_at,
            ended_at=data.ended_at,
            notes=data.notes,
            recorded_at=data.recorded_at,
            context=data.context,
        )
        await self.repo.create_log(log)
        await self.session.commit()
        loaded = await self.repo.get_log_by_id(log.id)
        return _to_response(loaded)

    async def list_logs(
        self,
        user_id: uuid.UUID,
        *,
        active_only: bool = False,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[SymptomLogResponse], int]:
        items = await self.repo.list_logs_by_user(
            user_id, active_only=active_only, offset=offset, limit=limit
        )
        total = await self.repo.count_logs_by_user(user_id, active_only=active_only)
        return [_to_response(log) for log in items], total
