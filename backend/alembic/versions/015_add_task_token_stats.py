"""add task token stats

Revision ID: 015
Revises: 014
Create Date: 2025-01-01 00:00:00.000000
"""
from alembic import op
import sqlalchemy as sa

revision = '015'
down_revision = '014'
branch_labels = None
depends_on = None


def upgrade():
    op.add_column('tasks', sa.Column('input_tokens', sa.Integer(), nullable=True))
    op.add_column('tasks', sa.Column('output_tokens', sa.Integer(), nullable=True))


def downgrade():
    op.drop_column('tasks', 'output_tokens')
    op.drop_column('tasks', 'input_tokens')
