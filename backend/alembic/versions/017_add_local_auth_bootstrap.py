"""add local authentication and system bootstrap

Revision ID: 017_add_local_auth_bootstrap
Revises: 016_add_mattermost_notifications
Create Date: 2026-03-17
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "017_add_local_auth_bootstrap"
down_revision: Union[str, None] = "016_add_mattermost_notifications"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Add local authentication fields to users table
    op.execute(
        """
        ALTER TABLE users 
        ADD COLUMN IF NOT EXISTS local_password_hash VARCHAR(255) NULL
        """
    )
    op.execute(
        """
        ALTER TABLE users 
        ADD COLUMN IF NOT EXISTS auth_provider VARCHAR(32) NOT NULL DEFAULT 'local'
        """
    )
    
    # Update existing users to 'gitlab_oidc' if they have oidc_sub
    op.execute(
        """
        UPDATE users 
        SET auth_provider = 'gitlab_oidc' 
        WHERE oidc_sub IS NOT NULL AND auth_provider = 'local'
        """
    )
    
    # Add indexes for auth_provider
    op.execute(
        "CREATE INDEX IF NOT EXISTS ix_users_auth_provider ON users (auth_provider)"
    )
    
    # 2. Make oidc_sub nullable (for local-only users)
    # Note: In PostgreSQL, we need to first drop the NOT NULL constraint
    op.execute(
        """
        ALTER TABLE users 
        ALTER COLUMN oidc_sub DROP NOT NULL
        """
    )
    
    # 3. Create system_bootstrap table
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS system_bootstrap (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            initialized BOOLEAN NOT NULL DEFAULT FALSE,
            initial_admin_user_id INTEGER NULL REFERENCES users(id) ON DELETE SET NULL,
            initialized_at TIMESTAMP NULL,
            created_at TIMESTAMP NOT NULL DEFAULT NOW()
        )
        """
    )
    
    # Initialize system_bootstrap with a single row if not exists
    op.execute(
        """
        INSERT INTO system_bootstrap (id, initialized) 
        VALUES (1, FALSE)
        ON CONFLICT (id) DO NOTHING
        """
    )
    
    # 4. Mark system as initialized if users already exist
    # This prevents breaking existing deployments
    op.execute(
        """
        UPDATE system_bootstrap 
        SET initialized = TRUE,
            initialized_at = NOW(),
            initial_admin_user_id = (
                SELECT id FROM users 
                WHERE platform_role = 'platform_admin' 
                ORDER BY id ASC 
                LIMIT 1
            )
        WHERE EXISTS (SELECT 1 FROM users)
        """
    )


def downgrade() -> None:
    # Drop system_bootstrap table
    op.execute("DROP TABLE IF EXISTS system_bootstrap")
    
    # Remove indexes
    op.execute("DROP INDEX IF EXISTS ix_users_auth_provider")
    
    # Remove columns
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS auth_provider")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS local_password_hash")
    
    # Restore oidc_sub NOT NULL constraint (recreate column)
    op.execute(
        """
        ALTER TABLE users 
        ALTER COLUMN oidc_sub SET NOT NULL
        """
    )
