"""Insight availability assessment — Onda 2 / B2.

Computes the ``DataAvailability`` envelope that every insight response
carries.  Keeps availability classification (can we say anything about this
insight?) strictly separate from signal classification (what does the data
say?).  The two are orthogonal: a response may be
``availability_status="partial"`` and ``signal_status="moderate"`` at the
same time.

Policies encoded here
---------------------
* ``BASELINE_MIN_POINTS = 3``  — z_score is NULL below this (matches the
  filter applied by ``v_metric_baseline``).
* ``STALE_THRESHOLD_DAYS_BY_METRIC`` — per-metric freshness budget based on
  the typical cadence of the source that emits it (Garmin daily: 2 days;
  body temperature: 3 days; HC900 body composition: 7 days).
* Aggregation across ``required_metrics``:
    - all ``ok``                   → ``ok``
    - all the same non-ok state    → that state
    - mixed states                 → ``partial``

The helper only reads live tables — ``measurements`` and ``source_cursors``.
It never mutates state, never classifies the signal, and never touches the
per-day classifications that the insight services emit.
"""
import uuid
from datetime import date, datetime

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.schemas.insights import AvailabilityStatus, DataAvailability

# Minimum points before v_metric_baseline yields a non-NULL z_score.
BASELINE_MIN_POINTS = 3

# Fallback budget (days) for metrics not explicitly listed below.  Chosen
# conservatively so unknown metrics don't masquerade as fresh.
_DEFAULT_STALE_BUDGET_DAYS = 3

# Per-metric staleness budget (days since latest ``measured_at``).  Mirrors
# real-world cadence: Garmin daily stats land every night, manual body
# temperature is spot-measured, HC900 step-ons are ~weekly.
STALE_THRESHOLD_DAYS_BY_METRIC: dict[str, int] = {
    # Garmin daily metrics — expect a refresh each day; 2d budget tolerates
    # one missed sync window.
    "hrv_rmssd": 2,
    "resting_hr": 2,
    "sleep_duration": 2,
    "sleep_score": 2,
    "steps": 2,
    "active_calories": 2,
    "stress_level": 2,
    "spo2": 2,
    "respiratory_rate": 2,
    "body_battery": 2,
    # Manual vitals (spot measurement on demand).
    "body_temperature": 3,
    # HC900 body composition — typical cadence is weekly.
    "weight": 7,
    "body_fat_pct": 7,
    "muscle_mass_kg": 7,
    "muscle_pct": 7,
    "skeletal_muscle_mass_kg": 7,
    "skeletal_muscle_pct": 7,
    "bone_mass_kg": 7,
    "water_pct": 7,
    "water_mass_kg": 7,
    "bmi": 7,
    "bmr": 7,
    "fat_mass_kg": 7,
    "fat_free_mass_kg": 7,
    "protein_mass_kg": 7,
    "protein_pct": 7,
    "ffmi": 7,
    "fmi": 7,
    "impedance_adc": 7,
    "metabolic_age": 7,
    "visceral_fat": 7,
    "subcutaneous_fat_pct": 7,
}


def stale_threshold_days(metric_slug: str) -> int:
    return STALE_THRESHOLD_DAYS_BY_METRIC.get(
        metric_slug, _DEFAULT_STALE_BUDGET_DAYS
    )


async def assess_availability(
    session: AsyncSession,
    user_id: uuid.UUID,
    required_metrics: list[str],
    target_date: date | None = None,
    sync_source_slugs: list[str] | None = None,
) -> DataAvailability:
    """Build a ``DataAvailability`` envelope for one insight response.

    Queries the curated tables (``measurements``, ``source_cursors``) and
    decides a per-metric state, then aggregates to a single
    ``availability_status``.

    Parameters
    ----------
    required_metrics :
        Metric slugs the insight depends on.
    target_date :
        The day the insight is classified for.  Defaults to today.
    sync_source_slugs :
        When provided, ``latest_synced_at`` only reflects cursors for these
        source slugs (e.g. ``["garmin_connect"]`` for illness/recovery).
        None means the global MAX across all sources.
    """
    target = target_date or date.today()

    per_metric_state: dict[str, AvailabilityStatus] = {}
    per_metric_latest: dict[str, datetime | None] = {}
    for slug in required_metrics:
        state, latest = await _metric_state(session, user_id, slug, target)
        per_metric_state[slug] = state
        per_metric_latest[slug] = latest

    overall = _aggregate_states(per_metric_state.values())

    missing = sorted(
        s for s, st in per_metric_state.items() if st == "no_data"
    )
    without_baseline = sorted(
        s for s, st in per_metric_state.items() if st == "insufficient_data"
    )
    with_baseline = sorted(
        s
        for s, st in per_metric_state.items()
        if st in ("ok", "no_data_today", "stale_data")
    )
    stale = sorted(
        s for s, st in per_metric_state.items() if st == "stale_data"
    )

    latest_measured = max(
        (v for v in per_metric_latest.values() if v is not None),
        default=None,
    )

    if required_metrics:
        has_for_target = await _has_any_data_on_date(
            session, user_id, required_metrics, target
        )
    else:
        has_for_target = None

    latest_synced = await _latest_synced_at(
        session, user_id, source_slugs=sync_source_slugs
    )

    return DataAvailability(
        availability_status=overall,
        target_date=target,
        has_data_for_target_date=has_for_target,
        latest_measured_at=latest_measured,
        latest_synced_at=latest_synced,
        missing_metrics=missing,
        metrics_with_baseline=with_baseline,
        metrics_without_baseline=without_baseline,
        stale_metrics=stale,
    )


async def assess_availability_any(
    session: AsyncSession,
    user_id: uuid.UUID,
    target_date: date | None = None,
    sync_source_slugs: list[str] | None = None,
) -> DataAvailability:
    """Availability for insights that are metric-agnostic.

    Used by physiological deviations, which scans whatever the user has.
    Treats the set of observed metrics (any metric with at least one
    measurement for this user) as the required list, so aggregate state
    genuinely reflects what data the insight could see.
    """
    observed = await _observed_metrics(session, user_id)
    if not observed:
        target = target_date or date.today()
        latest_synced = await _latest_synced_at(
            session, user_id, source_slugs=sync_source_slugs
        )
        return DataAvailability(
            availability_status="no_data",
            target_date=target,
            has_data_for_target_date=False,
            latest_measured_at=None,
            latest_synced_at=latest_synced,
            missing_metrics=[],
            metrics_with_baseline=[],
            metrics_without_baseline=[],
            stale_metrics=[],
        )
    return await assess_availability(
        session, user_id,
        required_metrics=observed,
        target_date=target_date,
        sync_source_slugs=sync_source_slugs,
    )


# ── Internal query helpers ───────────────────────────────────────────────


def _aggregate_states(states) -> AvailabilityStatus:
    """Fold per-metric states into one ``availability_status``.

    Policy: unanimous ``ok`` stays ``ok``; unanimous non-ok collapses to
    that non-ok state; any heterogeneous mix becomes ``partial``.
    """
    distinct = set(states)
    if not distinct:
        return "ok"
    if len(distinct) == 1:
        return next(iter(distinct))
    return "partial"


async def _metric_state(
    session: AsyncSession,
    user_id: uuid.UUID,
    metric_slug: str,
    target: date,
) -> tuple[AvailabilityStatus, datetime | None]:
    """Classify a single metric's availability state on ``target``.

    Decision order:
      1. No measurement ever              → ``no_data``.
      2. Fewer than ``BASELINE_MIN_POINTS`` → ``insufficient_data``.
      3. Latest ``measured_at`` older than the per-metric budget
         (relative to ``target``) → ``stale_data``.
      4. No measurement on ``target``     → ``no_data_today``.
      5. Otherwise                         → ``ok``.

    Staleness is computed from ``measured_at`` (when the data point
    represents), not ``ingested_at`` or ``last_synced_at`` — a source that
    syncs every hour with no new value for today is still stale for
    deviation purposes.
    """
    row = (
        await session.execute(
            text(
                """
                SELECT
                    COUNT(m.id) AS n,
                    MAX(m.measured_at) AS latest_measured
                FROM measurements m
                JOIN metric_types mt ON mt.id = m.metric_type_id
                WHERE m.user_id = :uid AND mt.slug = :slug
                """
            ),
            {"uid": user_id, "slug": metric_slug},
        )
    ).one()

    count = row.n or 0
    latest: datetime | None = row.latest_measured

    if count == 0:
        return "no_data", None
    if count < BASELINE_MIN_POINTS:
        return "insufficient_data", latest

    if latest is not None:
        days_old = (target - latest.date()).days
        if days_old > stale_threshold_days(metric_slug):
            return "stale_data", latest

    has_target = (
        await session.execute(
            text(
                """
                SELECT EXISTS(
                    SELECT 1 FROM measurements m
                    JOIN metric_types mt ON mt.id = m.metric_type_id
                    WHERE m.user_id = :uid
                      AND mt.slug = :slug
                      AND DATE(m.measured_at) = :target
                )
                """
            ),
            {"uid": user_id, "slug": metric_slug, "target": target},
        )
    ).scalar_one()
    if not has_target:
        return "no_data_today", latest
    return "ok", latest


async def _has_any_data_on_date(
    session: AsyncSession,
    user_id: uuid.UUID,
    metric_slugs: list[str],
    target: date,
) -> bool:
    row = await session.execute(
        text(
            """
            SELECT EXISTS(
                SELECT 1 FROM measurements m
                JOIN metric_types mt ON mt.id = m.metric_type_id
                WHERE m.user_id = :uid
                  AND mt.slug = ANY(:slugs)
                  AND DATE(m.measured_at) = :target
            )
            """
        ),
        {"uid": user_id, "slugs": metric_slugs, "target": target},
    )
    return bool(row.scalar_one())


async def _observed_metrics(
    session: AsyncSession, user_id: uuid.UUID
) -> list[str]:
    result = await session.execute(
        text(
            """
            SELECT DISTINCT mt.slug
            FROM measurements m
            JOIN metric_types mt ON mt.id = m.metric_type_id
            WHERE m.user_id = :uid
            ORDER BY mt.slug
            """
        ),
        {"uid": user_id},
    )
    return [row[0] for row in result.fetchall()]


async def _latest_synced_at(
    session: AsyncSession,
    user_id: uuid.UUID,
    source_slugs: list[str] | None = None,
) -> datetime | None:
    """Most recent cursor advance, optionally filtered to specific sources.

    Onda 1 writes to ``source_cursors`` on every successful ingestion
    run.  When ``source_slugs`` is provided (e.g. ``["garmin_connect"]``),
    only those cursors are considered so that a Garmin sync timestamp does
    not masquerade as freshness for manually-entered temperature readings.
    """
    if source_slugs:
        row = await session.execute(
            text(
                """
                SELECT MAX(sc.last_advanced_at)
                FROM source_cursors sc
                JOIN data_sources ds ON ds.id = sc.source_id
                WHERE sc.user_id = :uid AND ds.slug = ANY(:slugs)
                """
            ),
            {"uid": user_id, "slugs": source_slugs},
        )
    else:
        row = await session.execute(
            text(
                """
                SELECT MAX(last_advanced_at)
                FROM source_cursors
                WHERE user_id = :uid
                """
            ),
            {"uid": user_id},
        )
    return row.scalar_one()
