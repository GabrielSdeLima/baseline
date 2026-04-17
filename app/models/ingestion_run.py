import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    CheckConstraint,
    ForeignKey,
    Index,
    SmallInteger,
    String,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, uuid7


class IngestionRun(Base):
    __tablename__ = "ingestion_runs"
    __table_args__ = (
        CheckConstraint(
            "operation_type IN ('cloud_sync', 'ble_scan', 'replay', 'manual_entry', 'file_import', 'health_connect_pull')",
            name="ck_ingestion_runs_operation_type",
        ),
        CheckConstraint(
            "trigger_type IN ('startup', 'scheduled', 'manual', 'ui_button', 'wake', 'ui_stale', 'backfill', 'retry')",
            name="ck_ingestion_runs_trigger_type",
        ),
        CheckConstraint(
            "status IN ('running', 'completed', 'failed', 'partial', 'skipped')",
            name="ck_ingestion_runs_status",
        ),
        Index(
            "ix_ingestion_runs_user_source_started",
            "user_id",
            "source_id",
            "started_at",
        ),
        Index(
            "ix_ingestion_runs_running",
            "status",
            postgresql_where=text("status = 'running'"),
        ),
        Index(
            "ix_ingestion_runs_idempotency_key",
            "idempotency_key",
            unique=True,
            postgresql_where=text("idempotency_key IS NOT NULL"),
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    source_id: Mapped[int] = mapped_column(ForeignKey("data_sources.id"))
    agent_instance_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("agent_instances.id")
    )
    user_integration_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("user_integrations.id")
    )
    operation_type: Mapped[str] = mapped_column(String(31))
    trigger_type: Mapped[str] = mapped_column(String(31))
    idempotency_key: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(31), server_default="running")
    attempt_no: Mapped[int] = mapped_column(
        SmallInteger(), server_default=text("1"), default=1
    )
    started_at: Mapped[datetime] = mapped_column(server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column()
    raw_payloads_created: Mapped[int] = mapped_column(
        server_default=text("0"), default=0
    )
    raw_payloads_reused: Mapped[int] = mapped_column(
        server_default=text("0"), default=0
    )
    raw_payloads_failed: Mapped[int] = mapped_column(
        server_default=text("0"), default=0
    )
    measurements_created: Mapped[int] = mapped_column(
        server_default=text("0"), default=0
    )
    measurements_deleted: Mapped[int] = mapped_column(
        server_default=text("0"), default=0
    )
    error_message: Mapped[str | None] = mapped_column()
    metadata_json: Mapped[dict[str, Any]] = mapped_column(
        JSONB, server_default=text("'{}'::jsonb"), default=dict
    )

    payloads: Mapped[list["IngestionRunPayload"]] = relationship(  # noqa: F821
        back_populates="run"
    )
