"""add closed_via column to issues

Revision ID: 029_add_issue_closed_via
Revises: 028_add_webhook_events
Create Date: 2026-04-20
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "029_add_issue_closed_via"
down_revision: Union[str, None] = "028_add_webhook_events"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("issues", sa.Column("closed_via", sa.String(30), nullable=True))


def downgrade() -> None:
    op.drop_column("issues", "closed_via")
