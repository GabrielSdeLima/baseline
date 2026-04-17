"""operational platform Onda 1 — schema only

Revision ID: f1g2h3i4j5k6
Revises: e4f5a6b7c8d9
Create Date: 2026-04-17

Tables: user_integrations, user_devices, agent_instances, ingestion_runs,
        source_cursors, ingestion_run_payloads.
Alters: raw_payloads (user_device_id, agent_instance_id — nullable FKs).
No seeds. No user-scoped data.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "f1g2h3i4j5k6"
down_revision: Union[str, None] = "e4f5a6b7c8d9"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ------------------------------------------------------------------ #
    # 1. user_integrations                                                 #
    # ------------------------------------------------------------------ #
    op.create_table(
        "user_integrations",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(length=31), server_default="active", nullable=False),
        sa.Column(
            "config_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("credentials_ref", sa.String(length=255), nullable=True),
        sa.Column("last_sync_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error_message", sa.String(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "status IN ('active', 'suspended', 'revoked', 'error')",
            name="ck_user_integrations_status",
        ),
        sa.ForeignKeyConstraint(["source_id"], ["data_sources.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "source_id", name="uq_user_integrations_user_source"),
    )
    op.create_index("ix_user_integrations_user", "user_integrations", ["user_id"])

    # ------------------------------------------------------------------ #
    # 2. user_devices                                                      #
    # ------------------------------------------------------------------ #
    op.create_table(
        "user_devices",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("integration_id", sa.Uuid(), nullable=True),
        sa.Column("device_type", sa.String(length=31), nullable=False),
        sa.Column("identifier", sa.String(length=127), nullable=False),
        sa.Column("identifier_type", sa.String(length=31), nullable=False),
        sa.Column("display_name", sa.String(length=127), nullable=True),
        sa.Column("firmware_version", sa.String(length=63), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
        sa.Column(
            "config_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "device_type IN ('scale', 'wearable', 'phone', 'hub', 'other')",
            name="ck_user_devices_device_type",
        ),
        sa.CheckConstraint(
            "identifier_type IN ('mac', 'serial', 'imei', 'uuid', 'other')",
            name="ck_user_devices_identifier_type",
        ),
        sa.ForeignKeyConstraint(
            ["integration_id"], ["user_integrations.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["source_id"], ["data_sources.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "source_id",
            "identifier",
            name="uq_user_devices_user_source_identifier",
        ),
    )
    op.create_index("ix_user_devices_user_source", "user_devices", ["user_id", "source_id"])
    op.create_index("ix_user_devices_identifier", "user_devices", ["identifier"])

    # ------------------------------------------------------------------ #
    # 3. agent_instances                                                   #
    # ------------------------------------------------------------------ #
    op.create_table(
        "agent_instances",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=True),
        sa.Column("install_id", sa.String(length=127), nullable=False),
        sa.Column("agent_type", sa.String(length=63), nullable=False),
        sa.Column("display_name", sa.String(length=127), nullable=True),
        sa.Column("platform", sa.String(length=63), nullable=True),
        sa.Column("agent_version", sa.String(length=63), nullable=True),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "is_active", sa.Boolean(), server_default=sa.text("true"), nullable=False
        ),
        sa.Column(
            "metadata_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "agent_type IN ('local_pc', 'android', 'ios', 'browser', 'server', 'other')",
            name="ck_agent_instances_agent_type",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("install_id", name="uq_agent_instances_install_id"),
    )
    op.create_index(
        "ix_agent_instances_user",
        "agent_instances",
        ["user_id"],
        postgresql_where=sa.text("user_id IS NOT NULL"),
    )

    # ------------------------------------------------------------------ #
    # 4. ingestion_runs                                                    #
    # ------------------------------------------------------------------ #
    op.create_table(
        "ingestion_runs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("agent_instance_id", sa.Uuid(), nullable=True),
        sa.Column("user_integration_id", sa.Uuid(), nullable=True),
        sa.Column("operation_type", sa.String(length=31), nullable=False),
        sa.Column("trigger_type", sa.String(length=31), nullable=False),
        sa.Column("idempotency_key", sa.String(length=255), nullable=True),
        sa.Column(
            "status",
            sa.String(length=31),
            server_default="running",
            nullable=False,
        ),
        sa.Column(
            "attempt_no",
            sa.SmallInteger(),
            server_default=sa.text("1"),
            nullable=False,
        ),
        sa.Column(
            "started_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "raw_payloads_created",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "raw_payloads_reused",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "raw_payloads_failed",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "measurements_created",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column(
            "measurements_deleted",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("error_message", sa.String(), nullable=True),
        sa.Column(
            "metadata_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "operation_type IN ('cloud_sync', 'ble_scan', 'replay', 'manual_entry', 'file_import', 'health_connect_pull')",
            name="ck_ingestion_runs_operation_type",
        ),
        sa.CheckConstraint(
            "trigger_type IN ('startup', 'scheduled', 'manual', 'ui_button', 'wake', 'ui_stale', 'backfill', 'retry')",
            name="ck_ingestion_runs_trigger_type",
        ),
        sa.CheckConstraint(
            "status IN ('running', 'completed', 'failed', 'partial', 'skipped')",
            name="ck_ingestion_runs_status",
        ),
        sa.ForeignKeyConstraint(["agent_instance_id"], ["agent_instances.id"]),
        sa.ForeignKeyConstraint(["source_id"], ["data_sources.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.ForeignKeyConstraint(["user_integration_id"], ["user_integrations.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_ingestion_runs_user_source_started",
        "ingestion_runs",
        ["user_id", "source_id", "started_at"],
    )
    op.create_index(
        "ix_ingestion_runs_running",
        "ingestion_runs",
        ["status"],
        postgresql_where=sa.text("status = 'running'"),
    )
    op.create_index(
        "ix_ingestion_runs_idempotency_key",
        "ingestion_runs",
        ["idempotency_key"],
        unique=True,
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )

    # ------------------------------------------------------------------ #
    # 5. source_cursors                                                    #
    # ------------------------------------------------------------------ #
    op.create_table(
        "source_cursors",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("user_id", sa.Uuid(), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("cursor_name", sa.String(length=63), nullable=False),
        sa.Column(
            "cursor_scope_key",
            sa.String(length=127),
            server_default=sa.text("''"),
            nullable=False,
        ),
        sa.Column(
            "cursor_value_json",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'{}'::jsonb"),
            nullable=False,
        ),
        sa.Column("last_successful_run_id", sa.Uuid(), nullable=True),
        sa.Column("last_advanced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["last_successful_run_id"], ["ingestion_runs.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["source_id"], ["data_sources.id"]),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"]),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "source_id",
            "cursor_name",
            "cursor_scope_key",
            name="uq_source_cursors",
        ),
    )
    op.create_index(
        "ix_source_cursors_user_source", "source_cursors", ["user_id", "source_id"]
    )

    # ------------------------------------------------------------------ #
    # 6. ingestion_run_payloads                                            #
    # ------------------------------------------------------------------ #
    op.create_table(
        "ingestion_run_payloads",
        sa.Column("run_id", sa.Uuid(), nullable=False),
        sa.Column("payload_id", sa.Uuid(), nullable=False),
        sa.Column(
            "role",
            sa.String(length=31),
            server_default="created",
            nullable=False,
        ),
        sa.Column(
            "linked_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "role IN ('created', 'reused', 'reprocessed')",
            name="ck_ingestion_run_payloads_role",
        ),
        sa.ForeignKeyConstraint(["payload_id"], ["raw_payloads.id"]),
        sa.ForeignKeyConstraint(["run_id"], ["ingestion_runs.id"]),
        sa.PrimaryKeyConstraint("run_id", "payload_id"),
    )
    op.create_index(
        "ix_ingestion_run_payloads_payload", "ingestion_run_payloads", ["payload_id"]
    )

    # ------------------------------------------------------------------ #
    # 7. ALTER raw_payloads — nullable FKs, backward-compatible           #
    # ------------------------------------------------------------------ #
    op.add_column("raw_payloads", sa.Column("user_device_id", sa.Uuid(), nullable=True))
    op.add_column(
        "raw_payloads", sa.Column("agent_instance_id", sa.Uuid(), nullable=True)
    )
    op.create_foreign_key(
        "fk_raw_payloads_user_device",
        "raw_payloads",
        "user_devices",
        ["user_device_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "fk_raw_payloads_agent_instance",
        "raw_payloads",
        "agent_instances",
        ["agent_instance_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    # Reverse order: first remove what depends on later-created tables
    op.drop_constraint(
        "fk_raw_payloads_agent_instance", "raw_payloads", type_="foreignkey"
    )
    op.drop_constraint(
        "fk_raw_payloads_user_device", "raw_payloads", type_="foreignkey"
    )
    op.drop_column("raw_payloads", "agent_instance_id")
    op.drop_column("raw_payloads", "user_device_id")

    op.drop_index(
        "ix_ingestion_run_payloads_payload", table_name="ingestion_run_payloads"
    )
    op.drop_table("ingestion_run_payloads")

    op.drop_index("ix_source_cursors_user_source", table_name="source_cursors")
    op.drop_table("source_cursors")

    op.drop_index(
        "ix_ingestion_runs_idempotency_key",
        table_name="ingestion_runs",
        postgresql_where=sa.text("idempotency_key IS NOT NULL"),
    )
    op.drop_index(
        "ix_ingestion_runs_running",
        table_name="ingestion_runs",
        postgresql_where=sa.text("status = 'running'"),
    )
    op.drop_index("ix_ingestion_runs_user_source_started", table_name="ingestion_runs")
    op.drop_table("ingestion_runs")

    op.drop_index(
        "ix_agent_instances_user",
        table_name="agent_instances",
        postgresql_where=sa.text("user_id IS NOT NULL"),
    )
    op.drop_table("agent_instances")

    op.drop_index("ix_user_devices_identifier", table_name="user_devices")
    op.drop_index("ix_user_devices_user_source", table_name="user_devices")
    op.drop_table("user_devices")

    op.drop_index("ix_user_integrations_user", table_name="user_integrations")
    op.drop_table("user_integrations")
