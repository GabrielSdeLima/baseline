import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import CheckConstraint, ForeignKey, Index, Numeric, SmallInteger, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, uuid7


class WorkoutSession(Base):
    __tablename__ = "workout_sessions"
    __table_args__ = (
        CheckConstraint(
            "perceived_effort >= 1 AND perceived_effort <= 10",
            name="ck_workout_sessions_perceived_effort",
        ),
        Index("ix_workout_sessions_user_started", "user_id", "started_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    source_id: Mapped[int] = mapped_column(ForeignKey("data_sources.id"))
    title: Mapped[str | None] = mapped_column(String(255), default=None)
    workout_type: Mapped[str] = mapped_column(String(31))
    started_at: Mapped[datetime]
    ended_at: Mapped[datetime | None] = mapped_column(default=None)
    duration_seconds: Mapped[int | None] = mapped_column(default=None)
    perceived_effort: Mapped[int | None] = mapped_column(SmallInteger, default=None)
    notes: Mapped[str | None] = mapped_column(default=None)
    recorded_at: Mapped[datetime]
    ingested_at: Mapped[datetime] = mapped_column(server_default=func.now())
    raw_payload_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("raw_payloads.id"), default=None
    )
    context: Mapped[dict[str, Any] | None] = mapped_column(JSONB, default=None)

    # Relationships
    user: Mapped["User"] = relationship(back_populates="workout_sessions")  # noqa: F821
    source: Mapped["DataSource"] = relationship()  # noqa: F821
    raw_payload: Mapped["RawPayload | None"] = relationship()  # noqa: F821
    sets: Mapped[list["WorkoutSet"]] = relationship(back_populates="session")


class WorkoutSet(Base):
    __tablename__ = "workout_sets"
    __table_args__ = (Index("ix_workout_sets_session", "workout_session_id"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    workout_session_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("workout_sessions.id"))
    exercise_id: Mapped[int] = mapped_column(ForeignKey("exercises.id"))
    set_number: Mapped[int] = mapped_column(SmallInteger)
    reps: Mapped[int | None] = mapped_column(SmallInteger, default=None)
    weight_kg: Mapped[Decimal | None] = mapped_column(Numeric(7, 2), default=None)
    duration_seconds: Mapped[int | None] = mapped_column(default=None)
    distance_meters: Mapped[Decimal | None] = mapped_column(Numeric(10, 2), default=None)
    rest_seconds: Mapped[int | None] = mapped_column(SmallInteger, default=None)
    notes: Mapped[str | None] = mapped_column(default=None)

    # Relationships
    session: Mapped["WorkoutSession"] = relationship(back_populates="sets")
    exercise: Mapped["Exercise"] = relationship()  # noqa: F821
