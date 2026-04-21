"""add indexes for filter/sort performance

Revision ID: 026_add_filter_indexes
Revises: 025_issue_status_in_review
Create Date: 2026-07-13
"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "026_add_filter_indexes"
down_revision: Union[str, None] = "025_issue_status_in_review"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "ix_issues_merge_request_iid",
        "issues",
        ["merge_request_iid"],
        unique=False,
    )
    op.create_index(
        "ix_tasks_scheduled_at",
        "tasks",
        ["scheduled_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_tasks_scheduled_at", table_name="tasks")
    op.drop_index("ix_issues_merge_request_iid", table_name="issues")
