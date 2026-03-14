"""add task initiator fields

Revision ID: 012_add_task_initiator_fields
Revises: 011_add_session_refresh_token
Create Date: 2026-03-14
"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "012_add_task_initiator_fields"
down_revision: Union[str, None] = "011_add_session_refresh_token"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE tasks
        ADD COLUMN IF NOT EXISTS initiator_user_id INTEGER REFERENCES users(id) ON DELETE SET NULL
        """
    )
    op.execute(
        """
        ALTER TABLE tasks
        ADD COLUMN IF NOT EXISTS initiator_gitlab_user_id INTEGER
        """
    )
    op.execute(
        """
        ALTER TABLE tasks
        ADD COLUMN IF NOT EXISTS initiator_username VARCHAR(255)
        """
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_tasks_initiator_user_id ON tasks (initiator_user_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_tasks_initiator_gitlab_user_id ON tasks (initiator_gitlab_user_id)"
    )
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_tasks_initiator_username ON tasks (initiator_username)"
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_tasks_initiator_username")
    op.execute("DROP INDEX IF EXISTS ix_tasks_initiator_gitlab_user_id")
    op.execute("DROP INDEX IF EXISTS ix_tasks_initiator_user_id")
    op.execute("ALTER TABLE tasks DROP COLUMN IF EXISTS initiator_username")
    op.execute("ALTER TABLE tasks DROP COLUMN IF EXISTS initiator_gitlab_user_id")
    op.execute("ALTER TABLE tasks DROP COLUMN IF EXISTS initiator_user_id")
