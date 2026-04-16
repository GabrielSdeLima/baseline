"""Insight Layer response schemas.

Tier-2 schemas that wrap Tier-1 view features into consumable API responses.
Experimental heuristics (illness_signal, recovery_status) include a ``method``
field that names the heuristic version so consumers know the classification
is not clinical truth.
"""
import uuid
from datetime import date
from decimal import Decimal

from app.schemas.common import BaseSchema

# ── Stable: Medication Adherence ──────────────────────────────────────────


class MedicationAdherenceItem(BaseSchema):
    medication_name: str
    frequency: str
    taken: int
    skipped: int
    delayed: int
    total: int
    adherence_pct: Decimal


class MedicationAdherenceResponse(BaseSchema):
    user_id: uuid.UUID
    items: list[MedicationAdherenceItem]
    overall_adherence_pct: Decimal


# ── Stable: Physiological Deviations ──────────────────────────────────────


class MetricDeviation(BaseSchema):
    day: date
    metric_slug: str
    metric_name: str
    value: Decimal
    baseline_avg: Decimal
    baseline_stddev: Decimal
    z_score: Decimal
    delta_abs: Decimal
    delta_pct: Decimal | None


class PhysiologicalDeviationsResponse(BaseSchema):
    user_id: uuid.UUID
    baseline_window_days: int
    deviation_threshold: Decimal
    deviations: list[MetricDeviation]
    metrics_flagged: int


# ── Stable: Symptom Burden ────────────────────────────────────────────────


class SymptomBurdenDay(BaseSchema):
    day: date
    symptom_count: int
    max_intensity: int | None
    weighted_burden: Decimal
    dominant_symptom: str | None


class SymptomBurdenResponse(BaseSchema):
    user_id: uuid.UUID
    days: list[SymptomBurdenDay]
    total_symptom_days: int
    peak_burden_date: date | None


# ── Experimental: Illness Signal (V1 heuristic) ──────────────────────────


class IllnessSignalDay(BaseSchema):
    day: date
    temp_z: Decimal | None
    hrv_z: Decimal | None
    rhr_z: Decimal | None
    symptom_burden: Decimal
    energy: int | None
    signal_level: str  # "high" / "moderate" / "low"


class IllnessSignalResponse(BaseSchema):
    user_id: uuid.UUID
    method: str  # e.g. "baseline_deviation_v1"
    days: list[IllnessSignalDay]
    peak_signal: str
    peak_signal_date: date | None


# ── Experimental: Recovery Status (V1 heuristic) ─────────────────────────


class RecoveryDay(BaseSchema):
    day: date
    training_load: Decimal | None
    hrv_value: Decimal | None
    hrv_z: Decimal | None
    hrv_7d_avg: Decimal | None
    status: str  # "recovered"/"recovering"/"strained"/"overreaching"


class RecoveryStatusResponse(BaseSchema):
    user_id: uuid.UUID
    method: str  # e.g. "load_hrv_heuristic_v1"
    days: list[RecoveryDay]
    current_status: str


# ── Summary ───────────────────────────────────────────────────────────────


class InsightSummary(BaseSchema):
    user_id: uuid.UUID
    as_of: date
    overall_adherence_pct: Decimal
    active_deviations: int
    current_symptom_burden: Decimal
    illness_signal: str    # experimental
    recovery_status: str   # experimental
