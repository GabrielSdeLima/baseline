"""Scale surfaces — read-only views over HC900 measurements.

The ingestion pipeline (see :mod:`app.services.ingestion`) is the writer;
this module only reads.  The current surface is a single "latest reading"
endpoint that returns ONE weighing as a coherent unit (the UI should not
have to stitch together unrelated measurements to render a single card).
"""
from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.integrations.hc900.decoder import DECODER_VERSION
from app.models.data_source import DataSource
from app.models.measurement import Measurement
from app.models.raw_payload import RawPayload
from app.schemas.scale import LatestScaleReading, ScaleMetric, ScaleReadingStatus

_HC900_SOURCE_SLUG = "hc900_ble"

# Slugs that v1 (legacy Pulso) never emitted as separate measurements.
# If any of these is present on the persisted reading, the curated rows
# came from the current Python parser (hc900_ble_v2) regardless of what
# ``payload_json.decoded.decoder_version`` still says — payload_json is
# frozen at ingest time and does NOT reflect subsequent reprocessing.
_V2_EXCLUSIVE_SLUGS = frozenset({"impedance_adc", "bmi", "bmr"})

# Presence of ``body_fat_pct`` is the canonical signal that impedance was
# captured; every impedance-dependent metric is persisted together, so
# one probe is enough.
_BODY_COMP_PROBE_SLUG = "body_fat_pct"


def _detect_decoder_version(metric_slugs: set[str], raw: RawPayload | None) -> str:
    """Return the decoder version that produced the persisted measurements.

    Prefers evidence from the measurement set itself (authoritative post-
    reprocess); falls back to the ingested ``payload_json.decoded`` label
    and finally to the legacy ``hc900_ble_v1`` tag.
    """
    if _V2_EXCLUSIVE_SLUGS & metric_slugs:
        return DECODER_VERSION
    if raw is not None:
        decoded = raw.payload_json.get("decoded") or {}
        label = decoded.get("decoder_version")
        if label:
            return label
    return "hc900_ble_v1"


class ScaleService:
    """Read-side service for HC900 scale surfaces."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_latest_reading(self, user_id: UUID) -> LatestScaleReading:
        """Return the latest HC900 weighing for ``user_id`` as one unit.

        All metrics in the response belong to a single ``raw_payload_id``
        — never a mix of the latest weight with a stale body-comp read.
        """
        source_id_subq = (
            select(DataSource.id)
            .where(DataSource.slug == _HC900_SOURCE_SLUG)
            .scalar_subquery()
        )

        latest_raw_payload_id = await self.session.scalar(
            select(Measurement.raw_payload_id)
            .where(
                Measurement.user_id == user_id,
                Measurement.source_id == source_id_subq,
                Measurement.raw_payload_id.is_not(None),
            )
            .order_by(Measurement.measured_at.desc())
            .limit(1)
        )

        if latest_raw_payload_id is None:
            return LatestScaleReading(status="never_measured")

        result = await self.session.execute(
            select(Measurement)
            .options(selectinload(Measurement.metric_type))
            .where(Measurement.raw_payload_id == latest_raw_payload_id)
            .order_by(Measurement.measured_at.desc())
        )
        siblings = list(result.scalars().all())

        raw = await self.session.get(RawPayload, latest_raw_payload_id)

        metrics: dict[str, ScaleMetric] = {
            m.metric_type.slug: ScaleMetric(
                slug=m.metric_type.slug,
                value=m.value_num,
                unit=m.unit,
                is_derived=m.is_derived,
            )
            for m in siblings
        }

        has_impedance = _BODY_COMP_PROBE_SLUG in metrics
        status: ScaleReadingStatus = (
            "full_reading" if has_impedance else "weight_only"
        )

        return LatestScaleReading(
            status=status,
            measured_at=siblings[0].measured_at,
            raw_payload_id=latest_raw_payload_id,
            decoder_version=_detect_decoder_version(set(metrics.keys()), raw),
            has_impedance=has_impedance,
            metrics=metrics,
        )
