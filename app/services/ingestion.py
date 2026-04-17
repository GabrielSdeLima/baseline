"""Raw → Curated ingestion pipeline.

Receives a raw payload, persists it, then delegates to domain-specific
parsers that extract curated records (measurements, workouts, etc.)
with FK traceability back to the raw payload.
"""

import logging
import uuid
from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.ext.asyncio import AsyncSession

from app.integrations.hc900 import decode_hc900
from app.integrations.hc900.decoder import DecodedReading
from app.integrations.hc900.protocol import hex_to_bytes
from app.models.ingestion_run import IngestionRun
from app.models.ingestion_run_payload import IngestionRunPayload
from app.models.measurement import Measurement
from app.models.raw_payload import RawPayload
from app.repositories.lookup import LookupRepository
from app.repositories.measurement import MeasurementRepository
from app.repositories.raw_payload import RawPayloadRepository
from app.schemas.raw_payload import RawPayloadIngest

logger = logging.getLogger(__name__)


class IngestionService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.raw_repo = RawPayloadRepository(session)
        self.measurement_repo = MeasurementRepository(session)
        self.lookup_repo = LookupRepository(session)

    async def ingest(self, data: RawPayloadIngest) -> RawPayload:
        """Ingest a raw payload: persist it, then attempt to process it into curated data.

        If ``ingestion_run_id`` is set, the payload is linked to that run via
        ``ingestion_run_payloads`` in the same transaction. Role is ``"created"``
        for new payloads and ``"reused"`` when deduplicated by ``external_id``.
        Run counters are updated accordingly.
        """
        source = await self.lookup_repo.get_data_source_by_slug(data.source_slug)
        if not source:
            raise ValueError(f"Unknown data source: {data.source_slug}")

        run: IngestionRun | None = None
        if data.ingestion_run_id is not None:
            run = await self._validate_and_get_run(
                data.ingestion_run_id, data.user_id, source.id
            )

        # Deduplicate by external_id
        if data.external_id:
            existing = await self.raw_repo.find_by_external_id(source.id, data.external_id)
            if existing:
                if run is not None:
                    await self._link_payload_to_run(existing, run, "reused")
                    await self.session.commit()
                return existing

        payload = RawPayload(
            user_id=data.user_id,
            source_id=source.id,
            external_id=data.external_id,
            payload_type=data.payload_type,
            payload_json=data.payload_json,
            user_device_id=data.user_device_id,
            agent_instance_id=data.agent_instance_id,
        )
        await self.raw_repo.create(payload)

        if run is not None:
            await self._link_payload_to_run(payload, run, "created")

        # Attempt processing
        await self._process(payload)
        await self.session.commit()
        return payload

    async def _validate_and_get_run(
        self,
        run_id: uuid.UUID,
        user_id: uuid.UUID,
        source_id: int,
    ) -> IngestionRun:
        """Load and validate an IngestionRun for use in a payload link."""
        run = await self.session.get(IngestionRun, run_id)
        if run is None:
            raise ValueError(f"ingestion_run {run_id} not found")
        if run.user_id != user_id:
            raise ValueError("ingestion_run_id belongs to a different user")
        if run.source_id != source_id:
            raise ValueError(
                f"ingestion_run source mismatch: "
                f"run.source_id={run.source_id}, payload source_id={source_id}"
            )
        return run

    async def _link_payload_to_run(
        self,
        payload: RawPayload,
        run: IngestionRun,
        role: str,
    ) -> None:
        """Link a payload to a run; idempotent — skips if link already exists."""
        existing = await self.session.get(IngestionRunPayload, (run.id, payload.id))
        if existing is not None:
            return

        self.session.add(IngestionRunPayload(run_id=run.id, payload_id=payload.id, role=role))

        if role == "created":
            run.raw_payloads_created += 1
        elif role == "reused":
            run.raw_payloads_reused += 1

    async def _process(self, payload: RawPayload) -> None:
        """Route to the appropriate parser based on payload_type.

        Uses a savepoint so that if the parser fails mid-way (e.g. after flushing
        partial measurements), only the parser's work is rolled back. The raw payload
        itself survives in the outer transaction with status='failed'.
        """
        # Guard: skip if curated data already exists for this payload (prevents
        # duplication when a processed payload is manually reset to pending).
        if await self.measurement_repo.exists_for_raw_payload(payload.id):
            payload.processing_status = "skipped"
            payload.error_message = "Curated data already exists for this payload"
            return

        try:
            async with self.session.begin_nested():
                parser = self._get_parser(payload.payload_type)
                if parser:
                    await parser(payload)
            payload.processing_status = "processed"
            payload.processed_at = datetime.now(UTC)
        except Exception as e:
            payload.processing_status = "failed"
            payload.error_message = str(e)

    def _get_parser(self, payload_type: str):
        """Return the parser function for a given payload_type."""
        parsers = {
            "garmin_daily_summary": self._parse_garmin_daily_summary,
            "garmin_connect_daily": self._parse_garmin_connect_daily,
            "manual_measurement": self._parse_manual_measurement,
            "hc900_scale": self._parse_hc900_scale,
        }
        return parsers.get(payload_type)

    async def _parse_garmin_daily_summary(self, payload: RawPayload) -> None:
        """Extract measurements from a Garmin daily summary.

        Expected payload_json structure:
        {
            "date": "2024-01-15",
            "resting_hr": 58,
            "hrv_rmssd": 42.5,
            "steps": 8500,
            "stress_level": 35,
            "spo2": 97,
            "respiratory_rate": 15.2,
            "active_calories": 420,
            "sleep_duration_min": 450,
            "sleep_score": 82
        }
        """
        data = payload.payload_json
        metrics_map = {
            "resting_hr": ("resting_hr", "bpm"),
            "hrv_rmssd": ("hrv_rmssd", "ms"),
            "steps": ("steps", "steps"),
            "stress_level": ("stress_level", "score"),
            "spo2": ("spo2", "%"),
            "respiratory_rate": ("respiratory_rate", "brpm"),
            "active_calories": ("active_calories", "kcal"),
            "sleep_duration_min": ("sleep_duration", "min"),
            "sleep_score": ("sleep_score", "score"),
        }

        measurements = []
        for json_key, (metric_slug, unit) in metrics_map.items():
            value = data.get(json_key)
            if value is None:
                continue

            metric_type = await self.lookup_repo.get_metric_type_by_slug(metric_slug)
            if not metric_type:
                continue

            source = await self.lookup_repo.get_data_source_by_slug("garmin")
            if not source:
                continue

            measurement = Measurement(
                user_id=payload.user_id,
                metric_type_id=metric_type.id,
                source_id=source.id,
                value_num=value,
                unit=unit,
                measured_at=payload.ingested_at,
                recorded_at=payload.ingested_at,
                aggregation_level="daily",
                raw_payload_id=payload.id,
            )
            measurements.append(measurement)

        if measurements:
            await self.measurement_repo.create_many(measurements)

    async def _parse_manual_measurement(self, payload: RawPayload) -> None:
        """Extract a single measurement from a manual entry.

        Expected payload_json structure:
        {
            "metric_type_slug": "weight",
            "value": 81.5,
            "unit": "kg",
            "measured_at": "2024-01-15T07:30:00Z"
        }
        """
        data = payload.payload_json
        metric_type = await self.lookup_repo.get_metric_type_by_slug(data["metric_type_slug"])
        if not metric_type:
            raise ValueError(f"Unknown metric type: {data['metric_type_slug']}")

        measurement = Measurement(
            user_id=payload.user_id,
            metric_type_id=metric_type.id,
            source_id=payload.source_id,
            value_num=data["value"],
            unit=data.get("unit", metric_type.default_unit),
            measured_at=datetime.fromisoformat(data["measured_at"]),
            recorded_at=payload.ingested_at,
            aggregation_level="spot",
            raw_payload_id=payload.id,
        )
        await self.measurement_repo.create(measurement)

    async def _parse_hc900_scale(self, payload: RawPayload) -> None:
        """Extract all HC900 scale measurements from a raw payload.

        The parser re-decodes from the stored raw bytes
        (``raw_mfr_weight_hex`` / ``raw_mfr_impedance_hex``) whenever they're
        present, so re-running this over a v1 payload produces the full v2
        metric set.  If raw bytes are missing (shouldn't happen for scanner
        output, but possible for hand-crafted payloads), it falls back to
        the already-decoded dict at ``payload_json['decoded']`` and persists
        only the subset of fields that are present — never fabricating
        values.

        Metrics emitted (18 total):

        Primary (is_derived=false, 2):
            weight, impedance_adc

        Derived, impedance-independent (is_derived=true, 2):
            bmi, bmr  — computed from weight + profile; persisted even on
            weight-only readings.

        Derived, impedance-dependent (is_derived=true, 14):
            body_fat_pct, fat_free_mass_kg, fat_mass_kg,
            skeletal_muscle_mass_kg, skeletal_muscle_pct,
            muscle_mass_kg, muscle_pct,
            water_mass_kg, water_pct,
            protein_mass_kg, protein_pct,
            bone_mass_kg, ffmi, fmi.
        """
        data = payload.payload_json
        measured_at = datetime.fromisoformat(data["measured_at"])

        source = await self.lookup_repo.get_data_source_by_slug("hc900_ble")
        if not source:
            raise ValueError(
                "Data source 'hc900_ble' not found. Run: alembic upgrade head"
            )

        values = self._extract_hc900_metrics(data)

        measurements: list[Measurement] = []
        for metric_slug, (value, unit, is_derived) in values.items():
            if value is None:
                continue
            metric_type = await self.lookup_repo.get_metric_type_by_slug(metric_slug)
            if not metric_type:
                logger.warning(
                    "[hc900] metric_type %r not in DB — skipping. "
                    "Run: alembic upgrade head",
                    metric_slug,
                )
                continue
            measurements.append(
                Measurement(
                    user_id=payload.user_id,
                    metric_type_id=metric_type.id,
                    source_id=source.id,
                    value_num=value,
                    unit=unit,
                    measured_at=measured_at,
                    recorded_at=payload.ingested_at,
                    aggregation_level="spot",
                    is_derived=is_derived,
                    raw_payload_id=payload.id,
                )
            )

        if measurements:
            await self.measurement_repo.create_many(measurements)

    @staticmethod
    def _extract_hc900_metrics(
        data: dict,
    ) -> dict[str, tuple[float | int | None, str, bool]]:
        """Resolve the 18-metric map for an HC900 payload.

        Returns a dict keyed by metric_type slug with tuples of
        ``(value, unit, is_derived)``.  Values are None when the underlying
        reading doesn't support them (e.g., no impedance → body_fat_pct is None).

        Prefers re-decoding from raw bytes (source of truth) and falls back
        to the pre-decoded dict when raw bytes are absent.
        """
        decoded = IngestionService._decoded_view(data)
        return {
            # Primary
            "weight": (decoded.get("weight_kg"), "kg", False),
            "impedance_adc": (decoded.get("impedance_adc"), "adc", False),
            # Derived — impedance-independent
            "bmi": (decoded.get("bmi"), "kg/m²", True),
            "bmr": (decoded.get("bmr"), "kcal", True),
            # Derived — impedance-dependent
            "body_fat_pct": (decoded.get("body_fat_pct"), "%", True),
            "fat_free_mass_kg": (decoded.get("fat_free_mass_kg"), "kg", True),
            "fat_mass_kg": (decoded.get("fat_mass_kg"), "kg", True),
            "skeletal_muscle_mass_kg": (
                decoded.get("skeletal_muscle_mass_kg"),
                "kg",
                True,
            ),
            "skeletal_muscle_pct": (decoded.get("skeletal_muscle_pct"), "%", True),
            "muscle_mass_kg": (decoded.get("muscle_mass_kg"), "kg", True),
            "muscle_pct": (decoded.get("muscle_pct"), "%", True),
            "water_mass_kg": (decoded.get("water_mass_kg"), "kg", True),
            "water_pct": (decoded.get("water_pct"), "%", True),
            "protein_mass_kg": (decoded.get("protein_mass_kg"), "kg", True),
            "protein_pct": (decoded.get("protein_pct"), "%", True),
            "bone_mass_kg": (decoded.get("bone_mass_kg"), "kg", True),
            "ffmi": (decoded.get("ffmi"), "kg/m²", True),
            "fmi": (decoded.get("fmi"), "kg/m²", True),
        }

    @staticmethod
    def _decoded_view(data: dict) -> dict:
        """Return the 18-field decoded dict, preferring a live re-decode.

        Raw hex bytes are the source of truth.  When present, we re-run
        ``decode_hc900`` so v1 payloads pick up every v2 field.  Profile is
        taken from the ``user_profile_snapshot`` on the payload itself (the
        snapshot frozen at capture time).  When hex is absent we fall back
        to the stored decoded dict — the parser will persist only the
        fields that exist there without inventing anything.
        """
        hex_weight = data.get("raw_mfr_weight_hex")
        hex_imp = data.get("raw_mfr_impedance_hex")
        if not hex_weight:
            return dict(data.get("decoded") or {})

        profile = data.get("user_profile_snapshot") or {}
        height_cm = profile.get("height_cm")
        age = profile.get("age")
        sex = profile.get("sex")

        try:
            reading: DecodedReading = decode_hc900(
                hex_to_bytes(hex_weight),
                hex_to_bytes(hex_imp) if hex_imp else None,
                height_cm=height_cm,
                age=age,
                sex=sex,
            )
        except ValueError as e:
            # Malformed bytes or profile missing when impedance is present.
            # Surface via logger and fall back to whatever is in 'decoded';
            # the parser won't fabricate values for missing fields.
            logger.warning("[hc900] re-decode failed, using stored decoded: %s", e)
            return dict(data.get("decoded") or {})

        return reading.to_dict()

    async def _parse_garmin_connect_daily(self, payload: RawPayload) -> None:
        """Extract daily health metrics from a Garmin Connect daily summary payload.

        Expected payload_json structure (produced by scripts/sync_garmin.py):
        {
            "format_version": "garmin_connect_v1",
            "date":           "2026-04-15",
            "user_timezone":  "America/Sao_Paulo",
            "fetch_method":   "garminconnect_api",
            "stats": { ...raw get_stats() response... },
            "hrv":   { ...raw get_hrv_data() response... },
            "sleep": { ...raw get_sleep_data() response... }
        }

        Temporal semantics:
            measured_at = noon on `date` in the user's local timezone (stored as UTC).
            Daily aggregates have no single "instant" — noon is a neutral anchor that
            avoids midnight-boundary ambiguity (e.g., sleep data spanning two calendar
            dates in UTC). Re-syncing the same date is idempotent via external_id.

        Null safety:
            Any Garmin field can be None — device doesn't support it, or watch wasn't
            worn. Absent/null fields are silently skipped; the payload is still marked
            processed. No measurement is created for a null field.

        Persists measurements for (V1 scope):
            resting_hr, steps, active_calories, stress_level, spo2,
            respiratory_rate, body_battery, hrv_rmssd, sleep_duration, sleep_score
        """
        data = payload.payload_json
        date_str = data["date"]  # KeyError propagates → _process() marks payload failed
        tz_str = data.get("user_timezone") or "UTC"

        try:
            tz = ZoneInfo(tz_str)
        except (KeyError, ZoneInfoNotFoundError) as e:
            raise ValueError(f"Invalid user_timezone '{tz_str}': {e}") from e

        # Canonical timestamp: noon on the measured date in the user's local timezone.
        # Stable, unambiguous, and immune to UTC-day-boundary issues.
        measured_at = datetime.combine(
            date.fromisoformat(date_str),
            time(12, 0, 0),
            tzinfo=tz,
        )

        source = await self.lookup_repo.get_data_source_by_slug("garmin_connect")
        if not source:
            raise ValueError(
                "Data source 'garmin_connect' not found. Run: alembic upgrade head"
            )

        # Replace measurements from any prior snapshot for this logical date.
        # raw_payloads is append-only; each re-sync creates a new versioned row.
        # The curated layer always reflects the latest snapshot so intraday
        # updates (body battery, stress, HRV, sleep score) land on every refresh.
        # If this parse fails the savepoint rolls back, leaving prior data intact.
        await self.measurement_repo.delete_for_garmin_daily_snapshot(
            user_id=payload.user_id,
            source_id=source.id,
            logical_date=date_str,
            current_raw_payload_id=payload.id,
        )

        stats = data.get("stats") or {}
        hrv_data = data.get("hrv") or {}
        sleep_data = data.get("sleep") or {}

        hrv_summary = hrv_data.get("hrvSummary") or {}
        sleep_dto = sleep_data.get("dailySleepDTO") or {}
        sleep_seconds = sleep_dto.get("sleepTimeSeconds")
        sleep_score_block = (sleep_dto.get("sleepScores") or {}).get("overall") or {}

        raw_values: dict[str, tuple[object, str]] = {
            "resting_hr":       (stats.get("restingHeartRate"),           "bpm"),
            "steps":            (stats.get("totalSteps"),                 "steps"),
            "active_calories":  (stats.get("activeKilocalories"),         "kcal"),
            "stress_level":     (stats.get("averageStressLevel"),         "score"),
            "spo2":             (stats.get("averageSpo2"),                "%"),
            "respiratory_rate": (stats.get("avgWakingRespirationValue"),  "brpm"),
            "body_battery":     (stats.get("bodyBatteryMostRecentValue"), "score"),
            "hrv_rmssd":        (hrv_summary.get("lastNightAvg"),         "ms"),
            "sleep_duration":   (
                round(sleep_seconds / 60) if sleep_seconds is not None else None,
                "min",
            ),
            "sleep_score":      (sleep_score_block.get("value"),          "score"),
        }

        measurements = []
        for metric_slug, (value, unit) in raw_values.items():
            if value is None:
                continue
            metric_type = await self.lookup_repo.get_metric_type_by_slug(metric_slug)
            if not metric_type:
                continue
            measurements.append(
                Measurement(
                    user_id=payload.user_id,
                    metric_type_id=metric_type.id,
                    source_id=source.id,
                    value_num=value,
                    unit=unit,
                    measured_at=measured_at,
                    recorded_at=payload.ingested_at,
                    aggregation_level="daily",
                    raw_payload_id=payload.id,
                )
            )

        if measurements:
            await self.measurement_repo.create_many(measurements)

    async def reprocess_pending(self, limit: int = 100) -> int:
        """Reprocess all pending payloads. Returns count of processed."""
        pending = await self.raw_repo.list_pending(limit=limit)
        processed = 0
        for payload in pending:
            await self._process(payload)
            processed += 1
        await self.session.commit()
        return processed
