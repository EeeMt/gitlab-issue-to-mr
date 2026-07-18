"""capture the model service configuration used for task execution

Revision ID: 059_provider_runtime_snapshot
Revises: 058_issue_worker_affinity
Create Date: 2026-07-18
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "059_provider_runtime_snapshot"
down_revision: Union[str, None] = "058_issue_worker_affinity"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "tasks",
        sa.Column("provider_runtime_snapshot", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tasks", "provider_runtime_snapshot")
