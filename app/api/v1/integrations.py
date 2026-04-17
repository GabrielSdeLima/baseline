"""Integration triggers — endpoints that kick off device sync/scan pipelines."""
import asyncio
import sys
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.dependencies import get_db
from app.schemas.scale import LatestScaleReading
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
):
    """Trigger a BLE scan for the HC900 scale, decode, and ingest.

    Runs scripts/import_scale.py as a subprocess. Requires:
    - bleak installed (pip install bleak)
    - scripts/scale_profile.json configured (or height_cm/birth_date/sex params)

    Decoding is native Python (app.integrations.hc900) — no external runtime.

    Subprocess timeout is controlled by ``SCALE_SCAN_TIMEOUT`` (default 45s).
    """
    script = _SCRIPTS_DIR / "import_scale.py"
    if not script.exists():
        raise HTTPException(status_code=500, detail="import_scale.py not found")

    cmd = [sys.executable, str(script), "--user-id", str(user_id)]
    if height_cm is not None:
        cmd += ["--height-cm", str(height_cm)]
    if birth_date is not None:
        cmd += ["--birth-date", birth_date]
    if sex is not None:
        cmd += ["--sex", str(sex)]
    if mac:
        cmd += ["--mac", mac]

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
        return {"status": "ok", "message": output.strip() or "Import complete"}

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
