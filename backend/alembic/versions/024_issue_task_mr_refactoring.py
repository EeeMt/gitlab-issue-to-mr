"""issue task mr refactoring — add issues table, modify tasks table

Revision ID: 024_issue_task_mr_refactoring
Revises: 023_add_task_merge_request_title
Create Date: 2026-04-12
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "024_issue_task_mr_refactoring"
down_revision: Union[str, None] = "023_add_task_merge_request_title"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create issues table
    op.create_table(
        "issues",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("title", sa.String(512), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(20), server_default="open", nullable=False),
        sa.Column("branch_name", sa.String(255), nullable=True),
        sa.Column("base_branch", sa.String(255), nullable=True),
        sa.Column("target_branch", sa.String(255), nullable=True),
        sa.Column("merge_request_iid", sa.Integer(), nullable=True),
        sa.Column("merge_request_url", sa.String(512), nullable=True),
        sa.Column("claude_session_id", sa.String(255), nullable=True),
        sa.Column("session_storage_path", sa.String(512), nullable=True),
        sa.Column(
            "initiator_user_id",
            sa.Integer(),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("initiator_username", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_issues_project_id", "issues", ["project_id"])
    op.create_index("ix_issues_status_created", "issues", ["status", "created_at"])
    op.create_index("ix_issues_project_status", "issues", ["project_id", "status"])

    # Remove deprecated columns from tasks (drop old issue_id BEFORE adding new FK issue_id)
    op.drop_index("ix_tasks_project_issue", table_name="tasks")
    op.drop_column("tasks", "issue_iid")
    op.drop_column("tasks", "issue_id")  # old GitLab issue_id — removed before new FK added
    op.drop_column("tasks", "note_id")
    op.drop_column("tasks", "is_manual")
    op.drop_column("tasks", "branch_name")
    op.drop_column("tasks", "base_branch")
    op.drop_column("tasks", "target_branch")
    op.drop_column("tasks", "merge_request_iid")
    op.drop_column("tasks", "merge_request_url")
    op.drop_column("tasks", "retry_count")

    # Add new columns to tasks (issue_id is now FK to issues table)
    op.add_column(
        "tasks",
        sa.Column(
            "issue_id",
            sa.Integer(),
            sa.ForeignKey("issues.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.add_column(
        "tasks",
        sa.Column("is_retry", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.add_column(
        "tasks",
        sa.Column(
            "retry_source_task_id",
            sa.Integer(),
            sa.ForeignKey("tasks.id"),
            nullable=True,
        ),
    )
    op.create_index("ix_tasks_issue_id", "tasks", ["issue_id"])
    op.create_index("ix_tasks_issue_id_status", "tasks", ["issue_id", "status"])


def downgrade() -> None:
    # Re-add removed columns to tasks
    op.add_column("tasks", sa.Column("retry_count", sa.Integer(), server_default="0", nullable=False))
    op.add_column("tasks", sa.Column("merge_request_url", sa.String(512), nullable=True))
    op.add_column("tasks", sa.Column("merge_request_iid", sa.Integer(), nullable=True))
    op.add_column("tasks", sa.Column("target_branch", sa.String(255), nullable=True))
    op.add_column("tasks", sa.Column("base_branch", sa.String(255), nullable=True))
    op.add_column("tasks", sa.Column("branch_name", sa.String(255), nullable=True))
    op.add_column(
        "tasks",
        sa.Column("is_manual", sa.Boolean(), server_default=sa.text("false"), nullable=False),
    )
    op.add_column("tasks", sa.Column("note_id", sa.Integer(), nullable=True))
    op.add_column("tasks", sa.Column("issue_iid", sa.Integer(), nullable=True))
    op.create_index("ix_tasks_project_issue", "tasks", ["project_id", "issue_iid"])

    # Remove new columns from tasks
    op.drop_index("ix_tasks_issue_id_status", table_name="tasks")
    op.drop_index("ix_tasks_issue_id", table_name="tasks")
    op.drop_column("tasks", "retry_source_task_id")
    op.drop_column("tasks", "is_retry")
    op.drop_column("tasks", "issue_id")

    # Drop issues table
    op.drop_index("ix_issues_project_status", table_name="issues")
    op.drop_index("ix_issues_status_created", table_name="issues")
    op.drop_index("ix_issues_project_id", table_name="issues")
    op.drop_table("issues")
