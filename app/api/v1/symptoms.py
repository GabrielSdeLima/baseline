import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db
from app.schemas.symptom import SymptomLogCreate, SymptomLogList
from app.services.symptom import SymptomService

router = APIRouter(prefix="/symptoms", tags=["symptoms"])


@router.post("/logs", status_code=201)
async def create_symptom_log(
    data: SymptomLogCreate,
    db: AsyncSession = Depends(get_db),
):
    svc = SymptomService(db)
    try:
        return await svc.create_log(data)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.get("/logs", response_model=SymptomLogList)
async def list_symptom_logs(
    user_id: uuid.UUID,
    active_only: bool = False,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
):
    svc = SymptomService(db)
    items, total = await svc.list_logs(user_id, active_only=active_only, offset=offset, limit=limit)
    return SymptomLogList(items=items, total=total, offset=offset, limit=limit)
