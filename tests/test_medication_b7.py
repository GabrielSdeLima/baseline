"""B7 — Medication logs date-filter endpoint tests.

Covers:
 1. GET /medications/logs without date filter — backward compatible
 2. GET with start_date=today&end_date=today returns today's logs
 3. GET with date filter returns empty when no logs that day
 4. GET excludes logs from other dates (window boundary)
 5. Response shape is consistent and complete
"""
from datetime import UTC, date, datetime, timedelta

import httpx
import pytest

from app.models.user import User


async def _create_regimen(client: httpx.AsyncClient, user: User) -> str:
    defn = await client.post(
        "/api/v1/medications/definitions",
        json={"name": "Aspirin B7"},
    )
    assert defn.status_code == 201
    med_id = defn.json()["id"]

    reg = await client.post(
        "/api/v1/medications/regimens",
        json={
            "user_id": str(user.id),
            "medication_id": med_id,
            "dosage_amount": "100.00",
            "dosage_unit": "mg",
            "frequency": "daily",
            "started_at": date.today().isoformat(),
        },
    )
    assert reg.status_code == 201
    return reg.json()["id"]


async def _post_log(client: httpx.AsyncClient, user: User, regimen_id: str, scheduled_at: str) -> None:
    resp = await client.post(
        "/api/v1/medications/logs",
        json={
            "user_id": str(user.id),
            "regimen_id": regimen_id,
            "status": "taken",
            "scheduled_at": scheduled_at,
            "recorded_at": scheduled_at,
        },
    )
    assert resp.status_code == 201


class TestMedicationLogsDateFilter:
    # 1. no date filter — backward compatible
    async def test_no_date_filter_returns_all(self, client: httpx.AsyncClient, user: User):
        regimen_id = await _create_regimen(client, user)
        now = datetime.now(UTC).isoformat()
        await _post_log(client, user, regimen_id, now)

        resp = await client.get(f"/api/v1/medications/logs?user_id={user.id}")
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1
        assert len(body["items"]) == 1

    # 2. filter today → returns today's log
    async def test_filter_today_returns_today_log(self, client: httpx.AsyncClient, user: User):
        regimen_id = await _create_regimen(client, user)
        today_dt = datetime.now(UTC)
        await _post_log(client, user, regimen_id, today_dt.isoformat())

        today_str = today_dt.date().isoformat()
        resp = await client.get(
            f"/api/v1/medications/logs?user_id={user.id}&start_date={today_str}&end_date={today_str}"
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1
        assert body["items"][0]["regimen_id"] == regimen_id

    # 3. filter today → empty when no logs that day
    async def test_filter_empty_when_no_logs(self, client: httpx.AsyncClient, user: User):
        today_str = date.today().isoformat()
        resp = await client.get(
            f"/api/v1/medications/logs?user_id={user.id}&start_date={today_str}&end_date={today_str}"
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 0
        assert body["items"] == []

    # 4. filter today excludes yesterday's log
    async def test_filter_excludes_other_dates(self, client: httpx.AsyncClient, user: User):
        regimen_id = await _create_regimen(client, user)
        yesterday = (datetime.now(UTC) - timedelta(days=1)).isoformat()
        await _post_log(client, user, regimen_id, yesterday)

        today_str = date.today().isoformat()
        resp = await client.get(
            f"/api/v1/medications/logs?user_id={user.id}&start_date={today_str}&end_date={today_str}"
        )
        assert resp.status_code == 200
        assert resp.json()["total"] == 0

    # 5. response shape is complete
    async def test_response_shape(self, client: httpx.AsyncClient, user: User):
        regimen_id = await _create_regimen(client, user)
        now = datetime.now(UTC).isoformat()
        await _post_log(client, user, regimen_id, now)

        today_str = date.today().isoformat()
        resp = await client.get(
            f"/api/v1/medications/logs?user_id={user.id}&start_date={today_str}&end_date={today_str}"
        )
        assert resp.status_code == 200
        item = resp.json()["items"][0]
        for field in ("id", "user_id", "regimen_id", "status", "scheduled_at", "recorded_at", "ingested_at"):
            assert field in item, f"missing field: {field}"
        assert item["status"] == "taken"
        assert item["user_id"] == str(user.id)
