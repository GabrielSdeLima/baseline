import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, uuid7


class UserIntegration(Base):
    __tablename__ = "user_integrations"
    __table_args__ = (
        UniqueConstraint("user_id", "source_id", name="uq_user_integrations_user_source"),
        CheckConstraint(
            "status IN ('active', 'suspended', 'revoked', 'error')",
            name="ck_user_integrations_status",
        ),
        Index("ix_user_integrations_user", "user_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    source_id: Mapped[int] = mapped_column(ForeignKey("data_sources.id"))
    status: Mapped[str] = mapped_column(String(31), server_default="active")
    config_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb"), default=dict
    )
    credentials_ref: Mapped[str | None] = mapped_column(String(255))
    last_sync_at: Mapped[datetime | None] = mapped_column()
    last_error_at: Mapped[datetime | None] = mapped_column()
    last_error_message: Mapped[str | None] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now())

    user: Mapped["User"] = relationship()  # noqa: F821
    source: Mapped["DataSource"] = relationship()  # noqa: F821
    devices: Mapped[list["UserDevice"]] = relationship(back_populates="integration")  # noqa: F821
