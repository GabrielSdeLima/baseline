"""Schemas for HC900 scale reading surfaces."""

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel

from app.schemas.common import BaseSchema

ScaleReadingStatus = Literal["full_reading", "weight_only", "never_measured"]


class ScaleMetric(BaseModel):
    """One persisted metric from a single weighing."""

    slug: str
    value: Decimal
    unit: str
    is_derived: bool


class LatestScaleReading(BaseSchema):
    """The latest HC900 weighing for a user, as a coherent unit.

    A single response represents ONE weighing (one ``raw_payload_id``)
    so the UI can render it without stitching together unrelated
    measurements.

    ``status`` is explicit:
        - ``full_reading``    — impedance was captured; body-comp present
        - ``weight_only``     — no impedance; only weight (+ bmi/bmr if profile)
        - ``never_measured``  — user has no HC900 ingestion yet

    ``has_impedance`` mirrors the status split and is duplicated for
    frontend ergonomics (a single boolean check).
    """

    status: ScaleReadingStatus
    measured_at: datetime | None = None
    raw_payload_id: UUID | None = None
    decoder_version: str | None = None
    has_impedance: bool = False
    metrics: dict[str, ScaleMetric] = {}
