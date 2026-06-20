"""remove unused CI failure bundle retention config

Revision ID: 049_remove_ci_bundle_retention
Revises: 048_task_raw_logs_finalized
Create Date: 2026-06-20
"""

from typing import Sequence, Union

from alembic import op

revision: str = "049_remove_ci_bundle_retention"
down_revision: Union[str, None] = "048_task_raw_logs_finalized"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("DELETE FROM system_config WHERE key = 'ci_failure_bundle_retention_days'")


def downgrade() -> None:
    # The removed override cannot be reconstructed. The former default was 30.
    pass
