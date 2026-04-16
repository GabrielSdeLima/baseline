"""seed hc900_ble data source

Revision ID: c9d0e1f2a3b4
Revises: a1b2c3d4e5f6
Create Date: 2026-04-15 19:00:00.000000

Data migration: inserts the hc900_ble DataSource record required by the
HC900 BLE scale integration.  Safe to run against a DB that already has
the record — ON CONFLICT DO NOTHING guarantees idempotency.
"""

from alembic import op

revision = "c9d0e1f2a3b4"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        """
        INSERT INTO data_sources (slug, name, source_type, description, created_at)
        VALUES (
            'hc900_ble',
            'HC900 Scale (BLE)',
            'device',
            'HC900/FG260RB BLE smart scale — passive advertisement scan via bleak. '
            'Decoded by Pulso decode_scale.dart (hc900_ble_v1).',
            NOW()
        )
        ON CONFLICT (slug) DO NOTHING
        """
    )


def downgrade() -> None:
    op.execute("DELETE FROM data_sources WHERE slug = 'hc900_ble'")
