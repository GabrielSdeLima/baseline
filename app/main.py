import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

from app.api.v1.router import api_router
from app.core.logging_config import configure_logging
from app.services.garmin_scheduler import run_scheduler

_LOG_FILE = configure_logging()

_logger = logging.getLogger(__name__)
_logger.info("[startup] logging to %s (daily rotation, 14-day retention)", _LOG_FILE)


@asynccontextmanager
async def lifespan(app: FastAPI):
    task = asyncio.create_task(run_scheduler())
    try:
        yield
    finally:
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass
        except Exception:
            _logger.exception("[lifespan] scheduler task raised on shutdown")


app = FastAPI(
    title="Baseline",
    version="0.1.0",
    description="Personal longitudinal health data platform",
    lifespan=lifespan,
)

app.include_router(api_router)


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


_UI_DIR = Path(__file__).parent / "static" / "ui"

if (_UI_DIR / "assets").exists():
    app.mount("/assets", StaticFiles(directory=_UI_DIR / "assets"), name="ui_assets")


def _serve_index() -> FileResponse | PlainTextResponse:
    index = _UI_DIR / "index.html"
    if index.exists():
        return FileResponse(str(index))
    return PlainTextResponse(
        "UI not built yet. Run: cd ui && npm run build", status_code=503
    )


@app.get("/", include_in_schema=False, response_model=None)
async def serve_ui_root() -> FileResponse | PlainTextResponse:
    return _serve_index()


@app.get("/{full_path:path}", include_in_schema=False, response_model=None)
async def serve_ui(full_path: str) -> FileResponse | PlainTextResponse:
    if full_path.startswith("api/") or full_path in (
        "health", "docs", "redoc", "openapi.json",
    ):
        raise HTTPException(status_code=404, detail="Not found")
    return _serve_index()
