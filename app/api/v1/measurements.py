import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db
from app.schemas.measurement import MeasurementCreate, MeasurementList, MeasurementQuery
from app.services.measurement import MeasurementService

router = APIRouter(prefix="/measurements", tags=["measurements"])


@router.post("/", status_code=201)
async def create_measurement(
    data: MeasurementCreate,
    db: AsyncSession = Depends(get_db),
):
    svc = MeasurementService(db)
    try:
        return await svc.create(data)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.get("/", response_model=MeasurementList)
async def list_measurements(
    user_id: uuid.UUID,
    metric_type_slug: str | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    aggregation_level: str | None = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
):
    svc = MeasurementService(db)
    query = MeasurementQuery(
        user_id=user_id,
        metric_type_slug=metric_type_slug,
        start=start,
        end=end,
        aggregation_level=aggregation_level,
        offset=offset,
        limit=limit,
    )
    items, total = await svc.list(query)
    return MeasurementList(items=items, total=total, offset=offset, limit=limit)
