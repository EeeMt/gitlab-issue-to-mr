"""require every task to belong to an issue

Revision ID: 050_require_task_issue
Revises: 049_remove_ci_bundle_retention
Create Date: 2026-06-21
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "050_require_task_issue"
down_revision: Union[str, None] = "049_remove_ci_bundle_retention"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Tasks without a parent issue are invalid and cannot be repaired reliably.
    # Preserve any valid task that was manually linked to an orphan task as a
    # retry before deleting the orphan and its task-owned dependent rows.
    op.execute(
        """
        UPDATE tasks
        SET retry_source_task_id = NULL
        WHERE issue_id IS NOT NULL
          AND retry_source_task_id IN (
              SELECT id FROM tasks WHERE issue_id IS NULL
          )
        """
    )
    op.execute("DELETE FROM tasks WHERE issue_id IS NULL")

    op.drop_constraint("tasks_issue_id_fkey", "tasks", type_="foreignkey")
    op.alter_column(
        "tasks",
        "issue_id",
        existing_type=sa.Integer(),
        nullable=False,
    )
    op.create_foreign_key(
        "tasks_issue_id_fkey",
        "tasks",
        "issues",
        ["issue_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    # Deleted orphan tasks cannot be reconstructed.
    op.drop_constraint("tasks_issue_id_fkey", "tasks", type_="foreignkey")
    op.alter_column(
        "tasks",
        "issue_id",
        existing_type=sa.Integer(),
        nullable=True,
    )
    op.create_foreign_key(
        "tasks_issue_id_fkey",
        "tasks",
        "issues",
        ["issue_id"],
        ["id"],
        ondelete="SET NULL",
    )
