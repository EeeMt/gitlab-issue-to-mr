"""add task run archive retention support

Revision ID: 061_task_run_archive_retention
Revises: 060_issue_git_clone_options
Create Date: 2026-07-28
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "061_task_run_archive_retention"
down_revision: Union[str, None] = "060_issue_git_clone_options"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "task_run_archives",
        sa.Column("cleanup_next_attempt_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "ix_task_run_archives_created_id",
        "task_run_archives",
        ["created_at", "id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_task_run_archives_created_id", table_name="task_run_archives")
    op.drop_column("task_run_archives", "cleanup_next_attempt_at")
