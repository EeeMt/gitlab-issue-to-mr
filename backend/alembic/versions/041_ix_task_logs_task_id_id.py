"""Add composite index on task_logs(task_id, id) for log-stream poll performance

Revision ID: 041_ix_task_logs_task_id_id
Revises: 040_ix_issues_initiator_user_id
Create Date: 2026-05-23 00:00:00.000000
"""

from alembic import op

revision = "041_ix_task_logs_task_id_id"
down_revision = "040_ix_issues_initiator_user_id"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # The log-stream SSE endpoint polls with:
    #   WHERE task_id = X AND id > cursor ORDER BY id ASC LIMIT 500
    # The existing single-column ix_task_logs_task_id index forces PostgreSQL to
    # filter by task_id then sort the matching rows by PK separately.  A composite
    # index on (task_id, id) lets the planner satisfy both the filter and the ORDER
    # BY in a single index scan, which is significantly faster for tasks with many
    # log rows.
    op.create_index(
        "ix_task_logs_task_id_id",
        "task_logs",
        ["task_id", "id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_task_logs_task_id_id", table_name="task_logs")
