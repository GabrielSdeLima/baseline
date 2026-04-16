"""HC900 BLE scale integration tests.

Covers the full HC900 ingestion pipeline:
  A. Full pipeline — real representative payload → raw_payloads + 2 measurements
  B. Payload persistence — raw bytes, format_version, device_mac preserved verbatim
  C. Measurements traceability — raw_payload_id FK, correct values/units/aggregation
  D. Weight-only path — no impedance → only weight measurement, no body_fat_pct
  E. Deduplication — re-ingest same external_id → idempotent (same record, no new rows)
  F. Error paths — missing hc900_ble source, malformed payload (missing measured_at)
  G. Profile helpers — calculate_age, build_external_id, load_profile (pure unit tests)

Fixture data is derived from a real btsnoop_hci.log capture (2026-04-15):
  device  : HC900 / FG260RB, MAC A0:91:5C:92:CF:17
  weight  : 75.840 kg  (stable flag 0x20, 5 consecutive identical weight triples)
  impedance ADC : 527  (idle-phase reference — known limitation; see docs)
  external_id   : hc900_a0915c92cf17_20260415T0730_75840_527
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
from app.models.raw_payload import RawPayload
from app.models.user import User
from app.schemas.raw_payload import RawPayloadIngest
from app.services.ingestion import IngestionService

# Allow direct import of script helpers (scripts/ is not a package)
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))


# ── Shared payload fixtures ───────────────────────────────────────────────────

# Decoded output from the Dart CLI for the btsnoop capture.
_DECODED_FULL = {
    "weight_kg": 75.84,
    "decoder_version": "hc900_ble_v1",
    "impedance_adc": 527,
    "body_fat_pct": 24.4,
    "muscle_pct": 38.4,
    "bone_mass_kg": 3.2,
    "water_pct": 57.8,
    "bmr": 1889,
}

# Full hc900_ble_v1 payload — mirrors what import_scale.py::build_raw_payload produces.
# raw_mfr_*_hex values are the actual bytes from the btsnoop HCI log.
_FULL_PAYLOAD_JSON: dict = {
    "format_version": "hc900_ble_v1",
    "device_mac": "A0:91:5C:92:CF:17",
    "captured_at": "2026-04-15T07:30:00+00:00",
    "measured_at": "2026-04-15T07:30:00+00:00",
    "_measured_at_note": (
        "V1: measured_at == captured_at. Future versions may allow manual time override."
    ),
    "capture_method": "bleak_scan",
    "raw_mfr_weight_hex": "aca017cf925c91a0202d88e00da2",
    "raw_mfr_impedance_hex": "aca017cf925c91a0a2afa0a206b9",
    "decoded": _DECODED_FULL,
    "user_profile_snapshot": {
        "height_cm": 180,
        "birth_date": "1991-08-15",
        "age": 34,
        "sex": 1,
    },
}

# Weight-only variant: scale sent weight packet but no impedance packet before timeout.
_WEIGHT_ONLY_PAYLOAD_JSON: dict = {
    "format_version": "hc900_ble_v1",
    "device_mac": "A0:91:5C:92:CF:17",
    "captured_at": "2026-04-15T07:31:00+00:00",
    "measured_at": "2026-04-15T07:31:00+00:00",
    "_measured_at_note": "V1: measured_at == captured_at.",
    "capture_method": "bleak_scan",
    "raw_mfr_weight_hex": "aca017cf925c91a0202d88e00da2",
    "raw_mfr_impedance_hex": None,
    "decoded": {
        "weight_kg": 75.84,
        "decoder_version": "hc900_ble_v1",
        # body_fat_pct intentionally absent — no impedance available
    },
    "user_profile_snapshot": {
        "height_cm": 180,
        "birth_date": "1991-08-15",
        "age": 34,
        "sex": 1,
    },
}

_EXTERNAL_ID = "hc900_a0915c92cf17_20260415T0730_75840_527"


def _ingest_request(
    user: User, payload_json: dict, external_id: str | None = _EXTERNAL_ID
) -> RawPayloadIngest:
    return RawPayloadIngest(
        user_id=user.id,
        source_slug="hc900_ble",
        external_id=external_id,
        payload_type="hc900_scale",
        payload_json=payload_json,
    )


# ── A. Full pipeline ──────────────────────────────────────────────────────────


class TestHC900Pipeline:
    async def test_full_payload_creates_two_measurements(
        self, db: AsyncSession, user: User
    ):
        """Full HC900 payload (weight + body_fat_pct) → 2 measurements, status processed."""
        svc = IngestionService(db)
        payload = await svc.ingest(_ingest_request(user, _FULL_PAYLOAD_JSON))

        assert payload.processing_status == "processed"
        assert payload.processed_at is not None

        result = await db.execute(
            select(Measurement).where(Measurement.raw_payload_id == payload.id)
        )
        measurements = list(result.scalars().all())
        assert len(measurements) == 2

    async def test_measurement_values_and_units(
        self, db: AsyncSession, user: User
    ):
        """Decoded weight and body_fat_pct land in measurements with correct values/units."""
        svc = IngestionService(db)
        payload = await svc.ingest(_ingest_request(user, _FULL_PAYLOAD_JSON))

        result = await db.execute(
            select(Measurement).where(Measurement.raw_payload_id == payload.id)
        )
        by_slug: dict[str, Measurement] = {}
        for m in result.scalars():
            # Resolve metric slug via the MetricType FK (loaded eagerly through session)
            from app.models.metric_type import MetricType
            mt = await db.get(MetricType, m.metric_type_id)
            by_slug[mt.slug] = m

        assert "weight" in by_slug
        assert "body_fat_pct" in by_slug

        weight_m = by_slug["weight"]
        assert round(weight_m.value_num, 2) == Decimal("75.84")
        assert weight_m.unit == "kg"
        assert weight_m.aggregation_level == "spot"

        bf_m = by_slug["body_fat_pct"]
        assert round(bf_m.value_num, 1) == Decimal("24.4")
        assert bf_m.unit == "%"
        assert bf_m.aggregation_level == "spot"

    async def test_measured_at_preserved_on_measurements(
        self, db: AsyncSession, user: User
    ):
        """Measurements inherit measured_at from the payload, not ingestion time."""
        svc = IngestionService(db)
        payload = await svc.ingest(_ingest_request(user, _FULL_PAYLOAD_JSON))

        result = await db.execute(
            select(Measurement).where(Measurement.raw_payload_id == payload.id)
        )
        expected = datetime(2026, 4, 15, 7, 30, 0, tzinfo=UTC)
        for m in result.scalars():
            assert m.measured_at == expected


# ── B. Payload persistence ────────────────────────────────────────────────────


class TestHC900PayloadPersistence:
    async def test_raw_payload_fields_preserved(
        self, db: AsyncSession, user: User
    ):
        """Audit fields (device_mac, format_version, raw hex bytes) survive round-trip."""
        svc = IngestionService(db)
        payload = await svc.ingest(_ingest_request(user, _FULL_PAYLOAD_JSON))

        raw = await db.get(RawPayload, payload.id)
        assert raw is not None
        data = raw.payload_json
        assert data["format_version"] == "hc900_ble_v1"
        assert data["device_mac"] == "A0:91:5C:92:CF:17"
        assert data["capture_method"] == "bleak_scan"
        assert data["raw_mfr_weight_hex"] == "aca017cf925c91a0202d88e00da2"
        assert data["raw_mfr_impedance_hex"] == "aca017cf925c91a0a2afa0a206b9"

    async def test_raw_payload_type_and_source(
        self, db: AsyncSession, user: User
    ):
        """payload_type and source_slug are stored correctly on the raw record."""
        svc = IngestionService(db)
        payload = await svc.ingest(_ingest_request(user, _FULL_PAYLOAD_JSON))

        raw = await db.get(RawPayload, payload.id)
        assert raw.payload_type == "hc900_scale"

        from app.models.data_source import DataSource
        source = await db.get(DataSource, raw.source_id)
        assert source.slug == "hc900_ble"

    async def test_raw_payload_id_traced_to_measurements(
        self, db: AsyncSession, user: User
    ):
        """Every measurement FK-references the exact raw_payload that produced it."""
        svc = IngestionService(db)
        payload = await svc.ingest(_ingest_request(user, _FULL_PAYLOAD_JSON))

        result = await db.execute(
            select(Measurement).where(Measurement.raw_payload_id == payload.id)
        )
        for m in result.scalars():
            assert m.raw_payload_id == payload.id
            assert m.user_id == user.id


# ── C. Weight-only path ───────────────────────────────────────────────────────


class TestHC900WeightOnly:
    async def test_weight_only_creates_one_measurement(
        self, db: AsyncSession, user: User
    ):
        """When impedance is absent from the payload, only weight is created (no body_fat_pct)."""
        svc = IngestionService(db)
        payload = await svc.ingest(
            _ingest_request(
                user,
                _WEIGHT_ONLY_PAYLOAD_JSON,
                external_id="hc900_a0915c92cf17_20260415T0731_75840_x",
            )
        )

        assert payload.processing_status == "processed"

        result = await db.execute(
            select(Measurement).where(Measurement.raw_payload_id == payload.id)
        )
        measurements = list(result.scalars().all())
        assert len(measurements) == 1

        from app.models.metric_type import MetricType
        mt = await db.get(MetricType, measurements[0].metric_type_id)
        assert mt.slug == "weight"

    async def test_weight_only_value_correct(
        self, db: AsyncSession, user: User
    ):
        """Weight-only measurement value is correct."""
        svc = IngestionService(db)
        payload = await svc.ingest(
            _ingest_request(
                user,
                _WEIGHT_ONLY_PAYLOAD_JSON,
                external_id="hc900_a0915c92cf17_20260415T0731_75840_x",
            )
        )

        result = await db.execute(
            select(Measurement).where(Measurement.raw_payload_id == payload.id)
        )
        m = result.scalars().first()
        assert round(m.value_num, 2) == Decimal("75.84")
        assert m.unit == "kg"


# ── D. Deduplication ─────────────────────────────────────────────────────────


class TestHC900Deduplication:
    async def test_duplicate_external_id_returns_same_record(
        self, db: AsyncSession, user: User
    ):
        """Re-ingesting the same external_id returns the existing record unchanged."""
        svc = IngestionService(db)
        first = await svc.ingest(_ingest_request(user, _FULL_PAYLOAD_JSON))
        second = await svc.ingest(_ingest_request(user, _FULL_PAYLOAD_JSON))

        assert first.id == second.id

    async def test_duplicate_does_not_create_extra_raw_payload(
        self, db: AsyncSession, user: User
    ):
        """Deduplication: exactly one raw_payload row for the given external_id."""
        svc = IngestionService(db)
        await svc.ingest(_ingest_request(user, _FULL_PAYLOAD_JSON))
        await svc.ingest(_ingest_request(user, _FULL_PAYLOAD_JSON))

        count = await db.scalar(
            select(func.count())
            .select_from(RawPayload)
            .where(RawPayload.external_id == _EXTERNAL_ID)
        )
        assert count == 1

    async def test_duplicate_does_not_create_extra_measurements(
        self, db: AsyncSession, user: User
    ):
        """Deduplication: measurement count stays at 2 after re-ingest."""
        svc = IngestionService(db)
        first = await svc.ingest(_ingest_request(user, _FULL_PAYLOAD_JSON))
        await svc.ingest(_ingest_request(user, _FULL_PAYLOAD_JSON))

        count = await db.scalar(
            select(func.count())
            .select_from(Measurement)
            .where(Measurement.raw_payload_id == first.id)
        )
        assert count == 2


# ── E. Error paths ────────────────────────────────────────────────────────────


class TestHC900ErrorPaths:
    async def test_missing_hc900_source_raises_clear_error(
        self, db: AsyncSession, user: User
    ):
        """If hc900_ble is absent from DB (migrations not run), the error names it clearly."""
        # Remove hc900_ble within this test's transaction; rolls back after.
        await db.execute(delete(DataSource).where(DataSource.slug == "hc900_ble"))
        await db.flush()

        svc = IngestionService(db)
        with pytest.raises(ValueError, match="hc900_ble"):
            await svc.ingest(_ingest_request(user, _FULL_PAYLOAD_JSON))

    async def test_missing_measured_at_preserves_raw_marks_failed(
        self, db: AsyncSession, user: User
    ):
        """Parser failure on malformed payload: raw is preserved, status='failed'."""
        malformed = {
            "format_version": "hc900_ble_v1",
            "device_mac": "A0:91:5C:92:CF:17",
            # "measured_at" intentionally missing — parser will raise KeyError
            "decoded": {"weight_kg": 75.84},
        }
        svc = IngestionService(db)
        payload = await svc.ingest(
            _ingest_request(user, malformed, external_id=None)
        )

        assert payload.processing_status == "failed"
        assert payload.error_message is not None

        # Raw payload is preserved for reprocessing
        raw = await db.get(RawPayload, payload.id)
        assert raw is not None

        # No measurements leaked despite parser failure
        count = await db.scalar(
            select(func.count())
            .select_from(Measurement)
            .where(Measurement.raw_payload_id == payload.id)
        )
        assert count == 0


# ── F. Profile helpers (pure unit tests — no DB) ──────────────────────────────


class TestProfileHelpers:
    def test_calculate_age_before_birthday(self):
        from import_scale import calculate_age

        birth = date(1991, 8, 15)
        # Queried on April 15 — birthday (Aug 15) not yet reached → 34
        assert calculate_age(birth, date(2026, 4, 15)) == 34

    def test_calculate_age_on_exact_birthday(self):
        from import_scale import calculate_age

        birth = date(1991, 8, 15)
        # Queried on exact birthday → 35
        assert calculate_age(birth, date(2026, 8, 15)) == 35

    def test_calculate_age_after_birthday(self):
        from import_scale import calculate_age

        birth = date(1991, 8, 15)
        # Queried after birthday in the same year → 35
        assert calculate_age(birth, date(2026, 12, 31)) == 35

    def test_build_external_id_full(self):
        from import_scale import build_external_id

        eid = build_external_id(
            device_mac="A0:91:5C:92:CF:17",
            measured_at=datetime(2026, 4, 15, 7, 30, tzinfo=UTC),
            weight_kg=75.84,
            impedance_adc=527,
        )
        assert eid == "hc900_a0915c92cf17_20260415T0730_75840_527"

    def test_build_external_id_weight_only(self):
        from import_scale import build_external_id

        eid = build_external_id(
            device_mac="A0:91:5C:92:CF:17",
            measured_at=datetime(2026, 4, 15, 7, 31, tzinfo=UTC),
            weight_kg=75.84,
            impedance_adc=None,
        )
        assert eid == "hc900_a0915c92cf17_20260415T0731_75840_x"

    def test_build_external_id_strips_colons_and_lowercases_mac(self):
        from import_scale import build_external_id

        eid = build_external_id(
            device_mac="A0:91:5C:92:CF:17",
            measured_at=datetime(2026, 1, 1, 0, 0, tzinfo=UTC),
            weight_kg=70.0,
            impedance_adc=None,
        )
        assert eid.startswith("hc900_a0915c92cf17_")

    def test_load_profile_from_file(self, tmp_path):
        import json

        from import_scale import load_profile

        profile_file = tmp_path / "scale_profile.json"
        profile_file.write_text(
            json.dumps({"height_cm": 180, "birth_date": "1991-08-15", "sex": 1})
        )

        # Monkey-patch the module-level _PROFILE_PATH
        import import_scale as _m
        original = _m._PROFILE_PATH
        try:
            _m._PROFILE_PATH = profile_file
            profile = load_profile()
        finally:
            _m._PROFILE_PATH = original

        assert profile["height_cm"] == 180
        assert profile["birth_date"] == "1991-08-15"
        assert profile["sex"] == 1

    def test_load_profile_cli_overrides_file(self, tmp_path):
        import json

        from import_scale import load_profile

        profile_file = tmp_path / "scale_profile.json"
        profile_file.write_text(
            json.dumps({"height_cm": 170, "birth_date": "1985-01-01", "sex": 2})
        )

        import import_scale as _m
        original = _m._PROFILE_PATH
        try:
            _m._PROFILE_PATH = profile_file
            profile = load_profile(height_cm=185, sex=1)
        finally:
            _m._PROFILE_PATH = original

        # CLI values override file values
        assert profile["height_cm"] == 185
        assert profile["sex"] == 1
        # File value preserved when not overridden
        assert profile["birth_date"] == "1985-01-01"

    def test_load_profile_missing_fields_raises_valueerror(self, tmp_path):
        import import_scale as _m
        from import_scale import load_profile
        original = _m._PROFILE_PATH
        # Point to a path that doesn't exist → no file, no CLI args → missing fields
        try:
            _m._PROFILE_PATH = tmp_path / "nonexistent.json"
            with pytest.raises(ValueError, match="Missing profile fields"):
                load_profile()
        finally:
            _m._PROFILE_PATH = original

    def test_load_profile_comments_stripped(self, tmp_path):
        import json

        from import_scale import load_profile

        profile_file = tmp_path / "scale_profile.json"
        profile_file.write_text(
            json.dumps({
                "_comment": "ignored",
                "height_cm": 175,
                "birth_date": "1990-05-20",
                "sex": 1,
            })
        )

        import import_scale as _m
        original = _m._PROFILE_PATH
        try:
            _m._PROFILE_PATH = profile_file
            profile = load_profile()
        finally:
            _m._PROFILE_PATH = original

        assert "_comment" not in profile
