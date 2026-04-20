"""Schemas for the on-demand Garmin sync endpoint."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel


class GarminSyncRequest(BaseModel):
    user_id: uuid.UUID


class GarminSyncResponse(BaseModel):
    """Result of a UI-triggered Garmin sync.

    ``status`` drives the UI feedback verbatim:

    * ``completed`` — sync ran and new measurements advanced the latest
      Garmin ``measured_at``.
    * ``no_new_data`` — sync ran cleanly but nothing moved forward
      (Garmin Connect already in sync, or parser produced no new data).
    * ``failed`` — subprocess exited non-zero.  ``error_message`` carries
      the trimmed reason (e.g. ``"sync_garmin.py exited rc=1"``).
    * ``already_running`` — another sync (scheduler tick or prior UI
      click) held the shared lock at entry; no run was created for
      this request, so ``run_id`` / timestamps are null.
    """

    status: Literal["completed", "no_new_data", "failed", "already_running"]
    run_id: uuid.UUID | None = None
    started_at: datetime | None = None
    finished_at: datetime | None = None
    error_message: str | None = None
