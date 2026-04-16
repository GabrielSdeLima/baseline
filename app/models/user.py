import uuid
from datetime import datetime

from sqlalchemy import String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, uuid7


class User(Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    email: Mapped[str] = mapped_column(String(255), unique=True)
    name: Mapped[str] = mapped_column(String(255))
    timezone: Mapped[str] = mapped_column(String(63), server_default="UTC")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    # Relationships
    raw_payloads: Mapped[list["RawPayload"]] = relationship(back_populates="user")  # noqa: F821
    measurements: Mapped[list["Measurement"]] = relationship(back_populates="user")  # noqa: F821
    workout_sessions: Mapped[list["WorkoutSession"]] = relationship(  # noqa: F821
        back_populates="user"
    )
    medication_regimens: Mapped[list["MedicationRegimen"]] = relationship(  # noqa: F821
        back_populates="user"
    )
    medication_logs: Mapped[list["MedicationLog"]] = relationship(  # noqa: F821
        back_populates="user"
    )
    symptom_logs: Mapped[list["SymptomLog"]] = relationship(back_populates="user")  # noqa: F821
    daily_checkpoints: Mapped[list["DailyCheckpoint"]] = relationship(  # noqa: F821
        back_populates="user"
    )
