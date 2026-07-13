"""add durable task cancellation request

Revision ID: 055_task_cancel_request
Revises: 054_worker_docker_target
Create Date: 2026-07-12
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "055_task_cancel_request"
down_revision: Union[str, None] = "054_worker_docker_target"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("tasks", sa.Column("cancel_requested_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("tasks", "cancel_requested_at")
