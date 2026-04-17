import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.common import BaseSchema, PaginatedResponse


class RawPayloadIngest(BaseModel):
    """Input for the raw ingestion endpoint."""

    user_id: uuid.UUID
    source_slug: str = Field(description="Slug from data_sources (e.g. 'garmin', 'withings')")
    external_id: str | None = None
    payload_type: str = Field(max_length=63, description="e.g. 'garmin_daily_summary'")
    payload_json: dict[str, Any]
    ingestion_run_id: uuid.UUID | None = None
    user_device_id: uuid.UUID | None = None
    agent_instance_id: uuid.UUID | None = None


class RawPayloadResponse(BaseSchema):
    id: uuid.UUID
    user_id: uuid.UUID
    source_id: int
    external_id: str | None
    payload_type: str
    payload_json: dict[str, Any]
    ingested_at: datetime
    processing_status: str
    processed_at: datetime | None
    error_message: str | None


class RawPayloadList(PaginatedResponse):
    items: list[RawPayloadResponse]
