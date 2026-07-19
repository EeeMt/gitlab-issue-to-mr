"""add issue repository clone options

Revision ID: 060_issue_git_clone_options
Revises: 059_provider_runtime_snapshot
Create Date: 2026-07-19
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "060_issue_git_clone_options"
down_revision: Union[str, None] = "059_provider_runtime_snapshot"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("issues", sa.Column("git_clone_depth", sa.Integer(), nullable=True))
    op.add_column("issues", sa.Column("git_clone_filter", sa.String(length=64), nullable=True))
    op.create_check_constraint(
        "ck_issues_git_clone_depth",
        "issues",
        "git_clone_depth IS NULL OR git_clone_depth BETWEEN 1 AND 10000",
    )
    op.create_check_constraint(
        "ck_issues_git_clone_filter",
        "issues",
        "git_clone_filter IS NULL OR git_clone_filter = 'blob:none'",
    )


def downgrade() -> None:
    op.drop_constraint("ck_issues_git_clone_filter", "issues", type_="check")
    op.drop_constraint("ck_issues_git_clone_depth", "issues", type_="check")
    op.drop_column("issues", "git_clone_filter")
    op.drop_column("issues", "git_clone_depth")
