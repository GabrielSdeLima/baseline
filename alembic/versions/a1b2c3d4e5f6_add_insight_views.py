"""add insight views

Revision ID: a1b2c3d4e5f6
Revises: ebdc40be31cf
Create Date: 2026-04-15 18:00:00.000000

Tier-1 analytical views for the Insight Layer.
These views compute per-user features (rolling baselines, z-scores, deltas,
training load, symptom burden, medication adherence) without baking in
classification logic.  Classification lives in the Python service layer.

View SQL is defined in view_definitions/insight_views_a1b2c3d4e5f6.py (single
source of truth shared with test setup).  That file is IMMUTABLE once this
migration ships.
"""
from typing import Sequence, Union

from alembic import op

from view_definitions.insight_views_a1b2c3d4e5f6 import DROP_VIEW_SQL, VIEW_SQL

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, None] = "ebdc40be31cf"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    for sql in VIEW_SQL:
        op.execute(sql)


def downgrade() -> None:
    for sql in DROP_VIEW_SQL:
        op.execute(sql)
