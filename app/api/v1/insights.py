"""Insight Layer API — read-only endpoints over analytical views.

Stable:       medication-adherence, physiological-deviations, symptom-burden
Experimental: illness-signal, recovery-status (V1 heuristics)
"""
import uuid
from datetime import date
from decimal import Decimal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db
from app.schemas.insights import (
    IllnessSignalResponse,
    InsightSummary,
    MedicationAdherenceResponse,
    PhysiologicalDeviationsResponse,
    RecoveryStatusResponse,
    SymptomBurdenResponse,
)
from app.services.insights import InsightService

router = APIRouter(prefix="/insights", tags=["insights"])


@router.get("/medication-adherence", response_model=MedicationAdherenceResponse)
async def medication_adherence(
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    svc = InsightService(db)
    return await svc.medication_adherence(user_id)


@router.get(
    "/physiological-deviations",
    response_model=PhysiologicalDeviationsResponse,
)
async def physiological_deviations(
    user_id: uuid.UUID,
    start: date | None = None,
    end: date | None = None,
    threshold: Decimal = Query(default=Decimal("2.0"), ge=Decimal("0.5"), le=Decimal("5.0")),
    db: AsyncSession = Depends(get_db),
):
    svc = InsightService(db)
    return await svc.physiological_deviations(user_id, start, end, threshold)


@router.get("/symptom-burden", response_model=SymptomBurdenResponse)
async def symptom_burden(
    user_id: uuid.UUID,
    start: date | None = None,
    end: date | None = None,
    db: AsyncSession = Depends(get_db),
):
    svc = InsightService(db)
    return await svc.symptom_burden(user_id, start, end)


@router.get("/illness-signal", response_model=IllnessSignalResponse)
async def illness_signal(
    user_id: uuid.UUID,
    start: date | None = None,
    end: date | None = None,
    db: AsyncSession = Depends(get_db),
):
    svc = InsightService(db)
    return await svc.illness_signal(user_id, start, end)


@router.get("/recovery-status", response_model=RecoveryStatusResponse)
async def recovery_status(
    user_id: uuid.UUID,
    start: date | None = None,
    end: date | None = None,
    db: AsyncSession = Depends(get_db),
):
    svc = InsightService(db)
    return await svc.recovery_status(user_id, start, end)


@router.get("/summary", response_model=InsightSummary)
async def insight_summary(
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
):
    svc = InsightService(db)
    return await svc.summary(user_id)
