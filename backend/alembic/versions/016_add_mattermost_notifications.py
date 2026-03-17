"""add mattermost notifications

Revision ID: 016_add_mattermost_notifications
Revises: 015_add_task_token_stats
Create Date: 2026-03-17 00:00:00.000000
"""

from alembic import op
import sqlalchemy as sa


revision = "016_add_mattermost_notifications"
down_revision = "015_add_task_token_stats"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "mattermost_notification_profiles",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("target_type", sa.String(length=32), nullable=False),
        sa.Column("team_name", sa.String(length=255), nullable=True),
        sa.Column("channel_name", sa.String(length=255), nullable=True),
        sa.Column("mention_in_channel", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("event_types_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("field_keys_json", sa.Text(), nullable=False, server_default="[]"),
        sa.Column("send_for_manual_tasks", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
    )
    op.create_index(
        "ix_mattermost_notification_profiles_enabled",
        "mattermost_notification_profiles",
        ["enabled"],
        unique=False,
    )

    op.create_table(
        "mattermost_user_mappings",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("gitlab_user_id", sa.Integer(), nullable=True),
        sa.Column("gitlab_username", sa.String(length=255), nullable=True),
        sa.Column("mattermost_user_id", sa.String(length=64), nullable=False),
        sa.Column("mattermost_username", sa.String(length=255), nullable=False),
        sa.Column("source", sa.String(length=32), nullable=False, server_default="username"),
        sa.Column("last_verified_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("mattermost_user_id"),
    )
    op.create_index(
        "ix_mattermost_user_mappings_gitlab_user_id",
        "mattermost_user_mappings",
        ["gitlab_user_id"],
        unique=False,
    )
    op.create_index(
        "ix_mattermost_user_mappings_gitlab_username",
        "mattermost_user_mappings",
        ["gitlab_username"],
        unique=False,
    )

    op.create_table(
        "mattermost_notification_deliveries",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("task_id", sa.Integer(), nullable=False),
        sa.Column("profile_id", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("target_summary", sa.String(length=255), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["profile_id"], ["mattermost_notification_profiles.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
    )
    op.create_index(
        "ix_mattermost_notification_deliveries_task_id",
        "mattermost_notification_deliveries",
        ["task_id"],
        unique=False,
    )
    op.create_index(
        "ix_mattermost_notification_deliveries_profile_id",
        "mattermost_notification_deliveries",
        ["profile_id"],
        unique=False,
    )


def downgrade():
    op.drop_index("ix_mattermost_notification_deliveries_profile_id", table_name="mattermost_notification_deliveries")
    op.drop_index("ix_mattermost_notification_deliveries_task_id", table_name="mattermost_notification_deliveries")
    op.drop_table("mattermost_notification_deliveries")

    op.drop_index("ix_mattermost_user_mappings_gitlab_username", table_name="mattermost_user_mappings")
    op.drop_index("ix_mattermost_user_mappings_gitlab_user_id", table_name="mattermost_user_mappings")
    op.drop_table("mattermost_user_mappings")

    op.drop_index("ix_mattermost_notification_profiles_enabled", table_name="mattermost_notification_profiles")
    op.drop_table("mattermost_notification_profiles")
