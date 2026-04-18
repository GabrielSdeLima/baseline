"""System Status API — operational health of ingestion sources and agents."""

import uuid

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db
from app.repositories.status import StatusRepository
from app.schemas.status import SystemStatusResponse

router = APIRouter(prefix="/status", tags=["status"])


@router.get("/system", response_model=SystemStatusResponse)
async def system_status(
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    repo = StatusRepository(db)
    return await repo.build_system_status(user_id)
