"""HC900 BLE reprocessing — destructive re-parse of historical raw_payloads.

Re-runs the current HC900 parser (``hc900_ble_v2``) over already-ingested
``hc900_scale`` raw_payloads for a given user and date range.  For each
payload in scope, this:

    1. Checks idempotency: skips if a completed IngestionRun already exists
       for this payload (override with ``--force``).
    2. Deletes every ``measurements`` row with ``raw_payload_id = <id>``.
    3. Invokes :meth:`IngestionService._parse_hc900_scale` on the payload,
       which re-decodes from the preserved ``raw_mfr_*_hex`` bytes and
       re-inserts the full 18-metric set using the latest formulas.
    4. Creates an IngestionRun (``operation_type=replay``) and links the
       payload with ``role='reprocessed'``.

Raw bytes (``raw_mfr_weight_hex`` / ``raw_mfr_impedance_hex``) are NEVER
touched — they are the source of truth that makes this operation safe.

Safety rails
------------
  * Strictly scoped to ``source_slug='hc900_ble'``.  Other sources are
    untouchable through this script.
  * Filtered by ``--user-id`` + ``--start`` + ``--end`` (inclusive, on
    ``payload_json.measured_at``).
  * ``--dry-run`` is the default.  Nothing is deleted or written unless
    you pass ``--execute``.
  * Single transaction: every delete + re-insert + status update commits
    together at the end, or rolls back on any failure.
  * Full before/after logging per payload.

Usage
-----
    # preview (default)
    python scripts/reprocess_hc900.py --user-id <UUID> \\
        --start 2026-04-01 --end 2026-04-16

    # destructively rewrite
    python scripts/reprocess_hc900.py --user-id <UUID> \\
        --start 2026-04-01 --end 2026-04-16 --execute

    # force re-run even already-reprocessed payloads
    python scripts/reprocess_hc900.py --user-id <UUID> \\
        --start 2026-04-01 --end 2026-04-16 --execute --force
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import UTC, date, datetime
from uuid import UUID

from sqlalchemy import Date, cast, delete, func, select
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import async_session
from app.models.data_source import DataSource
from app.models.ingestion_run import IngestionRun
from app.models.ingestion_run_payload import IngestionRunPayload
from app.models.measurement import Measurement
from app.models.raw_payload import RawPayload
from app.services.ingestion import IngestionService

logger = logging.getLogger("reprocess_hc900")

_SOURCE_SLUG = "hc900_ble"
_PAYLOAD_TYPE = "hc900_scale"


# ── Query ─────────────────────────────────────────────────────────────────────


async def find_payloads(
    session: AsyncSession,
    user_id: UUID,
    start: date,
    end: date,
) -> list[RawPayload]:
    """Return all hc900_ble raw_payloads for the user in the inclusive range.

    Date matching uses ``payload_json ->> 'measured_at'`` cast to a
    timestamptz so the filter stays correct even if measurements were
    previously deleted.
    """
    source_id_subq = (
        select(DataSource.id).where(DataSource.slug == _SOURCE_SLUG).scalar_subquery()
    )

    measured_at_expr = cast(
        RawPayload.payload_json["measured_at"].astext,
        TIMESTAMP(timezone=True),
    )
    measured_date = cast(measured_at_expr, Date)

    stmt = (
        select(RawPayload)
        .where(
            RawPayload.user_id == user_id,
            RawPayload.source_id == source_id_subq,
            RawPayload.payload_type == _PAYLOAD_TYPE,
            measured_date >= start,
            measured_date <= end,
        )
        .order_by(measured_at_expr.asc())
    )
    result = await session.execute(stmt)
    return list(result.scalars().all())


async def count_measurements_for(session: AsyncSession, payload_id) -> int:
    return await session.scalar(
        select(func.count())
        .select_from(Measurement)
        .where(Measurement.raw_payload_id == payload_id)
    ) or 0


# ── Core operation ────────────────────────────────────────────────────────────


async def reprocess_one(
    session: AsyncSession,
    service: IngestionService,
    payload: RawPayload,
    source_id: int,
    *,
    dry_run: bool,
    force: bool = False,
) -> dict:
    """Reprocess a single payload. Returns a summary dict for logging.

    With ``dry_run=True`` this only counts current measurements and does
    NOT delete, re-decode or re-insert — callers get a preview of scope.

    In execute mode, creates a per-payload IngestionRun (operation_type=replay)
    and links the payload with role='reprocessed'.  Skips without --force if a
    completed run for this payload already exists.
    """
    before = await count_measurements_for(session, payload.id)
    measured_at = payload.payload_json.get("measured_at", "?")
    decoded_version = (payload.payload_json.get("decoded") or {}).get(
        "decoder_version", "?"
    )

    summary: dict = {
        "payload_id": str(payload.id),
        "measured_at": measured_at,
        "prior_decoder_version": decoded_version,
        "prior_status": payload.processing_status,
        "before": before,
    }

    if dry_run:
        summary["action"] = "preview"
        return summary

    # Idempotency: skip if a completed replay run already exists for this payload
    idempotency_key = f"hc900:reprocess:{payload.user_id}:{payload.id}"
    existing_run = await session.scalar(
        select(IngestionRun).where(IngestionRun.idempotency_key == idempotency_key)
    )
    if existing_run is not None:
        if existing_run.status == "completed" and not force:
            summary["action"] = "skipped"
            summary["reason"] = "already reprocessed; pass --force to override"
            summary["run_id"] = str(existing_run.id)
            return summary
        # completed+force or failed → release the key so the new run may claim it
        existing_run.idempotency_key = None
        await session.flush()

    # Create a per-payload IngestionRun
    run = IngestionRun(
        user_id=payload.user_id,
        source_id=source_id,
        operation_type="replay",
        trigger_type="manual",
        idempotency_key=idempotency_key,
    )
    session.add(run)
    await session.flush()

    # Delete curated rows, re-parse from raw bytes
    await session.execute(
        delete(Measurement).where(Measurement.raw_payload_id == payload.id)
    )
    await session.flush()

    payload.processing_status = "pending"
    payload.processed_at = None
    payload.error_message = None
    await session.flush()

    await service._process(payload)  # noqa: SLF001 — intentional internal reuse
    await session.flush()

    after = await count_measurements_for(session, payload.id)

    # Populate counters and close run
    run.measurements_deleted = before
    run.measurements_created = after
    run.finished_at = datetime.now(UTC)

    if payload.processing_status == "processed":
        run.status = "completed"
    else:
        run.status = "failed"
        run.raw_payloads_failed = 1
        run.error_message = payload.error_message

    # Link payload to this run
    session.add(
        IngestionRunPayload(run_id=run.id, payload_id=payload.id, role="reprocessed")
    )
    await session.flush()

    summary["action"] = "reprocessed"
    summary["after"] = after
    summary["new_status"] = payload.processing_status
    summary["run_id"] = str(run.id)
    if payload.processing_status == "failed":
        summary["error"] = payload.error_message
    return summary


# ── Main pipeline ─────────────────────────────────────────────────────────────


async def run(args: argparse.Namespace) -> int:
    try:
        user_id = UUID(args.user_id)
    except ValueError:
        logger.error("Invalid --user-id (must be a UUID): %s", args.user_id)
        return 2

    try:
        start = date.fromisoformat(args.start)
        end = date.fromisoformat(args.end)
    except ValueError as e:
        logger.error("Invalid date: %s", e)
        return 2

    if start > end:
        logger.error("--start (%s) is after --end (%s)", start, end)
        return 2

    mode = "EXECUTE" if args.execute else "DRY-RUN"
    force = getattr(args, "force", False)
    logger.info(
        "[%s] Reprocessing hc900_ble payloads for user=%s range=%s..%s%s",
        mode,
        user_id,
        start,
        end,
        " (--force)" if force else "",
    )

    async with async_session() as session:
        payloads = await find_payloads(session, user_id, start, end)
        logger.info("Found %d payload(s) in scope.", len(payloads))
        if not payloads:
            return 0

        # Look up source_id once — shared across all per-payload runs
        source_id = await session.scalar(
            select(DataSource.id).where(DataSource.slug == _SOURCE_SLUG)
        )

        service = IngestionService(session)
        summaries: list[dict] = []

        try:
            for p in payloads:
                s = await reprocess_one(
                    session, service, p, source_id,
                    dry_run=not args.execute,
                    force=force,
                )
                summaries.append(s)
                action = s.get("action", "?")
                if action == "preview":
                    logger.info(
                        "  %s  %s  current_measurements=%d  prior_decoder=%s  status=%s",
                        s["measured_at"], s["payload_id"],
                        s["before"], s["prior_decoder_version"], s["prior_status"],
                    )
                elif action == "skipped":
                    logger.info(
                        "  SKIP  %s  %s  reason=%s",
                        s["measured_at"], s["payload_id"], s.get("reason", ""),
                    )
                else:
                    logger.info(
                        "  %s  %s  before=%d  after=%d  status=%s  prior=%s",
                        s["measured_at"], s["payload_id"],
                        s["before"], s["after"],
                        s["new_status"], s["prior_decoder_version"],
                    )
                    if "error" in s:
                        logger.error("    error: %s", s["error"])

            if args.execute:
                await session.commit()
                executed = [s for s in summaries if s.get("action") == "reprocessed"]
                skipped = [s for s in summaries if s.get("action") == "skipped"]
                logger.info(
                    "COMMITTED — %d reprocessed, %d skipped.",
                    len(executed), len(skipped),
                )
            else:
                logger.info(
                    "DRY-RUN — nothing written. Pass --execute to perform the "
                    "destructive reprocess (deletes %d measurements groups, "
                    "re-inserts from raw bytes using hc900_ble_v2).",
                    len(summaries),
                )
        except Exception:
            if args.execute:
                await session.rollback()
                logger.exception(
                    "Reprocessing failed — transaction rolled back, no changes written."
                )
            raise

    # Non-zero exit if any payload ended up in 'failed' after reprocess.
    if args.execute and any(s.get("new_status") == "failed" for s in summaries):
        return 1
    return 0


# ── CLI ───────────────────────────────────────────────────────────────────────


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description=(
            "Re-parse historical HC900 BLE raw_payloads against the current "
            "decoder (hc900_ble_v2). Destructive; dry-run by default."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument(
        "--user-id", required=True, metavar="UUID",
        help="Baseline user UUID to scope the reprocess.",
    )
    p.add_argument(
        "--start", required=True, metavar="YYYY-MM-DD",
        help="Inclusive start date (on payload_json.measured_at).",
    )
    p.add_argument(
        "--end", required=True, metavar="YYYY-MM-DD",
        help="Inclusive end date (on payload_json.measured_at).",
    )
    p.add_argument(
        "--execute", action="store_true",
        help="Actually delete and re-insert. Without this, runs in dry-run mode.",
    )
    p.add_argument(
        "--force", action="store_true",
        help="Override idempotency: re-run even payloads already reprocessed.",
    )
    p.add_argument("--debug", action="store_true", help="Enable debug logging.")
    return p


if __name__ == "__main__":
    _args = _build_parser().parse_args()
    logging.basicConfig(
        level=logging.DEBUG if _args.debug else logging.INFO,
        format="%(levelname)s %(message)s",
    )
    sys.exit(asyncio.run(run(_args)))
