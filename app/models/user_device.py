import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, uuid7


class UserDevice(Base):
    __tablename__ = "user_devices"
    __table_args__ = (
        UniqueConstraint(
            "user_id", "source_id", "identifier",
            name="uq_user_devices_user_source_identifier",
        ),
        CheckConstraint(
            "device_type IN ('scale', 'wearable', 'phone', 'hub', 'other')",
            name="ck_user_devices_device_type",
        ),
        CheckConstraint(
            "identifier_type IN ('mac', 'serial', 'imei', 'uuid', 'other')",
            name="ck_user_devices_identifier_type",
        ),
        Index("ix_user_devices_user_source", "user_id", "source_id"),
        Index("ix_user_devices_identifier", "identifier"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    source_id: Mapped[int] = mapped_column(ForeignKey("data_sources.id"))
    integration_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("user_integrations.id", ondelete="SET NULL")
    )
    device_type: Mapped[str] = mapped_column(String(31))
    identifier: Mapped[str] = mapped_column(String(127))
    identifier_type: Mapped[str] = mapped_column(String(31))
    display_name: Mapped[str | None] = mapped_column(String(127))
    firmware_version: Mapped[str | None] = mapped_column(String(63))
    last_seen_at: Mapped[datetime | None] = mapped_column()
    is_active: Mapped[bool] = mapped_column(server_default=text("true"))
    config_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb"), default=dict
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now())

    user: Mapped["User"] = relationship()  # noqa: F821
    source: Mapped["DataSource"] = relationship()  # noqa: F821
    integration: Mapped["UserIntegration | None"] = relationship(back_populates="devices")  # noqa: F821
