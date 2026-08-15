"""add issue default harness key

Revision ID: 066_issue_default_harness_key
Revises: 065_worker_profile_verification
Create Date: 2026-08-06
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "066_issue_default_harness_key"
down_revision: Union[str, None] = "065_worker_profile_verification"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "issues",
        sa.Column("default_harness_key", sa.String(length=32), nullable=True),
    )
    op.execute(
        """
        UPDATE issues
        SET default_harness_key = COALESCE(worker_profiles.default_harness_key, 'claude')
        FROM worker_profiles
        WHERE issues.worker_profile_id = worker_profiles.id
        """
    )


def downgrade() -> None:
    op.drop_column("issues", "default_harness_key")
