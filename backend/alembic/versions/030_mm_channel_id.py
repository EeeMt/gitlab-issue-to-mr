"""persist mattermost channel ids

Revision ID: 030_mm_channel_id
Revises: 029_add_issue_closed_via
Create Date: 2026-04-21
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "030_mm_channel_id"
down_revision: Union[str, None] = "029_add_issue_closed_via"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("mattermost_notification_profiles", sa.Column("channel_id", sa.String(length=64), nullable=True))
    op.drop_column("mattermost_notification_profiles", "channel_name")
    op.drop_column("mattermost_notification_profiles", "team_name")
    op.drop_column("mattermost_notification_profiles", "send_for_manual_tasks")


def downgrade() -> None:
    op.add_column(
        "mattermost_notification_profiles",
        sa.Column("send_for_manual_tasks", sa.Boolean(), nullable=False, server_default=sa.false()),
    )
    op.add_column("mattermost_notification_profiles", sa.Column("team_name", sa.String(length=255), nullable=True))
    op.add_column("mattermost_notification_profiles", sa.Column("channel_name", sa.String(length=255), nullable=True))
    op.drop_column("mattermost_notification_profiles", "channel_id")
