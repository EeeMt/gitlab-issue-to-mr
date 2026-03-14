"""add auth audit logs

Revision ID: 009_add_auth_audit_logs
Revises: 008_add_session_gitlab_token
Create Date: 2026-03-14
"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "009_add_auth_audit_logs"
down_revision: Union[str, None] = "008_add_session_gitlab_token"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE IF NOT EXISTS auth_audit_logs (
            id SERIAL PRIMARY KEY,
            event_type VARCHAR(64) NOT NULL,
            username VARCHAR(255),
            user_id INTEGER REFERENCES users(id) ON DELETE SET NULL,
            success BOOLEAN NOT NULL DEFAULT FALSE,
            detail TEXT,
            ip_address VARCHAR(64),
            user_agent TEXT,
            created_at TIMESTAMP NOT NULL DEFAULT NOW()
        )
        """
    )
    op.execute("CREATE INDEX IF NOT EXISTS ix_auth_audit_logs_event_type ON auth_audit_logs (event_type)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_auth_audit_logs_user_id ON auth_audit_logs (user_id)")
    op.execute("CREATE INDEX IF NOT EXISTS ix_auth_audit_logs_created_at ON auth_audit_logs (created_at)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS auth_audit_logs")
