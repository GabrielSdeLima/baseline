"""Tests for ``app.services.garmin_scheduler``.

Covers the new robustness behaviour added for PC sleep/wake cycles:

  A. ``_catch_up`` refreshes today even when ``last_day == today`` so
     intraday updates (body battery, sleep score, HRV) are captured.
  B. ``_catch_up`` seeds a 7-day initial backfill when no prior data exists.
  C. ``_catch_up`` computes a gap range when the DB is behind today.
  D. ``_wake_aware_sleep`` returns False when wall-clock and monotonic agree.
  E. ``_wake_aware_sleep`` returns True (early exit) when wall-clock drifts
     forward relative to the monotonic clock during a hop (S3/S4 wake signal).
  F. ``_guarded_catch_up`` skips when the sync lock is already held.
  G. ``_guarded_catch_up`` runs once lock is free.
  H. ``_guarded_catch_up`` swallows exceptions so the scheduler stays alive.
  I. ``_prerequisites_ok`` returns the right (ok, reason) shape.

The tests do not touch Postgres, Garmin Connect, or subprocess spawning —
all external boundaries are patched at the module level so the logic under
test is the only thing exercised.
"""
from __future__ import annotations

import asyncio
import types
import uuid
from datetime import date, datetime, timedelta

import pytest

from app.services import garmin_scheduler as mod


_UID = "019d9334-bf04-77a1-aaf6-50b3280dec96"


# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def fresh_lock(monkeypatch):
    """Each test gets its own Lock bound to the running test loop."""
    monkeypatch.setattr(mod, "_sync_lock", asyncio.Lock())
    return mod._get_sync_lock()


@pytest.fixture
def mock_db_ops(monkeypatch):
    """Stub all scheduler DB operations so _catch_up tests stay DB-free."""
    async def _source_id():
        return 1

    async def _create(*_args, **_kwargs):
        return uuid.uuid4()

    async def _close(*_args, **_kwargs):
        pass

    async def _cursor(*_args, **_kwargs):
        pass

    monkeypatch.setattr(mod, "_get_garmin_source_id", _source_id)
    monkeypatch.setattr(mod, "_create_ingestion_run", _create)
    monkeypatch.setattr(mod, "_close_ingestion_run", _close)
    monkeypatch.setattr(mod, "_upsert_source_cursor", _cursor)


@pytest.fixture
def fake_today(monkeypatch):
    """Freeze ``date.today()`` used inside ``_catch_up`` to a known day."""
    fixed = date(2026, 4, 16)
    fake_date_cls = types.SimpleNamespace(today=lambda: fixed)
    monkeypatch.setattr(mod, "date", fake_date_cls)
    return fixed


# ── _catch_up ───────────────────────────────────────────────────────────────


async def test_catch_up_refreshes_today_when_already_up_to_date(
    monkeypatch, fake_today, mock_db_ops
):
    """Regression: old code returned early; new code re-syncs today."""
    captured: dict = {}

    async def fake_last(_uid):
        return fake_today  # last_day == today

    async def fake_run_sync(user_id, **kwargs):
        captured["user_id"] = user_id
        captured.update(kwargs)
        return 0

    monkeypatch.setattr(mod, "_last_garmin_day", fake_last)
    monkeypatch.setattr(mod, "_run_sync", fake_run_sync)

    await mod._catch_up(_UID)

    assert captured["user_id"] == _UID
    assert captured["start_date"] == fake_today
    assert captured["end_date"] == fake_today


async def test_catch_up_refreshes_today_when_last_is_in_future(
    monkeypatch, fake_today, mock_db_ops
):
    """Defensive: if clock drift produced a future last_day, still sync today."""
    captured: dict = {}

    async def fake_last(_uid):
        return fake_today + timedelta(days=1)

    async def fake_run_sync(user_id, **kwargs):
        captured.update(kwargs)
        return 0

    monkeypatch.setattr(mod, "_last_garmin_day", fake_last)
    monkeypatch.setattr(mod, "_run_sync", fake_run_sync)

    await mod._catch_up(_UID)

    assert captured["start_date"] == fake_today
    assert captured["end_date"] == fake_today


async def test_catch_up_fresh_user_backfills_seven_days(monkeypatch, fake_today, mock_db_ops):
    captured: dict = {}

    async def fake_last(_uid):
        return None  # no prior data

    async def fake_run_sync(user_id, **kwargs):
        captured.update(kwargs)
        return 0

    monkeypatch.setattr(mod, "_last_garmin_day", fake_last)
    monkeypatch.setattr(mod, "_run_sync", fake_run_sync)

    await mod._catch_up(_UID)

    assert captured["start_date"] == fake_today - timedelta(days=7)
    assert captured["end_date"] == fake_today


async def test_catch_up_fills_gap_between_last_and_today(monkeypatch, fake_today, mock_db_ops):
    captured: dict = {}

    async def fake_last(_uid):
        return fake_today - timedelta(days=3)

    async def fake_run_sync(user_id, **kwargs):
        captured.update(kwargs)
        return 0

    monkeypatch.setattr(mod, "_last_garmin_day", fake_last)
    monkeypatch.setattr(mod, "_run_sync", fake_run_sync)

    await mod._catch_up(_UID)

    assert captured["start_date"] == fake_today - timedelta(days=2)
    assert captured["end_date"] == fake_today


async def test_catch_up_rejects_invalid_uuid(monkeypatch, caplog):
    """Bad BASELINE_USER_ID logs an error but does not raise."""
    called = []

    async def fake_run_sync(*args, **kwargs):
        called.append(1)
        return 0

    monkeypatch.setattr(mod, "_run_sync", fake_run_sync)

    with caplog.at_level("ERROR", logger=mod.logger.name):
        await mod._catch_up("not-a-uuid")

    assert called == []  # short-circuits before the subprocess
    assert any("not a valid UUID" in r.message for r in caplog.records)


# ── _wake_aware_sleep ───────────────────────────────────────────────────────


async def test_wake_aware_sleep_completes_without_drift(monkeypatch):
    """No drift → sleeps full duration and returns False."""
    # Short real durations + tiny step so the test finishes quickly but still
    # exercises the real asyncio.sleep path.
    woke = await mod._wake_aware_sleep(0.05, step_s=0.02)
    assert woke is False


async def test_wake_aware_sleep_detects_wake_mid_loop(monkeypatch):
    """Simulate suspend: wall-clock jumps 120s while monotonic stays frozen."""
    hop_count = {"n": 0}

    async def fake_sleep(_delay):
        hop_count["n"] += 1

    # Each hop reads monotonic twice (before, after) and datetime twice.
    # Hop 1: both advance ~1ms  → no drift.
    # Hop 2: monotonic +1ms, wall +120s → drift ≈ 120s, triggers detection.
    mono_values = iter([
        0.0, 0.001,        # hop 1
        1.0, 1.001,        # hop 2
    ])
    wall_base = datetime(2026, 4, 16, 10, 0, 0)
    wall_values = iter([
        wall_base,                                    # hop 1 before
        wall_base + timedelta(milliseconds=1),        # hop 1 after
        wall_base + timedelta(seconds=1),             # hop 2 before
        wall_base + timedelta(seconds=121),           # hop 2 after → wake!
    ])

    fake_time_mod = types.SimpleNamespace(monotonic=lambda: next(mono_values))
    fake_datetime_cls = types.SimpleNamespace(now=lambda: next(wall_values))

    monkeypatch.setattr(mod.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(mod, "time", fake_time_mod)
    monkeypatch.setattr(mod, "datetime", fake_datetime_cls)

    woke = await mod._wake_aware_sleep(3600, step_s=30)

    assert woke is True
    assert hop_count["n"] == 2, "should exit immediately on hop that saw drift"


async def test_wake_aware_sleep_ignores_small_jitter(monkeypatch):
    """Drift well below the 60s threshold should not trip the detector."""
    async def fake_sleep(_delay):
        pass

    mono_values = iter([0.0, 0.5, 1.0, 1.5, 2.0, 2.5])
    wall_base = datetime(2026, 4, 16, 10, 0, 0)
    wall_values = iter([
        wall_base,
        wall_base + timedelta(milliseconds=700),   # 200ms drift — jitter
        wall_base + timedelta(seconds=1),
        wall_base + timedelta(seconds=1, milliseconds=700),
        wall_base + timedelta(seconds=2),
        wall_base + timedelta(seconds=2, milliseconds=700),
    ])

    monkeypatch.setattr(mod.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(
        mod, "time", types.SimpleNamespace(monotonic=lambda: next(mono_values))
    )
    monkeypatch.setattr(
        mod, "datetime", types.SimpleNamespace(now=lambda: next(wall_values))
    )

    woke = await mod._wake_aware_sleep(1.5, step_s=0.5)
    assert woke is False


# ── _guarded_catch_up ───────────────────────────────────────────────────────


async def test_guarded_catch_up_skips_when_lock_is_held(
    monkeypatch, fresh_lock, caplog
):
    """Tick fires while previous sync still running → log + skip."""
    ran = []

    async def fake_catch_up(uid, trigger_type="scheduled"):
        ran.append(uid)

    monkeypatch.setattr(mod, "_catch_up", fake_catch_up)

    await fresh_lock.acquire()
    try:
        with caplog.at_level("INFO", logger=mod.logger.name):
            did_run = await mod._guarded_catch_up(_UID)
    finally:
        fresh_lock.release()

    assert did_run is False
    assert ran == []
    assert any("skipping this tick" in r.message for r in caplog.records)


async def test_guarded_catch_up_runs_when_lock_is_free(
    monkeypatch, fresh_lock
):
    ran = []

    async def fake_catch_up(uid, trigger_type="scheduled"):
        ran.append(uid)

    monkeypatch.setattr(mod, "_catch_up", fake_catch_up)

    did_run = await mod._guarded_catch_up(_UID)

    assert did_run is True
    assert ran == [_UID]
    assert not fresh_lock.locked()  # released after use


async def test_guarded_catch_up_survives_exception(
    monkeypatch, fresh_lock, caplog
):
    """A failing inner call must not propagate; the lock must still release."""
    async def broken_catch_up(_uid, trigger_type="scheduled"):
        raise RuntimeError("network down")

    monkeypatch.setattr(mod, "_catch_up", broken_catch_up)

    with caplog.at_level("ERROR", logger=mod.logger.name):
        did_run = await mod._guarded_catch_up(_UID)

    assert did_run is True
    assert not fresh_lock.locked()
    assert any("sync failed" in r.message for r in caplog.records)


async def test_guarded_catch_up_serialises_concurrent_calls(
    monkeypatch, fresh_lock
):
    """If two callers race, the second one sees the lock held and skips."""
    in_flight = asyncio.Event()
    release_gate = asyncio.Event()
    ran = []

    async def slow_catch_up(uid, trigger_type="scheduled"):
        in_flight.set()
        await release_gate.wait()
        ran.append(uid)

    monkeypatch.setattr(mod, "_catch_up", slow_catch_up)

    first = asyncio.create_task(mod._guarded_catch_up(_UID))
    await in_flight.wait()

    # Second tick arrives while first is still inside _catch_up → skips.
    second = await mod._guarded_catch_up(_UID)
    assert second is False

    release_gate.set()
    first_result = await first
    assert first_result is True
    assert ran == [_UID]


# ── _prerequisites_ok ───────────────────────────────────────────────────────


def test_prerequisites_ok_rejects_missing_user_id(monkeypatch):
    monkeypatch.setattr(mod.settings, "sync_interval_min", 60)
    monkeypatch.setattr(mod.settings, "baseline_user_id", None)

    ok, reason = mod._prerequisites_ok()
    assert ok is False
    assert "BASELINE_USER_ID" in reason


def test_prerequisites_ok_rejects_disabled_interval(monkeypatch):
    monkeypatch.setattr(mod.settings, "sync_interval_min", 0)
    monkeypatch.setattr(mod.settings, "baseline_user_id", _UID)

    ok, reason = mod._prerequisites_ok()
    assert ok is False
    assert "loop disabled" in reason
