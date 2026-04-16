import logging
import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db
from app.repositories.raw_payload import RawPayloadRepository
from app.schemas.raw_payload import RawPayloadIngest, RawPayloadList, RawPayloadResponse
from app.services.ingestion import IngestionService

router = APIRouter(prefix="/raw-payloads", tags=["ingestion"])
_logger = logging.getLogger(__name__)


@router.post("/ingest", status_code=201, response_model=RawPayloadResponse)
async def ingest_raw_payload(
    data: RawPayloadIngest,
    db: AsyncSession = Depends(get_db),
):
    """Ingest a raw payload and process it into curated data."""
    svc = IngestionService(db)
    try:
        payload = await svc.ingest(data)
        return RawPayloadResponse.model_validate(payload)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        _logger.exception("Unhandled error in ingest endpoint")
        raise HTTPException(status_code=500, detail=f"Ingestion failed: {type(e).__name__}")


@router.get("/", response_model=RawPayloadList)
async def list_raw_payloads(
    user_id: uuid.UUID,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
):
    repo = RawPayloadRepository(db)
    items = await repo.list_by_user(user_id, offset=offset, limit=limit)
    total = await repo.count_by_user(user_id)
    return RawPayloadList(
        items=[RawPayloadResponse.model_validate(p) for p in items],
        total=total,
        offset=offset,
        limit=limit,
    )


@router.post("/reprocess", status_code=200)
async def reprocess_pending(
    limit: int = Query(100, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
):
    """Reprocess all pending raw payloads."""
    svc = IngestionService(db)
    count = await svc.reprocess_pending(limit=limit)
    return {"processed": count}
