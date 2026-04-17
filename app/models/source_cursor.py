import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, Index, String, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, uuid7


class SourceCursor(Base):
    __tablename__ = "source_cursors"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "source_id",
            "cursor_name",
            "cursor_scope_key",
            name="uq_source_cursors",
        ),
        Index("ix_source_cursors_user_source", "user_id", "source_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    source_id: Mapped[int] = mapped_column(ForeignKey("data_sources.id"))
    cursor_name: Mapped[str] = mapped_column(String(63))
    cursor_scope_key: Mapped[str] = mapped_column(
        String(127), server_default=text("''"), default=""
    )
    cursor_value_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb"), default=dict
    )
    last_successful_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("ingestion_runs.id", ondelete="SET NULL")
    )
    last_advanced_at: Mapped[datetime | None] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now())

    last_successful_run: Mapped["IngestionRun | None"] = relationship()  # noqa: F821
