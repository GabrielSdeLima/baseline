import uuid
from datetime import UTC, datetime
from typing import Annotated

from pydantic import AwareDatetime, BaseModel, ConfigDict

# All datetime inputs must be timezone-aware to avoid ambiguous storage in TIMESTAMPTZ.
# Pydantic's AwareDatetime rejects naive datetimes at validation time.
TZDatetime = Annotated[datetime, AwareDatetime]


class BaseSchema(BaseModel):
    model_config = ConfigDict(from_attributes=True)


def utcnow() -> datetime:
    return datetime.now(UTC)


class TimestampResponse(BaseSchema):
    ingested_at: datetime


class PaginationParams(BaseModel):
    offset: int = 0
    limit: int = 50


class PaginatedResponse(BaseSchema):
    total: int
    offset: int
    limit: int


class IdResponse(BaseSchema):
    id: uuid.UUID
