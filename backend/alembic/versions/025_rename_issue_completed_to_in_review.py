"""rename issue status completed to in_review

Revision ID: 025_issue_status_in_review
Revises: 024_issue_task_mr_refactoring
Create Date: 2026-06-15
"""

from typing import Sequence, Union

from alembic import op


# revision identifiers, used by Alembic.
revision: str = "025_issue_status_in_review"
down_revision: Union[str, None] = "024_issue_task_mr_refactoring"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.execute("UPDATE issues SET status = 'in_review' WHERE status = 'completed'")


def downgrade() -> None:
    op.execute("UPDATE issues SET status = 'completed' WHERE status = 'in_review'")
