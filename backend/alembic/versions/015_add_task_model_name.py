"""add model_name to tasks

Revision ID: 022_add_task_model_name
Revises: 021_add_structured_logs
Create Date: 2026-04-03
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "022_add_task_model_name"
down_revision: Union[str, None] = "021_add_structured_logs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "tasks",
        sa.Column("model_name", sa.String(128), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("tasks", "model_name")
