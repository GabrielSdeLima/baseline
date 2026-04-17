"""Garmin auto-sync scheduler — runs inside the FastAPI lifespan.

Behaviour
---------
1. **Startup catch-up**: on API boot, queries the most recent Garmin measurement
   for ``settings.baseline_user_id``.  If the gap to today is non-empty,
   invokes ``scripts/sync_garmin.py --start-date ... --end-date today`` to
   backfill every missed day in one shot.  A fresh user (no prior Garmin data)
   gets a 7-day initial backfill.

2. **Recurring loop**: every ``settings.sync_interval_min`` minutes, re-runs
   the same catch-up.  This both fills gaps created by PC sleep/hibernate and
   refreshes today's measurements (body battery, stress, sleep score and HRV
   are published throughout the day by Garmin Connect).  Set
   ``SYNC_INTERVAL_MIN=0`` (env) to disable the recurring tick.

3. **Wake-aware sleep**: the tick sleeps in short hops and watches wall-clock
   drift against a monotonic clock.  A large positive drift during a single
   hop means the host was suspended (S3/S4) and the wall-clock jumped forward
   while the monotonic clock stayed frozen.  On detection the scheduler
   exits the wait early and syncs immediately instead of sitting idle for
   the rest of the interval.

4. **Non-overlapping syncs**: an ``asyncio.Lock`` guards every invocation.
   If a tick fires while the previous sync is still running (slow network,
   long backfill) the new tick logs a skip and waits for the next cycle.

5. **Operational traceability**: each sync creates an ``IngestionRun`` before
   launching the subprocess and closes it as completed/failed afterward.
   A ``SourceCursor`` for ``daily_summary`` is upserted on every successful run.

Graceful degradation
--------------------
If prerequisites are missing the scheduler logs a single info line and exits
without error — the API keeps serving normally.  Prerequisites:

    - ``settings.baseline_user_id`` is set (env ``BASELINE_USER_ID``)
    - ``scripts/garmin_config.json`` exists
    - ``scripts/sync_garmin.py`` is present
    - ``settings.sync_interval_min`` > 0

Subprocess failures and unexpected exceptions from the inner catch-up are
caught and logged — the scheduler keeps running.
"""
from __future__ import annotations

import asyncio
import logging
import sys
import time
import uuid
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

from sqlalchemy import select, text

from app.core.config import settings
from app.core.database import async_session
from app.models.data_source import DataSource
from app.models.ingestion_run import IngestionRun
from app.models.source_cursor import SourceCursor

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS_DIR = _REPO_ROOT / "scripts"
_SYNC_SCRIPT = _SCRIPTS_DIR / "sync_garmin.py"
_GARMIN_CONFIG = _SCRIPTS_DIR / "garmin_config.json"
_INITIAL_BACKFILL_DAYS = 7

# Wake detection threshold.  If wall-clock advanced more than this over a
# single sleep hop while the monotonic clock barely moved, the host almost
# certainly went to S3/S4.  60s tolerates normal scheduler jitter.
_WAKE_DRIFT_THRESHOLD_S = 60.0

# Split long waits into short hops so wake is detected promptly instead of
# only after the full ``sync_interval_min`` has elapsed.
_SLEEP_STEP_S = 30.0

# Lazy — binds to the scheduler's running loop on first use.
_sync_lock: asyncio.Lock | None = None


def _get_sync_lock() -> asyncio.Lock:
    global _sync_lock
    if _sync_lock is None:
        _sync_lock = asyncio.Lock()
    return _sync_lock


# ---------------------------------------------------------------------------
# DB helpers — each opens its own session (scheduler runs outside request ctx)
# ---------------------------------------------------------------------------


async def _last_garmin_day(user_id: uuid.UUID) -> date | None:
    """Return the most recent ``measured_at`` date for any Garmin measurement."""
    async with async_session() as db:
        result = await db.execute(
            text(
                """
                SELECT MAX((m.measured_at AT TIME ZONE 'UTC')::date)
                FROM measurements m
                JOIN data_sources ds ON ds.id = m.source_id
                WHERE m.user_id = :uid AND ds.slug = 'garmin_connect'
                """
            ),
            {"uid": user_id},
        )
        return result.scalar()


async def _get_garmin_source_id() -> int | None:
    """Return the PK of the garmin_connect data source, or None if not seeded."""
    async with async_session() as db:
        result = await db.execute(
            select(DataSource.id).where(DataSource.slug == "garmin_connect")
        )
        return result.scalar_one_or_none()


async def _create_ingestion_run(
    user_id: uuid.UUID,
    source_id: int,
    trigger_type: str,
    idempotency_key: str | None,
) -> uuid.UUID:
    """Insert an IngestionRun with status='running' and return its ID."""
    async with async_session() as db:
        run = IngestionRun(
            user_id=user_id,
            source_id=source_id,
            operation_type="cloud_sync",
            trigger_type=trigger_type,
            idempotency_key=idempotency_key,
        )
        db.add(run)
        await db.flush()
        run_id = run.id
        await db.commit()
        return run_id


async def _close_ingestion_run(
    run_id: uuid.UUID,
    status: str,
    error_message: str | None = None,
) -> None:
    """Update a run's status and finished_at."""
    async with async_session() as db:
        run = await db.get(IngestionRun, run_id)
        if run is None:
            return
        run.status = status
        run.finished_at = datetime.now(UTC)
        if error_message:
            run.error_message = error_message
        await db.commit()


async def _upsert_source_cursor(
    user_id: uuid.UUID,
    source_id: int,
    logical_date: date,
    run_id: uuid.UUID,
) -> None:
    """Create or advance the garmin_connect daily_summary source cursor."""
    async with async_session() as db:
        result = await db.execute(
            select(SourceCursor).where(
                SourceCursor.user_id == user_id,
                SourceCursor.source_id == source_id,
                SourceCursor.cursor_name == "daily_summary",
                SourceCursor.cursor_scope_key == "",
            )
        )
        cursor = result.scalar_one_or_none()
        now = datetime.now(UTC)
        if cursor is not None:
            cursor.cursor_value_json = {"date": logical_date.isoformat()}
            cursor.last_successful_run_id = run_id
            cursor.last_advanced_at = now
            cursor.updated_at = now
        else:
            db.add(SourceCursor(
                user_id=user_id,
                source_id=source_id,
                cursor_name="daily_summary",
                cursor_scope_key="",
                cursor_value_json={"date": logical_date.isoformat()},
                last_successful_run_id=run_id,
                last_advanced_at=now,
            ))
        await db.commit()


# ---------------------------------------------------------------------------
# Subprocess launcher
# ---------------------------------------------------------------------------


async def _run_sync(
    user_id: str,
    *,
    days: int | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
    ingestion_run_id: str | None = None,
) -> int:
    """Invoke ``scripts/sync_garmin.py`` as a subprocess.  Returns the exit code."""
    args: list[str] = [sys.executable, str(_SYNC_SCRIPT), "--user-id", user_id]
    if days is not None:
        args += ["--days", str(days)]
    if start_date is not None and end_date is not None:
        args += ["--start-date", start_date.isoformat(), "--end-date", end_date.isoformat()]
    if ingestion_run_id is not None:
        args += ["--ingestion-run-id", ingestion_run_id]

    logger.info("[garmin-sync] launching: %s", " ".join(args[1:]))
    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await proc.communicate()
    rc = proc.returncode or 0
    if rc == 0:
        logger.info("[garmin-sync] completed ok")
    else:
        msg = (stderr.decode(errors="replace") or stdout.decode(errors="replace")).strip()
        logger.error("[garmin-sync] failed rc=%d: %s", rc, msg[:500])
    return rc


# ---------------------------------------------------------------------------
# Catch-up logic
# ---------------------------------------------------------------------------


async def _catch_up(user_id_str: str, trigger_type: str = "scheduled") -> None:
    """Backfill the gap between the last Garmin measurement and today.

    Creates an IngestionRun before launching sync_garmin.py and closes it
    as completed/failed after the subprocess returns.  Advances the
    daily_summary source cursor on success.

    When ``last_day >= today`` the function still re-syncs today so the
    intraday updates Garmin Connect publishes later (body battery, stress,
    steps, sleep score, HRV) are captured.  Each re-sync creates a new
    versioned raw_payload; the parser replaces curated measurements for that
    logical date with data from the latest snapshot.
    """
    try:
        uid = uuid.UUID(user_id_str)
    except ValueError:
        logger.error(
            "[garmin-sync] baseline_user_id is not a valid UUID: %r", user_id_str
        )
        return

    today = date.today()
    last_day = await _last_garmin_day(uid)

    if last_day is None:
        effective_trigger = "backfill"
        start = today - timedelta(days=_INITIAL_BACKFILL_DAYS)
        logger.info(
            "[garmin-sync] no prior Garmin data — backfilling %d days from %s",
            _INITIAL_BACKFILL_DAYS, start,
        )
    elif last_day >= today:
        effective_trigger = trigger_type
        start = today
        logger.info("[garmin-sync] refreshing today (last=%s)", last_day)
    else:
        effective_trigger = trigger_type
        start = last_day + timedelta(days=1)
        logger.info("[garmin-sync] catch-up from %s to %s", start, today)

    # Backfills are idempotent by date range so the same 7-day seed is never
    # doubled.  Scheduled/wake/startup refreshes use a null key — a completed
    # run must never block today's legitimate intraday refresh.
    idempotency_key: str | None = (
        f"garmin:backfill:{uid}:{start.isoformat()}:{today.isoformat()}"
        if effective_trigger == "backfill"
        else None
    )

    source_id = await _get_garmin_source_id()
    if source_id is None:
        logger.error(
            "[garmin-sync] garmin_connect data source not found — run: alembic upgrade head"
        )
        return

    run_id = await _create_ingestion_run(uid, source_id, effective_trigger, idempotency_key)

    rc = await _run_sync(
        user_id_str,
        start_date=start,
        end_date=today,
        ingestion_run_id=str(run_id),
    )

    if rc == 0:
        await _close_ingestion_run(run_id, "completed")
        await _upsert_source_cursor(uid, source_id, today, run_id)
    else:
        await _close_ingestion_run(
            run_id, "failed",
            error_message=f"sync_garmin.py exited rc={rc}",
        )


async def _guarded_catch_up(user_id: str, trigger_type: str = "scheduled") -> bool:
    """Run ``_catch_up`` under the anti-overlap lock.

    Returns True if the catch-up ran (even if the inner call failed), False
    if it was skipped because a previous sync was still in progress.
    Exceptions from ``_catch_up`` are logged and swallowed so the scheduler
    loop keeps ticking.
    """
    lock = _get_sync_lock()
    if lock.locked():
        logger.info(
            "[garmin-sync] previous sync still running — skipping this tick"
        )
        return False
    async with lock:
        try:
            await _catch_up(user_id, trigger_type)
        except Exception:
            logger.exception("[garmin-sync] sync failed; will retry next cycle")
    return True


async def _wake_aware_sleep(
    seconds: float, *, step_s: float = _SLEEP_STEP_S
) -> bool:
    """Sleep for up to ``seconds`` seconds, returning early when the host
    appears to have woken from S3/S4 sleep.

    Implementation: sleep in short hops.  After each hop, compare wall-clock
    elapsed against monotonic elapsed — a large positive drift means the
    host was suspended during the hop (wall-clock keeps advancing while the
    monotonic clock stays frozen on most OSes).  On detection, log and
    return True so the caller can run a catch-up immediately.

    Returns False when the full duration elapsed normally.
    """
    remaining = seconds
    while remaining > 0:
        step = min(step_s, remaining)
        wall_before = datetime.now()
        mono_before = time.monotonic()
        await asyncio.sleep(step)
        mono_elapsed = time.monotonic() - mono_before
        wall_elapsed = (datetime.now() - wall_before).total_seconds()
        drift = wall_elapsed - mono_elapsed
        if drift >= _WAKE_DRIFT_THRESHOLD_S:
            logger.info(
                "[garmin-sync] detected wake from system sleep "
                "(monotonic=%.0fs, wall=%.0fs, drift=%.0fs)",
                mono_elapsed, wall_elapsed, drift,
            )
            return True
        remaining -= step
    return False


def _prerequisites_ok() -> tuple[bool, str]:
    """Return (ok, reason).  ``reason`` is empty when ok."""
    if settings.sync_interval_min <= 0:
        return False, f"sync_interval_min={settings.sync_interval_min} — loop disabled"
    if not settings.baseline_user_id:
        return False, "BASELINE_USER_ID not set — auto-sync disabled"
    if not _GARMIN_CONFIG.exists():
        return False, f"{_GARMIN_CONFIG} missing — auto-sync disabled"
    if not _SYNC_SCRIPT.exists():
        return False, f"{_SYNC_SCRIPT} missing — auto-sync disabled"
    return True, ""


async def run_scheduler() -> None:
    """Main loop — called from the FastAPI lifespan.

    Cancelled cleanly on API shutdown.  Any subprocess failure or catch-up
    exception is caught by ``_guarded_catch_up`` and does not stop the loop.
    """
    ok, reason = _prerequisites_ok()
    if not ok:
        logger.info("[garmin-sync] %s", reason)
        return

    user_id = settings.baseline_user_id or ""  # narrow for type checker
    interval_s = settings.sync_interval_min * 60
    logger.info(
        "[garmin-sync] scheduler starting (user=%s, interval=%dmin)",
        user_id, settings.sync_interval_min,
    )

    try:
        await _guarded_catch_up(user_id, trigger_type="startup")
        while True:
            woke = await _wake_aware_sleep(interval_s)
            current_trigger = "wake" if woke else "scheduled"
            if woke:
                logger.info("[garmin-sync] running catch-up after wake")
            await _guarded_catch_up(user_id, trigger_type=current_trigger)
    except asyncio.CancelledError:
        logger.info("[garmin-sync] scheduler stopped")
        raise
