"""add merge_request_title to tasks

Revision ID: 023_add_task_merge_request_title
Revises: 022_add_task_model_name
Create Date: 2026-04-03
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "023_add_task_merge_request_title"
down_revision: Union[str, None] = "022_add_task_model_name"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "tasks",
        sa.Column("merge_request_title", sa.String(512), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tasks", "merge_request_title")
