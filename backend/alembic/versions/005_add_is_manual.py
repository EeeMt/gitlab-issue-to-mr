"""Add is_manual field and make issue fields nullable

Revision ID: 005_add_is_manual
Revises: 004_add_retry_count
Create Date: 2026-03-13

"""
from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "005_add_is_manual"
down_revision: Union[str, None] = "004_add_retry_count"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Add is_manual column
    op.execute(
        "ALTER TABLE tasks ADD COLUMN IF NOT EXISTS is_manual BOOLEAN NOT NULL DEFAULT FALSE"
    )
    # Make issue fields nullable for manual tasks
    op.execute(
        "ALTER TABLE tasks ALTER COLUMN issue_iid DROP NOT NULL"
    )
    op.execute(
        "ALTER TABLE tasks ALTER COLUMN issue_id DROP NOT NULL"
    )
    op.execute(
        "ALTER TABLE tasks ALTER COLUMN note_id DROP NOT NULL"
    )


def downgrade() -> None:
    op.execute("ALTER TABLE tasks DROP COLUMN IF EXISTS is_manual")
    # Note: Cannot easily restore NOT NULL constraints in downgrade
