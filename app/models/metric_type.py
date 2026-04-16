from datetime import datetime

from sqlalchemy import SmallInteger, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class MetricType(Base):
    __tablename__ = "metric_types"

    id: Mapped[int] = mapped_column(primary_key=True)
    slug: Mapped[str] = mapped_column(String(63), unique=True)
    name: Mapped[str] = mapped_column(String(127))
    category: Mapped[str] = mapped_column(String(63))
    default_unit: Mapped[str] = mapped_column(String(31))
    value_precision: Mapped[int | None] = mapped_column(SmallInteger, default=None)
    description: Mapped[str | None] = mapped_column(default=None)
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())
