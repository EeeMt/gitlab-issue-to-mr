"""add sort order to prompt templates

Revision ID: 044_prompt_template_sort_order
Revises: 043_add_ai_provider_disabled
Create Date: 2026-06-05
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "044_prompt_template_sort_order"
down_revision: Union[str, None] = "043_add_ai_provider_disabled"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "prompt_templates",
        sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
    )
    op.execute("UPDATE prompt_templates SET sort_order = id")


def downgrade() -> None:
    op.drop_column("prompt_templates", "sort_order")
