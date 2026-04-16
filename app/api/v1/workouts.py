import uuid

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db
from app.schemas.workout import WorkoutSessionCreate, WorkoutSessionList
from app.services.workout import WorkoutService

router = APIRouter(prefix="/workouts", tags=["workouts"])


@router.post("/sessions", status_code=201)
async def create_workout_session(
    data: WorkoutSessionCreate,
    db: AsyncSession = Depends(get_db),
):
    svc = WorkoutService(db)
    try:
        return await svc.create_session(data)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.get("/sessions/{session_id}")
async def get_workout_session(
    session_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    svc = WorkoutService(db)
    result = await svc.get_session(session_id)
    if not result:
        raise HTTPException(status_code=404, detail="Workout session not found")
    return result


@router.get("/sessions", response_model=WorkoutSessionList)
async def list_workout_sessions(
    user_id: uuid.UUID,
    offset: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=1000),
    db: AsyncSession = Depends(get_db),
):
    svc = WorkoutService(db)
    items, total = await svc.list_sessions(user_id, offset=offset, limit=limit)
    return WorkoutSessionList(items=items, total=total, offset=offset, limit=limit)
