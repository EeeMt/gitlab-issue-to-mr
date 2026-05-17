"""Add index on issues.initiator_user_id for dashboard query performance

Revision ID: 040_add_issue_initiator_user_id_index
Revises: 039_add_task_override_fields
Create Date: 2026-05-17 00:00:00.000000
"""

from alembic import op

revision = "040_add_issue_initiator_user_id_index"
down_revision = "039_add_task_override_fields"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_index(
        "ix_issues_initiator_user_id",
        "issues",
        ["initiator_user_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_issues_initiator_user_id", table_name="issues")
