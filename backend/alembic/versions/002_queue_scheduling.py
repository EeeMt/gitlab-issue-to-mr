"""P1 - Queue scheduling fields

Revision ID: 002_queue_scheduling
Revises: 001_initial
Create Date: 2026-03-08

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "002_queue_scheduling"
down_revision: Union[str, None] = "001_initial"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add new status values to enum
    op.execute("ALTER TYPE taskstatus ADD VALUE IF NOT EXISTS 'queued'")
    op.execute("ALTER TYPE taskstatus ADD VALUE IF NOT EXISTS 'cancelled'")
    # PostgreSQL forbids using a newly added enum label until the transaction
    # that added it commits. Alembic otherwise wraps a fresh-db upgrade through
    # head in one transaction, and later migrations query both labels.
    op.execute("COMMIT")

    # Add new columns to tasks table
    op.add_column(
        "tasks",
        sa.Column("priority", sa.Integer(), nullable=False, server_default="0")
    )
    op.add_column(
        "tasks",
        sa.Column("scheduled_at", sa.DateTime(), nullable=True)
    )
    op.add_column(
        "tasks",
        sa.Column("container_id", sa.String(64), nullable=True)
    )
    op.add_column(
        "tasks",
        sa.Column("target_branch", sa.String(255), nullable=False, server_default="main")
    )

    # Add new indexes
    op.create_index(
        "ix_tasks_status_priority",
        "tasks",
        ["status", "priority", "scheduled_at"]
    )
    op.create_index(
        "ix_tasks_project_issue",
        "tasks",
        ["project_id", "issue_iid"]
    )


def downgrade() -> None:
    # Drop indexes
    op.drop_index("ix_tasks_project_issue", table_name="tasks")
    op.drop_index("ix_tasks_status_priority", table_name="tasks")

    # Drop columns
    op.drop_column("tasks", "target_branch")
    op.drop_column("tasks", "container_id")
    op.drop_column("tasks", "scheduled_at")
    op.drop_column("tasks", "priority")

    # Note: Cannot easily drop enum values in PostgreSQL
    # Would need to recreate the type
