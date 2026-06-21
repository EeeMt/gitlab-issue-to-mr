"""fix retry_source_task_id ondelete to SET NULL

Revision ID: 051_fix_retry_source_ondelete
Revises: 050_require_task_issue
Create Date: 2026-06-21
"""

from typing import Sequence, Union

from alembic import op

revision: str = "051_fix_retry_source_ondelete"
down_revision: Union[str, None] = "050_require_task_issue"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint("tasks_retry_source_task_id_fkey", "tasks", type_="foreignkey")
    op.create_foreign_key(
        "tasks_retry_source_task_id_fkey",
        "tasks",
        "tasks",
        ["retry_source_task_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("tasks_retry_source_task_id_fkey", "tasks", type_="foreignkey")
    op.create_foreign_key(
        "tasks_retry_source_task_id_fkey",
        "tasks",
        "tasks",
        ["retry_source_task_id"],
        ["id"],
    )
