"""add worker profile codegraph toggle

Revision ID: 053_worker_profile_codegraph
Revises: 052_worker_profiles
Create Date: 2026-06-27
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "053_worker_profile_codegraph"
down_revision: Union[str, None] = "052_worker_profiles"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "worker_profiles",
        sa.Column(
            "codegraph_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )
    op.add_column(
        "task_worker_profile_snapshots",
        sa.Column(
            "codegraph_enabled",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
    )


def downgrade() -> None:
    op.drop_column("task_worker_profile_snapshots", "codegraph_enabled")
    op.drop_column("worker_profiles", "codegraph_enabled")
