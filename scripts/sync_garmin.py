"""Garmin Connect daily sync — end-to-end pipeline.

Fetches daily health summaries from Garmin Connect (stats, HRV, sleep) and
submits them to the Baseline ingestion API as garmin_connect_daily payloads.

Authentication:
  First run authenticates via Garmin SSO and persists OAuth2 tokens to disk.
  Subsequent runs reload the token file — no re-authentication needed until
  the refresh token expires (typically weeks).

  If your account has MFA enabled, you will be prompted interactively on the
  first run. Subsequent runs use the persisted token and skip MFA.

Prerequisites:
  - PostgreSQL running and migrations applied:
        docker compose up -d && alembic upgrade head
  - Baseline API running:
        uvicorn app.main:app --reload
  - Garmin integration extras installed:
        pip install -e ".[garmin]"
  - Config file:
        cp scripts/garmin_config.json.example scripts/garmin_config.json
        # edit email, password, token_store, user_timezone

Usage:
    python scripts/sync_garmin.py --user-id <UUID>                     # last 7 days
    python scripts/sync_garmin.py --user-id <UUID> --date 2026-04-15   # one day
    python scripts/sync_garmin.py --user-id <UUID> --days 30           # backfill 30 days
    python scripts/sync_garmin.py --user-id <UUID> --dry-run           # print, don't submit
    python scripts/sync_garmin.py --user-id <UUID> \\
        --start-date 2026-03-01 --end-date 2026-04-15                  # date range
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx

# garminconnect is an optional dependency ([garmin] extras).
# It is imported lazily inside login() so that the helper functions
# (build_external_id, date_range, load_config, build_payload, ingest) remain
# importable and testable without the extra installed.
_GARMINCONNECT_MISSING_MSG = (
    "garminconnect not installed.\n"
    "Run: pip install -e \".[garmin]\""
)

# ── Paths ─────────────────────────────────────────────────────────────────────

_SCRIPTS_DIR = Path(__file__).parent
_CONFIG_PATH = _SCRIPTS_DIR / "garmin_config.json"
_DEFAULT_API_URL = os.environ.get("BASELINE_API_URL", "http://localhost:8000")
_DEFAULT_USER_ID = os.environ.get("BASELINE_USER_ID")

logger = logging.getLogger(__name__)


# ── Config ────────────────────────────────────────────────────────────────────


def load_config(
    email: str | None = None,
    password: str | None = None,
    token_store: str | None = None,
    user_timezone: str | None = None,
) -> dict:
    """Load config from garmin_config.json, then apply CLI overrides.

    CLI arguments take precedence over the file.  Raises ValueError if any
    required field is missing after merging.
    """
    config: dict = {}

    if _CONFIG_PATH.exists():
        with open(_CONFIG_PATH) as f:
            raw = json.load(f)
        config = {k: v for k, v in raw.items() if not k.startswith("_")}
    else:
        logger.warning(
            "garmin_config.json not found at %s — relying on CLI arguments only.",
            _CONFIG_PATH,
        )

    if email is not None:
        config["email"] = email
    if password is not None:
        config["password"] = password
    if token_store is not None:
        config["token_store"] = token_store
    if user_timezone is not None:
        config["user_timezone"] = user_timezone

    missing = [
        f for f in ("email", "password", "token_store", "user_timezone")
        if f not in config
    ]
    if missing:
        raise ValueError(
            f"Missing config fields: {missing}. "
            "Create scripts/garmin_config.json or pass the corresponding CLI flags."
        )

    return config


# ── Garmin Connect client ─────────────────────────────────────────────────────


def login(config: dict):
    """Authenticate to Garmin Connect and return a logged-in Garmin client.

    Tokens are persisted to token_store so subsequent runs skip SSO.
    On first run (or after token expiry) email + password are used.
    MFA is prompted interactively if required by the account.

    Raises ImportError (with install instructions) if garminconnect is absent.
    """
    try:
        from garminconnect import (
            Garmin,
            GarminConnectAuthenticationError,
            GarminConnectConnectionError,
            GarminConnectTooManyRequestsError,
        )
    except ImportError as exc:
        raise ImportError(_GARMINCONNECT_MISSING_MSG) from exc

    token_path = Path(config["token_store"]).expanduser()
    token_path.mkdir(parents=True, exist_ok=True)

    gc = Garmin(email=config["email"], password=config["password"])
    try:
        gc.login(tokenstore=str(token_path))
    except GarminConnectAuthenticationError as e:
        raise RuntimeError(
            f"Garmin authentication failed: {e}\n"
            "Check email/password in garmin_config.json."
        ) from e
    except GarminConnectConnectionError as e:
        raise RuntimeError(f"Cannot reach Garmin Connect: {e}") from e
    except GarminConnectTooManyRequestsError as e:
        raise RuntimeError(
            f"Garmin rate-limited: {e}\n"
            "Wait a few minutes before retrying."
        ) from e

    return gc


# ── Data fetch ────────────────────────────────────────────────────────────────


def fetch_daily(gc: object, date_str: str) -> tuple[dict, dict, dict]:
    """Fetch stats, HRV, and sleep for a single calendar date.

    Each endpoint is fetched independently — a failure on one does not abort
    the others.  Partial data (e.g., HRV unavailable for the device) is
    accepted; the parser skips null fields gracefully.
    """
    logger.debug("[garmin] fetching %s …", date_str)

    try:
        stats: dict = gc.get_stats(date_str) or {}
    except Exception as e:
        logger.warning("[garmin] stats fetch failed (%s): %s", date_str, e)
        stats = {}

    try:
        hrv: dict = gc.get_hrv_data(date_str) or {}
    except Exception as e:
        logger.warning("[garmin] HRV fetch failed (%s): %s", date_str, e)
        hrv = {}

    try:
        sleep: dict = gc.get_sleep_data(date_str) or {}
    except Exception as e:
        logger.warning("[garmin] sleep fetch failed (%s): %s", date_str, e)
        sleep = {}

    return stats, hrv, sleep


# ── Payload / external ID ─────────────────────────────────────────────────────


def build_payload(
    date_str: str,
    user_timezone: str,
    stats: dict,
    hrv: dict,
    sleep: dict,
) -> dict:
    """Build the garmin_connect_v1 raw payload for the Baseline ingestion API.

    Raw API responses are preserved verbatim so the parser can reprocess
    with improved logic without re-fetching from Garmin Connect.

    user_timezone is embedded in the payload so the parser can derive the
    correct measured_at (noon in the user's local timezone) without a DB
    lookup.  It is sourced from garmin_config.json at fetch time.
    """
    return {
        "format_version": "garmin_connect_v1",
        "date": date_str,
        "user_timezone": user_timezone,
        "fetch_method": "garminconnect_api",
        "stats": stats,
        "hrv": hrv,
        "sleep": sleep,
    }


def build_external_id(date_str: str, sync_ts: str | None = None) -> str:
    """Unique key per fetch: logical date + UTC sync timestamp.

    Format: garmin_connect_{YYYY-MM-DD}_{YYYYMMDDTHHMMSSz}

    Each invocation of sync_garmin.py generates one sync_ts shared across all
    dates in the batch so the run is a coherent unit.  No two fetches produce
    the same external_id, enabling the parser to replace stale curated data
    with the latest snapshot for any given date (intraday refresh).
    """
    ts = sync_ts or datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    return f"garmin_connect_{date_str}_{ts}"


# ── Baseline API call ─────────────────────────────────────────────────────────


def ingest(
    api_url: str,
    user_id: str,
    external_id: str,
    payload_json: dict,
    *,
    ingestion_run_id: str | None = None,
) -> dict:
    """POST the normalised payload to the Baseline ingestion API."""
    body = {
        "user_id": user_id,
        "source_slug": "garmin_connect",
        "external_id": external_id,
        "payload_type": "garmin_connect_daily",
        "payload_json": payload_json,
    }
    if ingestion_run_id is not None:
        body["ingestion_run_id"] = ingestion_run_id
    with httpx.Client(timeout=30) as client:
        response = client.post(f"{api_url}/api/v1/raw-payloads/ingest", json=body)
        response.raise_for_status()
        return response.json()


# ── Date utilities ────────────────────────────────────────────────────────────


def date_range(start: date, end: date) -> list[str]:
    """Return ISO date strings for every day from start to end (inclusive)."""
    current = start
    result: list[str] = []
    while current <= end:
        result.append(current.isoformat())
        current += timedelta(days=1)
    return result


# ── Main pipeline ─────────────────────────────────────────────────────────────


def run(args: argparse.Namespace) -> None:
    # 1. Config
    try:
        config = load_config(
            email=args.email,
            password=args.password,
            token_store=args.token_store,
            user_timezone=args.timezone,
        )
    except ValueError as e:
        logger.error("%s", e)
        sys.exit(1)

    # 2. Determine date range
    if args.date:
        dates = [args.date]
    elif args.start_date and args.end_date:
        dates = date_range(
            date.fromisoformat(args.start_date),
            date.fromisoformat(args.end_date),
        )
    else:
        today = date.today()
        start = today - timedelta(days=args.days - 1)
        dates = date_range(start, today)

    logger.info("Syncing %d day(s): %s → %s", len(dates), dates[0], dates[-1])

    # One timestamp shared across all dates — all payloads in this run are
    # identifiable as a unit via their common sync_ts suffix.
    sync_ts = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")

    # 3. Garmin Connect login
    logger.info("Logging in to Garmin Connect …")
    try:
        gc = login(config)
    except RuntimeError as e:
        logger.error("%s", e)
        sys.exit(1)
    logger.info("Login successful.")

    # 4. Fetch + ingest per day
    success = failed = dry_run_count = 0

    for date_str in dates:
        stats, hrv, sleep = fetch_daily(gc, date_str)
        payload_json = build_payload(
            date_str, config["user_timezone"], stats, hrv, sleep
        )
        external_id = build_external_id(date_str, sync_ts=sync_ts)

        if args.dry_run:
            print(f"\n-- DRY RUN {date_str} {'-' * 46}")
            print(json.dumps({"external_id": external_id, "payload_json": payload_json}, indent=2))
            dry_run_count += 1
            continue

        logger.info("[%s] submitting (external_id=%s) …", date_str, external_id)
        try:
            result = ingest(
                api_url=args.api_url,
                user_id=args.user_id,
                external_id=external_id,
                payload_json=payload_json,
                ingestion_run_id=args.ingestion_run_id,
            )
        except httpx.HTTPStatusError as e:
            logger.error(
                "[%s] API error %d: %s", date_str, e.response.status_code, e.response.text
            )
            failed += 1
            continue

        status = result.get("processing_status", "unknown")
        logger.info("[%s] id=%s  status=%s", date_str, result.get("id"), status)

        if status == "failed":
            logger.error("[%s] parser failed: %s", date_str, result.get("error_message"))
            failed += 1
        else:
            success += 1

    if args.dry_run:
        logger.info("Dry run complete — %d payload(s) printed, nothing submitted.", dry_run_count)
    else:
        logger.info("Done — %d ok, %d failed.", success, failed)

    if failed:
        sys.exit(1)


# ── CLI ───────────────────────────────────────────────────────────────────────


def _build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Sync Garmin Connect daily data into Baseline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    p.add_argument(
        "--user-id",
        default=_DEFAULT_USER_ID,
        required=_DEFAULT_USER_ID is None,
        metavar="UUID",
        help=(
            "Baseline user UUID to associate measurements with "
            "(falls back to BASELINE_USER_ID env var)"
        ),
    )

    date_group = p.add_mutually_exclusive_group()
    date_group.add_argument(
        "--date",
        metavar="YYYY-MM-DD",
        help="Sync a single specific date",
    )
    date_group.add_argument(
        "--days",
        type=int,
        default=7,
        metavar="N",
        help="Sync the last N days (default: 7)",
    )
    p.add_argument(
        "--start-date",
        metavar="YYYY-MM-DD",
        help="Start of backfill range (use with --end-date)",
    )
    p.add_argument(
        "--end-date",
        metavar="YYYY-MM-DD",
        help="End of backfill range (use with --start-date)",
    )
    p.add_argument(
        "--api-url",
        default=_DEFAULT_API_URL,
        metavar="URL",
        help=f"Baseline API base URL (default: {_DEFAULT_API_URL})",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch and decode but print the payload instead of submitting",
    )
    g = p.add_argument_group("config overrides (take precedence over garmin_config.json)")
    g.add_argument("--email", metavar="EMAIL", help="Garmin Connect account email")
    g.add_argument("--password", metavar="PWD", help="Garmin Connect account password")
    g.add_argument(
        "--token-store",
        metavar="PATH",
        help="Directory for persisted OAuth2 tokens (default: from config file)",
    )
    g.add_argument(
        "--timezone",
        metavar="TZ",
        help="User timezone for measured_at derivation (e.g. America/Sao_Paulo)",
    )
    p.add_argument(
        "--ingestion-run-id",
        metavar="UUID",
        default=None,
        help="Link ingested payloads to this IngestionRun UUID (set by garmin_scheduler)",
    )
    p.add_argument("--debug", action="store_true", help="Enable debug logging")
    return p


if __name__ == "__main__":
    _args = _build_parser().parse_args()
    logging.basicConfig(
        level=logging.DEBUG if _args.debug else logging.INFO,
        format="%(levelname)s %(message)s",
    )
    run(_args)
