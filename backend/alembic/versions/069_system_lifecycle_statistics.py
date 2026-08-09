"""add system lifecycle statistics archives

Revision ID: 069_system_lifecycle_statistics
Revises: 068_issue_sequence_lineage
Create Date: 2026-08-09

Implements the system lifecycle statistics design (§12.1): creates the
``deleted_task_statistics`` / ``deleted_issue_statistics`` archives, the
single-row ``system_statistics_metadata`` gate, and the
``tasks.change_stats_recorded_at`` marker. ``capture_started_at`` stays NULL
here — the deployment step (§12.2) flips it once every old instance has exited
and the standard deletion entry points are guaranteed to archive. No delete
Trigger is installed.
"""

from __future__ import annotations

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "069_system_lifecycle_statistics"
down_revision: Union[str, None] = "068_issue_sequence_lineage"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

SCHEMA_VERSION = 1


def upgrade() -> None:
    op.add_column(
        "tasks",
        sa.Column("change_stats_recorded_at", sa.DateTime(), nullable=True),
    )

    op.create_table(
        "deleted_task_statistics",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("source_task_id", sa.Integer(), nullable=False, unique=True),
        sa.Column("source_issue_id", sa.Integer(), nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("initiator_user_id", sa.Integer(), nullable=True),
        sa.Column("provider_id", sa.Integer(), nullable=True),
        sa.Column("provider_name_snapshot", sa.String(length=255), nullable=True),
        sa.Column("provider_model_snapshot", sa.String(length=128), nullable=True),
        sa.Column("harness_key", sa.String(length=64), nullable=True),
        sa.Column("adapter_version", sa.String(length=64), nullable=True),
        sa.Column("cli_version", sa.String(length=128), nullable=True),
        sa.Column("worker_profile_id", sa.Integer(), nullable=True),
        sa.Column("worker_profile_name_snapshot", sa.String(length=100), nullable=True),
        sa.Column("task_mode", sa.String(length=16), nullable=True),
        sa.Column("trigger_source", sa.String(length=32), nullable=True),
        sa.Column("priority", sa.Integer(), nullable=True),
        sa.Column("is_retry", sa.Boolean(), nullable=True),
        sa.Column("last_status", sa.String(length=32), nullable=True),
        sa.Column("deleted_before_terminal", sa.Boolean(), nullable=True),
        sa.Column("is_manually_overridden", sa.Boolean(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("scheduled_at", sa.DateTime(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("terminal_at", sa.DateTime(), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=True),
        sa.Column("output_tokens", sa.Integer(), nullable=True),
        sa.Column("additions", sa.Integer(), nullable=True),
        sa.Column("deletions", sa.Integer(), nullable=True),
        sa.Column("total_changes", sa.Integer(), nullable=True),
        sa.Column("change_data_available", sa.Boolean(), nullable=True),
        sa.Column("source_deleted_at", sa.DateTime(), nullable=False),
        sa.Column("deletion_reason", sa.String(length=32), nullable=True),
        sa.Column("deleted_by_user_id", sa.Integer(), nullable=True),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("archived_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_deleted_task_statistics_created_at",
        "deleted_task_statistics",
        ["created_at"],
    )
    op.create_index(
        "ix_deleted_task_statistics_terminal_at",
        "deleted_task_statistics",
        ["terminal_at"],
    )
    op.create_index(
        "ix_deleted_task_statistics_last_status",
        "deleted_task_statistics",
        ["last_status"],
    )
    op.create_index(
        "ix_deleted_task_statistics_project_id",
        "deleted_task_statistics",
        ["project_id"],
    )
    op.create_index(
        "ix_deleted_task_statistics_provider_id",
        "deleted_task_statistics",
        ["provider_id"],
    )
    op.create_index(
        "ix_deleted_task_statistics_harness_key",
        "deleted_task_statistics",
        ["harness_key"],
    )
    op.create_index(
        "ix_deleted_task_statistics_source_deleted_at",
        "deleted_task_statistics",
        ["source_deleted_at"],
    )
    op.create_index(
        "ix_deleted_task_statistics_source_issue_id",
        "deleted_task_statistics",
        ["source_issue_id"],
    )

    op.create_table(
        "deleted_issue_statistics",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("source_issue_id", sa.Integer(), nullable=False, unique=True),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("initiator_user_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=True),
        sa.Column("last_status", sa.String(length=32), nullable=True),
        sa.Column("had_merge_request", sa.Boolean(), nullable=True),
        sa.Column("source_deleted_at", sa.DateTime(), nullable=False),
        sa.Column("deletion_reason", sa.String(length=32), nullable=True),
        sa.Column("deleted_by_user_id", sa.Integer(), nullable=True),
        sa.Column("forced_with_active_tasks", sa.Boolean(), nullable=True),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("archived_at", sa.DateTime(), nullable=False),
    )
    op.create_index(
        "ix_deleted_issue_statistics_project_id",
        "deleted_issue_statistics",
        ["project_id"],
    )
    op.create_index(
        "ix_deleted_issue_statistics_source_deleted_at",
        "deleted_issue_statistics",
        ["source_deleted_at"],
    )

    op.create_table(
        "system_statistics_metadata",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=False),
        sa.Column("capture_started_at", sa.DateTime(), nullable=True),
        sa.Column("schema_version", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    # Fixed single row; capture_started_at is intentionally left NULL and set by
    # the deployment step (design §12.2), never by the migration.
    op.execute(
        sa.text(
            "INSERT INTO system_statistics_metadata (id, capture_started_at, "
            "schema_version, updated_at) "
            f"VALUES (1, NULL, {SCHEMA_VERSION}, now())"
        )
    )


def downgrade() -> None:
    op.drop_table("system_statistics_metadata")
    op.drop_index(
        "ix_deleted_issue_statistics_source_deleted_at",
        table_name="deleted_issue_statistics",
    )
    op.drop_index(
        "ix_deleted_issue_statistics_project_id",
        table_name="deleted_issue_statistics",
    )
    op.drop_table("deleted_issue_statistics")
    op.drop_index(
        "ix_deleted_task_statistics_source_issue_id",
        table_name="deleted_task_statistics",
    )
    op.drop_index(
        "ix_deleted_task_statistics_source_deleted_at",
        table_name="deleted_task_statistics",
    )
    op.drop_index(
        "ix_deleted_task_statistics_harness_key",
        table_name="deleted_task_statistics",
    )
    op.drop_index(
        "ix_deleted_task_statistics_provider_id",
        table_name="deleted_task_statistics",
    )
    op.drop_index(
        "ix_deleted_task_statistics_project_id",
        table_name="deleted_task_statistics",
    )
    op.drop_index(
        "ix_deleted_task_statistics_last_status",
        table_name="deleted_task_statistics",
    )
    op.drop_index(
        "ix_deleted_task_statistics_terminal_at",
        table_name="deleted_task_statistics",
    )
    op.drop_index(
        "ix_deleted_task_statistics_created_at",
        table_name="deleted_task_statistics",
    )
    op.drop_table("deleted_task_statistics")
    op.drop_column("tasks", "change_stats_recorded_at")
