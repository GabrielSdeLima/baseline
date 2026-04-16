import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.workout import WorkoutSession, WorkoutSet
from app.repositories.lookup import LookupRepository
from app.repositories.workout import WorkoutRepository
from app.schemas.workout import (
    WorkoutSessionCreate,
    WorkoutSessionResponse,
    WorkoutSetResponse,
)


def _set_to_response(s: WorkoutSet) -> WorkoutSetResponse:
    return WorkoutSetResponse(
        id=s.id,
        exercise_id=s.exercise_id,
        exercise_slug=s.exercise.slug if s.exercise else None,
        exercise_name=s.exercise.name if s.exercise else None,
        set_number=s.set_number,
        reps=s.reps,
        weight_kg=s.weight_kg,
        duration_seconds=s.duration_seconds,
        distance_meters=s.distance_meters,
        rest_seconds=s.rest_seconds,
        notes=s.notes,
    )


def _session_to_response(ws: WorkoutSession) -> WorkoutSessionResponse:
    return WorkoutSessionResponse(
        id=ws.id,
        user_id=ws.user_id,
        source_id=ws.source_id,
        title=ws.title,
        workout_type=ws.workout_type,
        started_at=ws.started_at,
        ended_at=ws.ended_at,
        duration_seconds=ws.duration_seconds,
        perceived_effort=ws.perceived_effort,
        notes=ws.notes,
        recorded_at=ws.recorded_at,
        ingested_at=ws.ingested_at,
        raw_payload_id=ws.raw_payload_id,
        context=ws.context,
        sets=[_set_to_response(s) for s in ws.sets] if ws.sets else [],
    )


class WorkoutService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = WorkoutRepository(session)
        self.lookup = LookupRepository(session)

    async def create_session(self, data: WorkoutSessionCreate) -> WorkoutSessionResponse:
        source = await self.lookup.get_data_source_by_slug(data.source_slug)
        if not source:
            raise ValueError(f"Unknown data source: {data.source_slug}")

        workout = WorkoutSession(
            user_id=data.user_id,
            source_id=source.id,
            title=data.title,
            workout_type=data.workout_type,
            started_at=data.started_at,
            ended_at=data.ended_at,
            duration_seconds=data.duration_seconds,
            perceived_effort=data.perceived_effort,
            notes=data.notes,
            recorded_at=data.recorded_at,
            raw_payload_id=data.raw_payload_id,
            context=data.context,
        )
        await self.repo.create_session(workout)

        # Create sets
        if data.sets:
            sets = []
            for set_data in data.sets:
                exercise = await self.lookup.get_exercise_by_slug(set_data.exercise_slug)
                if not exercise:
                    raise ValueError(f"Unknown exercise: {set_data.exercise_slug}")
                ws = WorkoutSet(
                    workout_session_id=workout.id,
                    exercise_id=exercise.id,
                    set_number=set_data.set_number,
                    reps=set_data.reps,
                    weight_kg=set_data.weight_kg,
                    duration_seconds=set_data.duration_seconds,
                    distance_meters=set_data.distance_meters,
                    rest_seconds=set_data.rest_seconds,
                    notes=set_data.notes,
                )
                sets.append(ws)
            await self.repo.create_sets(sets)

        await self.session.commit()
        loaded = await self.repo.get_session_by_id(workout.id)
        return _session_to_response(loaded)

    async def get_session(self, session_id: uuid.UUID) -> WorkoutSessionResponse | None:
        ws = await self.repo.get_session_by_id(session_id)
        if not ws:
            return None
        return _session_to_response(ws)

    async def list_sessions(
        self, user_id: uuid.UUID, offset: int = 0, limit: int = 50
    ) -> tuple[list[WorkoutSessionResponse], int]:
        items = await self.repo.list_sessions_by_user(user_id, offset=offset, limit=limit)
        total = await self.repo.count_sessions_by_user(user_id)
        return [_session_to_response(ws) for ws in items], total
