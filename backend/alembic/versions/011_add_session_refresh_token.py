"""add session refresh token

Revision ID: 011_add_session_refresh_token
Revises: 010_add_user_role_source
Create Date: 2026-03-14
"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "011_add_session_refresh_token"
down_revision: Union[str, None] = "010_add_user_role_source"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE user_sessions
        ADD COLUMN IF NOT EXISTS gitlab_refresh_token_encrypted TEXT
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE user_sessions DROP COLUMN IF EXISTS gitlab_refresh_token_encrypted")
