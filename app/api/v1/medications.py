import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db
from app.schemas.medication import (
    MedicationDefinitionCreate,
    MedicationLogCreate,
    MedicationLogList,
    MedicationRegimenCreate,
    MedicationRegimenList,
)
from app.services.medication import MedicationService

router = APIRouter(prefix="/medications", tags=["medications"])


# --- Definitions ---


@router.post("/definitions", status_code=201)
async def create_medication_definition(
    data: MedicationDefinitionCreate,
    db: AsyncSession = Depends(get_db),
):
    svc = MedicationService(db)
    return await svc.create_definition(data)


@router.get("/definitions")
async def list_medication_definitions(db: AsyncSession = Depends(get_db)):
    svc = MedicationService(db)
    return await svc.list_definitions()


# --- Regimens ---


@router.post("/regimens", status_code=201)
async def create_medication_regimen(
    data: MedicationRegimenCreate,
    db: AsyncSession = Depends(get_db),
):
    svc = MedicationService(db)
    try:
        return await svc.create_regimen(data)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.patch("/regimens/{regimen_id}/deactivate")
async def deactivate_medication_regimen(
    regimen_id: uuid.UUID,
    user_id: uuid.UUID = Query(...),
    db: AsyncSession = Depends(get_db),
):
    svc = MedicationService(db)
    try:
        return await svc.deactivate_regimen(regimen_id, user_id)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.get("/regimens", response_model=MedicationRegimenList)
async def list_medication_regimens(
    user_id: uuid.UUID,
    active_only: bool = False,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
):
    svc = MedicationService(db)
    items, total = await svc.list_regimens(
        user_id, active_only=active_only, offset=offset, limit=limit
    )
    return MedicationRegimenList(items=items, total=total, offset=offset, limit=limit)


# --- Logs ---


@router.post("/logs", status_code=201)
async def create_medication_log(
    data: MedicationLogCreate,
    db: AsyncSession = Depends(get_db),
):
    svc = MedicationService(db)
    try:
        return await svc.create_log(data)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.get("/logs", response_model=MedicationLogList)
async def list_medication_logs(
    user_id: uuid.UUID,
    start_date: date | None = Query(None, description="Filter: logs with scheduled_at >= this date (UTC)"),
    end_date: date | None = Query(None, description="Filter: logs with scheduled_at <= this date (UTC)"),
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
):
    svc = MedicationService(db)
    items, total = await svc.list_logs(
        user_id, start_date=start_date, end_date=end_date, offset=offset, limit=limit
    )
    return MedicationLogList(items=items, total=total, offset=offset, limit=limit)
