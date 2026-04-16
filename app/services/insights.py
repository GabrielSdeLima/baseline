"""Insight service — Tier-2 classification over Tier-1 view features.

Stable insights (medication_adherence, physiological_deviations, symptom_burden)
are thin wrappers around views.

Experimental heuristics (illness_signal, recovery_status) apply V1 classification
rules in Python using z-scores from v_metric_baseline.

Baseline-first principle
------------------------
The primary signal is deviation from the user's individual 14-day rolling
baseline (z-score).  A z-score of NULL means fewer than 3 data points exist
in the baseline window — in that case the signal is ``"insufficient_data"``,
not a falsely optimistic "low" or "recovered".

"insufficient_data" means: baseline window too short to produce a reliable
deviation signal.  It is NOT a health signal — it is an absence of evidence.

This is pattern detection for personal health tracking, NOT clinical diagnosis.
"""
import uuid
from collections import defaultdict
from datetime import date
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.repositories.insights import InsightRepository
from app.schemas.insights import (
    IllnessSignalDay,
    IllnessSignalResponse,
    InsightSummary,
    MedicationAdherenceItem,
    MedicationAdherenceResponse,
    MetricDeviation,
    PhysiologicalDeviationsResponse,
    RecoveryDay,
    RecoveryStatusResponse,
    SymptomBurdenDay,
    SymptomBurdenResponse,
)

BASELINE_WINDOW_DAYS = 14
DEFAULT_DEVIATION_THRESHOLD = Decimal("2.0")

# Metrics relevant to illness detection
_ILLNESS_METRICS = ["body_temperature", "hrv_rmssd", "resting_hr"]

# Metrics relevant to recovery tracking
_RECOVERY_METRICS = ["hrv_rmssd"]

# Signal ranking for peak detection (insufficient_data < low < moderate < high)
_ILLNESS_SIGNAL_ORDER = {"high": 3, "moderate": 2, "low": 1, "insufficient_data": 0}


class InsightService:
    def __init__(self, session: AsyncSession):
        self.session = session
        self.repo = InsightRepository(session)

    # ── Stable: Medication Adherence ──────────────────────────────────

    async def medication_adherence(
        self, user_id: uuid.UUID
    ) -> MedicationAdherenceResponse:
        rows = await self.repo.get_medication_adherence(user_id)
        items = [
            MedicationAdherenceItem(
                medication_name=r.medication_name,
                frequency=r.frequency,
                taken=r.taken,
                skipped=r.skipped,
                delayed=r.delayed,
                total=r.total,
                adherence_pct=r.adherence_pct,
            )
            for r in rows
        ]
        total_taken = sum(i.taken for i in items)
        total_all = sum(i.total for i in items)
        overall = (
            Decimal("0") if total_all == 0
            else round(Decimal(100) * total_taken / total_all, 1)
        )
        return MedicationAdherenceResponse(
            user_id=user_id, items=items, overall_adherence_pct=overall
        )

    # ── Stable: Physiological Deviations ──────────────────────────────

    async def physiological_deviations(
        self,
        user_id: uuid.UUID,
        start: date | None = None,
        end: date | None = None,
        threshold: Decimal = DEFAULT_DEVIATION_THRESHOLD,
    ) -> PhysiologicalDeviationsResponse:
        rows = await self.repo.get_metric_baselines(user_id, start, end)
        deviations = []
        flagged_metrics: set[str] = set()
        for r in rows:
            if r.z_score is not None and abs(r.z_score) >= threshold:
                deviations.append(MetricDeviation(
                    day=r.day,
                    metric_slug=r.metric_slug,
                    metric_name=r.metric_name,
                    value=r.value,
                    baseline_avg=r.baseline_avg,
                    baseline_stddev=r.baseline_stddev,
                    z_score=r.z_score,
                    delta_abs=r.delta_abs,
                    delta_pct=r.delta_pct,
                ))
                flagged_metrics.add(r.metric_slug)
        return PhysiologicalDeviationsResponse(
            user_id=user_id,
            baseline_window_days=BASELINE_WINDOW_DAYS,
            deviation_threshold=threshold,
            deviations=deviations,
            metrics_flagged=len(flagged_metrics),
        )

    # ── Stable: Symptom Burden ────────────────────────────────────────

    async def symptom_burden(
        self,
        user_id: uuid.UUID,
        start: date | None = None,
        end: date | None = None,
    ) -> SymptomBurdenResponse:
        rows = await self.repo.get_symptom_burden(user_id, start, end)
        days = [
            SymptomBurdenDay(
                day=r.day,
                symptom_count=r.symptom_count,
                max_intensity=r.max_intensity,
                weighted_burden=r.weighted_burden,
                dominant_symptom=r.dominant_symptom,
            )
            for r in rows
        ]
        peak = max(days, key=lambda d: d.weighted_burden, default=None)
        return SymptomBurdenResponse(
            user_id=user_id,
            days=days,
            total_symptom_days=len(days),
            peak_burden_date=peak.day if peak else None,
        )

    # ── Experimental: Illness Signal (baseline_deviation_v1) ──────────
    #
    # Heuristic: combines per-metric z-scores from individual baseline.
    # Primary: personal deviation (z-scores from 14-day rolling window).
    #
    # INSUFFICIENT_DATA: all three z-scores are None (< 3 baseline points).
    #                    This is NOT a health signal — it means no evidence.
    # HIGH:     temp z > 1.5 AND hrv z < -1.5 AND symptom_burden > 0
    # MODERATE: any 2 of (temp z > 1.0, hrv z < -1.0, rhr z > 1.0,
    #           symptom_burden > 0)
    # LOW:      z-scores available but no convergence of signals

    async def illness_signal(
        self,
        user_id: uuid.UUID,
        start: date | None = None,
        end: date | None = None,
    ) -> IllnessSignalResponse:
        baselines = await self.repo.get_metric_baselines(
            user_id, start, end, metric_slugs=_ILLNESS_METRICS
        )
        burden_rows = await self.repo.get_symptom_burden(user_id, start, end)
        energy_rows = await self.repo.get_morning_energy(user_id, start, end)

        # Index features by day
        z_by_day: dict[date, dict[str, Decimal | None]] = defaultdict(dict)
        for r in baselines:
            z_by_day[r.day][r.metric_slug] = r.z_score

        burden_by_day = {r.day: r.weighted_burden for r in burden_rows}
        energy_by_day = {r.day: r.energy for r in energy_rows}

        all_days = sorted(
            set(z_by_day.keys()) | set(burden_by_day.keys())
        )

        days: list[IllnessSignalDay] = []
        for day in all_days:
            zscores = z_by_day.get(day, {})
            temp_z = zscores.get("body_temperature")
            hrv_z = zscores.get("hrv_rmssd")
            rhr_z = zscores.get("resting_hr")
            burden = burden_by_day.get(day, Decimal("0"))
            energy = energy_by_day.get(day)

            signal = _classify_illness(temp_z, hrv_z, rhr_z, burden)
            days.append(IllnessSignalDay(
                day=day,
                temp_z=temp_z,
                hrv_z=hrv_z,
                rhr_z=rhr_z,
                symptom_burden=burden,
                energy=energy,
                signal_level=signal,
            ))

        peak_day = max(
            days,
            key=lambda d: _ILLNESS_SIGNAL_ORDER[d.signal_level],
            default=None,
        )
        peak_signal = peak_day.signal_level if peak_day else "insufficient_data"
        peak_date = (
            peak_day.day
            if peak_day and peak_day.signal_level not in ("low", "insufficient_data")
            else None
        )

        return IllnessSignalResponse(
            user_id=user_id,
            method="baseline_deviation_v1",
            days=days,
            peak_signal=peak_signal,
            peak_signal_date=peak_date,
        )

    # ── Experimental: Recovery Status (load_hrv_heuristic_v1) ─────────
    #
    # Heuristic: classifies recovery based on training load and HRV z-score
    # relative to individual baseline.
    #
    # INSUFFICIENT_DATA: hrv_z is None (< 3 baseline points).
    #                    Cannot assess recovery without a personal HRV baseline.
    # overreaching: 3+ consecutive strained/overreaching days
    # strained:     hrv z < -1.0 AND training load present
    # recovering:   hrv z < 0 AND no load
    # recovered:    hrv z >= 0

    async def recovery_status(
        self,
        user_id: uuid.UUID,
        start: date | None = None,
        end: date | None = None,
    ) -> RecoveryStatusResponse:
        baselines = await self.repo.get_metric_baselines(
            user_id, start, end, metric_slugs=_RECOVERY_METRICS
        )
        load_rows = await self.repo.get_training_load(user_id, start, end)

        hrv_by_day = {
            r.day: (r.value, r.z_score)
            for r in baselines
            if r.metric_slug == "hrv_rmssd"
        }
        load_by_day = {r.day: r.training_load for r in load_rows}

        all_days = sorted(set(hrv_by_day.keys()) | set(load_by_day.keys()))

        # Compute 7-day rolling average of HRV values (only for days with baseline)
        hrv_values = [(d, hrv_by_day[d][0]) for d in all_days if d in hrv_by_day]
        hrv_7d: dict[date, Decimal] = {}
        for i, (day, _val) in enumerate(hrv_values):
            window = [v for _, v in hrv_values[max(0, i - 6):i + 1]]
            hrv_7d[day] = round(sum(window) / len(window), 1)

        days: list[RecoveryDay] = []
        consecutive_strained = 0
        for day in all_days:
            hrv_val, hrv_z = hrv_by_day.get(day, (None, None))
            load = load_by_day.get(day)

            status = _classify_recovery(hrv_z, load, consecutive_strained)
            if status in ("strained", "overreaching"):
                consecutive_strained += 1
            else:
                consecutive_strained = 0

            days.append(RecoveryDay(
                day=day,
                training_load=load,
                hrv_value=hrv_val,
                hrv_z=hrv_z,
                hrv_7d_avg=hrv_7d.get(day),
                status=status,
            ))

        current = days[-1].status if days else "insufficient_data"
        return RecoveryStatusResponse(
            user_id=user_id,
            method="load_hrv_heuristic_v1",
            days=days,
            current_status=current,
        )

    # ── Summary ───────────────────────────────────────────────────────

    async def summary(self, user_id: uuid.UUID) -> InsightSummary:
        today = date.today()

        adherence = await self.medication_adherence(user_id)
        deviations = await self.physiological_deviations(
            user_id, start=today, end=today
        )
        burden = await self.symptom_burden(user_id, start=today, end=today)
        illness = await self.illness_signal(user_id, start=today, end=today)
        recovery = await self.recovery_status(user_id)

        current_burden = (
            burden.days[0].weighted_burden if burden.days else Decimal("0")
        )
        return InsightSummary(
            user_id=user_id,
            as_of=today,
            overall_adherence_pct=adherence.overall_adherence_pct,
            active_deviations=deviations.metrics_flagged,
            current_symptom_burden=current_burden,
            illness_signal=illness.peak_signal,
            recovery_status=recovery.current_status,
        )


# ── Classification functions (pure, testable) ────────────────────────────


def _classify_illness(
    temp_z: Decimal | None,
    hrv_z: Decimal | None,
    rhr_z: Decimal | None,
    symptom_burden: Decimal,
) -> str:
    """Classify illness signal from individual baseline deviations.

    Returns one of: "insufficient_data", "low", "moderate", "high".

    "insufficient_data" is returned when all three z-scores are None, meaning
    the baseline window has fewer than 3 data points.  This explicitly signals
    absence of evidence — it must NOT be treated as "all clear".

    For partial baselines (some z-scores available, some None), available
    z-scores are used and missing ones are treated as neutral (0).
    """
    # All z-scores None = no baseline at all; cannot classify
    if temp_z is None and hrv_z is None and rhr_z is None:
        return "insufficient_data"

    # Partial baseline: treat missing metrics as neutral
    t = float(temp_z) if temp_z is not None else 0.0
    h = float(hrv_z) if hrv_z is not None else 0.0
    r = float(rhr_z) if rhr_z is not None else 0.0
    burden = float(symptom_burden)

    # HIGH: strong deviation on temp AND HRV, with symptoms present
    if t > 1.5 and h < -1.5 and burden > 0:
        return "high"

    # MODERATE: at least 2 converging signals
    signals = sum([
        t > 1.0,
        h < -1.0,
        r > 1.0,
        burden > 0,
    ])
    if signals >= 2:
        return "moderate"

    return "low"


def _classify_recovery(
    hrv_z: Decimal | None,
    training_load: Decimal | None,
    consecutive_strained_days: int,
) -> str:
    """Classify recovery status from HRV baseline deviation and training load.

    Returns one of: "insufficient_data", "recovering", "recovered",
    "strained", "overreaching".

    "insufficient_data" is returned when hrv_z is None, meaning the HRV
    baseline window has fewer than 3 data points.  Recovery assessment
    requires a personal HRV baseline — without it, no classification is made.
    This must NOT be treated as "recovered".
    """
    # No HRV baseline = cannot assess recovery
    if hrv_z is None:
        return "insufficient_data"

    z = float(hrv_z)
    has_load = training_load is not None and float(training_load) > 0

    # Overreaching: 3+ consecutive strained days (counter reaches 2 after day 2)
    if consecutive_strained_days >= 2 and z < -1.0:
        return "overreaching"

    # Strained: HRV significantly below baseline after training
    if z < -1.0 and has_load:
        return "strained"

    # Recovering: HRV below baseline but no heavy training today
    if z < 0 and not has_load:
        return "recovering"

    # Recovered: HRV at or above baseline
    return "recovered"
