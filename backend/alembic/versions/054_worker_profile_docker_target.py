"""add worker profile docker target

Revision ID: 054_worker_docker_target
Revises: 053_worker_profile_codegraph
Create Date: 2026-07-11
"""

from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "054_worker_docker_target"
down_revision: Union[str, None] = "053_worker_profile_codegraph"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    for table_name in ("worker_profiles", "task_worker_profile_snapshots"):
        op.add_column(table_name, sa.Column("docker_host", sa.String(length=500), nullable=True))
        op.add_column(table_name, sa.Column("docker_tls_ca", sa.String(length=1024), nullable=True))
        op.add_column(
            table_name,
            sa.Column("docker_tls_cert", sa.String(length=1024), nullable=True),
        )
        op.add_column(table_name, sa.Column("docker_tls_key", sa.String(length=1024), nullable=True))

    # Empty legacy overrides disabled workspaces and are incompatible with the shared-path
    # MVP. Non-empty values are retained for startup handoff validation against the bind mount.
    op.execute(
        sa.text(
            "DELETE FROM system_config "
            "WHERE key = 'worker_workspace_host_path' AND btrim(value) = ''"
        )
    )


def downgrade() -> None:
    for table_name in ("task_worker_profile_snapshots", "worker_profiles"):
        op.drop_column(table_name, "docker_tls_key")
        op.drop_column(table_name, "docker_tls_cert")
        op.drop_column(table_name, "docker_tls_ca")
        op.drop_column(table_name, "docker_host")
