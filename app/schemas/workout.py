import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.common import BaseSchema, PaginatedResponse, TZDatetime


class WorkoutSetCreate(BaseModel):
    exercise_slug: str
    set_number: int = Field(ge=1)
    reps: int | None = None
    weight_kg: Decimal | None = None
    duration_seconds: int | None = None
    distance_meters: Decimal | None = None
    rest_seconds: int | None = None
    notes: str | None = None


class WorkoutSessionCreate(BaseModel):
    user_id: uuid.UUID
    source_slug: str = "manual"
    title: str | None = None
    workout_type: str = Field(description="strength, cardio, mixed, flexibility, sport")
    started_at: TZDatetime
    ended_at: TZDatetime | None = None
    duration_seconds: int | None = None
    perceived_effort: int | None = Field(None, ge=1, le=10)
    notes: str | None = None
    recorded_at: TZDatetime
    context: dict[str, Any] | None = None
    raw_payload_id: uuid.UUID | None = None
    sets: list[WorkoutSetCreate] = []


class WorkoutSetResponse(BaseSchema):
    id: uuid.UUID
    exercise_id: int
    exercise_slug: str | None = None
    exercise_name: str | None = None
    set_number: int
    reps: int | None
    weight_kg: Decimal | None
    duration_seconds: int | None
    distance_meters: Decimal | None
    rest_seconds: int | None
    notes: str | None


class WorkoutSessionResponse(BaseSchema):
    id: uuid.UUID
    user_id: uuid.UUID
    source_id: int
    title: str | None
    workout_type: str
    started_at: datetime
    ended_at: datetime | None
    duration_seconds: int | None
    perceived_effort: int | None
    notes: str | None
    recorded_at: datetime
    ingested_at: datetime
    raw_payload_id: uuid.UUID | None
    context: dict[str, Any] | None
    sets: list[WorkoutSetResponse] = []


class WorkoutSessionList(PaginatedResponse):
    items: list[WorkoutSessionResponse]
