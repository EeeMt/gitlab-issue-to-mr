"""add webhook_events table

Revision ID: 028_add_webhook_events
Revises: 027_add_ai_providers
Create Date: 2026-04-20
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "028_add_webhook_events"
down_revision: Union[str, None] = "027_add_ai_providers"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "webhook_events",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("event_type", sa.String(50), nullable=False),
        sa.Column("event_action", sa.String(50), nullable=True),
        sa.Column("project_id", sa.Integer, nullable=False),
        sa.Column("merge_request_iid", sa.Integer, nullable=True),
        sa.Column(
            "issue_id",
            sa.Integer,
            sa.ForeignKey("issues.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("source_ip", sa.String(45), nullable=True),
        sa.Column("result", sa.String(50), nullable=False),
        sa.Column("result_detail", sa.Text, nullable=True),
        sa.Column("payload_summary", sa.JSON, nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime,
            nullable=False,
            server_default=sa.func.now(),
        ),
    )
    op.create_index("ix_webhook_events_project_id", "webhook_events", ["project_id"])
    op.create_index(
        "ix_webhook_events_project_created",
        "webhook_events",
        ["project_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_webhook_events_project_created", table_name="webhook_events")
    op.drop_index("ix_webhook_events_project_id", table_name="webhook_events")
    op.drop_table("webhook_events")
