"""Garmin Connect integration tests.

Covers the garmin_connect_daily ingestion pipeline:
  A. Parser — full payload → 10 measurements with correct values/units
  B. Temporal semantics — measured_at = noon in user's local timezone (UTC-stored)
  C. Null safety — absent/null Garmin fields skipped, payload still processed
  D. Deduplication — re-ingesting the same date is idempotent
  E. Error paths — missing source, missing date key
  F. Sync helpers — build_external_id, date_range, load_config (pure unit tests)

Fixture payloads are representative of real Garmin Connect API responses
(get_stats / get_hrv_data / get_sleep_data) for a healthy training day.

Temporal invariant verified:
  user_timezone = "America/Sao_Paulo" (UTC-3, Brazil dropped DST in 2019)
  date = "2026-04-15"
  measured_at = 2026-04-15T12:00:00-03:00 = 2026-04-15T15:00:00Z
"""

import sys
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.data_source import DataSource
from app.models.measurement import Measurement
from app.models.metric_type import MetricType
from app.models.raw_payload import RawPayload
from app.models.user import User
from app.schemas.raw_payload import RawPayloadIngest
from app.services.ingestion import IngestionService

sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))


# ── Representative payload fixtures ──────────────────────────────────────────

_STATS = {
    "calendarDate": "2026-04-15",
    "totalKilocalories": 2610,
    "activeKilocalories": 560,
    "totalSteps": 9842,
    "restingHeartRate": 56,
    "minHeartRate": 50,
    "maxHeartRate": 142,
    "averageStressLevel": 28,
    "maxStressLevel": 61,
    "bodyBatteryChargedValue": 95,
    "bodyBatteryDrainedValue": 72,
    "bodyBatteryMostRecentValue": 58,
    "averageSpo2": 96,
    "lowestSpo2": 91,
    "avgWakingRespirationValue": 14.2,
}

_HRV = {
    "hrvSummary": {
        "calendarDate": "2026-04-15",
        "weeklyAvg": 48,
        "lastNightAvg": 44,
        "lastNight5MinHigh": 62,
        "baseline": {
            "lowUpper": 40,
            "balancedLow": 44,
            "balancedUpper": 57,
            "markerValue": 0.0,
        },
        "status": "BALANCED",
        "feedbackPhrase": "HRV_BALANCED_2",
    },
    "hrvReadings": [
        {"hrvValue": 48, "readingTimeGmt": "2026-04-15T02:05:00Z"},
        {"hrvValue": 44, "readingTimeGmt": "2026-04-15T04:10:00Z"},
        {"hrvValue": 41, "readingTimeGmt": "2026-04-15T06:30:00Z"},
    ],
    "startTimestampGmt": "2026-04-15T02:00:00Z",
    "endTimestampGmt": "2026-04-15T09:00:00Z",
}

_SLEEP = {
    "dailySleepDTO": {
        "calendarDate": "2026-04-15",
        "sleepTimeSeconds": 26100,   # 435 min = 7h 15m
        "nRemSleepSeconds": 5400,
        "remSleepSeconds": 7200,
        "deepSleepSeconds": 5400,
        "lightSleepSeconds": 8100,
        "sleepScores": {
            "overall": {"value": 79, "qualifier": "FAIR"},
            "recovery": {"value": 74},
            "nap": None,
        },
        "averageSpO2Value": 96.2,
        "averageRespirationValue": 13.8,
    }
}

_FULL_PAYLOAD_JSON: dict = {
    "format_version": "garmin_connect_v1",
    "date": "2026-04-15",
    "user_timezone": "America/Sao_Paulo",
    "fetch_method": "garminconnect_api",
    "stats": _STATS,
    "hrv": _HRV,
    "sleep": _SLEEP,
}

_EXTERNAL_ID = "garmin_connect_2026-04-15"


def _ingest_request(
    user: User,
    payload_json: dict,
    external_id: str | None = _EXTERNAL_ID,
) -> RawPayloadIngest:
    return RawPayloadIngest(
        user_id=user.id,
        source_slug="garmin_connect",
        external_id=external_id,
        payload_type="garmin_connect_daily",
        payload_json=payload_json,
    )


# ── A. Parser — full payload ──────────────────────────────────────────────────


class TestGarminConnectParser:
    async def test_full_payload_creates_10_measurements(
        self, db: AsyncSession, user: User
    ):
        """All 10 V1 metrics are extracted from a complete daily payload."""
        svc = IngestionService(db)
        payload = await svc.ingest(_ingest_request(user, _FULL_PAYLOAD_JSON))

        assert payload.processing_status == "processed"
        assert payload.processed_at is not None

        result = await db.execute(
            select(Measurement).where(Measurement.raw_payload_id == payload.id)
        )
        assert len(list(result.scalars())) == 10

    async def test_measurement_values_spot_check(
        self, db: AsyncSession, user: User
    ):
        """Spot-check three key metric values and units."""
        svc = IngestionService(db)
        payload = await svc.ingest(_ingest_request(user, _FULL_PAYLOAD_JSON))

        result = await db.execute(
            select(Measurement).where(Measurement.raw_payload_id == payload.id)
        )
        by_slug: dict[str, Measurement] = {}
        for m in result.scalars():
            mt = await db.get(MetricType, m.metric_type_id)
            by_slug[mt.slug] = m

        assert round(by_slug["resting_hr"].value_num, 0) == Decimal("56")
        assert by_slug["resting_hr"].unit == "bpm"

        assert round(by_slug["hrv_rmssd"].value_num, 0) == Decimal("44")
        assert by_slug["hrv_rmssd"].unit == "ms"

        assert round(by_slug["body_battery"].value_num, 0) == Decimal("58")
        assert by_slug["body_battery"].unit == "score"

        assert round(by_slug["sleep_duration"].value_num, 0) == Decimal("435")
        assert by_slug["sleep_duration"].unit == "min"

        assert round(by_slug["sleep_score"].value_num, 0) == Decimal("79")

    async def test_aggregation_level_is_daily(
        self, db: AsyncSession, user: User
    ):
        """Garmin daily metrics use aggregation_level='daily'."""
        svc = IngestionService(db)
        payload = await svc.ingest(_ingest_request(user, _FULL_PAYLOAD_JSON))

        result = await db.execute(
            select(Measurement).where(Measurement.raw_payload_id == payload.id)
        )
        for m in result.scalars():
            assert m.aggregation_level == "daily"

    async def test_source_is_garmin_connect(
        self, db: AsyncSession, user: User
    ):
        """All measurements are attributed to the garmin_connect data source."""
        svc = IngestionService(db)
        payload = await svc.ingest(_ingest_request(user, _FULL_PAYLOAD_JSON))

        result = await db.execute(
            select(Measurement).where(Measurement.raw_payload_id == payload.id)
        )
        for m in result.scalars():
            source = await db.get(DataSource, m.source_id)
            assert source.slug == "garmin_connect"

    async def test_raw_payload_id_traced(self, db: AsyncSession, user: User):
        """Every measurement FK-references the raw payload that produced it."""
        svc = IngestionService(db)
        payload = await svc.ingest(_ingest_request(user, _FULL_PAYLOAD_JSON))

        result = await db.execute(
            select(Measurement).where(Measurement.raw_payload_id == payload.id)
        )
        for m in result.scalars():
            assert m.raw_payload_id == payload.id
            assert m.user_id == user.id


# ── B. Temporal semantics ─────────────────────────────────────────────────────


class TestGarminMeasuredAt:
    async def test_measured_at_is_noon_in_user_timezone(
        self, db: AsyncSession, user: User
    ):
        """measured_at = noon on the measured date in the user's local timezone.

        America/Sao_Paulo is UTC-3 year-round (Brazil dropped DST in 2019).
        Noon 2026-04-15 in Sao Paulo = 2026-04-15T15:00:00Z.
        """
        svc = IngestionService(db)
        payload = await svc.ingest(_ingest_request(user, _FULL_PAYLOAD_JSON))

        result = await db.execute(
            select(Measurement).where(Measurement.raw_payload_id == payload.id)
        )
        expected = datetime(2026, 4, 15, 15, 0, 0, tzinfo=UTC)
        for m in result.scalars():
            assert m.measured_at == expected

    async def test_measured_at_utc_timezone_stays_at_noon_utc(
        self, db: AsyncSession, user: User
    ):
        """When user_timezone is UTC, noon is noon UTC (15:00Z = noon+0:00)."""
        utc_payload = {**_FULL_PAYLOAD_JSON, "user_timezone": "UTC"}
        svc = IngestionService(db)
        payload = await svc.ingest(
            _ingest_request(user, utc_payload, external_id="garmin_connect_2026-04-15-utc")
        )

        result = await db.execute(
            select(Measurement).where(Measurement.raw_payload_id == payload.id)
        )
        expected = datetime(2026, 4, 15, 12, 0, 0, tzinfo=UTC)
        for m in result.scalars():
            assert m.measured_at == expected

    async def test_measured_at_missing_timezone_defaults_to_utc(
        self, db: AsyncSession, user: User
    ):
        """Payload without user_timezone field falls back to UTC noon."""
        no_tz_payload = {k: v for k, v in _FULL_PAYLOAD_JSON.items() if k != "user_timezone"}
        svc = IngestionService(db)
        payload = await svc.ingest(
            _ingest_request(user, no_tz_payload, external_id="garmin_connect_2026-04-15-notz")
        )

        assert payload.processing_status == "processed"
        result = await db.execute(
            select(Measurement).where(Measurement.raw_payload_id == payload.id)
        )
        expected = datetime(2026, 4, 15, 12, 0, 0, tzinfo=UTC)
        for m in result.scalars():
            assert m.measured_at == expected


# ── C. Null safety ────────────────────────────────────────────────────────────


class TestGarminNullSafety:
    async def test_null_hrv_skipped(self, db: AsyncSession, user: User):
        """HRV lastNightAvg=null → hrv_rmssd measurement absent, others intact."""
        hrv_null = {
            "hrvSummary": {**_HRV["hrvSummary"], "lastNightAvg": None},
            "hrvReadings": _HRV["hrvReadings"],
        }
        payload_json = {**_FULL_PAYLOAD_JSON, "hrv": hrv_null}
        svc = IngestionService(db)
        payload = await svc.ingest(
            _ingest_request(user, payload_json, external_id="garmin_connect_2026-04-15-nohrv")
        )

        assert payload.processing_status == "processed"
        result = await db.execute(
            select(Measurement).where(Measurement.raw_payload_id == payload.id)
        )
        slugs = set()
        for m in result.scalars():
            mt = await db.get(MetricType, m.metric_type_id)
            slugs.add(mt.slug)

        assert "hrv_rmssd" not in slugs
        assert "resting_hr" in slugs   # other metrics unaffected

    async def test_null_stats_restinghr_skipped(self, db: AsyncSession, user: User):
        """restingHeartRate=null → resting_hr skipped, other stats unaffected."""
        stats_no_rhr = {**_STATS, "restingHeartRate": None}
        payload_json = {**_FULL_PAYLOAD_JSON, "stats": stats_no_rhr}
        svc = IngestionService(db)
        payload = await svc.ingest(
            _ingest_request(user, payload_json, external_id="garmin_connect_2026-04-15-norhr")
        )

        result = await db.execute(
            select(Measurement).where(Measurement.raw_payload_id == payload.id)
        )
        slugs = set()
        for m in result.scalars():
            mt = await db.get(MetricType, m.metric_type_id)
            slugs.add(mt.slug)

        assert "resting_hr" not in slugs
        assert "steps" in slugs

    async def test_empty_endpoints_produces_no_measurements(
        self, db: AsyncSession, user: User
    ):
        """All three endpoints returning {} → zero measurements, status=processed."""
        empty_payload = {
            "format_version": "garmin_connect_v1",
            "date": "2026-04-15",
            "user_timezone": "UTC",
            "fetch_method": "garminconnect_api",
            "stats": {},
            "hrv": {},
            "sleep": {},
        }
        svc = IngestionService(db)
        payload = await svc.ingest(
            _ingest_request(user, empty_payload, external_id="garmin_connect_2026-04-15-empty")
        )

        assert payload.processing_status == "processed"
        count = await db.scalar(
            select(func.count())
            .select_from(Measurement)
            .where(Measurement.raw_payload_id == payload.id)
        )
        assert count == 0


# ── D. Deduplication ─────────────────────────────────────────────────────────


class TestGarminDeduplication:
    async def test_same_date_returns_same_record(
        self, db: AsyncSession, user: User
    ):
        """Re-ingesting the same date returns the existing record unchanged."""
        svc = IngestionService(db)
        first = await svc.ingest(_ingest_request(user, _FULL_PAYLOAD_JSON))
        second = await svc.ingest(_ingest_request(user, _FULL_PAYLOAD_JSON))
        assert first.id == second.id

    async def test_same_date_no_extra_raw_payload(
        self, db: AsyncSession, user: User
    ):
        """Exactly one raw_payload per external_id after two ingests."""
        svc = IngestionService(db)
        await svc.ingest(_ingest_request(user, _FULL_PAYLOAD_JSON))
        await svc.ingest(_ingest_request(user, _FULL_PAYLOAD_JSON))

        count = await db.scalar(
            select(func.count())
            .select_from(RawPayload)
            .where(RawPayload.external_id == _EXTERNAL_ID)
        )
        assert count == 1

    async def test_different_dates_are_independent(
        self, db: AsyncSession, user: User
    ):
        """Two different dates produce two independent raw_payloads."""
        svc = IngestionService(db)
        p1_json = {**_FULL_PAYLOAD_JSON, "date": "2026-04-14"}
        p2_json = {**_FULL_PAYLOAD_JSON, "date": "2026-04-15"}
        p1 = await svc.ingest(
            _ingest_request(user, p1_json, external_id="garmin_connect_2026-04-14")
        )
        p2 = await svc.ingest(
            _ingest_request(user, p2_json, external_id="garmin_connect_2026-04-15")
        )
        assert p1.id != p2.id


# ── E. Error paths ────────────────────────────────────────────────────────────


class TestGarminErrorPaths:
    async def test_missing_garmin_connect_source_raises_clear_error(
        self, db: AsyncSession, user: User
    ):
        """If garmin_connect source is absent (migrations not run), error names it."""
        await db.execute(
            delete(DataSource).where(DataSource.slug == "garmin_connect")
        )
        await db.flush()

        svc = IngestionService(db)
        with pytest.raises(ValueError, match="garmin_connect"):
            await svc.ingest(_ingest_request(user, _FULL_PAYLOAD_JSON))

    async def test_missing_date_key_marks_payload_failed(
        self, db: AsyncSession, user: User
    ):
        """Payload missing the required 'date' key → raw preserved, status=failed."""
        no_date = {k: v for k, v in _FULL_PAYLOAD_JSON.items() if k != "date"}
        svc = IngestionService(db)
        payload = await svc.ingest(_ingest_request(user, no_date, external_id=None))

        assert payload.processing_status == "failed"
        assert payload.error_message is not None

        raw = await db.get(RawPayload, payload.id)
        assert raw is not None

        count = await db.scalar(
            select(func.count())
            .select_from(Measurement)
            .where(Measurement.raw_payload_id == payload.id)
        )
        assert count == 0

    async def test_invalid_timezone_marks_payload_failed(
        self, db: AsyncSession, user: User
    ):
        """Unknown timezone string → raw preserved, status=failed with informative error."""
        bad_tz_payload = {**_FULL_PAYLOAD_JSON, "user_timezone": "Not/ATimezone"}
        svc = IngestionService(db)
        payload = await svc.ingest(
            _ingest_request(user, bad_tz_payload, external_id=None)
        )

        assert payload.processing_status == "failed"
        assert "Not/ATimezone" in (payload.error_message or "")


# ── F. Sync helpers (pure unit tests — no DB) ─────────────────────────────────


class TestSyncHelpers:
    def test_build_external_id_format(self):
        from sync_garmin import build_external_id

        assert build_external_id("2026-04-15") == "garmin_connect_2026-04-15"
        assert build_external_id("2026-01-01") == "garmin_connect_2026-01-01"

    def test_date_range_consecutive(self):
        from sync_garmin import date_range

        result = date_range(date(2026, 4, 13), date(2026, 4, 15))
        assert result == ["2026-04-13", "2026-04-14", "2026-04-15"]

    def test_date_range_single_day(self):
        from sync_garmin import date_range

        assert date_range(date(2026, 4, 15), date(2026, 4, 15)) == ["2026-04-15"]

    def test_date_range_empty_when_start_after_end(self):
        from sync_garmin import date_range

        assert date_range(date(2026, 4, 16), date(2026, 4, 15)) == []

    def test_build_payload_structure(self):
        from sync_garmin import build_payload

        p = build_payload("2026-04-15", "America/Sao_Paulo", _STATS, _HRV, _SLEEP)
        assert p["format_version"] == "garmin_connect_v1"
        assert p["date"] == "2026-04-15"
        assert p["user_timezone"] == "America/Sao_Paulo"
        assert p["fetch_method"] == "garminconnect_api"
        assert p["stats"] is _STATS
        assert p["hrv"] is _HRV
        assert p["sleep"] is _SLEEP

    def test_load_config_from_file(self, tmp_path):
        import json

        from sync_garmin import load_config

        cfg_file = tmp_path / "garmin_config.json"
        cfg_file.write_text(json.dumps({
            "email": "test@example.com",
            "password": "secret",
            "token_store": "/tmp/tokens",
            "user_timezone": "America/Sao_Paulo",
        }))

        import sync_garmin as _m
        original = _m._CONFIG_PATH
        try:
            _m._CONFIG_PATH = cfg_file
            config = load_config()
        finally:
            _m._CONFIG_PATH = original

        assert config["email"] == "test@example.com"
        assert config["user_timezone"] == "America/Sao_Paulo"

    def test_load_config_cli_overrides_file(self, tmp_path):
        import json

        from sync_garmin import load_config

        cfg_file = tmp_path / "garmin_config.json"
        cfg_file.write_text(json.dumps({
            "email": "old@example.com",
            "password": "old-secret",
            "token_store": "/tmp/tokens",
            "user_timezone": "UTC",
        }))

        import sync_garmin as _m
        original = _m._CONFIG_PATH
        try:
            _m._CONFIG_PATH = cfg_file
            config = load_config(email="new@example.com", user_timezone="Europe/London")
        finally:
            _m._CONFIG_PATH = original

        assert config["email"] == "new@example.com"
        assert config["user_timezone"] == "Europe/London"
        assert config["password"] == "old-secret"   # not overridden

    def test_load_config_missing_fields_raises_valueerror(self, tmp_path):
        import sync_garmin as _m
        from sync_garmin import load_config
        original = _m._CONFIG_PATH
        try:
            _m._CONFIG_PATH = tmp_path / "nonexistent.json"
            with pytest.raises(ValueError, match="Missing config fields"):
                load_config()
        finally:
            _m._CONFIG_PATH = original
