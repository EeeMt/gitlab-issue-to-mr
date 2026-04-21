"""add log_type and metadata columns to task_logs for structured log support

Revision ID: 021_add_structured_logs
Revises: 020_target_branch_nullable
Create Date: 2026-04-15
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "021_add_structured_logs"
down_revision: Union[str, None] = "020_target_branch_nullable"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # log_type distinguishes plain output from structured entries (e.g. 'tool_calls_json')
    op.add_column(
        "task_logs",
        sa.Column("log_type", sa.String(50), nullable=True),
    )
    # metadata stores arbitrary JSON for structured log entries
    op.add_column(
        "task_logs",
        sa.Column("log_metadata", sa.Text, nullable=True),
    )


def downgrade() -> None:
    op.drop_column("task_logs", "log_metadata")
    op.drop_column("task_logs", "log_type")
