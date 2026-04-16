"""HTTP integration tests.

Full request cycle: HTTP → FastAPI → Service → Repository → DB → response.
Verifies status codes, response shapes, pagination, and error propagation.
"""
from datetime import UTC, date, datetime

import httpx

from app.models.user import User

# ── Measurements ───────────────────────────────────────────────────────────


class TestMeasurementsAPI:
    async def test_create_201(self, client: httpx.AsyncClient, user: User):
        now = datetime.now(UTC).isoformat()
        resp = await client.post(
            "/api/v1/measurements/",
            json={
                "user_id": str(user.id),
                "metric_type_slug": "weight",
                "source_slug": "manual",
                "value_num": "81.5",
                "unit": "kg",
                "measured_at": now,
                "recorded_at": now,
            },
        )
        assert resp.status_code == 201
        body = resp.json()
        assert body["metric_type_slug"] == "weight"
        assert body["source_slug"] == "manual"

    async def test_invalid_slug_422(self, client: httpx.AsyncClient, user: User):
        now = datetime.now(UTC).isoformat()
        resp = await client.post(
            "/api/v1/measurements/",
            json={
                "user_id": str(user.id),
                "metric_type_slug": "nonexistent",
                "source_slug": "manual",
                "value_num": "42",
                "unit": "?",
                "measured_at": now,
                "recorded_at": now,
            },
        )
        assert resp.status_code == 422

    async def test_list_pagination(self, client: httpx.AsyncClient, user: User):
        now = datetime.now(UTC).isoformat()
        for _ in range(3):
            await client.post(
                "/api/v1/measurements/",
                json={
                    "user_id": str(user.id),
                    "metric_type_slug": "weight",
                    "source_slug": "manual",
                    "value_num": "80",
                    "unit": "kg",
                    "measured_at": now,
                    "recorded_at": now,
                },
            )
        resp = await client.get(
            "/api/v1/measurements/",
            params={"user_id": str(user.id), "limit": 2},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 3
        assert len(body["items"]) == 2


# ── Ingestion ──────────────────────────────────────────────────────────────


class TestIngestionAPI:
    async def test_ingest_garmin_201(self, client: httpx.AsyncClient, user: User):
        resp = await client.post(
            "/api/v1/raw-payloads/ingest",
            json={
                "user_id": str(user.id),
                "source_slug": "garmin",
                "external_id": "garmin_api_20260315",
                "payload_type": "garmin_daily_summary",
                "payload_json": {
                    "resting_hr": 58,
                    "hrv_rmssd": 42.5,
                    "steps": 8500,
                },
            },
        )
        assert resp.status_code == 201
        assert resp.json()["processing_status"] == "processed"

    async def test_duplicate_returns_same_id(
        self, client: httpx.AsyncClient, user: User
    ):
        payload = {
            "user_id": str(user.id),
            "source_slug": "garmin",
            "external_id": "garmin_dedup_test",
            "payload_type": "garmin_daily_summary",
            "payload_json": {"resting_hr": 60},
        }
        r1 = await client.post("/api/v1/raw-payloads/ingest", json=payload)
        r2 = await client.post("/api/v1/raw-payloads/ingest", json=payload)
        assert r1.json()["id"] == r2.json()["id"]


# ── Workouts ───────────────────────────────────────────────────────────────


class TestWorkoutsAPI:
    async def test_create_with_sets_201(
        self, client: httpx.AsyncClient, user: User
    ):
        now = datetime.now(UTC).isoformat()
        resp = await client.post(
            "/api/v1/workouts/sessions",
            json={
                "user_id": str(user.id),
                "source_slug": "manual",
                "workout_type": "strength",
                "started_at": now,
                "recorded_at": now,
                "perceived_effort": 8,
                "sets": [
                    {"exercise_slug": "bench_press", "set_number": 1,
                     "reps": 10, "weight_kg": "80"},
                    {"exercise_slug": "bench_press", "set_number": 2,
                     "reps": 8, "weight_kg": "85"},
                ],
            },
        )
        assert resp.status_code == 201
        body = resp.json()
        assert len(body["sets"]) == 2
        assert body["perceived_effort"] == 8


# ── Daily checkpoints ─────────────────────────────────────────────────────


class TestCheckpointsAPI:
    async def test_create_201(self, client: httpx.AsyncClient, user: User):
        now = datetime.now(UTC).isoformat()
        resp = await client.post(
            "/api/v1/checkpoints/",
            json={
                "user_id": str(user.id),
                "checkpoint_type": "morning",
                "checkpoint_date": str(date.today()),
                "checkpoint_at": now,
                "recorded_at": now,
                "mood": 7,
                "energy": 8,
            },
        )
        assert resp.status_code == 201

    async def test_duplicate_422(self, client: httpx.AsyncClient, user: User):
        now = datetime.now(UTC).isoformat()
        payload = {
            "user_id": str(user.id),
            "checkpoint_type": "night",
            "checkpoint_date": str(date.today()),
            "checkpoint_at": now,
            "recorded_at": now,
            "mood": 5,
        }
        r1 = await client.post("/api/v1/checkpoints/", json=payload)
        assert r1.status_code == 201
        r2 = await client.post("/api/v1/checkpoints/", json=payload)
        assert r2.status_code == 422
