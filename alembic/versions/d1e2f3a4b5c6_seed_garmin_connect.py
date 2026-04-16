"""seed garmin_connect data source and body_battery metric type

Revision ID: d1e2f3a4b5c6
Revises: c9d0e1f2a3b4
Create Date: 2026-04-15 00:00:00.000000

Adds:
  - data_sources: garmin_connect  (Garmin Connect API integration)
  - metric_types: body_battery    (Garmin Body Battery 0-100 wellness score)

All inserts are idempotent (ON CONFLICT DO NOTHING) — safe to run on databases
that already have these records from seed.py or a previous partial migration.
"""

from typing import Sequence, Union

from alembic import op

revision: str = "d1e2f3a4b5c6"
down_revision: Union[str, None] = "c9d0e1f2a3b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("""
        INSERT INTO data_sources (slug, name, source_type, description, created_at)
        VALUES (
            'garmin_connect',
            'Garmin Connect (API)',
            'device',
            'Daily health summaries fetched via Garmin Connect API '
            '(python-garminconnect). Includes HRV, sleep, activity, stress, '
            'body battery, and SpO2.',
            NOW()
        )
        ON CONFLICT (slug) DO NOTHING
    """)

    op.execute("""
        INSERT INTO metric_types
            (slug, name, category, default_unit, value_precision, description, created_at)
        VALUES (
            'body_battery',
            'Body Battery',
            'wellness',
            'score',
            0,
            'Garmin Body Battery energy level (0-100). Reflects recovery state: '
            'charged during sleep, drained by activity and stress.',
            NOW()
        )
        ON CONFLICT (slug) DO NOTHING
    """)


def downgrade() -> None:
    op.execute("DELETE FROM data_sources WHERE slug = 'garmin_connect'")
    op.execute("DELETE FROM metric_types WHERE slug = 'body_battery'")
