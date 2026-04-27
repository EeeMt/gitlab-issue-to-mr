"""add usage limit tables

Revision ID: 033_add_usage_limits
Revises: 032_worker_env_vars
Create Date: 2026-04-27
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "033_add_usage_limits"
down_revision: Union[str, None] = "032_worker_env_vars"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "usage_limit_policies",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("scope_type", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("daily_tokens_mode", sa.String(length=16), nullable=False, server_default="custom"),
        sa.Column("daily_tokens_value", sa.Integer(), nullable=True),
        sa.Column("weekly_tokens_mode", sa.String(length=16), nullable=False, server_default="custom"),
        sa.Column("weekly_tokens_value", sa.Integer(), nullable=True),
        sa.Column("daily_tasks_mode", sa.String(length=16), nullable=False, server_default="custom"),
        sa.Column("daily_tasks_value", sa.Integer(), nullable=True),
        sa.Column("weekly_tasks_mode", sa.String(length=16), nullable=False, server_default="custom"),
        sa.Column("weekly_tasks_value", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_usage_limit_policies_user_id"),
    )
    op.create_index(
        "ix_usage_limit_policies_scope_type",
        "usage_limit_policies",
        ["scope_type"],
        unique=False,
    )
    op.create_index(
        "uq_usage_limit_policies_system_default",
        "usage_limit_policies",
        ["scope_type"],
        unique=True,
        postgresql_where=sa.text("scope_type = 'system_default' AND user_id IS NULL"),
        sqlite_where=sa.text("scope_type = 'system_default' AND user_id IS NULL"),
    )

    op.create_table(
        "task_usage_ledger",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("task_status", sa.String(length=32), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=False),
        sa.Column("timezone_day", sa.Date(), nullable=False),
        sa.Column("timezone_week_start", sa.Date(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("task_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.CheckConstraint("task_count = 1", name="ck_task_usage_ledger_task_count_is_one"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("task_id", name="uq_task_usage_ledger_task_id"),
    )
    op.create_index(
        "ix_task_usage_ledger_completed_at",
        "task_usage_ledger",
        ["completed_at"],
        unique=False,
    )
    op.create_index(
        "ix_task_usage_ledger_user_day",
        "task_usage_ledger",
        ["user_id", "timezone_day"],
        unique=False,
    )
    op.create_index(
        "ix_task_usage_ledger_user_week",
        "task_usage_ledger",
        ["user_id", "timezone_week_start"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_task_usage_ledger_user_week", table_name="task_usage_ledger")
    op.drop_index("ix_task_usage_ledger_user_day", table_name="task_usage_ledger")
    op.drop_index("ix_task_usage_ledger_completed_at", table_name="task_usage_ledger")
    op.drop_table("task_usage_ledger")

    op.drop_index("uq_usage_limit_policies_system_default", table_name="usage_limit_policies")
    op.drop_index("ix_usage_limit_policies_scope_type", table_name="usage_limit_policies")
    op.drop_table("usage_limit_policies")
