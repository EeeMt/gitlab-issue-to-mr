"""add worker profile verification timestamp

Revision ID: 065_worker_profile_verification
Revises: 064_multi_harness
Create Date: 2026-08-03
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "065_worker_profile_verification"
down_revision: Union[str, None] = "064_multi_harness"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "worker_profiles",
        sa.Column("verified_at", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("worker_profiles", "verified_at")
