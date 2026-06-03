"""Add task_mode column to tasks table

Revision ID: 042_add_task_mode
Revises: 041_ix_task_logs_task_id_id
Create Date: 2026-06-03 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "042_add_task_mode"
down_revision = "041_ix_task_logs_task_id_id"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tasks",
        sa.Column(
            "task_mode",
            sa.String(16),
            nullable=False,
            server_default="execute",
        ),
    )
    op.create_check_constraint(
        "ck_tasks_task_mode",
        "tasks",
        "task_mode IN ('execute', 'plan')",
    )


def downgrade() -> None:
    op.drop_constraint("ck_tasks_task_mode", "tasks", type_="check")
    op.drop_column("tasks", "task_mode")
