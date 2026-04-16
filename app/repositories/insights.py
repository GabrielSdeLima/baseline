"""Insight repository — reads from Tier-1 analytical views.

Does NOT extend BaseRepository (views are read-only projections, not ORM
models).  Uses raw ``text()`` queries and returns ``Row`` objects that the
service maps to Pydantic schemas.
"""
import uuid
from datetime import date

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


class InsightRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    # ── Medication Adherence ──────────────────────────────────────────

    async def get_medication_adherence(self, user_id: uuid.UUID):
        result = await self.session.execute(
            text("""
                SELECT medication_name, frequency,
                       taken, skipped, delayed, total, adherence_pct
                FROM v_medication_adherence
                WHERE user_id = :uid
                ORDER BY medication_name
            """),
            {"uid": user_id},
        )
        return result.fetchall()

    # ── Metric Baseline (for deviations, illness signal, recovery) ───

    async def get_metric_baselines(
        self,
        user_id: uuid.UUID,
        start: date | None = None,
        end: date | None = None,
        metric_slugs: list[str] | None = None,
    ):
        clauses = ["user_id = :uid", "baseline_points >= 3"]
        params: dict = {"uid": user_id}
        if start:
            clauses.append("day >= :start")
            params["start"] = start
        if end:
            clauses.append("day <= :end")
            params["end"] = end
        if metric_slugs:
            clauses.append("metric_slug = ANY(:slugs)")
            params["slugs"] = metric_slugs
        where = " AND ".join(clauses)
        result = await self.session.execute(
            text(f"""
                SELECT day, metric_slug, metric_name,
                       value, baseline_avg, baseline_stddev,
                       z_score, delta_abs, delta_pct
                FROM v_metric_baseline
                WHERE {where}
                ORDER BY day, metric_slug
            """),
            params,
        )
        return result.fetchall()

    # ── Symptom Burden ────────────────────────────────────────────────

    async def get_symptom_burden(
        self,
        user_id: uuid.UUID,
        start: date | None = None,
        end: date | None = None,
    ):
        clauses = ["user_id = :uid"]
        params: dict = {"uid": user_id}
        if start:
            clauses.append("day >= :start")
            params["start"] = start
        if end:
            clauses.append("day <= :end")
            params["end"] = end
        where = " AND ".join(clauses)
        result = await self.session.execute(
            text(f"""
                SELECT day, symptom_count, max_intensity,
                       weighted_burden, dominant_symptom
                FROM v_daily_symptom_burden
                WHERE {where}
                ORDER BY day
            """),
            params,
        )
        return result.fetchall()

    # ── Training Load ─────────────────────────────────────────────────

    async def get_training_load(
        self,
        user_id: uuid.UUID,
        start: date | None = None,
        end: date | None = None,
    ):
        clauses = ["user_id = :uid"]
        params: dict = {"uid": user_id}
        if start:
            clauses.append("day >= :start")
            params["start"] = start
        if end:
            clauses.append("day <= :end")
            params["end"] = end
        where = " AND ".join(clauses)
        result = await self.session.execute(
            text(f"""
                SELECT day, sessions, total_duration_s,
                       training_load, max_rpe
                FROM v_daily_training_load
                WHERE {where}
                ORDER BY day
            """),
            params,
        )
        return result.fetchall()

    # ── Daily Checkpoint Energy (for illness signal) ──────────────────

    async def get_morning_energy(
        self, user_id: uuid.UUID, start: date | None = None, end: date | None = None
    ):
        clauses = ["user_id = :uid", "checkpoint_type = 'morning'"]
        params: dict = {"uid": user_id}
        if start:
            clauses.append("checkpoint_date >= :start")
            params["start"] = start
        if end:
            clauses.append("checkpoint_date <= :end")
            params["end"] = end
        where = " AND ".join(clauses)
        result = await self.session.execute(
            text(f"""
                SELECT checkpoint_date AS day, energy
                FROM daily_checkpoints
                WHERE {where}
                ORDER BY checkpoint_date
            """),
            params,
        )
        return result.fetchall()
