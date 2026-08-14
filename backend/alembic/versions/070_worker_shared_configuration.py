"""add worker shared configuration and effective-config digests

Revision ID: 070_worker_shared_configuration
Revises: 069_system_lifecycle_statistics
Create Date: 2026-08-14

Implements the worker shared configuration design (§9, §18). Creates the
``worker_shared_configurations`` singleton and ``worker_shared_environment_variables``
tables, seeds the baseline from the system default Worker Profile (§18.2), and
keeps every existing Profile fully explicit for zero behavior drift:

- ``worker_profiles.worker_kit_source`` defaults to ``profile`` (explicit);
- existing scripts/templates/mounts/environment variables stay explicit
  overrides (environment rows become ``operation=set``);
- ``volume_mount_masks`` starts empty;
- Task snapshots gain ``shared_configuration_revision`` and
  ``effective_configuration_digest``, backfilled from the frozen snapshot values
  (all pre-feature snapshots were fully explicit). Every active Task snapshot
  must backfill successfully or the migration fails closed (§18.8).
"""

from __future__ import annotations

import json
from typing import Sequence, Union

import sqlalchemy as sa

from alembic import op
from app.core.task_prompt import (
    BUILT_IN_CI_AUTO_REPAIR_RUN_INSTRUCTION_TEMPLATE,
    BUILT_IN_EXECUTE_RUN_INSTRUCTION_TEMPLATE,
    BUILT_IN_PLAN_RUN_INSTRUCTION_TEMPLATE,
)

revision: str = "070_worker_shared_configuration"
down_revision: Union[str, None] = "069_system_lifecycle_statistics"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SHARED_CONFIGURATION_ID = 1
_ACTIVE_TASK_STATUSES = ("pending", "queued", "running")


def _empty_json_array_default() -> sa.TextClause:
    if op.get_context().dialect.name == "postgresql":
        return sa.text("'[]'::json")
    return sa.text("'[]'")


def upgrade() -> None:
    op.create_table(
        "worker_shared_configurations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=False),
        sa.Column("revision", sa.Integer(), nullable=False, server_default=sa.text("1")),
        sa.Column("runtime_mode", sa.String(length=32), nullable=False, server_default="baked_image"),
        sa.Column("worker_kit_version", sa.String(length=128), nullable=True),
        sa.Column("worker_kit_path", sa.String(length=1024), nullable=True),
        sa.Column(
            "volume_mounts",
            sa.JSON(),
            nullable=False,
            server_default=_empty_json_array_default(),
        ),
        sa.Column("pre_script", sa.Text(), nullable=True),
        sa.Column("post_script", sa.Text(), nullable=True),
        sa.Column("default_execute_run_instruction_template", sa.Text(), nullable=True),
        sa.Column("default_plan_run_instruction_template", sa.Text(), nullable=True),
        sa.Column("ci_auto_repair_run_instruction_template", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )

    op.create_table(
        "worker_shared_environment_variables",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("worker_shared_configuration_id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(length=255), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("is_secret", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["worker_shared_configuration_id"],
            ["worker_shared_configurations.id"],
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "uq_worker_shared_environment_key",
        "worker_shared_environment_variables",
        ["worker_shared_configuration_id", "key"],
        unique=True,
    )
    op.create_index(
        "ix_worker_shared_environment_variables_config_id",
        "worker_shared_environment_variables",
        ["worker_shared_configuration_id"],
    )

    op.add_column(
        "worker_profiles",
        sa.Column(
            "worker_kit_source",
            sa.String(length=16),
            nullable=False,
            server_default="profile",
        ),
    )
    op.add_column(
        "worker_profiles",
        sa.Column(
            "volume_mount_masks",
            sa.JSON(),
            nullable=False,
            server_default=_empty_json_array_default(),
        ),
    )
    op.add_column(
        "worker_profiles",
        sa.Column("verified_runtime_configuration_digest", sa.String(length=64), nullable=True),
    )
    op.alter_column("worker_profiles", "pre_script", existing_type=sa.Text(), nullable=True)
    op.alter_column("worker_profiles", "post_script", existing_type=sa.Text(), nullable=True)
    op.alter_column(
        "worker_profiles",
        "default_execute_run_instruction_template",
        existing_type=sa.Text(),
        nullable=True,
    )
    op.alter_column(
        "worker_profiles",
        "default_plan_run_instruction_template",
        existing_type=sa.Text(),
        nullable=True,
    )
    op.alter_column(
        "worker_profiles",
        "ci_auto_repair_run_instruction_template",
        existing_type=sa.Text(),
        nullable=True,
    )

    op.add_column(
        "worker_profile_environment_variables",
        sa.Column(
            "operation",
            sa.String(length=16),
            nullable=False,
            server_default="set",
        ),
    )
    op.alter_column(
        "worker_profile_environment_variables",
        "value",
        existing_type=sa.Text(),
        nullable=True,
    )

    op.add_column(
        "task_worker_profile_snapshots",
        sa.Column("shared_configuration_revision", sa.Integer(), nullable=True),
    )
    op.add_column(
        "task_worker_profile_snapshots",
        sa.Column("effective_configuration_digest", sa.String(length=64), nullable=True),
    )

    _seed_shared_configuration()
    _backfill_snapshot_digests()


def _seed_shared_configuration() -> None:
    """Seed the shared configuration singleton from the default worker profile."""
    conn = op.get_bind()
    profile = conn.execute(
        sa.text(
            "SELECT id, runtime_mode, worker_kit_version, worker_kit_path, "
            "volume_mounts, pre_script, post_script, "
            "default_execute_run_instruction_template, "
            "default_plan_run_instruction_template, "
            "ci_auto_repair_run_instruction_template "
            "FROM worker_profiles WHERE is_default = true AND enabled = true "
            "ORDER BY id LIMIT 1"
        )
    ).fetchone()
    if profile is None:
        profile = conn.execute(
            sa.text(
                "SELECT id, runtime_mode, worker_kit_version, worker_kit_path, "
                "volume_mounts, pre_script, post_script, "
                "default_execute_run_instruction_template, "
                "default_plan_run_instruction_template, "
                "ci_auto_repair_run_instruction_template "
                "FROM worker_profiles WHERE enabled = true "
                "ORDER BY id LIMIT 1"
            )
        ).fetchone()
    if profile is None:
        conn.execute(
            sa.text(
                "INSERT INTO worker_shared_configurations (id, revision, runtime_mode, "
                "volume_mounts, pre_script, post_script, "
                "default_execute_run_instruction_template, "
                "default_plan_run_instruction_template, "
                "ci_auto_repair_run_instruction_template, created_at, updated_at) "
                "VALUES (:id, 1, 'baked_image', '[]'::json, '', '', "
                ":execute, :plan, :ci, now(), now())"
            ),
            {
                "id": _SHARED_CONFIGURATION_ID,
                "execute": BUILT_IN_EXECUTE_RUN_INSTRUCTION_TEMPLATE,
                "plan": BUILT_IN_PLAN_RUN_INSTRUCTION_TEMPLATE,
                "ci": BUILT_IN_CI_AUTO_REPAIR_RUN_INSTRUCTION_TEMPLATE,
            },
        )
        return
    profile_id = profile[0]
    volume_mounts = profile[4] if profile[4] is not None else []
    conn.execute(
        sa.text(
            "INSERT INTO worker_shared_configurations (id, revision, runtime_mode, "
            "worker_kit_version, worker_kit_path, volume_mounts, pre_script, post_script, "
            "default_execute_run_instruction_template, "
            "default_plan_run_instruction_template, "
            "ci_auto_repair_run_instruction_template, created_at, updated_at) "
            "VALUES (:id, 1, :runtime_mode, :kit_version, :kit_path, "
            "CAST(:volume_mounts AS json), "
            ":pre_script, :post_script, :execute, :plan, :ci, now(), now())"
        ),
        {
            "id": _SHARED_CONFIGURATION_ID,
            "runtime_mode": profile[1],
            "kit_version": profile[2],
            "kit_path": profile[3],
            "volume_mounts": json.dumps(volume_mounts),
            "pre_script": profile[5] or "",
            "post_script": profile[6] or "",
            "execute": profile[7],
            "plan": profile[8],
            "ci": profile[9],
        },
    )
    conn.execute(
        sa.text(
            "INSERT INTO worker_shared_environment_variables "
            "(worker_shared_configuration_id, key, value, is_secret, created_at, updated_at) "
            "SELECT :config_id, key, value, is_secret, now(), now() "
            "FROM worker_profile_environment_variables WHERE worker_profile_id = :profile_id"
        ),
        {"config_id": _SHARED_CONFIGURATION_ID, "profile_id": profile_id},
    )


def _backfill_snapshot_digests() -> None:
    """Backfill snapshot digests from the frozen snapshot values (§18.8)."""
    from app.core.worker_shared_configuration import compute_effective_configuration_digest

    conn = op.get_bind()
    rows = conn.execute(
        sa.text(
            "SELECT s.task_id, s.image, s.runtime_mode, s.worker_kit_version, "
            "s.worker_kit_path, s.volume_mounts, s.environment_variables, "
            "s.pre_script, s.post_script, "
            "s.default_execute_run_instruction_template, "
            "s.default_plan_run_instruction_template, "
            "s.ci_auto_repair_run_instruction_template, t.status "
            "FROM task_worker_profile_snapshots s "
            "JOIN tasks t ON t.id = s.task_id"
        )
    ).fetchall()
    for row in rows:
        status = row[12] or ""
        is_active = status in _ACTIVE_TASK_STATUSES
        required = (
            row[1],
            row[2],
            row[9],
            row[10],
            row[11],
        )
        if any(value is None or value == "" for value in required):
            if is_active:
                raise RuntimeError(
                    f"Active task {row[0]} has an incomplete worker snapshot; refusing to "
                    "leave effective_configuration_digest unbackfilled"
                )
            continue
        digest = compute_effective_configuration_digest(
            image=row[1],
            runtime_mode=row[2],
            worker_kit_version=row[3],
            worker_kit_path=row[4],
            volume_mounts=row[5] or [],
            environment_variables=row[6] or [],
            pre_script=row[7] or "",
            post_script=row[8] or "",
            default_execute_run_instruction_template=row[9],
            default_plan_run_instruction_template=row[10],
            ci_auto_repair_run_instruction_template=row[11],
        )
        conn.execute(
            sa.text(
                "UPDATE task_worker_profile_snapshots "
                "SET effective_configuration_digest = :digest, "
                "shared_configuration_revision = :revision "
                "WHERE task_id = :task_id"
            ),
            {"digest": digest, "revision": _SHARED_CONFIGURATION_ID, "task_id": row[0]},
        )


def downgrade() -> None:
    op.drop_column("task_worker_profile_snapshots", "effective_configuration_digest")
    op.drop_column("task_worker_profile_snapshots", "shared_configuration_revision")
    op.alter_column(
        "worker_profile_environment_variables",
        "value",
        existing_type=sa.Text(),
        nullable=False,
    )
    op.drop_column("worker_profile_environment_variables", "operation")
    op.alter_column(
        "worker_profiles",
        "ci_auto_repair_run_instruction_template",
        existing_type=sa.Text(),
        nullable=False,
    )
    op.alter_column(
        "worker_profiles",
        "default_plan_run_instruction_template",
        existing_type=sa.Text(),
        nullable=False,
    )
    op.alter_column(
        "worker_profiles",
        "default_execute_run_instruction_template",
        existing_type=sa.Text(),
        nullable=False,
    )
    op.alter_column("worker_profiles", "post_script", existing_type=sa.Text(), nullable=False)
    op.alter_column("worker_profiles", "pre_script", existing_type=sa.Text(), nullable=False)
    op.drop_column("worker_profiles", "verified_runtime_configuration_digest")
    op.drop_column("worker_profiles", "volume_mount_masks")
    op.drop_column("worker_profiles", "worker_kit_source")
    op.drop_index(
        "ix_worker_shared_environment_variables_config_id",
        table_name="worker_shared_environment_variables",
    )
    op.drop_index(
        "uq_worker_shared_environment_key",
        table_name="worker_shared_environment_variables",
    )
    op.drop_table("worker_shared_environment_variables")
    op.drop_table("worker_shared_configurations")
