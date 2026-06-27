"""Worker profile validation, default resolution, and task snapshots."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.config_crypto import decrypt_config_secret
from app.core.task_prompt import (
    TaskPromptValidationError,
    validate_run_instruction_template,
)
from app.core.worker_environment_variables import (
    serialize_worker_environment_variable_value,
    validate_worker_environment_variable_key,
)
from app.models import (
    AIProvider,
    Issue,
    Task,
    TaskWorkerProfileSnapshot,
    WorkerProfile,
    WorkerProfileEnvironmentVariable,
)


class WorkerProfileValidationError(ValueError):
    """Raised when a worker profile payload is invalid."""


@dataclass(frozen=True)
class TaskWorkerRuntime:
    """Resolved task worker runtime loaded from a task snapshot."""

    image: str
    codegraph_enabled: bool
    volume_mounts: list[dict[str, str]]
    environment: dict[str, str]
    pre_script: str
    post_script: str


def _profile_value(item: Any, field: str, default: Any = None) -> Any:
    if isinstance(item, Mapping):
        return item.get(field, default)
    return getattr(item, field, default)


def _validate_environment_key(key: str) -> str:
    if len(key) > 255:
        raise WorkerProfileValidationError(
            "Worker environment variable keys must be 255 characters or fewer"
        )
    try:
        return validate_worker_environment_variable_key(key)
    except ValueError as exc:
        raise WorkerProfileValidationError(str(exc)) from exc


def validate_worker_profile_mounts(raw_mounts: Any) -> list[dict[str, str]]:
    """Validate and normalize worker profile mount entries."""
    if raw_mounts in (None, ""):
        return []
    if not isinstance(raw_mounts, list):
        raise WorkerProfileValidationError("volume_mounts must be a list")

    normalized: list[dict[str, str]] = []
    seen_container_paths: set[str] = set()
    for mount in raw_mounts:
        if not isinstance(mount, Mapping):
            raise WorkerProfileValidationError("volume mount entries must be objects")
        host_path = str(mount.get("host_path") or "").strip()
        container_path = str(mount.get("container_path") or "").strip()
        mode = str(mount.get("mode") or "ro").strip().lower()
        if not host_path or not container_path:
            raise WorkerProfileValidationError(
                "volume mounts require host_path and container_path"
            )
        if mode not in {"ro", "rw"}:
            raise WorkerProfileValidationError("volume mount mode must be ro or rw")
        if container_path in seen_container_paths:
            raise WorkerProfileValidationError(
                f"duplicate container mount path: {container_path}"
            )
        seen_container_paths.add(container_path)
        normalized.append(
            {"host_path": host_path, "container_path": container_path, "mode": mode}
        )
    return normalized


def parse_worker_profile_mounts(value: Any) -> list[dict[str, str]]:
    """Parse legacy JSON string or JSON list profile mounts."""
    if isinstance(value, str):
        if not value.strip():
            return []
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise WorkerProfileValidationError("volume_mounts must be valid JSON") from exc
    return validate_worker_profile_mounts(value)


def validate_profile_templates(
    *,
    execute_template: str,
    plan_template: str,
    ci_template: str,
) -> tuple[str, str, str]:
    """Validate and normalize the three worker run-instruction templates."""
    try:
        return (
            validate_run_instruction_template(execute_template),
            validate_run_instruction_template(plan_template),
            validate_run_instruction_template(ci_template),
        )
    except TaskPromptValidationError as exc:
        raise WorkerProfileValidationError(str(exc)) from exc


def serialize_profile_environment_variable_for_api(
    row: WorkerProfileEnvironmentVariable,
) -> dict[str, Any]:
    """Serialize one profile env var without leaking secret values."""
    return {
        "id": row.id,
        "key": row.key,
        "value": None if row.is_secret else row.value,
        "is_secret": row.is_secret,
        "value_configured": row.value is not None,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def serialize_worker_profile_for_api(profile: WorkerProfile) -> dict[str, Any]:
    """Serialize one worker profile for API responses."""
    return {
        "id": profile.id,
        "name": profile.name,
        "description": profile.description,
        "enabled": profile.enabled,
        "is_default": profile.is_default,
        "image": profile.image,
        "codegraph_enabled": bool(getattr(profile, "codegraph_enabled", False)),
        "volume_mounts": profile.volume_mounts or [],
        "environment_variables": [
            serialize_profile_environment_variable_for_api(row)
            for row in profile.environment_variables
        ],
        "pre_script": profile.pre_script,
        "post_script": profile.post_script,
        "default_execute_run_instruction_template": (
            profile.default_execute_run_instruction_template
        ),
        "default_plan_run_instruction_template": profile.default_plan_run_instruction_template,
        "ci_auto_repair_run_instruction_template": (
            profile.ci_auto_repair_run_instruction_template
        ),
        "created_at": profile.created_at,
        "updated_at": profile.updated_at,
    }


def _profile_env_to_snapshot(row: WorkerProfileEnvironmentVariable) -> dict[str, Any]:
    return {
        "key": row.key,
        "value": row.value,
        "is_secret": row.is_secret,
    }


def build_worker_profile_environment_map(rows: Iterable[Mapping[str, Any]]) -> dict[str, str]:
    """Build runtime env from snapshot environment rows."""
    env: dict[str, str] = {}
    for row in rows:
        key = _validate_environment_key(str(row["key"]))
        value = str(row.get("value") or "")
        is_secret = bool(row.get("is_secret"))
        if not is_secret:
            env[key] = value
            continue
        try:
            env[key] = decrypt_config_secret(value)
        except Exception as exc:
            raise WorkerProfileValidationError(
                f"Unable to decrypt worker environment variable {key}"
            ) from exc
    return env


async def list_worker_profiles(db: AsyncSession) -> list[WorkerProfile]:
    """Load all worker profiles for management screens."""
    result = await db.execute(
        select(WorkerProfile)
        .options(selectinload(WorkerProfile.environment_variables))
        .order_by(WorkerProfile.is_default.desc(), WorkerProfile.name.asc())
    )
    return list(result.scalars().all())


async def get_default_worker_profile(db: AsyncSession) -> WorkerProfile | None:
    result = await db.execute(
        select(WorkerProfile)
        .where(WorkerProfile.is_default == True, WorkerProfile.enabled == True)
        .options(selectinload(WorkerProfile.environment_variables))
        .execution_options(populate_existing=True)
        .limit(1)
    )
    return result.scalar_one_or_none()


async def get_default_provider(db: AsyncSession) -> AIProvider | None:
    result = await db.execute(
        select(AIProvider)
        .where(AIProvider.is_default == True, AIProvider.is_disabled == False)
        .limit(1)
    )
    return result.scalar_one_or_none()


async def resolve_worker_profile_for_issue(
    db: AsyncSession,
    issue: Issue,
    explicit_worker_profile_id: int | None = None,
    *,
    allow_system_default: bool = True,
) -> WorkerProfile:
    """Resolve explicit, issue default, then system default worker profile."""
    candidate_id = explicit_worker_profile_id or getattr(issue, "default_worker_profile_id", None)
    profile: WorkerProfile | None = None
    if candidate_id is not None:
        result = await db.execute(
            select(WorkerProfile)
            .where(WorkerProfile.id == candidate_id)
            .options(selectinload(WorkerProfile.environment_variables))
            .execution_options(populate_existing=True)
        )
        profile = result.scalar_one_or_none()
    elif allow_system_default:
        profile = await get_default_worker_profile(db)

    if profile is None:
        raise WorkerProfileValidationError("No worker profile is configured for this issue")
    if not profile.enabled:
        raise WorkerProfileValidationError(f"Worker profile '{profile.name}' is disabled")
    return profile


async def resolve_provider_for_issue(
    db: AsyncSession,
    issue: Issue,
    explicit_provider_id: int | None = None,
    *,
    allow_system_default: bool = True,
) -> AIProvider:
    """Resolve explicit, issue default, then system default provider."""
    candidate_id = (
        explicit_provider_id
        if explicit_provider_id is not None
        else getattr(issue, "default_provider_id", None)
    )
    if candidate_id is not None:
        provider = await db.get(AIProvider, candidate_id)
        if provider is None:
            raise WorkerProfileValidationError(
                f"configured AI provider {candidate_id} not found"
            )
    elif allow_system_default:
        provider = await get_default_provider(db)
    else:
        provider = None
    if provider is None:
        raise WorkerProfileValidationError("No enabled AI provider is configured for this issue")
    if provider.is_disabled:
        raise WorkerProfileValidationError(f"AI provider '{provider.name}' is disabled")
    return provider


def snapshot_from_profile(task: Task, profile: WorkerProfile) -> TaskWorkerProfileSnapshot:
    """Build an immutable task worker snapshot from a loaded profile."""
    return TaskWorkerProfileSnapshot(
        task_id=task.id,
        worker_profile_id=profile.id,
        profile_name=profile.name,
        image=profile.image,
        codegraph_enabled=bool(getattr(profile, "codegraph_enabled", False)),
        volume_mounts=list(profile.volume_mounts or []),
        environment_variables=[
            _profile_env_to_snapshot(row) for row in profile.environment_variables
        ],
        pre_script=profile.pre_script or "",
        post_script=profile.post_script or "",
        default_execute_run_instruction_template=profile.default_execute_run_instruction_template,
        default_plan_run_instruction_template=profile.default_plan_run_instruction_template,
        ci_auto_repair_run_instruction_template=profile.ci_auto_repair_run_instruction_template,
    )


async def replace_task_worker_snapshot(
    db: AsyncSession,
    task: Task,
    profile: WorkerProfile,
) -> TaskWorkerProfileSnapshot:
    """Replace one task's worker profile snapshot."""
    existing = await db.get(TaskWorkerProfileSnapshot, task.id)
    if existing is not None:
        await db.delete(existing)
        await db.flush()
    snapshot = snapshot_from_profile(task, profile)
    db.add(snapshot)
    task.worker_profile_id = profile.id
    await db.flush()
    return snapshot


def select_snapshot_run_instruction_template(
    snapshot: TaskWorkerProfileSnapshot,
    *,
    task_mode: str,
    trigger_source: str = "manual",
) -> str:
    """Select the validated run-instruction template from a task snapshot."""
    if trigger_source == "ci_auto_repair":
        return validate_run_instruction_template(snapshot.ci_auto_repair_run_instruction_template)
    if task_mode == "plan":
        return validate_run_instruction_template(snapshot.default_plan_run_instruction_template)
    return validate_run_instruction_template(snapshot.default_execute_run_instruction_template)


async def load_task_worker_runtime(db: AsyncSession, task: Task) -> TaskWorkerRuntime:
    """Load the immutable runtime fields used by worker execution."""
    snapshot = await db.get(TaskWorkerProfileSnapshot, task.id)
    if snapshot is None:
        raise WorkerProfileValidationError(f"Task {task.id} has no worker profile snapshot")
    return TaskWorkerRuntime(
        image=snapshot.image,
        codegraph_enabled=bool(getattr(snapshot, "codegraph_enabled", False)),
        volume_mounts=parse_worker_profile_mounts(snapshot.volume_mounts),
        environment=build_worker_profile_environment_map(snapshot.environment_variables),
        pre_script=snapshot.pre_script or "",
        post_script=snapshot.post_script or "",
    )


async def replace_profile_environment_variables(
    db: AsyncSession,
    profile: WorkerProfile,
    items: Iterable[Any],
) -> None:
    """Replace all environment variables for one worker profile."""
    result = await db.execute(
        select(WorkerProfileEnvironmentVariable).where(
            WorkerProfileEnvironmentVariable.worker_profile_id == profile.id
        )
    )
    existing_rows = list(result.scalars().all())
    existing_by_key = {row.key: row for row in existing_rows}
    seen_keys: set[str] = set()

    for item in items:
        key = _validate_environment_key(str(_profile_value(item, "key") or "").strip())
        if key in seen_keys:
            raise WorkerProfileValidationError(
                f"Duplicate worker environment variable key: {key}"
            )
        seen_keys.add(key)

        value = str(_profile_value(item, "value", "") or "")
        is_secret = bool(_profile_value(item, "is_secret", False))
        existing_row = existing_by_key.get(key)

        if is_secret and value == "":
            if existing_row is None or not existing_row.is_secret:
                raise WorkerProfileValidationError(
                    f"New secret worker environment variable {key} cannot use a blank value"
                )
            stored_value = existing_row.value
        else:
            stored_value = serialize_worker_environment_variable_value(
                value,
                is_secret=is_secret,
            )

        if existing_row is None:
            db.add(
                WorkerProfileEnvironmentVariable(
                    worker_profile_id=profile.id,
                    key=key,
                    value=stored_value,
                    is_secret=is_secret,
                )
            )
        else:
            existing_row.value = stored_value
            existing_row.is_secret = is_secret

    for row in existing_rows:
        if row.key not in seen_keys:
            await db.delete(row)

    await db.flush()


async def set_default_worker_profile(db: AsyncSession, profile: WorkerProfile) -> None:
    """Mark one enabled worker profile as default and unset all others."""
    if not profile.enabled:
        raise WorkerProfileValidationError("Disabled worker profiles cannot be default")
    await db.execute(update(WorkerProfile).values(is_default=False))
    profile.is_default = True
    await db.flush()


async def disable_worker_profile(db: AsyncSession, profile: WorkerProfile) -> None:
    """Disable a worker profile unless it is the current default."""
    if profile.is_default:
        raise WorkerProfileValidationError("Default worker profile cannot be disabled")
    profile.enabled = False
    await db.flush()
