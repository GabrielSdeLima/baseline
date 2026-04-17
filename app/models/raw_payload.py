import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import ForeignKey, Index, String, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, uuid7


class RawPayload(Base):
    __tablename__ = "raw_payloads"
    __table_args__ = (
        Index(
            "ix_raw_payloads_source_external",
            "source_id",
            "external_id",
            unique=True,
            postgresql_where=text("external_id IS NOT NULL"),
        ),
        Index(
            "ix_raw_payloads_pending",
            "processing_status",
            postgresql_where=text("processing_status = 'pending'"),
        ),
        Index("ix_raw_payloads_user_ingested", "user_id", "ingested_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    source_id: Mapped[int] = mapped_column(ForeignKey("data_sources.id"))
    external_id: Mapped[str | None] = mapped_column(String(255), default=None)
    payload_type: Mapped[str] = mapped_column(String(63))
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSONB)
    ingested_at: Mapped[datetime] = mapped_column(server_default=func.now())
    processing_status: Mapped[str] = mapped_column(String(31), server_default="pending")
    processed_at: Mapped[datetime | None] = mapped_column(default=None)
    error_message: Mapped[str | None] = mapped_column(default=None)
    # Operational provenance — nullable; existing payloads remain valid with NULL
    user_device_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("user_devices.id", ondelete="SET NULL"), default=None
    )
    agent_instance_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agent_instances.id", ondelete="SET NULL"), default=None
    )

    # Relationships
    user: Mapped["User"] = relationship(back_populates="raw_payloads")  # noqa: F821
    source: Mapped["DataSource"] = relationship()  # noqa: F821
    measurements: Mapped[list["Measurement"]] = relationship(  # noqa: F821
        back_populates="raw_payload"
    )
    user_device: Mapped["UserDevice | None"] = relationship()  # noqa: F821
    agent_instance: Mapped["AgentInstance | None"] = relationship()  # noqa: F821
