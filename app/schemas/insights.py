"""Insight Layer response schemas.

Tier-2 schemas that wrap Tier-1 view features into consumable API responses.
Experimental heuristics (illness_signal, recovery_status) include a ``method``
field that names the heuristic version so consumers know the classification
is not clinical truth.

Onda 2 — B1: semantic-state types.  ``availability_status`` describes whether
the data needed to compute an insight is present; ``signal_status`` describes
the classification the insight produced.  The two are orthogonal — a response
can be ``availability_status="partial"`` AND ``signal_status="moderate"``
simultaneously, carrying both pieces of information without mixing them.
"""
import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import Field

from app.schemas.common import BaseSchema

# ── Semantic state types ─────────────────────────────────────────────────
#
# ``availability_status`` describes DATA availability.  It is orthogonal to
# any insight classification.
#
#   ok                  — enough data is present to classify.
#   no_data             — the user has no measurements of the required kind.
#   no_data_today       — historical data exists, but the target date (today
#                         for summary) has no row.  Distinct from stale_data:
#                         the source may have synced recently without yet
#                         producing a value for today.
#   insufficient_data   — data exists but baseline window is too short
#                         (< 3 points) to compute a deviation signal.
#   stale_data          — baseline exists but the latest measurement is
#                         older than the per-source freshness budget.
#   partial             — some required metrics have data, others do not.
#                         A signal may still be produced but is caveated.
#   not_applicable      — the feature is not in use (e.g. medication
#                         adherence with no active regimens).
AvailabilityStatus = Literal[
    "ok",
    "no_data",
    "no_data_today",
    "insufficient_data",
    "stale_data",
    "partial",
    "not_applicable",
]

# Signal vocabularies per-domain.  Never mixed with availability.
IllnessSignal = Literal["low", "moderate", "high"]
RecoverySignal = Literal["recovered", "recovering", "strained", "overreaching"]

# Per-item medication state.
MedicationItemStatus = Literal["ok", "pending_first_log"]


class DataAvailability(BaseSchema):
    """Per-response availability envelope.

    Distinguishes ``latest_measured_at`` (when the data point represents) from
    ``latest_synced_at`` (when the source last completed a sync).  A source
    that synced today but found no new value for today yields
    ``has_data_for_target_date=False`` even though ``latest_synced_at`` is
    current.
    """
    availability_status: AvailabilityStatus = "ok"
    target_date: date | None = None
    has_data_for_target_date: bool | None = None
    latest_measured_at: datetime | None = None
    latest_synced_at: datetime | None = None
    missing_metrics: list[str] = Field(default_factory=list)
    metrics_with_baseline: list[str] = Field(default_factory=list)
    metrics_without_baseline: list[str] = Field(default_factory=list)
    stale_metrics: list[str] = Field(default_factory=list)


# ── Stable: Medication Adherence ──────────────────────────────────────────


class MedicationAdherenceItem(BaseSchema):
    medication_name: str
    frequency: str
    taken: int
    skipped: int
    delayed: int
    total: int
    # B3 — None when regimen has no logs yet (item_status = pending_first_log).
    adherence_pct: Decimal | None
    # B1 — distinguishes "no logs yet" from legitimate 0% adherence.
    item_status: MedicationItemStatus = "ok"


class MedicationAdherenceResponse(BaseSchema):
    user_id: uuid.UUID
    items: list[MedicationAdherenceItem]
    # B3 — None when not_applicable (no active regimens) or all pending.
    overall_adherence_pct: Decimal | None
    # B1 — ``not_applicable`` when no active regimens; ``ok`` otherwise.
    availability_status: AvailabilityStatus = "ok"
    data_availability: DataAvailability | None = None


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
    # B1 — prevents UI from rendering ``metrics_flagged=0`` as "all clear"
    # when the real reason is no_data / no_data_today / insufficient_data.
    availability_status: AvailabilityStatus = "ok"
    data_availability: DataAvailability | None = None


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
    # B1 — distinguishes "user never engaged with symptom tracking" from
    # "user has tracked before and logged nothing today".
    availability_status: AvailabilityStatus = "ok"
    tracking_ever_used: bool = True
    data_availability: DataAvailability | None = None


# ── Experimental: Illness Signal (V1 heuristic) ──────────────────────────


class IllnessSignalDay(BaseSchema):
    day: date
    temp_z: Decimal | None
    hrv_z: Decimal | None
    rhr_z: Decimal | None
    symptom_burden: Decimal
    energy: int | None
    signal_level: str  # "high" / "moderate" / "low" / "insufficient_data"


class IllnessSignalResponse(BaseSchema):
    user_id: uuid.UUID
    method: str  # e.g. "baseline_deviation_v1"
    days: list[IllnessSignalDay]
    peak_signal: str
    peak_signal_date: date | None
    # B1 — orthogonal availability vs. signal.  ``peak_signal`` is kept for
    # backward compatibility and may still contain "insufficient_data".  New
    # fields split the concerns cleanly.
    availability_status: AvailabilityStatus = "ok"
    signal_status: IllnessSignal | None = None
    data_availability: DataAvailability | None = None


# ── Experimental: Recovery Status (V1 heuristic) ─────────────────────────


class RecoveryDay(BaseSchema):
    day: date
    training_load: Decimal | None
    hrv_value: Decimal | None
    hrv_z: Decimal | None
    hrv_7d_avg: Decimal | None
    status: str  # recovered / recovering / strained / overreaching / insufficient_data


class RecoveryStatusResponse(BaseSchema):
    user_id: uuid.UUID
    method: str  # e.g. "load_hrv_heuristic_v1"
    days: list[RecoveryDay]
    current_status: str
    # B1 — ``current_status`` is kept (and may be "insufficient_data") but
    # the separated fields describe availability vs. signal for the current
    # position, and ``data_availability.latest_measured_at`` makes staleness
    # observable.
    current_availability_status: AvailabilityStatus = "ok"
    current_signal_status: RecoverySignal | None = None
    data_availability: DataAvailability | None = None


# ── Summary ───────────────────────────────────────────────────────────────


class SummaryBlockAvailability(BaseSchema):
    """Per-block availability for the aggregate summary.

    Each field mirrors the top-level ``availability_status`` of the
    corresponding insight response so the summary consumer can branch per
    block without fetching each endpoint separately.
    """
    deviations: AvailabilityStatus = "ok"
    illness: AvailabilityStatus = "ok"
    recovery: AvailabilityStatus = "ok"
    adherence: AvailabilityStatus = "ok"
    symptoms: AvailabilityStatus = "ok"


class InsightSummary(BaseSchema):
    user_id: uuid.UUID
    as_of: date
    # B3 — None when no active medication regimens (not_applicable).
    overall_adherence_pct: Decimal | None
    active_deviations: int
    current_symptom_burden: Decimal
    illness_signal: str    # experimental
    recovery_status: str   # experimental
    # B1 — aggregate availability.  ``block_availability`` keeps each insight
    # honest: UI can gate "all clear" text on the per-block status instead of
    # inferring from zero counters.  ``data_availability`` carries the
    # aggregated envelope (worst-of across blocks, most recent measurement
    # across all sources).
    block_availability: SummaryBlockAvailability = Field(
        default_factory=SummaryBlockAvailability
    )
    data_availability: DataAvailability | None = None
