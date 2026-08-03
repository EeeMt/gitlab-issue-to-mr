"""Task API response mapping and post-commit refresh helpers."""

from typing import Any

from sqlalchemy import inspect as sa_inspect
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.skills import skill_snapshots_from_task_snapshot
from app.core.task_helpers import _serialize_task as _serialize_task_base
from app.models import Task, TaskWorkerProfileSnapshot

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
                        (snapshot.model_endpoint_snapshot or {}).get("wire_protocol")
                        if snapshot.model_endpoint_snapshot
                        else None
                    ),
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
