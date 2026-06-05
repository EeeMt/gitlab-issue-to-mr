"""add disabled flag to ai_providers

Revision ID: 043_add_ai_provider_disabled
Revises: 042_add_task_mode
Create Date: 2026-06-05
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "043_add_ai_provider_disabled"
down_revision: Union[str, None] = "042_add_task_mode"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "ai_providers",
        sa.Column("is_disabled", sa.Boolean(), nullable=False, server_default="false"),
    )


def downgrade() -> None:
    op.drop_column("ai_providers", "is_disabled")
