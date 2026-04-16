"""Garmin auto-sync scheduler — runs inside the FastAPI lifespan.

Behaviour
---------
1. **Startup catch-up**: on API boot, queries the most recent Garmin measurement
   for ``settings.baseline_user_id``.  If the gap to today is non-empty,
   invokes ``scripts/sync_garmin.py --start-date ... --end-date today`` to
   backfill every missed day in one shot.  A fresh user (no prior Garmin data)
   gets a 7-day initial backfill.

2. **Recurring loop**: every ``settings.sync_interval_min`` minutes, invokes
   ``scripts/sync_garmin.py --days 1`` to pull the latest daily summary as
   Garmin Connect emits updates throughout the day.  Set ``SYNC_INTERVAL_MIN=0``
   (env) to disable.

Graceful degradation
--------------------
If prerequisites are missing the scheduler logs a single info line and exits
without error — the API keeps serving normally.  Prerequisites:

    - ``settings.baseline_user_id`` is set (env ``BASELINE_USER_ID``)
    - ``scripts/garmin_config.json`` exists
    - ``scripts/sync_garmin.py`` is present
    - ``settings.sync_interval_min`` > 0

The scheduler invokes ``sync_garmin.py`` as a subprocess (same pattern as the
``/scale/scan`` endpoint) so the ingestion logic has one source of truth.
"""
from __future__ import annotations

import asyncio
import logging
import sys
import uuid
from datetime import date, timedelta
from pathlib import Path

from sqlalchemy import text

from app.core.config import settings
from app.core.database import async_session

logger = logging.getLogger(__name__)

_REPO_ROOT = Path(__file__).resolve().parents[2]
_SCRIPTS_DIR = _REPO_ROOT / "scripts"
_SYNC_SCRIPT = _SCRIPTS_DIR / "sync_garmin.py"
_GARMIN_CONFIG = _SCRIPTS_DIR / "garmin_config.json"
_INITIAL_BACKFILL_DAYS = 7


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


async def _run_sync(
    user_id: str,
    *,
    days: int | None = None,
    start_date: date | None = None,
    end_date: date | None = None,
) -> int:
    """Invoke ``scripts/sync_garmin.py`` as a subprocess.  Returns the exit code."""
    args: list[str] = [sys.executable, str(_SYNC_SCRIPT), "--user-id", user_id]
    if days is not None:
        args += ["--days", str(days)]
    if start_date is not None and end_date is not None:
        args += ["--start-date", start_date.isoformat(), "--end-date", end_date.isoformat()]

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


async def _catch_up(user_id_str: str) -> None:
    """Backfill gap between the last Garmin measurement and today."""
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
        start = today - timedelta(days=_INITIAL_BACKFILL_DAYS)
        logger.info(
            "[garmin-sync] no prior Garmin data — backfilling %d days from %s",
            _INITIAL_BACKFILL_DAYS, start,
        )
    elif last_day >= today:
        logger.info("[garmin-sync] already up to date (last=%s)", last_day)
        return
    else:
        start = last_day + timedelta(days=1)
        logger.info("[garmin-sync] catch-up from %s to %s", start, today)

    await _run_sync(user_id_str, start_date=start, end_date=today)


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

    Cancelled cleanly on API shutdown.  Any subprocess failure is logged and
    does not stop the loop; the next iteration will retry.
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
        await _catch_up(user_id)
        while True:
            await asyncio.sleep(interval_s)
            try:
                await _run_sync(user_id, days=1)
            except Exception:
                logger.exception("[garmin-sync] iteration failed; will retry next cycle")
    except asyncio.CancelledError:
        logger.info("[garmin-sync] scheduler stopped")
        raise
