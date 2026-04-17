"""Unified logging setup for the Baseline API.

Writes every ``app.*`` log record to both the console and a rotating file at
``logs/baseline.log`` (relative to the repo root).  The file rotates at local
midnight and keeps 14 days of history, so a week of PC sleep/wake cycles and
Garmin syncs are always recoverable for debugging.

Security posture
----------------
* The ``logs/`` directory is gitignored — rotated files never leave the host.
* File inherits the user's NTFS ACLs (Windows) or umask (POSIX); on a
  personal workstation that means user-only access.
* Callers are responsible for not emitting secrets.  The scheduler and
  ingestion paths log UUIDs, date ranges, exit codes and trimmed subprocess
  stderr — no tokens, no passwords, no request bodies.
"""
from __future__ import annotations

import logging
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path

_LOG_DIR = Path(__file__).resolve().parents[2] / "logs"
_LOG_FILE = _LOG_DIR / "baseline.log"
_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
_DATEFMT = "%Y-%m-%d %H:%M:%S"
_BACKUP_DAYS = 14
_OWN_TAG = "_baseline_owned"


def _is_owned(handler: logging.Handler) -> bool:
    return getattr(handler, _OWN_TAG, False)


def configure_logging(level: int = logging.INFO) -> Path:
    """Install console + rotating-file handlers on the root logger.

    Idempotent: re-running cleans up handlers this module previously
    installed (so ``uvicorn --reload`` does not duplicate output) and then
    re-attaches fresh ones.

    Returns the absolute log-file path so callers can surface it at startup.
    """
    _LOG_DIR.mkdir(parents=True, exist_ok=True)

    root = logging.getLogger()
    for h in list(root.handlers):
        if _is_owned(h):
            root.removeHandler(h)
            try:
                h.close()
            except Exception:
                pass

    formatter = logging.Formatter(_FORMAT, _DATEFMT)

    console = logging.StreamHandler()
    console.setFormatter(formatter)
    setattr(console, _OWN_TAG, True)
    root.addHandler(console)

    file_h = TimedRotatingFileHandler(
        _LOG_FILE,
        when="midnight",
        backupCount=_BACKUP_DAYS,
        encoding="utf-8",
        delay=True,
    )
    file_h.setFormatter(formatter)
    setattr(file_h, _OWN_TAG, True)
    root.addHandler(file_h)

    root.setLevel(level)
    return _LOG_FILE
