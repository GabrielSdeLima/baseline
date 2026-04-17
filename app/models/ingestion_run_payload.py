import uuid
from datetime import datetime

from sqlalchemy import CheckConstraint, ForeignKey, Index, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base


class IngestionRunPayload(Base):
    __tablename__ = "ingestion_run_payloads"
    __table_args__ = (
        CheckConstraint(
            "role IN ('created', 'reused', 'reprocessed')",
            name="ck_ingestion_run_payloads_role",
        ),
        Index("ix_ingestion_run_payloads_payload", "payload_id"),
    )

    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("ingestion_runs.id"), primary_key=True
    )
    payload_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("raw_payloads.id"), primary_key=True
    )
    role: Mapped[str] = mapped_column(String(31), server_default="created")
    linked_at: Mapped[datetime] = mapped_column(server_default=func.now())

    run: Mapped["IngestionRun"] = relationship(back_populates="payloads")  # noqa: F821
    payload: Mapped["RawPayload"] = relationship()  # noqa: F821
