"""add system config table

Revision ID: 006_add_system_config
Revises: 005_add_is_manual
Create Date: 2026-03-14
"""

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision = "006_add_system_config"
down_revision = "005_add_is_manual"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "system_config",
        sa.Column("key", sa.String(length=100), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("value_type", sa.String(length=20), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.PrimaryKeyConstraint("key"),
    )


def downgrade() -> None:
    op.drop_table("system_config")
