"""rename merge_request_title to commit_message in tasks

Revision ID: 037_task_commit_message
Revises: 036_add_task_require_changes
Create Date: 2026-05-08 00:00:00.000000
"""

from alembic import op


revision = "037_task_commit_message"
down_revision = "036_add_task_require_changes"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("tasks", "merge_request_title", new_column_name="commit_message")


def downgrade() -> None:
    op.alter_column("tasks", "commit_message", new_column_name="merge_request_title")
