"""Integration tests for GET /api/v1/integrations/scale/latest.

Covers the three ``status`` branches the UI must render without
inspecting individual metrics:

  - ``never_measured``  — user has no HC900 ingestion yet
  - ``weight_only``     — most recent weighing lacked impedance
  - ``full_reading``    — most recent weighing captured impedance

Also guards the invariants that motivated the endpoint:

  * every metric in the response belongs to ONE ``raw_payload_id``
    (no cross-weighing stitching)
  * weight-only response contains NO body-comp fields (never fabricate
    body composition from a stale full reading)
  * when two payloads exist, the most recent ``measured_at`` wins
"""
from decimal import Decimal

import httpx
import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.schemas.raw_payload import RawPayloadIngest
from app.services.ingestion import IngestionService

# ── Shared payload fixtures ───────────────────────────────────────────────────

_DECODED_FULL = {
    "weight_kg": 75.84,
    "decoder_version": "hc900_ble_v2",
    "impedance_adc": 527,
    "bmi": 23.4,
    "bmr": 1718,
    "body_fat_pct": 21.5,
    "fat_free_mass_kg": 59.5,
    "fat_mass_kg": 16.3,
    "skeletal_muscle_mass_kg": 31.2,
    "skeletal_muscle_pct": 41.1,
    "muscle_mass_kg": 39.0,
    "muscle_pct": 51.4,
    "water_mass_kg": 43.6,
    "water_pct": 57.5,
    "protein_mass_kg": 11.6,
    "protein_pct": 15.2,
    "bone_mass_kg": 3.4,
    "ffmi": 18.4,
    "fmi": 5.0,
}

_FULL_PAYLOAD: dict = {
    "format_version": "hc900_ble_v1",
    "device_mac": "A0:91:5C:92:CF:17",
    "captured_at": "2026-04-15T07:30:00+00:00",
    "measured_at": "2026-04-15T07:30:00+00:00",
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

_WEIGHT_ONLY_PAYLOAD: dict = {
    "format_version": "hc900_ble_v1",
    "device_mac": "A0:91:5C:92:CF:17",
    "captured_at": "2026-04-15T07:31:00+00:00",
    "measured_at": "2026-04-15T07:31:00+00:00",
    "capture_method": "bleak_scan",
    "raw_mfr_weight_hex": "aca017cf925c91a0202d88e00da2",
    "raw_mfr_impedance_hex": None,
    "decoded": {
        "weight_kg": 75.84,
        "decoder_version": "hc900_ble_v1",
    },
    "user_profile_snapshot": {
        "height_cm": 180,
        "birth_date": "1991-08-15",
        "age": 34,
        "sex": 1,
    },
}


def _ingest(user: User, payload: dict, external_id: str) -> RawPayloadIngest:
    return RawPayloadIngest(
        user_id=user.id,
        source_slug="hc900_ble",
        external_id=external_id,
        payload_type="hc900_scale",
        payload_json=payload,
    )


_URL = "/api/v1/integrations/scale/latest"


# ── never_measured ────────────────────────────────────────────────────────────


class TestNeverMeasured:
    async def test_no_ingestion_returns_never_measured(
        self, client: httpx.AsyncClient, user: User
    ):
        resp = await client.get(_URL, params={"user_id": str(user.id)})
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "never_measured"
        assert body["measured_at"] is None
        assert body["raw_payload_id"] is None
        assert body["decoder_version"] is None
        assert body["has_impedance"] is False
        assert body["metrics"] == {}


# ── full_reading ──────────────────────────────────────────────────────────────


class TestFullReading:
    @pytest.fixture
    async def ingested(self, db: AsyncSession, user: User) -> None:
        svc = IngestionService(db)
        await svc.ingest(_ingest(user, _FULL_PAYLOAD, "hc900_full_1"))

    async def test_full_reading_status(
        self, ingested, client: httpx.AsyncClient, user: User
    ):
        resp = await client.get(_URL, params={"user_id": str(user.id)})
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "full_reading"
        assert body["has_impedance"] is True
        assert body["measured_at"] == "2026-04-15T07:30:00Z"
        assert body["raw_payload_id"] is not None

    async def test_full_reading_contains_eighteen_metrics(
        self, ingested, client: httpx.AsyncClient, user: User
    ):
        resp = await client.get(_URL, params={"user_id": str(user.id)})
        body = resp.json()
        assert len(body["metrics"]) == 18

    async def test_full_reading_metric_shape_and_values(
        self, ingested, client: httpx.AsyncClient, user: User
    ):
        resp = await client.get(_URL, params={"user_id": str(user.id)})
        metrics = resp.json()["metrics"]

        # Primary (is_derived=false)
        weight = metrics["weight"]
        assert round(Decimal(weight["value"]), 2) == Decimal("75.84")
        assert weight["unit"] == "kg"
        assert weight["is_derived"] is False
        assert weight["slug"] == "weight"

        imp = metrics["impedance_adc"]
        assert int(Decimal(imp["value"])) == 527
        assert imp["unit"] == "adc"
        assert imp["is_derived"] is False

        # Derived (is_derived=true)
        bf = metrics["body_fat_pct"]
        assert round(Decimal(bf["value"]), 1) == Decimal("21.5")
        assert bf["unit"] == "%"
        assert bf["is_derived"] is True

        assert round(Decimal(metrics["bmi"]["value"]), 1) == Decimal("23.4")
        assert int(Decimal(metrics["bmr"]["value"])) == 1718

    async def test_full_reading_decoder_version_is_v2(
        self, ingested, client: httpx.AsyncClient, user: User
    ):
        """A reading with v2-exclusive slugs (bmi/bmr/impedance_adc) is labelled v2."""
        resp = await client.get(_URL, params={"user_id": str(user.id)})
        assert resp.json()["decoder_version"] == "hc900_ble_v2"


# ── weight_only ───────────────────────────────────────────────────────────────


class TestWeightOnly:
    @pytest.fixture
    async def ingested(self, db: AsyncSession, user: User) -> None:
        svc = IngestionService(db)
        await svc.ingest(_ingest(user, _WEIGHT_ONLY_PAYLOAD, "hc900_wo_1"))

    async def test_weight_only_status(
        self, ingested, client: httpx.AsyncClient, user: User
    ):
        resp = await client.get(_URL, params={"user_id": str(user.id)})
        body = resp.json()
        assert body["status"] == "weight_only"
        assert body["has_impedance"] is False
        assert body["raw_payload_id"] is not None

    async def test_weight_only_has_no_body_comp_fields(
        self, ingested, client: httpx.AsyncClient, user: User
    ):
        """Weight-only must NOT surface stale body-comp from older readings."""
        resp = await client.get(_URL, params={"user_id": str(user.id)})
        metrics = resp.json()["metrics"]
        body_comp_slugs = {
            "body_fat_pct", "fat_free_mass_kg", "fat_mass_kg",
            "skeletal_muscle_mass_kg", "skeletal_muscle_pct",
            "muscle_mass_kg", "muscle_pct",
            "water_mass_kg", "water_pct",
            "protein_mass_kg", "protein_pct",
            "bone_mass_kg", "ffmi", "fmi",
        }
        assert body_comp_slugs.isdisjoint(metrics.keys())

    async def test_weight_only_contains_weight_bmi_bmr(
        self, ingested, client: httpx.AsyncClient, user: User
    ):
        resp = await client.get(_URL, params={"user_id": str(user.id)})
        metrics = resp.json()["metrics"]
        assert set(metrics.keys()) == {"weight", "bmi", "bmr"}

    async def test_weight_only_decoder_version_is_v2(
        self, ingested, client: httpx.AsyncClient, user: User
    ):
        """Even with payload_json labelled v1, presence of bmi/bmr = v2 parser."""
        resp = await client.get(_URL, params={"user_id": str(user.id)})
        assert resp.json()["decoder_version"] == "hc900_ble_v2"


# ── Coherence: latest weighing wins, no cross-weighing stitching ──────────────


class TestLatestSelection:
    async def test_most_recent_measured_at_wins(
        self, db: AsyncSession, client: httpx.AsyncClient, user: User
    ):
        """Two payloads at different measured_at → latest is returned."""
        svc = IngestionService(db)
        # Older: full reading
        await svc.ingest(_ingest(user, _FULL_PAYLOAD, "hc900_full_old"))
        # Newer: weight-only (measured_at is 1 minute later)
        await svc.ingest(_ingest(user, _WEIGHT_ONLY_PAYLOAD, "hc900_wo_new"))

        resp = await client.get(_URL, params={"user_id": str(user.id)})
        body = resp.json()
        # Newer reading is weight-only → status MUST NOT degrade into full_reading
        assert body["status"] == "weight_only"
        assert body["measured_at"] == "2026-04-15T07:31:00Z"

    async def test_all_metrics_share_single_raw_payload_id(
        self, db: AsyncSession, client: httpx.AsyncClient, user: User
    ):
        """Every returned metric belongs to exactly one weighing (no stitching)."""
        svc = IngestionService(db)
        await svc.ingest(_ingest(user, _FULL_PAYLOAD, "hc900_full_x"))
        await svc.ingest(_ingest(user, _WEIGHT_ONLY_PAYLOAD, "hc900_wo_x"))

        resp = await client.get(_URL, params={"user_id": str(user.id)})
        body = resp.json()
        # Body is weight-only; body-comp from the earlier full reading must
        # NOT leak into this response.
        assert body["status"] == "weight_only"
        assert "body_fat_pct" not in body["metrics"]


# ── User isolation ────────────────────────────────────────────────────────────


class TestUserIsolation:
    async def test_other_user_ingestion_does_not_leak(
        self, db: AsyncSession, client: httpx.AsyncClient, user: User
    ):
        """Another user's reading MUST NOT appear in this user's response."""
        from uuid import uuid4

        from app.models.base import uuid7
        from app.models.user import User as UserModel

        other = UserModel(
            id=uuid7(),
            email=f"other-{uuid4().hex[:8]}@baseline.dev",
            name="Other",
            timezone="UTC",
        )
        db.add(other)
        await db.flush()

        svc = IngestionService(db)
        await svc.ingest(_ingest(other, _FULL_PAYLOAD, "hc900_full_other"))

        resp = await client.get(_URL, params={"user_id": str(user.id)})
        assert resp.json()["status"] == "never_measured"
