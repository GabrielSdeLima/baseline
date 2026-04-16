import uuid
from datetime import datetime

import uuid_utils
from sqlalchemy import DateTime
from sqlalchemy.orm import DeclarativeBase


def uuid7() -> uuid.UUID:
    """Generate a UUIDv7 as stdlib uuid.UUID (Pydantic/SQLAlchemy compatible)."""
    return uuid.UUID(bytes=uuid_utils.uuid7().bytes)


class Base(DeclarativeBase):
    type_annotation_map = {
        datetime: DateTime(timezone=True),
    }
