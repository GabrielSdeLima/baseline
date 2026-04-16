import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Index, SmallInteger, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, uuid7


class Symptom(Base):
    __tablename__ = "symptoms"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(63), unique=True)
    name: Mapped[str] = mapped_column(String(127))
    category: Mapped[str] = mapped_column(String(63))
    description: Mapped[str | None] = mapped_column(default=None)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class SymptomLog(Base):
    __tablename__ = "symptom_logs"
    __table_args__ = (
        CheckConstraint("intensity >= 1 AND intensity <= 10", name="ck_symptom_logs_intensity"),
        Index("ix_symptom_logs_user_started", "user_id", "started_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    symptom_id: Mapped[int] = mapped_column(ForeignKey("symptoms.id"))
    intensity: Mapped[int] = mapped_column(SmallInteger)
    status: Mapped[str] = mapped_column(String(15), server_default="active")
    trigger: Mapped[str | None] = mapped_column(String(255), default=None)
    functional_impact: Mapped[str | None] = mapped_column(String(15), default=None)
    started_at: Mapped[datetime]
    ended_at: Mapped[datetime | None] = mapped_column(default=None)
    notes: Mapped[str | None] = mapped_column(default=None)
    recorded_at: Mapped[datetime]
    ingested_at: Mapped[datetime] = mapped_column(server_default=func.now())
    context: Mapped[dict[str, Any] | None] = mapped_column(JSONB, default=None)

    # Relationships
    user: Mapped["User"] = relationship(back_populates="symptom_logs")  # noqa: F821
    symptom: Mapped["Symptom"] = relationship()
