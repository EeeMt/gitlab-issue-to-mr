"""make task.target_branch nullable to support no-MR manual tasks

Revision ID: 020_target_branch_nullable
Revises: 019_add_variable_tips
Create Date: 2026-04-03
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "020_target_branch_nullable"
down_revision: Union[str, None] = "019_add_variable_tips"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Allow target_branch to be NULL (manual tasks that skip MR creation)
    op.alter_column(
        "tasks",
        "target_branch",
        existing_type=sa.String(255),
        nullable=True,
    )


def downgrade() -> None:
    # Fill NULLs before restoring NOT NULL constraint
    op.execute("UPDATE tasks SET target_branch = 'main' WHERE target_branch IS NULL")
    op.alter_column(
        "tasks",
        "target_branch",
        existing_type=sa.String(255),
        nullable=False,
    )
