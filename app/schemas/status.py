from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from app.schemas.common import BaseSchema


class SourceStatus(BaseSchema):
    source_slug: str
    integration_configured: bool
    device_paired: bool | None  # None = concept not applicable (e.g. Garmin cloud)
    last_sync_at: datetime | None
    last_advanced_at: datetime | None
    last_run_status: str | None
    last_run_at: datetime | None


AgentStatus = Literal["active", "stale", "unknown"]


class AgentSummary(BaseSchema):
    agent_type: str
    display_name: str | None
    status: AgentStatus
    last_seen_at: datetime | None


class SystemStatusResponse(BaseSchema):
    user_id: uuid.UUID
    sources: list[SourceStatus]
    agents: list[AgentSummary]
    as_of: datetime
