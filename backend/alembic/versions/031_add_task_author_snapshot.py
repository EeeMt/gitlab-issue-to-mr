"""add task author snapshot fields

Revision ID: 031_add_task_author_snapshot
Revises: 030_mm_channel_id
Create Date: 2026-04-23
"""

from typing import Sequence, Union

from alembic import op


revision: str = "031_add_task_author_snapshot"
down_revision: Union[str, None] = "030_mm_channel_id"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE tasks
        ADD COLUMN IF NOT EXISTS initiator_display_name VARCHAR(255)
        """
    )
    op.execute(
        """
        ALTER TABLE tasks
        ADD COLUMN IF NOT EXISTS initiator_email VARCHAR(255)
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE tasks DROP COLUMN IF EXISTS initiator_email")
    op.execute("ALTER TABLE tasks DROP COLUMN IF EXISTS initiator_display_name")
