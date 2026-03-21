"""alter users gitlab_user_id to be nullable for local auth

Revision ID: 018_users_gitlab_nullable
Revises: 017_add_local_auth_bootstrap
Create Date: 2026-03-21
"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "018_users_gitlab_nullable"
down_revision: Union[str, None] = "017_add_local_auth_bootstrap"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Allow gitlab_user_id to be NULL for local authentication users
    # who don't have an associated GitLab account
    op.execute(
        """
        ALTER TABLE users
        ALTER COLUMN gitlab_user_id DROP NOT NULL
        """
    )


def downgrade() -> None:
    # Restore NOT NULL constraint (existing local users will need gitlab_user_id set)
    op.execute(
        """
        UPDATE users SET gitlab_user_id = 0 WHERE gitlab_user_id IS NULL
        """
    )
    op.execute(
        """
        ALTER TABLE users
        ALTER COLUMN gitlab_user_id SET NOT NULL
        """
    )