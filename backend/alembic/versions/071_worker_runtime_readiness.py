"""add worker runtime readiness records and snapshot locator fingerprints

Revision ID: 071_worker_runtime_readiness
Revises: 070_worker_shared_configuration
Create Date: 2026-08-14

Implements Phase 2 of the shared worker configuration design (§9.6, §10.3,
§13, §18). Creates the ``worker_runtime_readiness`` table keyed by runtime
locator fingerprint with generation/CAS and TTL fields, adds
``task_worker_profile_snapshots.runtime_locator_fingerprint``, and backfills
fingerprints for existing snapshots.

Backfill rules (§18.8-§18.9):

- baked-image snapshots have no mounted Kit and therefore no fingerprint;
- mounted-kit terminal snapshots that cannot be fully resolved stay NULL;
- every active (pending/queued/running) mounted-kit snapshot must backfill a
  fingerprint or the migration fails closed;
- no readiness rows are seeded: every backfilled fingerprint is ``unknown``.
"""

from __future__ import annotations

from typing import Any, Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "071_worker_runtime_readiness"
down_revision: Union[str, None] = "070_worker_shared_configuration"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_ACTIVE_TASK_STATUSES = ("pending", "queued", "running")


def upgrade() -> None:
    op.create_table(
        "worker_runtime_readiness",
        sa.Column("runtime_locator_fingerprint", sa.String(length=64), primary_key=True),
        sa.Column("docker_daemon_key", sa.String(length=500), nullable=True),
        sa.Column("runtime_mode", sa.String(length=32), nullable=True),
        sa.Column("worker_kit_version", sa.String(length=128), nullable=True),
        sa.Column("worker_kit_path", sa.String(length=1024), nullable=True),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default="unknown",
        ),
        sa.Column("failure_code", sa.String(length=64), nullable=True),
        sa.Column("failure_message", sa.Text(), nullable=True),
        sa.Column("checked_at", sa.DateTime(), nullable=True),
        sa.Column("ready_until", sa.DateTime(), nullable=True),
        sa.Column("check_generation", sa.Integer(), nullable=False, server_default=sa.text("0")),
        sa.Column("check_started_at", sa.DateTime(), nullable=True),
        sa.Column(
            "updated_at",
            sa.DateTime(),
            nullable=False,
            server_default=sa.func.now(),
        ),
    )

    op.add_column(
        "task_worker_profile_snapshots",
        sa.Column("runtime_locator_fingerprint", sa.String(length=64), nullable=True),
    )

    _backfill_snapshot_fingerprints()


def _backfill_snapshot_fingerprints() -> None:
    """Backfill snapshot locator fingerprints (§18.8)."""
    from app.config import get_effective_settings
    from app.core.worker_kit import MOUNTED_KIT_MODE
    from app.core.worker_runtime_readiness import fingerprint_from_docker_target

    settings = get_effective_settings()
    conn = op.get_bind()
    rows = conn.execute(
        sa.text(
            "SELECT s.task_id, s.runtime_mode, s.worker_kit_version, s.worker_kit_path, "
            "s.docker_host, s.docker_tls_ca, s.docker_tls_cert, s.docker_tls_key, t.status "
            "FROM task_worker_profile_snapshots s "
            "JOIN tasks t ON t.id = s.task_id"
        )
    ).fetchall()
    for (
        task_id,
        runtime_mode,
        worker_kit_version,
        worker_kit_path,
        docker_host,
        docker_tls_ca,
        docker_tls_cert,
        docker_tls_key,
        status,
    ) in rows:
        mode = (runtime_mode or "baked_image").strip()
        if mode != MOUNTED_KIT_MODE:
            continue
        is_active = (status or "") in _ACTIVE_TASK_STATUSES
        if not worker_kit_version or not worker_kit_path:
            if is_active:
                raise RuntimeError(
                    f"Active task {task_id} has an incomplete mounted-kit snapshot; "
                    "refusing to leave runtime_locator_fingerprint unbackfilled"
                )
            continue
        fingerprint = fingerprint_from_docker_target(
            settings,
            docker_host=docker_host,
            docker_tls_ca=docker_tls_ca,
            docker_tls_cert=docker_tls_cert,
            docker_tls_key=docker_tls_key,
            runtime_mode=mode,
            worker_kit_version=worker_kit_version,
            worker_kit_path=worker_kit_path,
        )
        if fingerprint is None:
            continue
        conn.execute(
            sa.text(
                "UPDATE task_worker_profile_snapshots "
                "SET runtime_locator_fingerprint = :fingerprint "
                "WHERE task_id = :task_id"
            ),
            {"fingerprint": fingerprint, "task_id": task_id},
        )


def downgrade() -> None:
    op.drop_column("task_worker_profile_snapshots", "runtime_locator_fingerprint")
    op.drop_table("worker_runtime_readiness")
