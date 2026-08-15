"""materialize per-item shared inheritance masks for zero drift

Revision ID: 072_shared_per_item_inheritance
Revises: 071_worker_runtime_readiness
Create Date: 2026-08-15

Implements F1 per-item inheritance (§7.2/§7.3). Before this change a fully
explicit Profile (kit source ``profile``, every script/template set, no mount
masks, no ``mask`` environment rows) resolved without the shared baseline, so
shared environment variables and volume mounts never leaked into it. F1 always
merges the shared baseline per-item, so without compensation those Profiles
would silently gain shared env/mounts after upgrade.

For zero drift this migration materializes explicit masks on every such
Profile: one ``operation='mask'`` environment row per shared key the Profile
does not override, and one ``volume_mount_masks`` entry per shared mount path
the Profile does not override. After the migration the resolved effective
configuration is byte-for-byte identical to before, and the Profile's per-item
inheritance posture is persisted as explicit mask rows/mount masks so the UI can
render 跟随系统/覆盖/屏蔽 per item. Profiles that already merged
shared (``worker_kit_source=system``, NULL scalars, existing masks) are
untouched because they already resolved against the shared baseline.
"""

from __future__ import annotations

import json
import os
from typing import Any, Sequence, Union

import sqlalchemy as sa

from alembic import op

revision: str = "072_shared_per_item_inheritance"
down_revision: Union[str, None] = "071_worker_runtime_readiness"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_SCALARS = (
    "pre_script",
    "post_script",
    "default_execute_run_instruction_template",
    "default_plan_run_instruction_template",
    "ci_auto_repair_run_instruction_template",
)


def _norm_path(path: Any) -> str:
    return os.path.normpath(str(path or "").strip())


def _load_list(value: Any) -> list[Any]:
    if value is None:
        return []
    if isinstance(value, str):
        if not value.strip():
            return []
        try:
            value = json.loads(value)
        except json.JSONDecodeError:
            return []
    return list(value or [])


def _is_fully_explicit(
    conn,
    *,
    profile_id: int,
    kit_source: Any,
    scalars: tuple[Any, ...],
    volume_mount_masks: Any,
) -> bool:
    """Replicate the pre-F1 ``profile_inherits_shared`` gate (returns True gate).

    A profile that returned ``False`` for the gate (fully explicit) is the only
    one whose effective configuration changes under F1 and therefore needs
    compensation masks.
    """
    if kit_source != "profile":
        return False
    if any(value is None for value in scalars):
        return False
    if _load_list(volume_mount_masks):
        return False
    has_mask_row = conn.execute(
        sa.text(
            "SELECT 1 FROM worker_profile_environment_variables "
            "WHERE worker_profile_id = :pid AND operation = 'mask' LIMIT 1"
        ),
        {"pid": profile_id},
    ).fetchone()
    return has_mask_row is None


def upgrade() -> None:
    conn = op.get_bind()
    shared = conn.execute(
        sa.text("SELECT volume_mounts FROM worker_shared_configurations WHERE id = 1")
    ).fetchone()
    if shared is None:
        # No shared baseline exists: nothing can be inherited, so there is no
        # drift to compensate for.
        return

    shared_mount_paths = sorted(
        {
            _norm_path(mount.get("container_path"))
            for mount in _load_list(shared[0])
            if _norm_path(mount.get("container_path"))
        }
    )
    shared_env_keys = sorted(
        row[0]
        for row in conn.execute(
            sa.text(
                "SELECT key FROM worker_shared_environment_variables "
                "WHERE worker_shared_configuration_id = 1 ORDER BY key"
            )
        ).fetchall()
    )

    rows = conn.execute(
        sa.text(
            "SELECT id, worker_kit_source, pre_script, post_script, "
            "default_execute_run_instruction_template, "
            "default_plan_run_instruction_template, "
            "ci_auto_repair_run_instruction_template, "
            "volume_mounts, volume_mount_masks "
            "FROM worker_profiles ORDER BY id"
        )
    ).fetchall()

    for row in rows:
        (
            profile_id,
            kit_source,
            pre_script,
            post_script,
            execute_template,
            plan_template,
            ci_template,
            volume_mounts,
            volume_mount_masks,
        ) = row
        scalars = (
            pre_script,
            post_script,
            execute_template,
            plan_template,
            ci_template,
        )
        if not _is_fully_explicit(
            conn,
            profile_id=profile_id,
            kit_source=kit_source,
            scalars=scalars,
            volume_mount_masks=volume_mount_masks,
        ):
            continue

        profile_mount_paths = {
            _norm_path(mount.get("container_path"))
            for mount in _load_list(volume_mounts)
            if _norm_path(mount.get("container_path"))
        }
        added_masks = sorted(set(shared_mount_paths) - profile_mount_paths)
        if added_masks:
            conn.execute(
                sa.text(
                    "UPDATE worker_profiles SET volume_mount_masks = CAST(:masks AS json) "
                    "WHERE id = :pid"
                ),
                {"masks": json.dumps(added_masks), "pid": profile_id},
            )

        for key in shared_env_keys:
            owned = conn.execute(
                sa.text(
                    "SELECT 1 FROM worker_profile_environment_variables "
                    "WHERE worker_profile_id = :pid AND key = :key LIMIT 1"
                ),
                {"pid": profile_id, "key": key},
            ).fetchone()
            if owned is None:
                conn.execute(
                    sa.text(
                        "INSERT INTO worker_profile_environment_variables "
                        "(worker_profile_id, key, value, is_secret, operation, "
                        "created_at, updated_at) "
                        "VALUES (:pid, :key, NULL, false, 'mask', now(), now())"
                    ),
                    {"pid": profile_id, "key": key},
                )


def downgrade() -> None:
    """Remove the per-item inheritance compensation masks.

    The pre-F1 (069) schema has no ``operation`` column and a ``NOT NULL``
    ``value``, so an ``operation='mask'`` row (always stored with a NULL value)
    cannot be represented below 070 at all — and the whole-Profile gate the
    downgraded code restores ignores masks. Deleting every mask row is the only
    representation-preserving choice: it keeps 070's downgrade (which restores
    ``value NOT NULL``) from failing on the NULL mask values, so a single-pass
    head→069 downgrade succeeds. Mask intent is inherently unrecoverable when
    downgrading past the revision that introduced it, which is the expected cost
    of reverting a data-model change.
    """
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "DELETE FROM worker_profile_environment_variables WHERE operation = 'mask'"
        )
    )
