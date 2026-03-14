"""add session gitlab token

Revision ID: 008_add_session_gitlab_token
Revises: 007_add_auth_tables
Create Date: 2026-03-14
"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "008_add_session_gitlab_token"
down_revision: Union[str, None] = "007_add_auth_tables"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE user_sessions
        ADD COLUMN IF NOT EXISTS gitlab_access_token_encrypted TEXT
        """
    )


def downgrade() -> None:
    op.execute(
        """
        ALTER TABLE user_sessions
        DROP COLUMN IF EXISTS gitlab_access_token_encrypted
        """
    )
