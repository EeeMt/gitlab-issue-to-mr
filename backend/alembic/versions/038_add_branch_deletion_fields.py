"""Add delete_branch_on_close and branch_deleted to issues

Revision ID: 038_add_branch_deletion_fields
Revises: 037_task_commit_message
Create Date: 2026-05-10 00:00:00.000000
"""

import sqlalchemy as sa
from alembic import op

revision = "038_add_branch_deletion_fields"
down_revision = "037_task_commit_message"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "issues",
        sa.Column(
            "delete_branch_on_close",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
    )
    op.add_column(
        "issues",
        sa.Column(
            "branch_deleted",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("issues", "branch_deleted")
    op.drop_column("issues", "delete_branch_on_close")
