"""add base_branch to tasks

Revision ID: 014_add_task_base_branch
Revises: 013_add_project_webhook_config
Create Date: 2026-03-20
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "014_add_task_base_branch"
down_revision: Union[str, None] = "013_add_project_webhook_config"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "tasks",
        sa.Column("base_branch", sa.String(255), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tasks", "base_branch")
