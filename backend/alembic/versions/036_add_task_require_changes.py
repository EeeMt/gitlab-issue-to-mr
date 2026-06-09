"""add require_changes to task

Revision ID: 036_add_task_require_changes
Revises: 035_issue_execution_locks
Create Date: 2026-05-05 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "036_add_task_require_changes"
down_revision = "035_issue_execution_locks"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tasks",
        sa.Column(
            "require_changes",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )


def downgrade() -> None:
    op.drop_column("tasks", "require_changes")
