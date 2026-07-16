"""add task session mode and session lineage

Revision ID: 057_task_session_mode
Revises: 056_worker_mounted_kit
Create Date: 2026-07-16
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "057_task_session_mode"
down_revision: Union[str, None] = "056_worker_mounted_kit"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "tasks",
        sa.Column(
            "session_mode",
            sa.String(length=16),
            nullable=False,
            server_default="continue",
        ),
    )
    op.add_column("tasks", sa.Column("input_session_id", sa.String(length=255), nullable=True))
    op.add_column("tasks", sa.Column("output_session_id", sa.String(length=255), nullable=True))


def downgrade() -> None:
    op.drop_column("tasks", "output_session_id")
    op.drop_column("tasks", "input_session_id")
    op.drop_column("tasks", "session_mode")
