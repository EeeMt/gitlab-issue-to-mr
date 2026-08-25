"""Persist Worker Kit identity and per-harness inventory evidence.

Revision ID: 077_v2_worker_kit_identity
Revises: 076_v2_worker_image_identity

- ``worker_profiles.worker_kit_identity`` freezes the content-addressed Kit
  identity (``codify.worker.kit-identity/v1``) recorded by the last verified
  Kit installation; ``worker_kit_identity_generation`` invalidates stale
  verification evidence the same way the image identity generation does.
- ``worker_runtime_readiness.harness_inventory`` stores the probe's
  availability/reason map for all four harness keys;
  ``worker_runtime_readiness.kit_identity`` stores the observed manifest
  identity so start-time checks can fail closed on any change.
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "077_v2_worker_kit_identity"
down_revision: Union[str, None] = "076_v2_worker_image_identity"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("worker_profiles", sa.Column("worker_kit_identity", sa.JSON(), nullable=True))
    op.add_column(
        "worker_profiles",
        sa.Column("worker_kit_identity_generation", sa.Integer(), nullable=False, server_default="0"),
    )
    op.alter_column("worker_profiles", "worker_kit_identity_generation", server_default=None)
    op.add_column("worker_runtime_readiness", sa.Column("harness_inventory", sa.JSON(), nullable=True))
    op.add_column("worker_runtime_readiness", sa.Column("kit_identity", sa.JSON(), nullable=True))


def downgrade() -> None:
    raise RuntimeError("077_v2_worker_kit_identity is roll-forward-only; restore from backup")
