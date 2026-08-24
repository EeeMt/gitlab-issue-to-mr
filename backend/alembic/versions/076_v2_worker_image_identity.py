"""Persist verified Worker-image identity for explicit V2 task snapshots.

Revision ID: 076_v2_worker_image_identity
Revises: 075_pi_command_dispatch_journal
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "076_v2_worker_image_identity"
down_revision: Union[str, None] = "075_pi_command_dispatch_journal"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("worker_profiles", sa.Column("v2_worker_image_identity", sa.JSON(), nullable=True))
    op.add_column(
        "worker_profiles",
        sa.Column("v2_worker_image_identity_generation", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("worker_profiles", sa.Column("v2_harness_verification_evidence", sa.JSON(), nullable=True))
    op.alter_column("worker_profiles", "v2_worker_image_identity_generation", server_default=None)


def downgrade() -> None:
    raise RuntimeError("076_v2_worker_image_identity is roll-forward-only; restore from backup")
