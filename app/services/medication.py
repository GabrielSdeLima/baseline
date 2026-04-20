import uuid
from datetime import date, datetime  # noqa: F401 (datetime reserved for future use)

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.medication import MedicationDefinition, MedicationLog, MedicationRegimen
from app.repositories.medication import MedicationRepository
from app.schemas.medication import (
    MedicationDefinitionCreate,
    MedicationDefinitionResponse,
    MedicationLogCreate,
    MedicationLogResponse,
    MedicationRegimenCreate,
    MedicationRegimenResponse,
)


class MedicationService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = MedicationRepository(session)

    # --- Definitions ---

    async def create_definition(
        self, data: MedicationDefinitionCreate
    ) -> MedicationDefinitionResponse:
        definition = MedicationDefinition(
            name=data.name,
            active_ingredient=data.active_ingredient,
            dosage_form=data.dosage_form,
            description=data.description,
        )
        await self.repo.create_definition(definition)
        await self.session.commit()
        return MedicationDefinitionResponse.model_validate(definition)

    async def list_definitions(self) -> list[MedicationDefinitionResponse]:
        items = await self.repo.list_definitions()
        return [MedicationDefinitionResponse.model_validate(d) for d in items]

    # --- Regimens ---

    async def create_regimen(self, data: MedicationRegimenCreate) -> MedicationRegimenResponse:
        # Validate medication exists
        med = await self.repo.get_definition_by_id(data.medication_id)
        if not med:
            raise ValueError(f"Unknown medication: {data.medication_id}")

        regimen = MedicationRegimen(
            user_id=data.user_id,
            medication_id=data.medication_id,
            dosage_amount=data.dosage_amount,
            dosage_unit=data.dosage_unit,
            frequency=data.frequency,
            instructions=data.instructions,
            prescribed_by=data.prescribed_by,
            started_at=data.started_at,
            ended_at=data.ended_at,
        )
        await self.repo.create_regimen(regimen)
        await self.session.commit()
        loaded = await self.repo.get_regimen_by_id(regimen.id)
        return _regimen_to_response(loaded)

    async def list_regimens(
        self,
        user_id: uuid.UUID,
        *,
        active_only: bool = False,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[MedicationRegimenResponse], int]:
        items = await self.repo.list_regimens_by_user(
            user_id, active_only=active_only, offset=offset, limit=limit
        )
        total = await self.repo.count_regimens_by_user(user_id, active_only=active_only)
        return [_regimen_to_response(r) for r in items], total

    async def deactivate_regimen(
        self, regimen_id: uuid.UUID, user_id: uuid.UUID
    ) -> MedicationRegimenResponse:
        regimen = await self.repo.get_regimen_by_id(regimen_id)
        if not regimen:
            raise ValueError(f"Unknown regimen: {regimen_id}")
        if regimen.user_id != user_id:
            raise ValueError("Regimen does not belong to this user")
        regimen.is_active = False
        if not regimen.ended_at:
            regimen.ended_at = date.today()
        await self.session.commit()
        loaded = await self.repo.get_regimen_by_id(regimen_id)
        return _regimen_to_response(loaded)

    # --- Logs ---

    async def create_log(self, data: MedicationLogCreate) -> MedicationLogResponse:
        # Validate regimen exists and belongs to user
        regimen = await self.repo.get_regimen_by_id(data.regimen_id)
        if not regimen:
            raise ValueError(f"Unknown regimen: {data.regimen_id}")
        if regimen.user_id != data.user_id:
            raise ValueError("Regimen does not belong to this user")

        log = MedicationLog(
            user_id=data.user_id,
            regimen_id=data.regimen_id,
            status=data.status,
            scheduled_at=data.scheduled_at,
            taken_at=data.taken_at,
            dosage_amount=data.dosage_amount,
            dosage_unit=data.dosage_unit,
            notes=data.notes,
            recorded_at=data.recorded_at,
        )
        await self.repo.create_log(log)
        await self.session.commit()
        return MedicationLogResponse.model_validate(log)

    async def list_logs(
        self,
        user_id: uuid.UUID,
        *,
        start_date: date | None = None,
        end_date: date | None = None,
        offset: int = 0,
        limit: int = 50,
    ) -> tuple[list[MedicationLogResponse], int]:
        if start_date is not None or end_date is not None:
            items = await self.repo.list_logs_by_user_date_range(
                user_id, start_date=start_date, end_date=end_date, offset=offset, limit=limit
            )
            total = await self.repo.count_logs_by_user_date_range(
                user_id, start_date=start_date, end_date=end_date
            )
        else:
            items = await self.repo.list_logs_by_user(user_id, offset=offset, limit=limit)
            total = await self.repo.count_logs_by_user(user_id)
        return [MedicationLogResponse.model_validate(log) for log in items], total


def _regimen_to_response(r: MedicationRegimen) -> MedicationRegimenResponse:
    return MedicationRegimenResponse(
        id=r.id,
        user_id=r.user_id,
        medication_id=r.medication_id,
        medication_name=r.medication.name if r.medication else None,
        dosage_amount=r.dosage_amount,
        dosage_unit=r.dosage_unit,
        frequency=r.frequency,
        instructions=r.instructions,
        prescribed_by=r.prescribed_by,
        started_at=r.started_at,
        ended_at=r.ended_at,
        is_active=r.is_active,
        created_at=r.created_at,
        updated_at=r.updated_at,
    )
