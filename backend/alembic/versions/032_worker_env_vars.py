"""add worker environment variables table

Revision ID: 032_worker_env_vars
Revises: 031_add_task_author_snapshot
Create Date: 2026-04-25
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "032_worker_env_vars"
down_revision: Union[str, None] = "031_add_task_author_snapshot"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "worker_environment_variables",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(length=255), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("is_secret", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_worker_environment_variables_key",
        "worker_environment_variables",
        ["key"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_worker_environment_variables_key",
        table_name="worker_environment_variables",
    )
    op.drop_table("worker_environment_variables")
