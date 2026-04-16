import uuid
from datetime import datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import ForeignKey, Index, Numeric, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import Base, uuid7


class Measurement(Base):
    __tablename__ = "measurements"
    __table_args__ = (
        Index("ix_measurements_user_measured", "user_id", "measured_at"),
        Index("ix_measurements_user_metric_measured", "user_id", "metric_type_id", "measured_at"),
        Index("ix_measurements_raw_payload", "raw_payload_id"),
    )

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid7)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id"))
    metric_type_id: Mapped[int] = mapped_column(ForeignKey("metric_types.id"))
    source_id: Mapped[int] = mapped_column(ForeignKey("data_sources.id"))
    value_num: Mapped[Decimal] = mapped_column(Numeric)
    unit: Mapped[str] = mapped_column(String(31))
    measured_at: Mapped[datetime]
    started_at: Mapped[datetime | None] = mapped_column(default=None)
    ended_at: Mapped[datetime | None] = mapped_column(default=None)
    recorded_at: Mapped[datetime]
    ingested_at: Mapped[datetime] = mapped_column(server_default=func.now())
    aggregation_level: Mapped[str] = mapped_column(String(15), server_default="spot")
    is_derived: Mapped[bool] = mapped_column(server_default="false")
    confidence: Mapped[Decimal | None] = mapped_column(Numeric(3, 2), default=None)
    context: Mapped[dict[str, Any] | None] = mapped_column(JSONB, default=None)
    raw_payload_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("raw_payloads.id"), default=None
    )

    # Relationships
    user: Mapped["User"] = relationship(back_populates="measurements")  # noqa: F821
    metric_type: Mapped["MetricType"] = relationship()  # noqa: F821
    source: Mapped["DataSource"] = relationship()  # noqa: F821
    raw_payload: Mapped["RawPayload | None"] = relationship(  # noqa: F821
        back_populates="measurements"
    )
