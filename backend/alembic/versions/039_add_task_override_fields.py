"""Add manual status override fields to tasks

Revision ID: 039_add_task_override_fields
Revises: 038_add_branch_deletion_fields
Create Date: 2026-05-11 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "039_add_task_override_fields"
down_revision = "038_add_branch_deletion_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "tasks",
        sa.Column(
            "is_manually_overridden",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "tasks",
        sa.Column("override_reason", sa.Text(), nullable=True),
    )
    op.add_column(
        "tasks",
        sa.Column("overridden_by_user_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "tasks",
        sa.Column("overridden_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tasks", "overridden_at")
    op.drop_column("tasks", "overridden_by_user_id")
    op.drop_column("tasks", "override_reason")
    op.drop_column("tasks", "is_manually_overridden")
