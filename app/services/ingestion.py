"""Raw → Curated ingestion pipeline.

Receives a raw payload, persists it, then delegates to domain-specific
parsers that extract curated records (measurements, workouts, etc.)
with FK traceability back to the raw payload.
"""

from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.measurement import Measurement
from app.models.raw_payload import RawPayload
from app.repositories.lookup import LookupRepository
from app.repositories.measurement import MeasurementRepository
from app.repositories.raw_payload import RawPayloadRepository
from app.schemas.raw_payload import RawPayloadIngest


class IngestionService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.raw_repo = RawPayloadRepository(session)
        self.measurement_repo = MeasurementRepository(session)
        self.lookup_repo = LookupRepository(session)

    async def ingest(self, data: RawPayloadIngest) -> RawPayload:
        """Ingest a raw payload: persist it, then attempt to process it into curated data."""
        source = await self.lookup_repo.get_data_source_by_slug(data.source_slug)
        if not source:
            raise ValueError(f"Unknown data source: {data.source_slug}")

        # Deduplicate by external_id
        if data.external_id:
            existing = await self.raw_repo.find_by_external_id(source.id, data.external_id)
            if existing:
                return existing

        payload = RawPayload(
            user_id=data.user_id,
            source_id=source.id,
            external_id=data.external_id,
            payload_type=data.payload_type,
            payload_json=data.payload_json,
        )
        await self.raw_repo.create(payload)

        # Attempt processing
        await self._process(payload)
        await self.session.commit()
        return payload

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
        """Extract weight and body-fat measurements from an HC900 BLE scale payload.

        Expected payload_json structure (produced by scripts/import_scale.py):
        {
            "format_version": "hc900_ble_v1",
            "device_mac":     "A0:91:5C:92:CF:17",
            "captured_at":    "2026-04-15T07:30:15Z",
            "measured_at":    "2026-04-15T07:30:15Z",
            "capture_method": "bleak_scan",
            "raw_mfr_weight_hex":    "...",
            "raw_mfr_impedance_hex": "...",   // optional
            "decoded": {
                "weight_kg":    74.8,
                "body_fat_pct": 18.3,         // optional — only when impedance captured
                "impedance_adc": 47450,       // optional
                "muscle_pct":   62.5,         // optional
                "bone_mass_kg": 3.2,          // optional
                "water_pct":    60.1,         // optional
                "bmr":          1820,         // optional
                "decoder_version": "hc900_ble_v1"
            },
            "user_profile_snapshot": {"height_cm": 175, "age": 30, "sex": 1}
        }

        Persists measurements for:
          - weight (always present)
          - body_fat_pct (only when decoded.body_fat_pct is present)
        """
        data = payload.payload_json
        decoded = data.get("decoded", {})
        measured_at = datetime.fromisoformat(data["measured_at"])

        source = await self.lookup_repo.get_data_source_by_slug("hc900_ble")
        if not source:
            raise ValueError(
                "Data source 'hc900_ble' not found. Run: alembic upgrade head"
            )

        # V1 scope: weight + body_fat_pct only.
        metrics_map = {
            "weight_kg": ("weight", "kg"),
            "body_fat_pct": ("body_fat_pct", "%"),
        }

        measurements = []
        for decoded_key, (metric_slug, unit) in metrics_map.items():
            value = decoded.get(decoded_key)
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
                    aggregation_level="spot",
                    raw_payload_id=payload.id,
                )
            )

        if measurements:
            await self.measurement_repo.create_many(measurements)

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
