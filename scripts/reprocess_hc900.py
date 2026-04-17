"""HC900 BLE reprocessing — destructive re-parse of historical raw_payloads.

Re-runs the current HC900 parser (``hc900_ble_v2``) over already-ingested
``hc900_scale`` raw_payloads for a given user and date range.  For each
payload in scope, this:

    1. Deletes every ``measurements`` row with ``raw_payload_id = <id>``.
    2. Invokes :meth:`IngestionService._parse_hc900_scale` on the payload,
       which re-decodes from the preserved ``raw_mfr_*_hex`` bytes and
       re-inserts the full 18-metric set using the latest formulas.
    3. Updates the payload's ``processing_status``/``processed_at``.

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
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from datetime import date
from uuid import UUID

from sqlalchemy import Date, cast, delete, func, select
from sqlalchemy.dialects.postgresql import TIMESTAMP
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import async_session
from app.models.data_source import DataSource
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
    *,
    dry_run: bool,
) -> dict:
    """Reprocess a single payload. Returns a summary dict for logging.

    With ``dry_run=True`` this only counts current measurements and does
    NOT delete, re-decode or re-insert — callers get a preview of scope.
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

    # Destructive path: delete curated rows, then re-parse from raw bytes.
    await session.execute(
        delete(Measurement).where(Measurement.raw_payload_id == payload.id)
    )
    await session.flush()

    # Reset status so _process doesn't short-circuit on "already has data".
    payload.processing_status = "pending"
    payload.processed_at = None
    payload.error_message = None
    await session.flush()

    await service._process(payload)  # noqa: SLF001 — intentional internal reuse
    await session.flush()

    after = await count_measurements_for(session, payload.id)
    summary["action"] = "reprocessed"
    summary["after"] = after
    summary["new_status"] = payload.processing_status
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
    logger.info(
        "[%s] Reprocessing hc900_ble payloads for user=%s range=%s..%s",
        mode,
        user_id,
        start,
        end,
    )

    async with async_session() as session:
        payloads = await find_payloads(session, user_id, start, end)
        logger.info("Found %d payload(s) in scope.", len(payloads))
        if not payloads:
            return 0

        service = IngestionService(session)
        summaries: list[dict] = []

        try:
            for p in payloads:
                s = await reprocess_one(session, service, p, dry_run=not args.execute)
                summaries.append(s)
                if args.execute:
                    logger.info(
                        "  %s  %s  before=%d  after=%d  status=%s  prior=%s",
                        s["measured_at"],
                        s["payload_id"],
                        s["before"],
                        s["after"],
                        s["new_status"],
                        s["prior_decoder_version"],
                    )
                    if "error" in s:
                        logger.error("    error: %s", s["error"])
                else:
                    logger.info(
                        "  %s  %s  current_measurements=%d  prior_decoder=%s  status=%s",
                        s["measured_at"],
                        s["payload_id"],
                        s["before"],
                        s["prior_decoder_version"],
                        s["prior_status"],
                    )

            if args.execute:
                await session.commit()
                logger.info(
                    "COMMITTED — %d payload(s) reprocessed.", len(summaries)
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
    p.add_argument("--debug", action="store_true", help="Enable debug logging.")
    return p


if __name__ == "__main__":
    _args = _build_parser().parse_args()
    logging.basicConfig(
        level=logging.DEBUG if _args.debug else logging.INFO,
        format="%(levelname)s %(message)s",
    )
    sys.exit(asyncio.run(run(_args)))
