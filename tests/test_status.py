"""Section O — B1 System Status endpoint (10 tests).

  O-1  Empty state: new user → no integrations, no devices, no agents
  O-2  Garmin integration active → integration_configured=True, device_paired=None
  O-3  Garmin last_sync_at exposed separately (last_advanced_at still null)
  O-4  last_advanced_at from source_cursor (distinct from last_sync_at)
  O-5  HC900 integration configured but no device → device_paired=False
  O-6  HC900 active device → device_paired=True
  O-7  Latest ingestion run status and finished_at exposed
  O-8  Agent seen <24h → status='active'
  O-9  Agent seen ~48h → status='stale'
  O-10 Agent is_active=False → status='unknown'
"""
from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest
from httpx import AsyncClient
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent_instance import AgentInstance
from app.models.base import uuid7
from app.models.data_source import DataSource
from app.models.ingestion_run import IngestionRun
from app.models.source_cursor import SourceCursor
from app.models.user import User
from app.models.user_device import UserDevice
from app.models.user_integration import UserIntegration


async def _source_id(db: AsyncSession, slug: str) -> int:
    row = await db.execute(select(DataSource.id).where(DataSource.slug == slug))
    return row.scalar_one()


async def _make_integration(
    db: AsyncSession,
    user: User,
    source_id: int,
    *,
    status: str = "active",
    last_sync_at: datetime | None = None,
) -> UserIntegration:
    integ = UserIntegration(
        id=uuid7(),
        user_id=user.id,
        source_id=source_id,
        status=status,
        last_sync_at=last_sync_at,
    )
    db.add(integ)
    await db.flush()
    return integ


# ── O-1 ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_o1_empty_state_new_user(client: AsyncClient, user: User):
    resp = await client.get(f"/api/v1/status/system?user_id={user.id}")
    assert resp.status_code == 200
    data = resp.json()
    assert data["user_id"] == str(user.id)
    sources = {s["source_slug"]: s for s in data["sources"]}
    assert "garmin_connect" in sources
    assert "hc900_ble" in sources
    assert sources["garmin_connect"]["integration_configured"] is False
    assert sources["garmin_connect"]["device_paired"] is None  # no device concept for cloud
    assert sources["hc900_ble"]["integration_configured"] is False
    assert sources["hc900_ble"]["device_paired"] is False  # concept applies, not paired
    assert data["agents"] == []


# ── O-2 ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_o2_garmin_integration_active(client: AsyncClient, db: AsyncSession, user: User):
    garmin_id = await _source_id(db, "garmin_connect")
    await _make_integration(db, user, garmin_id)

    resp = await client.get(f"/api/v1/status/system?user_id={user.id}")
    assert resp.status_code == 200
    sources = {s["source_slug"]: s for s in resp.json()["sources"]}
    assert sources["garmin_connect"]["integration_configured"] is True
    assert sources["garmin_connect"]["device_paired"] is None


# ── O-3 ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_o3_garmin_last_sync_at_separate_from_advanced(
    client: AsyncClient, db: AsyncSession, user: User
):
    garmin_id = await _source_id(db, "garmin_connect")
    sync_ts = datetime(2026, 4, 16, 8, 0, 0)
    await _make_integration(db, user, garmin_id, last_sync_at=sync_ts)

    resp = await client.get(f"/api/v1/status/system?user_id={user.id}")
    src = {s["source_slug"]: s for s in resp.json()["sources"]}["garmin_connect"]
    assert src["last_sync_at"] is not None
    assert "2026-04-16" in src["last_sync_at"]
    assert src["last_advanced_at"] is None  # no cursor → data never advanced


# ── O-4 ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_o4_last_advanced_at_from_cursor(
    client: AsyncClient, db: AsyncSession, user: User
):
    garmin_id = await _source_id(db, "garmin_connect")
    await _make_integration(db, user, garmin_id)
    adv_ts = datetime(2026, 4, 15, 6, 0, 0)
    db.add(
        SourceCursor(
            id=uuid7(),
            user_id=user.id,
            source_id=garmin_id,
            cursor_name="daily_summary",
            last_advanced_at=adv_ts,
        )
    )
    await db.flush()

    resp = await client.get(f"/api/v1/status/system?user_id={user.id}")
    src = {s["source_slug"]: s for s in resp.json()["sources"]}["garmin_connect"]
    assert src["last_advanced_at"] is not None
    assert "2026-04-15" in src["last_advanced_at"]


# ── O-5 ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_o5_hc900_configured_no_device(
    client: AsyncClient, db: AsyncSession, user: User
):
    hc900_id = await _source_id(db, "hc900_ble")
    await _make_integration(db, user, hc900_id)

    resp = await client.get(f"/api/v1/status/system?user_id={user.id}")
    src = {s["source_slug"]: s for s in resp.json()["sources"]}["hc900_ble"]
    assert src["integration_configured"] is True
    assert src["device_paired"] is False


# ── O-6 ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_o6_hc900_device_paired(client: AsyncClient, db: AsyncSession, user: User):
    hc900_id = await _source_id(db, "hc900_ble")
    integ = await _make_integration(db, user, hc900_id)
    db.add(
        UserDevice(
            id=uuid7(),
            user_id=user.id,
            source_id=hc900_id,
            integration_id=integ.id,
            device_type="scale",
            identifier="A0:91:5C:92:CF:17",
            identifier_type="mac",
            is_active=True,
        )
    )
    await db.flush()

    resp = await client.get(f"/api/v1/status/system?user_id={user.id}")
    src = {s["source_slug"]: s for s in resp.json()["sources"]}["hc900_ble"]
    assert src["integration_configured"] is True
    assert src["device_paired"] is True


# ── O-7 ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_o7_latest_run_status_exposed(
    client: AsyncClient, db: AsyncSession, user: User
):
    hc900_id = await _source_id(db, "hc900_ble")
    await _make_integration(db, user, hc900_id)
    finished = datetime(2026, 4, 16, 9, 30, 0)
    db.add(
        IngestionRun(
            id=uuid7(),
            user_id=user.id,
            source_id=hc900_id,
            operation_type="ble_scan",
            trigger_type="ui_button",
            status="completed",
            finished_at=finished,
        )
    )
    await db.flush()

    resp = await client.get(f"/api/v1/status/system?user_id={user.id}")
    src = {s["source_slug"]: s for s in resp.json()["sources"]}["hc900_ble"]
    assert src["last_run_status"] == "completed"
    assert src["last_run_at"] is not None
    assert "2026-04-16" in src["last_run_at"]


# ── O-8 ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_o8_agent_active_recent_heartbeat(
    client: AsyncClient, db: AsyncSession, user: User
):
    now_naive = datetime.now(UTC).replace(tzinfo=None)
    db.add(
        AgentInstance(
            id=uuid7(),
            user_id=user.id,
            install_id="pc-test-o8",
            agent_type="local_pc",
            display_name="Desktop",
            last_seen_at=now_naive - timedelta(hours=2),
            is_active=True,
        )
    )
    await db.flush()

    resp = await client.get(f"/api/v1/status/system?user_id={user.id}")
    agents = resp.json()["agents"]
    assert len(agents) == 1
    assert agents[0]["status"] == "active"
    assert agents[0]["display_name"] == "Desktop"


# ── O-9 ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_o9_agent_stale_old_heartbeat(
    client: AsyncClient, db: AsyncSession, user: User
):
    now_naive = datetime.now(UTC).replace(tzinfo=None)
    db.add(
        AgentInstance(
            id=uuid7(),
            user_id=user.id,
            install_id="pc-test-o9",
            agent_type="local_pc",
            display_name="Old Desktop",
            last_seen_at=now_naive - timedelta(hours=48),
            is_active=True,
        )
    )
    await db.flush()

    resp = await client.get(f"/api/v1/status/system?user_id={user.id}")
    agents = resp.json()["agents"]
    assert len(agents) == 1
    assert agents[0]["status"] == "stale"


# ── O-10 ─────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_o10_agent_inactive_is_unknown(
    client: AsyncClient, db: AsyncSession, user: User
):
    now_naive = datetime.now(UTC).replace(tzinfo=None)
    db.add(
        AgentInstance(
            id=uuid7(),
            user_id=user.id,
            install_id="pc-test-o10",
            agent_type="local_pc",
            last_seen_at=now_naive - timedelta(hours=1),
            is_active=False,
        )
    )
    await db.flush()

    resp = await client.get(f"/api/v1/status/system?user_id={user.id}")
    agents = resp.json()["agents"]
    assert len(agents) == 1
    assert agents[0]["status"] == "unknown"
