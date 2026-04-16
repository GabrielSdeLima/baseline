import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.common import BaseSchema, PaginatedResponse, TZDatetime


class MeasurementCreate(BaseModel):
    user_id: uuid.UUID
    metric_type_slug: str = Field(
        description="Slug from metric_types lookup (e.g. 'weight', 'hrv_rmssd')"
    )
    source_slug: str = Field(description="Slug from data_sources lookup (e.g. 'manual', 'garmin')")
    value_num: Decimal
    unit: str = Field(max_length=31)
    measured_at: TZDatetime
    started_at: TZDatetime | None = None
    ended_at: TZDatetime | None = None
    recorded_at: TZDatetime
    aggregation_level: str = "spot"
    is_derived: bool = False
    confidence: Decimal | None = Field(None, ge=0, le=1)
    context: dict[str, Any] | None = None
    raw_payload_id: uuid.UUID | None = None


class MeasurementResponse(BaseSchema):
    id: uuid.UUID
    user_id: uuid.UUID
    metric_type_id: int
    metric_type_slug: str | None = None
    metric_type_name: str | None = None
    source_id: int
    source_slug: str | None = None
    value_num: Decimal
    unit: str
    measured_at: datetime
    started_at: datetime | None
    ended_at: datetime | None
    recorded_at: datetime
    ingested_at: datetime
    aggregation_level: str
    is_derived: bool
    confidence: Decimal | None
    context: dict[str, Any] | None
    raw_payload_id: uuid.UUID | None


class MeasurementList(PaginatedResponse):
    items: list[MeasurementResponse]


class MeasurementQuery(BaseModel):
    user_id: uuid.UUID
    metric_type_slug: str | None = None
    start: datetime | None = None
    end: datetime | None = None
    aggregation_level: str | None = None
    offset: int = 0
    limit: int = Field(50, le=1000)
