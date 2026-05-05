"""add issue execution locks

Revision ID: 035_issue_execution_locks
Revises: 034_add_task_event_archive_state
Create Date: 2026-05-05 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "035_issue_execution_locks"
down_revision = "034_add_task_event_archive_state"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "issue_execution_locks",
        sa.Column("issue_id", sa.Integer(), nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("acquired_at", sa.DateTime(), nullable=False),
        sa.Column("heartbeat_at", sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(["issue_id"], ["issues.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("issue_id"),
    )
    op.create_index(
        "ix_issue_execution_locks_task_id",
        "issue_execution_locks",
        ["task_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_issue_execution_locks_task_id", table_name="issue_execution_locks")
    op.drop_table("issue_execution_locks")
