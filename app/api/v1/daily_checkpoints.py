import uuid
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db
from app.schemas.daily_checkpoint import DailyCheckpointCreate, DailyCheckpointList
from app.services.daily_checkpoint import DailyCheckpointService

router = APIRouter(prefix="/checkpoints", tags=["daily_checkpoints"])


@router.post("/", status_code=201)
async def create_daily_checkpoint(
    data: DailyCheckpointCreate,
    db: AsyncSession = Depends(get_db),
):
    svc = DailyCheckpointService(db)
    try:
        return await svc.create(data)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.get("/", response_model=DailyCheckpointList)
async def list_daily_checkpoints(
    user_id: uuid.UUID,
    start_date: date | None = None,
    end_date: date | None = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
):
    svc = DailyCheckpointService(db)
    items, total = await svc.list(
        user_id, start_date=start_date, end_date=end_date, offset=offset, limit=limit
    )
    return DailyCheckpointList(items=items, total=total, offset=offset, limit=limit)
