"""Tests for ``POST /api/v1/integrations/garmin/sync`` and the underlying
``app.services.garmin_sync.perform_on_demand_sync`` service.

All Postgres and subprocess boundaries are patched — the tests exercise the
status-derivation logic, lock behaviour, and run lifecycle with no real
Garmin login, no subprocess spawn and no schema dependency.  Endpoint tests
reuse the :func:`client` fixture for a thin end-to-end shape check.
"""
from __future__ import annotations

import asyncio
import uuid
from datetime import UTC, datetime

import httpx
import pytest

from app.services import garmin_sync as svc


_UID = "019d9334-bf04-77a1-aaf6-50b3280dec96"


# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def fresh_lock(monkeypatch):
    """Each test gets its own Lock bound to the running test loop.

    The scheduler's module-level ``_sync_lock`` would otherwise leak state
    between tests (and between the scheduler itself and these tests).
    """
    from app.services import garmin_scheduler
    monkeypatch.setattr(garmin_scheduler, "_sync_lock", asyncio.Lock())
    return garmin_scheduler._get_sync_lock()


@pytest.fixture
def stub_infra(monkeypatch):
    """Stub every external boundary the service touches.

    Returns a mutable ``captured`` dict + ``tune`` callable so each test can
    declare its scenario: rc, before/after timestamps, whether the source
    is seeded, and receives back what calls were made.
    """
    captured: dict = {
        "run_created": False,
        "run_closed_status": None,
        "run_closed_error": None,
        "cursor_upserted": False,
        "run_sync_kwargs": None,
    }
    scenario: dict = {
        "rc": 0,
        "source_id": 1,
        "max_before": None,
        "max_after": None,
    }

    async def _source_id():
        return scenario["source_id"]

    async def _create_run(uid, source_id, trigger_type, idempotency_key):
        captured["run_created"] = True
        captured["trigger_type"] = trigger_type
        captured["idempotency_key"] = idempotency_key
        return uuid.UUID("019d9334-1111-7777-8888-000000000001")

    async def _close_run(run_id, status, error_message=None):
        captured["run_closed_run_id"] = run_id
        captured["run_closed_status"] = status
        captured["run_closed_error"] = error_message

    async def _cursor(uid, source_id, logical_date, run_id):
        captured["cursor_upserted"] = True
        captured["cursor_run_id"] = run_id
        captured["cursor_logical_date"] = logical_date

    async def _run_sync(user_id, **kwargs):
        captured["run_sync_user_id"] = user_id
        captured["run_sync_kwargs"] = kwargs
        return scenario["rc"]

    async def _latest(uid):
        # Return before on first call, after on subsequent calls.
        if "latest_call_count" not in captured:
            captured["latest_call_count"] = 0
        captured["latest_call_count"] += 1
        return scenario["max_before"] if captured["latest_call_count"] == 1 else scenario["max_after"]

    monkeypatch.setattr(svc, "_get_garmin_source_id", _source_id)
    monkeypatch.setattr(svc, "_create_ingestion_run", _create_run)
    monkeypatch.setattr(svc, "_close_ingestion_run", _close_run)
    monkeypatch.setattr(svc, "_upsert_source_cursor", _cursor)
    monkeypatch.setattr(svc, "_run_sync", _run_sync)
    monkeypatch.setattr(svc, "_latest_garmin_measured_at", _latest)

    def tune(**kwargs):
        scenario.update(kwargs)

    return captured, tune


# ── Service unit tests: status derivation ───────────────────────────────────


async def test_completed_when_latest_advances(fresh_lock, stub_infra):
    """rc=0 and latest Garmin measured_at moved forward → completed."""
    captured, tune = stub_infra
    tune(
        rc=0,
        max_before=datetime(2026, 4, 17, 12, 0, tzinfo=UTC),
        max_after=datetime(2026, 4, 18, 12, 0, tzinfo=UTC),
    )

    result = await svc.perform_on_demand_sync(_UID)

    assert result.status == "completed"
    assert result.run_id is not None
    assert result.started_at is not None
    assert result.finished_at is not None
    assert result.error_message is None
    assert captured["run_closed_status"] == "completed"
    assert captured["cursor_upserted"] is True


async def test_no_new_data_when_latest_unchanged(fresh_lock, stub_infra):
    """rc=0 but latest Garmin measured_at did NOT move → no_new_data.

    The run still closes as completed (the sync itself succeeded), the
    cursor still advances, but the UI-facing status is ``no_new_data`` so
    the user gets honest feedback instead of a misleading "Synced".
    """
    captured, tune = stub_infra
    same = datetime(2026, 4, 18, 12, 0, tzinfo=UTC)
    tune(rc=0, max_before=same, max_after=same)

    result = await svc.perform_on_demand_sync(_UID)

    assert result.status == "no_new_data"
    assert result.run_id is not None
    assert result.error_message is None
    assert captured["run_closed_status"] == "completed"
    # Cursor still upserted — the sync really did run, we just got no delta.
    assert captured["cursor_upserted"] is True


async def test_completed_when_first_ever_sync(fresh_lock, stub_infra):
    """max_before is None (no prior Garmin data) and rc=0 → completed."""
    _, tune = stub_infra
    tune(
        rc=0,
        max_before=None,
        max_after=datetime(2026, 4, 18, 12, 0, tzinfo=UTC),
    )

    result = await svc.perform_on_demand_sync(_UID)

    assert result.status == "completed"


async def test_completed_when_first_ever_sync_stays_empty(fresh_lock, stub_infra):
    """max_before=None AND max_after=None: sync ran, Garmin returned nothing.

    Current rule: any successful sync for a user with no prior data is
    considered ``completed`` (we cannot distinguish "Garmin empty" from
    "Garmin had data" without probing the raw payload).  The important
    thing is we don't crash.
    """
    _, tune = stub_infra
    tune(rc=0, max_before=None, max_after=None)

    result = await svc.perform_on_demand_sync(_UID)

    assert result.status == "completed"


# ── Service unit tests: failure paths ──────────────────────────────────────


async def test_failed_when_subprocess_nonzero(fresh_lock, stub_infra):
    """rc!=0 → failed; run closed as failed with error_message set."""
    captured, tune = stub_infra
    tune(rc=1)

    result = await svc.perform_on_demand_sync(_UID)

    assert result.status == "failed"
    assert result.run_id is not None
    assert result.error_message == "sync_garmin.py exited rc=1"
    assert captured["run_closed_status"] == "failed"
    assert captured["run_closed_error"] == "sync_garmin.py exited rc=1"
    # Cursor must NOT advance on failure.
    assert captured["cursor_upserted"] is False


async def test_failed_when_source_not_seeded(fresh_lock, stub_infra):
    """garmin_connect data source missing → failed without touching subprocess."""
    captured, tune = stub_infra
    tune(source_id=None)

    result = await svc.perform_on_demand_sync(_UID)

    assert result.status == "failed"
    assert result.run_id is None
    assert "not seeded" in (result.error_message or "")
    # We never reached run-creation or subprocess.
    assert captured["run_created"] is False
    assert captured["run_sync_kwargs"] is None


async def test_failed_when_user_id_invalid(fresh_lock, stub_infra):
    """Non-UUID user_id → failed; no DB/subprocess calls."""
    captured, _ = stub_infra
    result = await svc.perform_on_demand_sync("not-a-uuid")

    assert result.status == "failed"
    assert result.run_id is None
    assert "invalid user_id" in (result.error_message or "")
    assert captured["run_created"] is False


# ── Anti-overlap ───────────────────────────────────────────────────────────


async def test_already_running_when_lock_held(fresh_lock, stub_infra):
    """If the scheduler/prior click still holds the lock → already_running.

    No run is created, no subprocess is launched, no timestamps are returned
    (the in-flight run belongs to whoever acquired the lock).
    """
    captured, _ = stub_infra
    async with fresh_lock:
        result = await svc.perform_on_demand_sync(_UID)

    assert result.status == "already_running"
    assert result.run_id is None
    assert result.started_at is None
    assert result.finished_at is None
    assert captured["run_created"] is False
    assert captured["run_sync_kwargs"] is None


async def test_double_click_serialises_via_lock(fresh_lock, stub_infra, monkeypatch):
    """Two concurrent clicks: first runs, second sees lock held → already_running.

    This is the anti-double-click guarantee the UI depends on — a racing
    second request never spawns a second subprocess.
    """
    captured, tune = stub_infra
    tune(rc=0, max_before=None, max_after=datetime(2026, 4, 18, 12, 0, tzinfo=UTC))

    async def _slow_run_sync(user_id, **kwargs):
        # Simulate a subprocess that takes time — hold the lock long enough
        # for the second caller to observe it.
        captured["run_sync_user_id"] = user_id
        captured["run_sync_kwargs"] = kwargs
        await asyncio.sleep(0.05)
        return 0

    # Replace the already-stubbed _run_sync with a slow version.  Using the
    # monkeypatch fixture here stacks a second setattr on top of the one
    # stub_infra already installed — both get undone at test teardown.
    monkeypatch.setattr(svc, "_run_sync", _slow_run_sync)

    first_task = asyncio.create_task(svc.perform_on_demand_sync(_UID))
    # Give the first task a chance to acquire the lock before issuing the
    # second call.  A single event-loop yield is enough.
    await asyncio.sleep(0)
    second_result = await svc.perform_on_demand_sync(_UID)
    first_result = await first_task

    assert second_result.status == "already_running"
    assert first_result.status in ("completed", "no_new_data")


async def test_concurrent_requests_do_not_race_through_lock(
    fresh_lock, stub_infra, monkeypatch
):
    """Regression: two fully-concurrent calls (gather) must not both create a run.

    The original implementation checked ``lock.locked()`` and then awaited
    ``_get_garmin_source_id()`` before entering ``async with lock:`` — the
    intervening yield let a second concurrent task pass the same check, so
    both calls went on to acquire the lock sequentially and each spawned
    its own subprocess.  The live smoke test on 2026-04-18 caught this:
    two back-to-back POSTs both returned ``no_new_data`` with different
    ``run_id`` values instead of one returning ``already_running``.

    With the fixed flow (atomic check-and-acquire, source lookup moved
    inside the lock), only one of the two concurrent calls can get past
    the gate.  The other must short-circuit with ``already_running``.
    """
    captured, tune = stub_infra
    tune(rc=0, max_before=None, max_after=datetime(2026, 4, 18, 12, 0, tzinfo=UTC))

    run_count = {"n": 0}

    async def _slow_run_sync(user_id, **kwargs):
        run_count["n"] += 1
        await asyncio.sleep(0.05)
        return 0

    monkeypatch.setattr(svc, "_run_sync", _slow_run_sync)

    a, b = await asyncio.gather(
        svc.perform_on_demand_sync(_UID),
        svc.perform_on_demand_sync(_UID),
    )

    statuses = sorted([a.status, b.status])
    # Exactly one call went through (completed/no_new_data) and exactly one
    # was rejected — the subprocess fires at most once.
    assert statuses[0] == "already_running"
    assert statuses[1] in ("completed", "no_new_data")
    assert run_count["n"] == 1


# ── Run lifecycle + subprocess plumbing ────────────────────────────────────


async def test_run_gets_trigger_ui_button(fresh_lock, stub_infra):
    """UI-triggered runs are labelled trigger_type='ui_button'."""
    captured, tune = stub_infra
    tune(rc=0, max_before=None, max_after=datetime(2026, 4, 18, 12, 0, tzinfo=UTC))

    await svc.perform_on_demand_sync(_UID)

    assert captured["trigger_type"] == "ui_button"
    # No idempotency key on UI clicks — the lock is the anti-duplicate guard.
    assert captured["idempotency_key"] is None


async def test_run_id_passed_to_subprocess(fresh_lock, stub_infra):
    """The endpoint must hand its run_id to sync_garmin.py so ingested
    raw_payloads are linked back to the correct IngestionRun."""
    captured, tune = stub_infra
    tune(rc=0, max_before=None, max_after=datetime(2026, 4, 18, 12, 0, tzinfo=UTC))

    result = await svc.perform_on_demand_sync(_UID)

    assert result.run_id is not None
    assert captured["run_sync_kwargs"]["ingestion_run_id"] == str(result.run_id)


async def test_cursor_advanced_with_run_id(fresh_lock, stub_infra):
    """On success the daily_summary source cursor references the new run."""
    captured, tune = stub_infra
    tune(rc=0, max_before=None, max_after=datetime(2026, 4, 18, 12, 0, tzinfo=UTC))

    result = await svc.perform_on_demand_sync(_UID)

    assert captured["cursor_upserted"] is True
    assert captured["cursor_run_id"] == result.run_id


# ── Endpoint shape via HTTPX client ────────────────────────────────────────


async def test_endpoint_returns_completed_shape(
    fresh_lock, stub_infra, client: httpx.AsyncClient
):
    """POST /integrations/garmin/sync returns the documented JSON shape."""
    _, tune = stub_infra
    tune(
        rc=0,
        max_before=datetime(2026, 4, 17, 12, 0, tzinfo=UTC),
        max_after=datetime(2026, 4, 18, 12, 0, tzinfo=UTC),
    )

    resp = await client.post(
        "/api/v1/integrations/garmin/sync",
        json={"user_id": _UID},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "completed"
    assert body["run_id"] is not None
    assert body["started_at"] is not None
    assert body["finished_at"] is not None
    assert body["error_message"] is None


async def test_endpoint_returns_already_running_shape(
    fresh_lock, stub_infra, client: httpx.AsyncClient
):
    """already_running response has null run_id / timestamps as documented."""
    async with fresh_lock:
        resp = await client.post(
            "/api/v1/integrations/garmin/sync",
            json={"user_id": _UID},
        )

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "already_running"
    assert body["run_id"] is None
    assert body["started_at"] is None
    assert body["finished_at"] is None


async def test_endpoint_returns_no_new_data_shape(
    fresh_lock, stub_infra, client: httpx.AsyncClient
):
    """no_new_data still returns run metadata — the run really did execute."""
    _, tune = stub_infra
    same = datetime(2026, 4, 18, 12, 0, tzinfo=UTC)
    tune(rc=0, max_before=same, max_after=same)

    resp = await client.post(
        "/api/v1/integrations/garmin/sync",
        json={"user_id": _UID},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "no_new_data"
    assert body["run_id"] is not None


async def test_endpoint_returns_failed_shape(
    fresh_lock, stub_infra, client: httpx.AsyncClient
):
    """Failed sync propagates error_message to the client."""
    _, tune = stub_infra
    tune(rc=1)

    resp = await client.post(
        "/api/v1/integrations/garmin/sync",
        json={"user_id": _UID},
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "failed"
    assert body["error_message"] == "sync_garmin.py exited rc=1"
