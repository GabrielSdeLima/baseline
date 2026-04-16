import uuid
from datetime import date, datetime
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.common import BaseSchema, PaginatedResponse, TZDatetime


class DailyCheckpointCreate(BaseModel):
    user_id: uuid.UUID
    checkpoint_type: str = Field(description="morning or night")
    checkpoint_date: date
    checkpoint_at: TZDatetime
    mood: int | None = Field(None, ge=1, le=10)
    energy: int | None = Field(None, ge=1, le=10)
    sleep_quality: int | None = Field(None, ge=1, le=10)
    body_state_score: int | None = Field(None, ge=1, le=10)
    notes: str | None = None
    recorded_at: TZDatetime
    context: dict[str, Any] | None = None


class DailyCheckpointResponse(BaseSchema):
    id: uuid.UUID
    user_id: uuid.UUID
    checkpoint_type: str
    checkpoint_date: date
    checkpoint_at: datetime
    mood: int | None
    energy: int | None
    sleep_quality: int | None
    body_state_score: int | None
    notes: str | None
    recorded_at: datetime
    ingested_at: datetime
    context: dict[str, Any] | None


class DailyCheckpointList(PaginatedResponse):
    items: list[DailyCheckpointResponse]
