"""On-demand Garmin sync service.

Exposes a single entrypoint — :func:`perform_on_demand_sync` — that the
``POST /api/v1/integrations/garmin/sync`` endpoint calls when the user clicks
"Refresh Garmin" in the Today v2 UI.

The heavy lifting (subprocess launch, raw-payload ingestion, cursor advance)
is already implemented for the background scheduler in
:mod:`app.services.garmin_scheduler`.  This module wraps those primitives
with two extra concerns the UI needs:

* **Semantic status** — the endpoint must distinguish a sync that brought
  new data (``completed``) from a sync that ran cleanly but found nothing
  new (``no_new_data``).  We derive this by comparing the latest Garmin
  ``measured_at`` before and after the subprocess.  ``measurements_created``
  is not populated by the Garmin parser today, so it cannot be the signal.

* **Anti-overlap across scheduler + UI** — the scheduler already uses a
  module-level :class:`asyncio.Lock`.  We check ``lock.locked()`` at entry
  and return ``already_running`` without touching DB when a sync is
  in-flight (scheduler tick or a prior UI click still running).  This keeps
  double-clicks from fanning out to two subprocesses fighting for the same
  Garmin token file.
"""
from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from typing import Literal

from sqlalchemy import text

from app.core.database import async_session
from app.services.garmin_scheduler import (
    _close_ingestion_run,
    _create_ingestion_run,
    _get_garmin_source_id,
    _get_sync_lock,
    _run_sync,
    _upsert_source_cursor,
)

logger = logging.getLogger(__name__)

SyncStatus = Literal["completed", "no_new_data", "failed", "already_running"]

# On-demand syncs always cover today — the scheduler handles backfill.
# If the caller's last Garmin day is older than today, catch-up is the
# scheduler's job; here we just refresh the current day so the dashboard
# reflects whatever Garmin Connect has published since the last tick.
_ON_DEMAND_WINDOW_DAYS = 1


@dataclass
class GarminSyncResult:
    status: SyncStatus
    run_id: uuid.UUID | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error_message: str | None = None


async def _latest_garmin_measured_at(user_id: uuid.UUID) -> datetime | None:
    """MAX(measured_at) across all garmin_connect measurements for ``user_id``.

    Used as the before/after signal for completed vs no_new_data.  Returns
    ``None`` when the user has never had a Garmin measurement — in that
    case any successful sync counts as ``completed``.
    """
    async with async_session() as db:
        result = await db.execute(
            text(
                """
                SELECT MAX(m.measured_at)
                FROM measurements m
                JOIN data_sources ds ON ds.id = m.source_id
                WHERE m.user_id = :uid AND ds.slug = 'garmin_connect'
                """
            ),
            {"uid": user_id},
        )
        return result.scalar()


async def perform_on_demand_sync(user_id_str: str) -> GarminSyncResult:
    """Run one Garmin sync synchronously, coordinated with the scheduler lock.

    Flow:
      1. Validate the user_id.
      2. If the shared sync lock is already held → ``already_running``.
      3. Resolve the garmin_connect source.  If missing → ``failed``.
      4. Acquire the lock.  Capture ``max_before``.
      5. Create an IngestionRun with trigger_type='ui_button'.
      6. Launch ``scripts/sync_garmin.py`` covering today (single-day window).
      7. On non-zero rc: mark run failed, return ``failed``.
      8. On zero rc: close run as completed, advance the source cursor,
         capture ``max_after``.  If it advanced → ``completed``, else
         ``no_new_data``.

    The function does **not** raise on expected failure paths — it returns
    a :class:`GarminSyncResult` with the appropriate status so the endpoint
    can render it to the UI verbatim.
    """
    try:
        uid = uuid.UUID(user_id_str)
    except ValueError:
        return GarminSyncResult(
            status="failed", error_message=f"invalid user_id: {user_id_str!r}"
        )

    lock = _get_sync_lock()

    # Atomic check-and-acquire: asyncio is single-threaded, so as long as
    # there is no `await` between ``lock.locked()`` and the synchronous path
    # of ``lock.acquire()`` (which completes without yielding when the lock
    # is free), no other task can sneak in.  The earlier version of this
    # function checked the lock, then awaited a DB lookup, which yielded the
    # loop and allowed two concurrent HTTP requests to both pass the check
    # and then serialize through ``async with lock:`` — the second caller
    # ran a second subprocess instead of being rejected as ``already_running``.
    # Observed on 2026-04-18 smoke test: two back-to-back POSTs both
    # completed a sync instead of one short-circuiting.
    if lock.locked():
        logger.info("[garmin-sync] on-demand request skipped — sync already running")
        return GarminSyncResult(status="already_running")
    await lock.acquire()
    try:
        source_id = await _get_garmin_source_id()
        if source_id is None:
            return GarminSyncResult(
                status="failed",
                error_message="garmin_connect data source not seeded",
            )

        started_at = datetime.now(UTC)
        max_before = await _latest_garmin_measured_at(uid)

        run_id = await _create_ingestion_run(
            uid, source_id, trigger_type="ui_button", idempotency_key=None
        )

        today = date.today()
        start = today - timedelta(days=_ON_DEMAND_WINDOW_DAYS - 1)
        rc = await _run_sync(
            user_id_str,
            start_date=start,
            end_date=today,
            ingestion_run_id=str(run_id),
        )

        finished_at = datetime.now(UTC)

        if rc != 0:
            error_msg = f"sync_garmin.py exited rc={rc}"
            await _close_ingestion_run(run_id, "failed", error_message=error_msg)
            return GarminSyncResult(
                status="failed",
                run_id=run_id,
                started_at=started_at,
                finished_at=finished_at,
                error_message=error_msg,
            )

        await _close_ingestion_run(run_id, "completed")
        await _upsert_source_cursor(uid, source_id, today, run_id)

        max_after = await _latest_garmin_measured_at(uid)
        advanced = max_before is None or (
            max_after is not None and max_after > max_before
        )

        return GarminSyncResult(
            status="completed" if advanced else "no_new_data",
            run_id=run_id,
            started_at=started_at,
            finished_at=finished_at,
        )
    finally:
        lock.release()
