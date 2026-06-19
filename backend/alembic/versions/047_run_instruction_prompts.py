"""persist task run instruction prompts

Revision ID: 047_run_instruction_prompts
Revises: 046_ci_failure_auto_repair
Create Date: 2026-06-19
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "047_run_instruction_prompts"
down_revision: Union[str, None] = "046_ci_failure_auto_repair"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("tasks", sa.Column("run_instruction_template", sa.Text(), nullable=True))
    op.add_column("tasks", sa.Column("rendered_prompt", sa.Text(), nullable=True))
    op.add_column("tasks", sa.Column("rendered_prompt_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("tasks", "rendered_prompt_at")
    op.drop_column("tasks", "rendered_prompt")
    op.drop_column("tasks", "run_instruction_template")
