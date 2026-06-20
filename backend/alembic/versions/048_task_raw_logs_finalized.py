"""track task raw log finalization

Revision ID: 048_task_raw_logs_finalized
Revises: 047_run_instruction_prompts
Create Date: 2026-06-20
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "048_task_raw_logs_finalized"
down_revision: Union[str, None] = "047_run_instruction_prompts"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("tasks", sa.Column("raw_logs_finalized_at", sa.DateTime(), nullable=True))
    op.execute(
        """
        UPDATE tasks
        SET raw_logs_finalized_at = COALESCE(completed_at, updated_at)
        WHERE status IN ('completed', 'failed', 'cancelled')
        """
    )


def downgrade() -> None:
    op.drop_column("tasks", "raw_logs_finalized_at")
