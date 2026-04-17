import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, UniqueConstraint, func, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, uuid7


class AgentInstance(Base):
    __tablename__ = "agent_instances"
    __table_args__ = (
        UniqueConstraint("install_id", name="uq_agent_instances_install_id"),
        CheckConstraint(
            "agent_type IN ('local_pc', 'android', 'ios', 'browser', 'server', 'other')",
            name="ck_agent_instances_agent_type",
        ),
        Index(
            "ix_agent_instances_user",
            "user_id",
            postgresql_where=text("user_id IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id"))
    install_id: Mapped[str] = mapped_column(String(127))
    agent_type: Mapped[str] = mapped_column(String(63))
    display_name: Mapped[str | None] = mapped_column(String(127))
    platform: Mapped[str | None] = mapped_column(String(63))
    agent_version: Mapped[str | None] = mapped_column(String(63))
    last_seen_at: Mapped[datetime | None] = mapped_column()
    is_active: Mapped[bool] = mapped_column(server_default=text("true"))
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb"), default=dict
    )
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now())
