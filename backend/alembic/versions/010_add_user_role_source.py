"""add user role source

Revision ID: 010_add_user_role_source
Revises: 009_add_auth_audit_logs
Create Date: 2026-03-14
"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "010_add_user_role_source"
down_revision: Union[str, None] = "009_add_auth_audit_logs"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        ALTER TABLE users
        ADD COLUMN IF NOT EXISTS platform_role_source VARCHAR(32) NOT NULL DEFAULT 'bootstrap'
        """
    )


def downgrade() -> None:
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS platform_role_source")
