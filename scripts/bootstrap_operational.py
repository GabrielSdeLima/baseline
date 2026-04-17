"""Operational bootstrap — idempotent setup for per-user integrations and agents.

Creates user_integrations for Garmin Connect and HC900 BLE, registers the local
agent instance, and optionally migrates HC900 device history.

Usage:
    python scripts/bootstrap_operational.py --user-id <UUID>
    python scripts/bootstrap_operational.py --user-id <UUID> --migrate-hc900-device
    python scripts/bootstrap_operational.py --user-id <UUID> --dry-run

Prerequisites:
    - PostgreSQL running and alembic upgrade head applied
    - BASELINE_USER_ID set in .env (or pass --user-id explicitly)
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import platform
import socket
import sys
import uuid
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

# Add project root to path so app.* imports resolve when run as a script
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.core.config import settings
from app.services.bootstrap import BootstrapService

logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

_CONFIG_DIR = Path.home() / ".config" / "baseline"
_INSTALL_ID_FILE = _CONFIG_DIR / "install_id"
_AGENT_CONFIG_FILE = _CONFIG_DIR / "agent_config.json"


# ---------------------------------------------------------------------------
# Agent config helpers
# ---------------------------------------------------------------------------


def load_or_create_install_id() -> str:
    _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if _INSTALL_ID_FILE.exists():
        return _INSTALL_ID_FILE.read_text().strip()
    new_id = str(uuid.uuid4())
    _INSTALL_ID_FILE.write_text(new_id)
    return new_id


def load_agent_config() -> dict:
    if _AGENT_CONFIG_FILE.exists():
        return json.loads(_AGENT_CONFIG_FILE.read_text())
    return {}


def save_agent_config(config: dict) -> None:
    _CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    _AGENT_CONFIG_FILE.write_text(json.dumps(config, indent=2))


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Bootstrap operational tables: integrations, agent, devices."
    )
    parser.add_argument(
        "--user-id",
        default=settings.baseline_user_id,
        help="Target user UUID (default: BASELINE_USER_ID from .env)",
    )
    parser.add_argument(
        "--migrate-hc900-device",
        action="store_true",
        help="Migrate HC900 MAC from raw_payloads history into user_devices",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without committing to the database",
    )
    return parser


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------


async def run(args: argparse.Namespace) -> None:
    if not args.user_id:
        print(
            "ERROR: --user-id is required (or set BASELINE_USER_ID in .env)",
            file=sys.stderr,
        )
        sys.exit(1)

    try:
        user_id = uuid.UUID(args.user_id)
    except ValueError:
        print(f"ERROR: invalid UUID: {args.user_id}", file=sys.stderr)
        sys.exit(1)

    dry = args.dry_run
    prefix = "[DRY RUN] " if dry else ""

    engine = create_async_engine(settings.database_url, echo=False)
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

    async with factory() as session:
        svc = BootstrapService(session)

        # -- 1. user_integrations -----------------------------------------
        print(f"{prefix}→ Ensuring user_integrations...")
        integrations = await svc.ensure_user_integrations(user_id)
        for slug, integ in integrations.items():
            print(f"  {prefix}✓ {slug}: id={integ.id}")

        # -- 2. agent_instance --------------------------------------------
        install_id = load_or_create_install_id()
        agent_config = load_agent_config()

        display_name = socket.gethostname()
        plat = platform.platform()

        print(f"{prefix}→ Registering agent (install_id={install_id})...")
        agent = await svc.register_agent(
            user_id,
            install_id,
            display_name=display_name,
            platform=plat,
        )
        print(f"  {prefix}✓ agent_instance: id={agent.id} ({display_name})")
        agent_config["install_id"] = install_id
        agent_config["agent_instance_id"] = str(agent.id)

        # -- 3. HC900 device (optional) -----------------------------------
        if args.migrate_hc900_device:
            hc900_integ = integrations.get("hc900_ble")
            if hc900_integ is None:
                print("  WARN: hc900_ble integration not available — skipping device migration")
            else:
                print(f"{prefix}→ Migrating HC900 device...")
                device = await svc.migrate_hc900_device(user_id, hc900_integ.id)
                if device:
                    print(f"  {prefix}✓ user_device: {device.identifier} id={device.id}")
                    agent_config["hc900_device_id"] = str(device.id)
                else:
                    print("  No HC900 history found — device not created")
                    agent_config.pop("hc900_device_id", None)

        # -- commit or rollback -------------------------------------------
        if not dry:
            await session.commit()
            if not args.migrate_hc900_device or True:
                save_agent_config(agent_config)
            print("Bootstrap complete.")
        else:
            await session.rollback()
            print("[DRY RUN] No changes committed. agent_config.json not written.")

    await engine.dispose()


def main() -> None:
    import asyncio
    import sys

    # Ensure UTF-8 output on Windows consoles that default to cp1252
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    parser = build_parser()
    args = parser.parse_args()
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
