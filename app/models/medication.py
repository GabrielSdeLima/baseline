import uuid
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import Date, ForeignKey, Index, Numeric, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, uuid7


class MedicationDefinition(Base):
    __tablename__ = "medication_definitions"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255))
    active_ingredient: Mapped[str | None] = mapped_column(String(255), default=None)
    dosage_form: Mapped[str | None] = mapped_column(String(63), default=None)
    description: Mapped[str | None] = mapped_column(default=None)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())

    # Relationships
    regimens: Mapped[list["MedicationRegimen"]] = relationship(back_populates="medication")


class MedicationRegimen(Base):
    __tablename__ = "medication_regimens"
    __table_args__ = (Index("ix_medication_regimens_user_active", "user_id", "is_active"),)

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    medication_id: Mapped[int] = mapped_column(ForeignKey("medication_definitions.id"))
    dosage_amount: Mapped[Decimal] = mapped_column(Numeric(7, 2))
    dosage_unit: Mapped[str] = mapped_column(String(31))
    frequency: Mapped[str] = mapped_column(String(31))
    instructions: Mapped[str | None] = mapped_column(default=None)
    prescribed_by: Mapped[str | None] = mapped_column(String(255), default=None)
    started_at: Mapped[date] = mapped_column(Date)
    ended_at: Mapped[date | None] = mapped_column(Date, default=None)
    is_active: Mapped[bool] = mapped_column(server_default="true")
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())

    # Relationships
    user: Mapped["User"] = relationship(back_populates="medication_regimens")  # noqa: F821
    medication: Mapped["MedicationDefinition"] = relationship(back_populates="regimens")
    logs: Mapped[list["MedicationLog"]] = relationship(back_populates="regimen")


class MedicationLog(Base):
    """Rich event temporality: scheduled_at (prescription), taken_at (action),
    recorded_at (observation), ingested_at (system)."""

    __tablename__ = "medication_logs"
    __table_args__ = (
        Index("ix_medication_logs_user_scheduled", "user_id", "scheduled_at"),
        Index("ix_medication_logs_regimen", "regimen_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    regimen_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("medication_regimens.id"))
    status: Mapped[str] = mapped_column(String(15))
    scheduled_at: Mapped[datetime]
    taken_at: Mapped[datetime | None] = mapped_column(default=None)
    dosage_amount: Mapped[Decimal | None] = mapped_column(Numeric(7, 2), default=None)
    dosage_unit: Mapped[str | None] = mapped_column(String(31), default=None)
    notes: Mapped[str | None] = mapped_column(default=None)
    recorded_at: Mapped[datetime]
    ingested_at: Mapped[datetime] = mapped_column(server_default=func.now())

    # Relationships
    user: Mapped["User"] = relationship(back_populates="medication_logs")  # noqa: F821
    regimen: Mapped["MedicationRegimen"] = relationship(back_populates="logs")
