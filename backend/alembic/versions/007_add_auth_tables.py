"""add auth tables

Revision ID: 007_add_auth_tables
Revises: 006_add_system_config
Create Date: 2026-03-14
"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "007_add_auth_tables"
down_revision: Union[str, None] = "006_add_system_config"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS users (
            id SERIAL PRIMARY KEY,
            oidc_sub VARCHAR(255) NOT NULL UNIQUE,
            gitlab_user_id INTEGER NOT NULL UNIQUE,
            username VARCHAR(255) NOT NULL UNIQUE,
            display_name VARCHAR(255),
            email VARCHAR(255),
            avatar_url VARCHAR(1024),
            platform_role VARCHAR(32) NOT NULL DEFAULT 'platform_user',
            state VARCHAR(32) NOT NULL DEFAULT 'active',
            last_login_at TIMESTAMP,
            created_at TIMESTAMP NOT NULL DEFAULT NOW(),
            updated_at TIMESTAMP NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_users_gitlab_user_id ON users (gitlab_user_id)")

    op.execute(
        """
        CREATE TABLE IF NOT EXISTS user_sessions (
            id VARCHAR(36) PRIMARY KEY,
            user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            session_token_hash VARCHAR(128) NOT NULL UNIQUE,
            expires_at TIMESTAMP NOT NULL,
            last_seen_at TIMESTAMP,
            ip_address VARCHAR(64),
            user_agent TEXT,
            revoked_at TIMESTAMP,
            created_at TIMESTAMP NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_user_sessions_user_id ON user_sessions (user_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_user_sessions_expires_at ON user_sessions (expires_at)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS user_sessions")
    op.execute("DROP TABLE IF EXISTS users")
