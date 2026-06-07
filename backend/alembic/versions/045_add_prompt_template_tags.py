"""add tags to prompt templates

Revision ID: 045_add_prompt_template_tags
Revises: 044_prompt_template_sort_order
Create Date: 2026-06-06
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "045_add_prompt_template_tags"
down_revision: Union[str, None] = "044_prompt_template_sort_order"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "prompt_templates",
        sa.Column("tags", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
    )
    op.alter_column("prompt_templates", "tags", server_default=None)


def downgrade() -> None:
    op.drop_column("prompt_templates", "tags")
