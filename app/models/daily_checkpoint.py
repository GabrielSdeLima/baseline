import uuid
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    SmallInteger,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, uuid7


class DailyCheckpoint(Base):
    __tablename__ = "daily_checkpoints"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "checkpoint_type",
            "checkpoint_date",
            name="uq_daily_checkpoint_user_type_date",
        ),
        CheckConstraint("mood >= 1 AND mood <= 10", name="ck_daily_checkpoints_mood"),
        CheckConstraint("energy >= 1 AND energy <= 10", name="ck_daily_checkpoints_energy"),
        CheckConstraint(
            "sleep_quality >= 1 AND sleep_quality <= 10",
            name="ck_daily_checkpoints_sleep_quality",
        ),
        CheckConstraint(
            "body_state_score >= 1 AND body_state_score <= 10",
            name="ck_daily_checkpoints_body_state_score",
        ),
        Index("ix_daily_checkpoints_user_date", "user_id", "checkpoint_date"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    checkpoint_type: Mapped[str] = mapped_column(String(15))
    checkpoint_date: Mapped[date] = mapped_column(Date)
    checkpoint_at: Mapped[datetime]
    mood: Mapped[int | None] = mapped_column(SmallInteger, default=None)
    energy: Mapped[int | None] = mapped_column(SmallInteger, default=None)
    sleep_quality: Mapped[int | None] = mapped_column(SmallInteger, default=None)
    body_state_score: Mapped[int | None] = mapped_column(SmallInteger, default=None)
    notes: Mapped[str | None] = mapped_column(default=None)
    recorded_at: Mapped[datetime]
    ingested_at: Mapped[datetime] = mapped_column(server_default=func.now())
    context: Mapped[dict[str, Any] | None] = mapped_column(JSONB, default=None)

    # Relationships
    user: Mapped["User"] = relationship(back_populates="daily_checkpoints")  # noqa: F821
