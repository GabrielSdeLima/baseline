import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.common import BaseSchema, PaginatedResponse, TZDatetime


class SymptomLogCreate(BaseModel):
    user_id: uuid.UUID
    symptom_slug: str = Field(description="Slug from symptoms lookup (e.g. 'headache', 'fatigue')")
    intensity: int = Field(ge=1, le=10)
    status: str = "active"
    trigger: str | None = None
    functional_impact: str | None = Field(None, description="none, mild, moderate, severe")
    started_at: TZDatetime
    ended_at: TZDatetime | None = None
    notes: str | None = None
    recorded_at: TZDatetime
    context: dict[str, Any] | None = None


class SymptomLogResponse(BaseSchema):
    id: uuid.UUID
    user_id: uuid.UUID
    symptom_id: int
    symptom_slug: str | None = None
    symptom_name: str | None = None
    intensity: int
    status: str
    trigger: str | None
    functional_impact: str | None
    started_at: datetime
    ended_at: datetime | None
    notes: str | None
    recorded_at: datetime
    ingested_at: datetime
    context: dict[str, Any] | None


class SymptomLogList(PaginatedResponse):
    items: list[SymptomLogResponse]
