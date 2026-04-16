"""Integration triggers — endpoints that kick off device sync/scan pipelines."""
import asyncio
import sys
import uuid
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query

from app.core.config import settings

router = APIRouter(prefix="/integrations", tags=["integrations"])

_SCRIPTS_DIR = Path(__file__).parents[3] / "scripts"


@router.post("/scale/scan")
async def scan_scale(
    user_id: uuid.UUID = Query(...),
    height_cm: int | None = Query(None),
    birth_date: str | None = Query(None),
    sex: int | None = Query(None),
):
    """Trigger a BLE scan for the HC900 scale, decode, and ingest.

    Runs scripts/import_scale.py as a subprocess. Requires:
    - bleak installed (pip install bleak)
    - Dart runtime on PATH
    - Pulso app at C:/src/pulso/pulso-app (or ``BASELINE_PULSO_APP_DIR``)
    - scripts/scale_profile.json configured (or height_cm/birth_date/sex params)

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

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(
            proc.communicate(), timeout=settings.scale_scan_timeout
        )
    except TimeoutError:
        raise HTTPException(
            status_code=504,
            detail=(
                f"Scale scan timed out ({settings.scale_scan_timeout}s). "
                "Is the scale active?"
            ),
        )

    output = stdout.decode(errors="replace").strip()
    errors = stderr.decode(errors="replace").strip()

    if proc.returncode == 0:
        return {"status": "ok", "message": output or "Import complete"}

    raise HTTPException(
        status_code=502,
        detail=errors or output or f"import_scale.py exited with code {proc.returncode}",
    )
