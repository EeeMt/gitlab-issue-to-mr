"""Task API response mapping and post-commit refresh helpers."""

from typing import Any

from sqlalchemy import inspect as sa_inspect
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_effective_settings
from app.core.harness_protocol import HARNESS_CONTRACT_VERSION_V2
from app.core.skills import skill_snapshots_from_task_snapshot
from app.core.task_helpers import _serialize_task as _serialize_task_base
from app.models import Task, TaskWorkerProfileSnapshot, User

TASK_RESPONSE_REFRESH_ATTRIBUTES = ["id", "status", "created_at", "updated_at"]
SNAPSHOT_RESPONSE_REFRESH_ATTRIBUTES = [
    "task_id",
    "worker_profile_id",
    "profile_name",
    "image",
    "runtime_mode",
    "worker_kit_version",
    "skill_selection_source",
    "created_at",
]


def loaded_task_relationship(task: Task, name: str) -> Any | None:
    """Return an already-loaded relationship without triggering async lazy IO."""
    try:
        inspection = sa_inspect(task)
        if name in inspection.unloaded:
            return None
    except Exception:
        pass
    value = getattr(task, name, None)
    if value.__class__.__module__.startswith("unittest.mock"):
        return None
    return value


def _snapshot_harness_options(snapshot: Any) -> dict[str, Any]:
    """Return only the selected harness's non-secret frozen options."""
    config = getattr(snapshot, "harness_config_snapshot", None)
    options = config.get("options") if isinstance(config, dict) else None
    harness_key = getattr(snapshot, "harness_key", None)
    selected = options.get(harness_key) if isinstance(options, dict) else None
    return dict(selected) if isinstance(selected, dict) else {}


async def compute_task_queue_contexts(
    db: AsyncSession,
    tasks: list[Task],
) -> dict[int, dict[str, Any]]:
    """Batch queue context keyed by task_id for a set of Tasks (no per-task N+1).

    Queue context is computed once per distinct Issue, then flattened by task_id.
    Tasks whose Issue is not loaded are skipped; the caller can fall back to
    per-issue computation when it already holds the rows.
    """
    from app.core.issue_task_order import compute_queue_context

    contexts: dict[int, dict[str, Any]] = {}
    issue_ids = sorted({t.issue_id for t in tasks if t.issue_id is not None})
    for issue_id in issue_ids:
        contexts.update(await compute_queue_context(db, issue_id=issue_id))
    return contexts


def apply_queue_context(
    data: dict[str, Any],
    task_id: int,
    contexts: dict[int, dict[str, Any]],
    current_user: User | None = None,
) -> dict[str, Any]:
    """Merge per-task queue context fields into a serialized Task dict."""
    ctx = contexts.get(task_id) or {}
    data["queue_position"] = ctx.get("queue_position")
    data["blocked_by_task_id"] = ctx.get("blocked_by_task_id")
    data["waiting_reason"] = ctx.get("waiting_reason")
    data["lock_owner_task_id"] = ctx.get("lock_owner_task_id")
    data["waiting_since"] = ctx.get("waiting_since")
    data["runtime_failure_code"] = ctx.get("runtime_failure_code")
    data["runtime_failure_message"] = ctx.get("runtime_failure_message")
    data["runtime_checked_at"] = ctx.get("runtime_checked_at")
    # §13.3/F4: the locator fingerprint exposes the daemon host/TLS identity of
    # the frozen worker snapshot, so it is restricted to platform admins. A
    # caller that does not resolve an admin user (anonymous, non-admin, or an
    # unresolved dependency in direct-call contexts) fails closed to non-admin.
    if getattr(current_user, "platform_role", None) == "platform_admin":
        data["runtime_locator_fingerprint"] = ctx.get("runtime_locator_fingerprint")
    return data


def serialize_task(*args, **kwargs) -> dict:
    """Serialize a task with immutable worker snapshot display metadata."""
    task = args[0] if args else kwargs["task"]
    data = _serialize_task_base(*args, **kwargs)
    snapshot = loaded_task_relationship(task, "worker_profile_snapshot")
    worker_profile = loaded_task_relationship(task, "worker_profile")
    worker_profile_id = getattr(task, "worker_profile_id", None)
    if not isinstance(worker_profile_id, int):
        worker_profile_id = None
    skill_snapshots: list[dict[str, Any]] | None = []
    if snapshot is not None:
        try:
            if "skill_references" in sa_inspect(snapshot).unloaded:
                skill_snapshots = None
            else:
                skill_snapshots = skill_snapshots_from_task_snapshot(snapshot)
        except Exception:
            skill_snapshots = skill_snapshots_from_task_snapshot(snapshot)
    runtime_contract_version = (
        getattr(snapshot, "runtime_contract_version", None) if snapshot is not None else None
    )
    legacy_contract = runtime_contract_version != HARNESS_CONTRACT_VERSION_V2
    execution_mode = get_effective_settings().harness_execution_mode
    execution_read_only = legacy_contract and (
        execution_mode == "v2_only" or runtime_contract_version is None
    )
    data.update(
        {
            "worker_profile_id": worker_profile_id,
            "worker_profile_name": (
                snapshot.profile_name
                if snapshot is not None
                else (worker_profile.name if worker_profile is not None else None)
            ),
            "worker_image": snapshot.image if snapshot is not None else None,
            "worker_runtime_mode": (
                getattr(snapshot, "runtime_mode", None) if snapshot is not None else None
            ),
            "worker_kit_version": (
                getattr(snapshot, "worker_kit_version", None) if snapshot is not None else None
            ),
            "worker_snapshot_created_at": (
                snapshot.created_at.isoformat()
                if snapshot is not None and snapshot.created_at
                else None
            ),
            "skill_selection_source": (
                getattr(snapshot, "skill_selection_source", "profile")
                if snapshot is not None
                else "profile"
            ),
            "harness_key": getattr(snapshot, "harness_key", None) if snapshot is not None else None,
            "execution_contract": {
                "contract_version": runtime_contract_version,
                "legacy": legacy_contract,
                "read_only": execution_read_only,
                "reason": (
                    "legacy_contract_not_executable" if execution_read_only else None
                ),
            },
            "harness_snapshot": (
                {
                    "harness_adapter_version": snapshot.harness_adapter_version,
                    "harness_adapter_digest": snapshot.harness_adapter_digest,
                    "cli_source": snapshot.cli_source,
                    "cli_executable_path": snapshot.cli_executable_path,
                    "cli_version": snapshot.cli_version,
                    "cli_binary_digest": snapshot.cli_binary_digest,
                    "image_digest": snapshot.image_digest,
                    "runtime_bundle_digest": snapshot.runtime_bundle_digest,
                    "endpoint_protocol": (
                        (snapshot.model_endpoint_snapshot or {}).get("model_protocol")
                        # Pre-074 snapshots stored the pre-rename key; fall back
                        # so historical V1 reads keep returning the original value.
                        or (snapshot.model_endpoint_snapshot or {}).get("wire_protocol")
                        if snapshot.model_endpoint_snapshot
                        else None
                    ),
                    "harness_options": _snapshot_harness_options(snapshot),
                }
                if snapshot is not None
                else None
            ),
        }
    )
    if skill_snapshots is not None:
        data.update(
            {
                "skill_ids": [
                    item.get("id")
                    for item in skill_snapshots
                    if isinstance(item, dict) and isinstance(item.get("id"), int)
                ],
                "skill_names": [
                    str(item.get("name"))
                    for item in skill_snapshots
                    if isinstance(item, dict) and item.get("name")
                ],
                "skill_snapshots": skill_snapshots,
            }
        )
    return data


def attach_task_worker_snapshot(
    task: Task,
    snapshot: TaskWorkerProfileSnapshot | None,
) -> None:
    """Keep snapshot metadata available for immediate API serialization."""
    if snapshot is not None:
        task.worker_profile_snapshot = snapshot


async def refresh_task_response_state(
    db: AsyncSession,
    task: Task,
    snapshot: TaskWorkerProfileSnapshot | None,
) -> None:
    """Refresh only response fields that may be assigned by the database."""
    await db.refresh(task, attribute_names=TASK_RESPONSE_REFRESH_ATTRIBUTES)
    if isinstance(snapshot, TaskWorkerProfileSnapshot):
        await db.refresh(
            snapshot,
            attribute_names=SNAPSHOT_RESPONSE_REFRESH_ATTRIBUTES,
        )
