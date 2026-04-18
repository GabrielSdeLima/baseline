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
        """Legacy: read from view (INNER JOIN — only regimens with logs)."""
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

    async def get_active_medication_regimens(self, user_id: uuid.UUID):
        """B3: LEFT JOIN ensures regimens without logs are included.

        Rows with total=0 signal ``pending_first_log``; adherence_pct is
        NULL for those rows so the service can distinguish them from
        legitimate 0% adherence.
        """
        result = await self.session.execute(
            text("""
                SELECT
                    mr.id          AS regimen_id,
                    md.name        AS medication_name,
                    mr.frequency,
                    COALESCE(COUNT(ml.id), 0)                          AS total,
                    COALESCE(COUNT(ml.id) FILTER (WHERE ml.status = 'taken'),   0) AS taken,
                    COALESCE(COUNT(ml.id) FILTER (WHERE ml.status = 'skipped'), 0) AS skipped,
                    COALESCE(COUNT(ml.id) FILTER (WHERE ml.status = 'delayed'), 0) AS delayed,
                    CASE
                        WHEN COUNT(ml.id) = 0 THEN NULL
                        ELSE ROUND(
                            100.0
                            * COUNT(ml.id) FILTER (WHERE ml.status = 'taken')
                            / NULLIF(COUNT(ml.id), 0),
                        1)
                    END AS adherence_pct
                FROM medication_regimens mr
                JOIN medication_definitions md ON mr.medication_id = md.id
                LEFT JOIN medication_logs ml ON ml.regimen_id = mr.id
                WHERE mr.user_id = :uid AND mr.is_active = true
                GROUP BY mr.id, md.name, mr.frequency
                ORDER BY md.name
            """),
            {"uid": user_id},
        )
        return result.fetchall()

    async def has_any_symptom_logs(self, user_id: uuid.UUID) -> bool:
        """Return True if the user has ever logged any symptom."""
        row = await self.session.execute(
            text("""
                SELECT EXISTS(
                    SELECT 1 FROM symptom_logs WHERE user_id = :uid
                )
            """),
            {"uid": user_id},
        )
        return bool(row.scalar_one())

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
