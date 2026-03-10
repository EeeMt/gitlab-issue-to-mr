"""Initial migration - create tasks and task_logs tables

Revision ID: 001_initial
Revises:
Create Date: 2026-03-08

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


# revision identifiers, used by Alembic.
revision: str = "001_initial"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Create enum type
    task_status = postgresql.ENUM(
        "pending", "running", "completed", "failed", name="taskstatus", create_type=False
    )
    task_status.create(op.get_bind(), checkfirst=True)

    # Create tasks table
    op.create_table(
        "tasks",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("project_id", sa.Integer(), nullable=False),
        sa.Column("issue_iid", sa.Integer(), nullable=False),
        sa.Column("issue_id", sa.Integer(), nullable=False),
        sa.Column("note_id", sa.Integer(), nullable=False),
        sa.Column("user_prompt", sa.Text(), nullable=False),
        sa.Column("branch_name", sa.String(255), nullable=True),
        sa.Column("merge_request_iid", sa.Integer(), nullable=True),
        sa.Column("merge_request_url", sa.String(512), nullable=True),
        sa.Column("status", task_status, nullable=False, server_default="pending"),
        sa.Column("commit_sha", sa.String(40), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )

    # Create indexes
    op.create_index("ix_tasks_project_id", "tasks", ["project_id"])
    op.create_index("ix_tasks_status_created", "tasks", ["status", "created_at"])
    op.create_index("ix_tasks_note_id_unique", "tasks", ["note_id"], unique=True)

    # Create task_logs table
    op.create_table(
        "task_logs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("log_level", sa.String(20), nullable=False, server_default="INFO"),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(
            ["task_id"],
            ["tasks.id"],
            name="fk_task_logs_task_id",
            ondelete="CASCADE",
        ),
    )

    op.create_index("ix_task_logs_task_id", "task_logs", ["task_id"])


def downgrade() -> None:
    op.drop_table("task_logs")
    op.drop_table("tasks")
    op.execute("DROP TYPE IF EXISTS taskstatus")
