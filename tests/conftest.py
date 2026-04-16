import asyncio

import httpx
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.core.config import settings
from app.core.dependencies import get_db
from app.main import app
from app.models import Base
from app.models.base import uuid7
from app.models.data_source import DataSource
from app.models.exercise import Exercise
from app.models.metric_type import MetricType
from app.models.symptom import Symptom
from app.models.user import User
from view_definitions.insight_views_a1b2c3d4e5f6 import VIEW_SQL

# ---------------------------------------------------------------------------
# Test database: isolated from the main "baseline" database
# ---------------------------------------------------------------------------

TEST_DB_NAME = "baseline_test"
TEST_DATABASE_URL = settings.database_url.rsplit("/", 1)[0] + f"/{TEST_DB_NAME}"

# Module-level engine — connections are lazy, created when first needed inside
# the test event-loop.  The session-scoped sync fixture below only uses its
# own *temporary* engine (different instance) so there is no event-loop clash.
test_engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)


# ---------------------------------------------------------------------------
# Session-scoped setup: create DB, tables and seed lookup data
# ---------------------------------------------------------------------------


@pytest.fixture(scope="session", autouse=True)
def _create_test_schema():
    """Sync wrapper executed once per test session (before any test runs)."""

    async def _setup():
        # 1. Ensure the test database exists
        sys_engine = create_async_engine(
            settings.database_url, isolation_level="AUTOCOMMIT"
        )
        async with sys_engine.connect() as conn:
            row = await conn.execute(
                text(f"SELECT 1 FROM pg_database WHERE datname = '{TEST_DB_NAME}'")
            )
            if not row.scalar():
                await conn.execute(text(f"CREATE DATABASE {TEST_DB_NAME}"))
        await sys_engine.dispose()

        # 2. Recreate all tables (clean slate)
        tmp_engine = create_async_engine(TEST_DATABASE_URL)
        async with tmp_engine.begin() as conn:
            # Drop views before tables — views depend on tables
            from view_definitions.insight_views_a1b2c3d4e5f6 import DROP_VIEW_SQL
            for sql in DROP_VIEW_SQL:
                await conn.execute(text(sql))
            await conn.run_sync(Base.metadata.drop_all)
            await conn.run_sync(Base.metadata.create_all)
            # Create Tier-1 analytical views from the versioned SQL module.
            # Same source as the Alembic migration — single source of truth.
            for sql in VIEW_SQL:
                await conn.execute(text(sql))

        # 3. Seed lookup / reference data
        factory = async_sessionmaker(
            tmp_engine, class_=AsyncSession, expire_on_commit=False
        )
        async with factory() as session:
            await _seed_lookups(session)
            await session.commit()

        await tmp_engine.dispose()

    asyncio.run(_setup())
    yield


# ---------------------------------------------------------------------------
# Per-test fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def db():
    """Provide a transactional session that rolls back after each test.

    Uses ``join_transaction_block`` so that service-level ``session.commit()``
    calls become savepoint releases — the outer transaction is never committed.
    """
    async with test_engine.connect() as conn:
        trans = await conn.begin()
        session = AsyncSession(
            bind=conn, join_transaction_mode="create_savepoint", expire_on_commit=False
        )
        yield session
        await session.close()
        await trans.rollback()


@pytest.fixture
async def client(db: AsyncSession):
    """HTTPX async client with the FastAPI ``get_db`` dependency overridden."""

    async def _override():
        yield db

    app.dependency_overrides[get_db] = _override
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
    app.dependency_overrides.clear()


@pytest.fixture
async def user(db: AsyncSession) -> User:
    """A fresh test user, visible within the test transaction."""
    u = User(
        id=uuid7(),
        email="test@baseline.dev",
        name="Test User",
        timezone="America/Sao_Paulo",
    )
    db.add(u)
    await db.flush()
    return u


# ---------------------------------------------------------------------------
# Lookup seed data (deterministic IDs: SERIAL starts at 1)
# ---------------------------------------------------------------------------
# DataSource  : manual=1, garmin=2, withings=3, apple_health=4
# MetricType  : weight=1 … respiratory_rate=12  (insertion order)
# Exercise    : bench_press=1 … plank=6
# Symptom     : headache=1 … insomnia=6


async def _seed_lookups(session: AsyncSession) -> None:
    session.add_all(
        [
            DataSource(slug="manual", name="Manual Entry", source_type="manual"),
            DataSource(slug="garmin", name="Garmin", source_type="device"),
            DataSource(slug="withings", name="Withings", source_type="device"),
            DataSource(slug="apple_health", name="Apple Health", source_type="app"),
            DataSource(
                slug="hc900_ble",
                name="HC900 Scale (BLE)",
                source_type="device",
                description="HC900/FG260RB smart scale via BLE passive scan",
            ),
            DataSource(
                slug="garmin_connect",
                name="Garmin Connect (API)",
                source_type="device",
                description="Daily health summaries via Garmin Connect API",
            ),
        ]
    )

    mt = MetricType
    session.add_all(
        [
            mt(slug="weight", name="Weight", category="body_composition",
               default_unit="kg", value_precision=2),
            mt(slug="body_fat_pct", name="Body Fat %", category="body_composition",
               default_unit="%", value_precision=1),
            mt(slug="body_temperature", name="Body Temperature", category="vitals",
               default_unit="°C", value_precision=1),
            mt(slug="resting_hr", name="Resting Heart Rate",
               category="cardiovascular", default_unit="bpm", value_precision=0),
            mt(slug="hrv_rmssd", name="HRV (RMSSD)",
               category="cardiovascular", default_unit="ms", value_precision=1),
            mt(slug="spo2", name="SpO2", category="respiratory",
               default_unit="%", value_precision=0),
            mt(slug="steps", name="Steps", category="activity",
               default_unit="steps", value_precision=0),
            mt(slug="active_calories", name="Active Calories",
               category="activity", default_unit="kcal", value_precision=0),
            mt(slug="sleep_duration", name="Sleep Duration", category="sleep",
               default_unit="min", value_precision=0),
            mt(slug="sleep_score", name="Sleep Score", category="sleep",
               default_unit="score", value_precision=0),
            mt(slug="stress_level", name="Stress Level",
               category="cardiovascular", default_unit="score", value_precision=0),
            mt(slug="respiratory_rate", name="Respiratory Rate",
               category="respiratory", default_unit="brpm", value_precision=1),
            mt(slug="body_battery", name="Body Battery",
               category="wellness", default_unit="score", value_precision=0),
        ]
    )

    ex = Exercise
    session.add_all(
        [
            ex(slug="bench_press", name="Bench Press", category="strength",
               muscle_group="chest", equipment="barbell"),
            ex(slug="squat", name="Squat", category="strength",
               muscle_group="legs", equipment="barbell"),
            ex(slug="deadlift", name="Deadlift", category="strength",
               muscle_group="back", equipment="barbell"),
            ex(slug="running", name="Running", category="cardio",
               muscle_group="legs"),
            ex(slug="pull_up", name="Pull Up", category="strength",
               muscle_group="back", equipment="bodyweight"),
            ex(slug="plank", name="Plank", category="strength",
               muscle_group="core", equipment="bodyweight"),
        ]
    )

    session.add_all(
        [
            Symptom(slug="headache", name="Headache", category="neurological"),
            Symptom(slug="fatigue", name="Fatigue", category="systemic"),
            Symptom(slug="knee_pain", name="Knee Pain", category="musculoskeletal"),
            Symptom(slug="lower_back_pain", name="Lower Back Pain", category="musculoskeletal"),
            Symptom(slug="nausea", name="Nausea", category="digestive"),
            Symptom(slug="insomnia", name="Insomnia", category="neurological"),
        ]
    )

    await session.flush()
