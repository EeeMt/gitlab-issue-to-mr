"""add mounted worker kit fields

Revision ID: 056_worker_mounted_kit
Revises: 055_task_cancel_request
Create Date: 2026-07-13
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "056_worker_mounted_kit"
down_revision: Union[str, None] = "055_task_cancel_request"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    for table_name in ("worker_profiles", "task_worker_profile_snapshots"):
        op.add_column(
            table_name,
            sa.Column(
                "runtime_mode",
                sa.String(length=32),
                nullable=False,
                server_default="baked_image",
            ),
        )
        op.add_column(
            table_name,
            sa.Column("worker_kit_version", sa.String(length=128), nullable=True),
        )
        op.add_column(
            table_name,
            sa.Column("worker_kit_path", sa.String(length=1024), nullable=True),
        )


def downgrade() -> None:
    for table_name in ("task_worker_profile_snapshots", "worker_profiles"):
        op.drop_column(table_name, "worker_kit_path")
        op.drop_column(table_name, "worker_kit_version")
        op.drop_column(table_name, "runtime_mode")
