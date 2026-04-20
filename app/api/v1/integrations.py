"""Integration triggers — endpoints that kick off device sync/scan pipelines."""
import asyncio
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.dependencies import get_db
from app.models.agent_instance import AgentInstance
from app.models.data_source import DataSource
from app.models.ingestion_run import IngestionRun
from app.models.user_device import UserDevice
from app.schemas.garmin_sync import GarminSyncRequest, GarminSyncResponse
from app.schemas.scale import LatestScaleReading
from app.services.garmin_sync import perform_on_demand_sync
from app.services.scale import ScaleService

router = APIRouter(prefix="/integrations", tags=["integrations"])

_SCRIPTS_DIR = Path(__file__).parents[3] / "scripts"

_LOG_NOISE_PREFIXES = ("INFO ", "WARNING ", "DEBUG ")


def _extract_error(stderr: str, stdout: str, returncode: int | None) -> str:
    """Pull the actual error out of a subprocess' log stream.

    import_scale.py uses `logging.basicConfig(format="%(levelname)s %(message)s")`,
    so stderr is a mix of INFO/WARNING/ERROR lines. Return everything from the
    first ERROR line onwards (captures the error plus any trailing traceback);
    fall back to the last non-empty non-noise line, then stdout, then exit code.
    """
    lines = stderr.splitlines()
    for i, line in enumerate(lines):
        if line.startswith("ERROR "):
            return "\n".join(lines[i:]).strip()

    for line in reversed(lines):
        stripped = line.strip()
        if stripped and not stripped.startswith(_LOG_NOISE_PREFIXES):
            return stripped

    return stdout.strip() or f"import_scale.py exited with code {returncode}"


async def _kill_proc(proc: asyncio.subprocess.Process) -> None:
    """Best-effort termination of a still-running subprocess."""
    if proc.returncode is not None:
        return
    try:
        proc.kill()
    except ProcessLookupError:
        return
    try:
        await asyncio.wait_for(proc.wait(), timeout=2.0)
    except TimeoutError:
        pass


@router.post("/scale/scan")
async def scan_scale(
    user_id: uuid.UUID = Query(...),
    height_cm: int | None = Query(None),
    birth_date: str | None = Query(None),
    sex: int | None = Query(None),
    mac: str | None = Query(None),
    x_idempotency_key: str | None = Header(None, alias="X-Idempotency-Key"),
    db: AsyncSession = Depends(get_db),
):
    """Trigger a BLE scan for the HC900 scale, decode, and ingest.

    Creates an IngestionRun before launching import_scale.py and closes it as
    completed/failed afterward.  Accepts X-Idempotency-Key to deduplicate
    double-clicks.  Rejects concurrent scans for the same user with 409.
    """
    script = _SCRIPTS_DIR / "import_scale.py"
    if not script.exists():
        raise HTTPException(status_code=500, detail="import_scale.py not found")

    # Resolve source
    source_id: int | None = await db.scalar(
        select(DataSource.id).where(DataSource.slug == "hc900_ble")
    )
    if source_id is None:
        raise HTTPException(status_code=500, detail="hc900_ble data source not found")

    # Idempotency dedup
    if x_idempotency_key is not None:
        existing = await db.scalar(
            select(IngestionRun).where(
                IngestionRun.idempotency_key == x_idempotency_key
            )
        )
        if existing is not None:
            if existing.status == "running":
                raise HTTPException(
                    status_code=409,
                    detail="Scan already in progress for this idempotency key",
                )
            if existing.status == "completed":
                return {"status": "ok", "message": "Already completed (idempotent)"}
            # status == "failed" → retry: release the key so the new run may claim it
            existing.idempotency_key = None
            await db.flush()

    # Anti-overlap: any running ble_scan for this user/source → 409
    overlap = await db.scalar(
        select(IngestionRun).where(
            IngestionRun.user_id == user_id,
            IngestionRun.source_id == source_id,
            IngestionRun.operation_type == "ble_scan",
            IngestionRun.status == "running",
        )
    )
    if overlap is not None:
        raise HTTPException(status_code=409, detail="A scale scan is already in progress")

    # Device provenance — best-effort lookup by MAC, never auto-created
    user_device_id: uuid.UUID | None = None
    if mac is not None:
        normalized = mac.replace(":", "").lower()
        device = await db.scalar(
            select(UserDevice).where(
                UserDevice.user_id == user_id,
                UserDevice.identifier == normalized,
                UserDevice.identifier_type == "mac",
                UserDevice.is_active.is_(True),
            )
        )
        if device is not None:
            user_device_id = device.id

    # Agent instance provenance — active local agent, if any
    agent_instance_id: uuid.UUID | None = None
    agent = await db.scalar(
        select(AgentInstance).where(
            AgentInstance.user_id == user_id,
            AgentInstance.is_active.is_(True),
        )
    )
    if agent is not None:
        agent_instance_id = agent.id

    # Create run — server_default sets status='running'
    run = IngestionRun(
        user_id=user_id,
        source_id=source_id,
        operation_type="ble_scan",
        trigger_type="ui_button",
        idempotency_key=x_idempotency_key,
        agent_instance_id=agent_instance_id,
    )
    db.add(run)
    await db.flush()
    run_id = run.id

    # Commit so the subprocess can see the run via its own session
    await db.commit()

    cmd = [
        sys.executable, str(script),
        "--user-id", str(user_id),
        "--ingestion-run-id", str(run_id),
    ]
    if height_cm is not None:
        cmd += ["--height-cm", str(height_cm)]
    if birth_date is not None:
        cmd += ["--birth-date", birth_date]
    if sex is not None:
        cmd += ["--sex", str(sex)]
    if mac:
        cmd += ["--mac", mac]
    if user_device_id is not None:
        cmd += ["--user-device-id", str(user_device_id)]
    if agent_instance_id is not None:
        cmd += ["--agent-instance-id", str(agent_instance_id)]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    try:
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=settings.scale_scan_timeout
        )
    except TimeoutError:
        await _kill_proc(proc)
        run.status = "failed"
        run.error_message = f"BLE scan timed out ({settings.scale_scan_timeout}s)"
        run.finished_at = datetime.now(UTC)
        await db.commit()
        raise HTTPException(
            status_code=504,
            detail=(
                f"Scale scan timed out ({settings.scale_scan_timeout}s). "
                "Is the scale active?"
            ),
        )

    output = stdout.decode(errors="replace")
    errors = stderr.decode(errors="replace")

    if proc.returncode == 0:
        run.status = "completed"
        run.finished_at = datetime.now(UTC)
        await db.commit()
        return {"status": "ok", "message": output.strip() or "Import complete"}

    run.status = "failed"
    run.error_message = _extract_error(errors, output, proc.returncode)[:500]
    run.finished_at = datetime.now(UTC)
    await db.commit()
    raise HTTPException(
        status_code=502,
        detail=_extract_error(errors, output, proc.returncode),
    )


@router.get("/scale/discover")
async def discover_scales(timeout: int = Query(15, ge=3, le=60)):
    """Stream HC900 BLE devices as they are discovered.

    Launches scripts/discover_scales.py and relays its NDJSON stdout to the
    client as `application/x-ndjson`. Each line is a JSON object:
        {"mac": "A0:91:5C:92:CF:17", "name": "HC900", "rssi": -52}

    The subprocess is killed if the client disconnects or if the scan exceeds
    ``timeout + 5s`` wall-clock (safety net).
    """
    script = _SCRIPTS_DIR / "discover_scales.py"
    if not script.exists():
        raise HTTPException(status_code=500, detail="discover_scales.py not found")

    proc = await asyncio.create_subprocess_exec(
        sys.executable,
        str(script),
        "--timeout",
        str(timeout),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    async def stream():
        try:
            assert proc.stdout is not None
            while True:
                line = await proc.stdout.readline()
                if not line:
                    break
                yield line
        finally:
            await _kill_proc(proc)

    return StreamingResponse(stream(), media_type="application/x-ndjson")


@router.post("/garmin/sync", response_model=GarminSyncResponse)
async def sync_garmin(body: GarminSyncRequest) -> GarminSyncResponse:
    """Run a UI-triggered Garmin sync (today's window) and report the outcome.

    Shares the scheduler's :class:`asyncio.Lock` for anti-overlap — if a
    background tick or a prior click is still running, responds immediately
    with ``status="already_running"`` and does not create a new run.
    """
    result = await perform_on_demand_sync(str(body.user_id))
    return GarminSyncResponse(
        status=result.status,
        run_id=result.run_id,
        started_at=result.started_at,
        finished_at=result.finished_at,
        error_message=result.error_message,
    )


@router.get("/scale/latest", response_model=LatestScaleReading)
async def latest_scale_reading(
    user_id: uuid.UUID = Query(...),
    db: AsyncSession = Depends(get_db),
):
    """Return the user's latest HC900 weighing as a single coherent unit.

    The response always belongs to ONE ``raw_payload_id`` — callers never
    have to stitch metrics from different weighings.  ``status`` is
    explicit (``full_reading`` / ``weight_only`` / ``never_measured``) so
    the UI can pick its render branch without inspecting the metric set.
    """
    svc = ScaleService(db)
    return await svc.get_latest_reading(user_id)
