"""add index on task_harness_attempts.harness_key

Revision ID: 064_harness_key
Revises: 063_harness_runtime
Create Date: 2026-08-06
"""

from typing import Sequence, Union

from alembic import op

revision: str = "064_harness_key"
down_revision: Union[str, None] = "063_harness_runtime"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_task_harness_attempts_harness_key",
        "task_harness_attempts",
        ["harness_key"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_task_harness_attempts_harness_key",
        table_name="task_harness_attempts",
    )
