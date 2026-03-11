"""Add MR change stats fields

Revision ID: 003_add_mr_stats
Revises: 002_queue_scheduling
Create Date: 2026-03-11

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "003_add_mr_stats"
down_revision: Union[str, None] = "002_queue_scheduling"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add new columns to tasks table
    op.add_column(
        "tasks",
        sa.Column("additions", sa.Integer(), nullable=False, server_default="0")
    )
    op.add_column(
        "tasks",
        sa.Column("deletions", sa.Integer(), nullable=False, server_default="0")
    )
    op.add_column(
        "tasks",
        sa.Column("total_changes", sa.Integer(), nullable=False, server_default="0")
    )


def downgrade() -> None:
    # Drop columns
    op.drop_column("tasks", "total_changes")
    op.drop_column("tasks", "deletions")
    op.drop_column("tasks", "additions")
