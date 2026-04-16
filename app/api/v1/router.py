from fastapi import APIRouter

from app.api.v1.daily_checkpoints import router as checkpoints_router
from app.api.v1.insights import router as insights_router
from app.api.v1.integrations import router as integrations_router
from app.api.v1.measurements import router as measurements_router
from app.api.v1.medications import router as medications_router
from app.api.v1.raw_payloads import router as raw_payloads_router
from app.api.v1.symptoms import router as symptoms_router
from app.api.v1.workouts import router as workouts_router

api_router = APIRouter(prefix="/api/v1")

api_router.include_router(measurements_router)
api_router.include_router(raw_payloads_router)
api_router.include_router(workouts_router)
api_router.include_router(medications_router)
api_router.include_router(symptoms_router)
api_router.include_router(checkpoints_router)
api_router.include_router(insights_router)
api_router.include_router(integrations_router)
