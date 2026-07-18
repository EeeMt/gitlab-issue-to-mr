"""Lazy task runtime summary endpoints for the task detail popovers."""

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload, undefer

from app.api.task_responses import loaded_task_relationship
from app.core.worker_kit import MOUNTED_KIT_MODE, worker_kit_mounts
from app.database import get_db
from app.dependencies.project_access import (
    ProjectAccessScope,
    require_project_access,
    require_project_access_scope,
)
from app.models import Task

router = APIRouter()


async def _get_task_for_runtime_summary(
    task_id: int,
    db: AsyncSession,
    access_scope: ProjectAccessScope,
    *load_options: Any,
) -> Task:
    """Load one runtime relationship after enforcing task project access."""
    result = await db.execute(
        select(Task)
        .options(*load_options)
        .where(Task.id == task_id)
    )
    task = result.scalar_one_or_none()
    if task is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task {task_id} not found",
        )
    require_project_access(task.project_id, access_scope)
    return task


def serialize_model_service_summary(task: Task) -> dict[str, Any]:
    """Serialize the execution snapshot, falling back to current provider config."""
    runtime_snapshot = getattr(task, "provider_runtime_snapshot", None)
    if isinstance(runtime_snapshot, dict):
        return {
            "configuration_source": "execution_snapshot",
            "provider_config_available": True,
            "provider_id": runtime_snapshot.get("provider_id"),
            "provider_name": runtime_snapshot.get("provider_name"),
            "base_url": runtime_snapshot.get("base_url"),
            "configured_model": runtime_snapshot.get("configured_model"),
            "actual_model": getattr(task, "model_name", None),
            "max_turns": runtime_snapshot.get("max_turns"),
            "system_prompt": runtime_snapshot.get("system_prompt"),
            "api_key_configured": bool(runtime_snapshot.get("api_key_configured")),
            "configuration_captured_at": runtime_snapshot.get("captured_at"),
        }

    provider = loaded_task_relationship(task, "provider")
    return {
        "configuration_source": (
            "current_provider" if provider is not None else "unavailable"
        ),
        "provider_config_available": provider is not None,
        "provider_id": getattr(task, "provider_id", None),
        "provider_name": provider.name if provider is not None else None,
        "base_url": provider.base_url if provider is not None else None,
        "configured_model": provider.model if provider is not None else None,
        "actual_model": getattr(task, "model_name", None),
        "max_turns": provider.max_turns if provider is not None else None,
        "system_prompt": provider.system_prompt if provider is not None else None,
        "api_key_configured": bool(provider and provider.api_key),
        "configuration_captured_at": None,
    }


def _snapshot_value(row: Any, key: str) -> Any:
    if isinstance(row, dict):
        return row.get(key)
    return getattr(row, key, None)


def _serialize_worker_mounts(snapshot: Any) -> list[dict[str, str]]:
    mounts: list[dict[str, str]] = []
    runtime_mode = getattr(snapshot, "runtime_mode", None)
    worker_kit_path = getattr(snapshot, "worker_kit_path", None)
    if runtime_mode == MOUNTED_KIT_MODE and worker_kit_path:
        for host_path, config in worker_kit_mounts(worker_kit_path).items():
            mounts.append(
                {
                    "source": "worker_kit",
                    "host_path": host_path,
                    "container_path": config["bind"],
                    "mode": config["mode"],
                }
            )

    for row in getattr(snapshot, "volume_mounts", None) or []:
        host_path = str(_snapshot_value(row, "host_path") or "").strip()
        container_path = str(_snapshot_value(row, "container_path") or "").strip()
        if not host_path or not container_path:
            continue
        mounts.append(
            {
                "source": "profile",
                "host_path": host_path,
                "container_path": container_path,
                "mode": str(_snapshot_value(row, "mode") or "rw"),
            }
        )
    return mounts


def _serialize_worker_environment(snapshot: Any) -> list[dict[str, Any]]:
    variables: list[dict[str, Any]] = []
    for row in getattr(snapshot, "environment_variables", None) or []:
        key = str(_snapshot_value(row, "key") or "").strip()
        if not key:
            continue
        value = _snapshot_value(row, "value")
        variables.append(
            {
                "key": key,
                "is_secret": bool(_snapshot_value(row, "is_secret")),
                "value_configured": value is not None and str(value) != "",
            }
        )
    return variables


def serialize_worker_runtime_summary(task: Task) -> dict[str, Any]:
    """Serialize the immutable worker snapshot without Docker credentials or values."""
    snapshot = loaded_task_relationship(task, "worker_profile_snapshot")
    if snapshot is None:
        return {
            "snapshot_available": False,
            "worker_profile_id": getattr(task, "worker_profile_id", None),
            "worker_profile_name": None,
            "image": None,
            "runtime_mode": None,
            "worker_kit_version": None,
            "worker_kit_path": None,
            "codegraph_enabled": False,
            "mounts": [],
            "environment_variables": [],
            "pre_script_configured": False,
            "post_script_configured": False,
            "snapshot_created_at": None,
        }

    return {
        "snapshot_available": True,
        "worker_profile_id": snapshot.worker_profile_id,
        "worker_profile_name": snapshot.profile_name,
        "image": snapshot.image,
        "runtime_mode": snapshot.runtime_mode,
        "worker_kit_version": snapshot.worker_kit_version,
        "worker_kit_path": snapshot.worker_kit_path,
        "codegraph_enabled": bool(snapshot.codegraph_enabled),
        "mounts": _serialize_worker_mounts(snapshot),
        "environment_variables": _serialize_worker_environment(snapshot),
        "pre_script_configured": bool((snapshot.pre_script or "").strip()),
        "post_script_configured": bool((snapshot.post_script or "").strip()),
        "snapshot_created_at": (
            snapshot.created_at.isoformat() if snapshot.created_at else None
        ),
    }


@router.get("/tasks/{task_id}/model-service-summary")
async def get_task_model_service_summary(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    access_scope: ProjectAccessScope = Depends(require_project_access_scope),
):
    """Return model-service details only when the user opens its popover."""
    task = await _get_task_for_runtime_summary(
        task_id,
        db,
        access_scope,
        undefer(Task.provider_runtime_snapshot),
        selectinload(Task.provider),
    )
    return serialize_model_service_summary(task)


@router.get("/tasks/{task_id}/worker-runtime-summary")
async def get_task_worker_runtime_summary(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    access_scope: ProjectAccessScope = Depends(require_project_access_scope),
):
    """Return the immutable worker runtime snapshot for its detail popover."""
    task = await _get_task_for_runtime_summary(
        task_id,
        db,
        access_scope,
        selectinload(Task.worker_profile_snapshot),
    )
    return serialize_worker_runtime_summary(task)
