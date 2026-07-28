"""Worker profile validation, default resolution, and task snapshots."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Any, Iterable, Mapping
from urllib.parse import urlparse

from sqlalchemy import inspect as sa_inspect
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import get_effective_settings
from app.core.config_crypto import decrypt_config_secret
from app.core.docker_client import (
    DockerConnectionConfig,
    canonicalize_docker_host,
    resolve_docker_connection,
)
from app.core.skills import (
    SkillValidationError,
    hydrate_skill_snapshots,
    skill_snapshots_from_task_snapshot,
    validate_runtime_supports_skills,
)
from app.core.task_prompt import (
    TaskPromptValidationError,
    validate_run_instruction_template,
)
from app.core.worker_environment_variables import (
    serialize_worker_environment_variable_value,
    validate_worker_environment_variable_key,
)
from app.core.worker_kit import (
    BAKED_IMAGE_MODE,
    KIT_CONTAINER_USER,
    KIT_ENTRYPOINT,
    MOUNTED_KIT_MODE,
    WorkerKitValidationError,
    validate_no_worker_kit_mount_collision,
    validate_worker_kit_config,
    validate_worker_kit_mounts,
    worker_kit_environment,
    worker_kit_mounts,
)
from app.models import (
    AIProvider,
    Issue,
    Task,
    TaskWorkerProfileSnapshot,
    WorkerProfile,
    WorkerProfileEnvironmentVariable,
)

logger = logging.getLogger(__name__)

_LEGACY_IGNORED_RUNTIME_ENVIRONMENT_KEYS = frozenset(
    {"CODIFY_RUNTIME_DIR", "CODIFY_ARTIFACT_DIR"}
)


class WorkerProfileValidationError(ValueError):
    """Raised when a worker profile payload is invalid."""


_SYSTEM_MOUNT_ROOTS = (
    PurePosixPath("/workspace"),
    PurePosixPath("/home/codify/.claude"),
    PurePosixPath("/opt/codify-issue-shared"),
    PurePosixPath("/opt/codify-issue-meta"),
    PurePosixPath("/tmp/codify-runtime"),
)
_SEALED_SYSTEM_MOUNT_ROOTS = {
    PurePosixPath("/opt/codify-issue-meta"),
    PurePosixPath("/tmp/codify-runtime"),
}


@dataclass(frozen=True)
class TaskWorkerRuntime:
    """Resolved task worker runtime loaded from a task snapshot."""

    image: str
    codegraph_enabled: bool
    volume_mounts: list[dict[str, str]]
    environment: dict[str, str]
    pre_script: str
    post_script: str
    skills: list[dict[str, Any]] = field(default_factory=list)
    runtime_mode: str = BAKED_IMAGE_MODE
    worker_kit_version: str | None = None
    worker_kit_path: str | None = None
    docker_host: str | None = None
    docker_tls_ca: str | None = None
    docker_tls_cert: str | None = None
    docker_tls_key: str | None = None

    def docker_connection(self, settings: Any) -> DockerConnectionConfig:
        return resolve_docker_connection(
            settings,
            docker_host=self.docker_host,
            docker_tls_ca=self.docker_tls_ca,
            docker_tls_cert=self.docker_tls_cert,
            docker_tls_key=self.docker_tls_key,
        )

    def container_overrides(self) -> dict[str, Any]:
        """Return Docker arguments and environment owned by the delivery mode."""
        try:
            mode, kit_version, kit_path = validate_worker_kit_config(
                runtime_mode=self.runtime_mode,
                worker_kit_version=self.worker_kit_version,
                worker_kit_path=self.worker_kit_path,
            )
        except WorkerKitValidationError as exc:
            raise WorkerProfileValidationError(str(exc)) from exc
        if mode != MOUNTED_KIT_MODE:
            return {"volumes": {}, "environment": {}, "entrypoint": None, "user": None}
        assert kit_version is not None and kit_path is not None
        try:
            validate_no_worker_kit_mount_collision(self.volume_mounts)
        except WorkerKitValidationError as exc:
            raise WorkerProfileValidationError(str(exc)) from exc
        return {
            "volumes": worker_kit_mounts(kit_path),
            "environment": worker_kit_environment(kit_version),
            "entrypoint": KIT_ENTRYPOINT,
            "user": KIT_CONTAINER_USER,
        }


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


def validate_worker_profile_docker_target(
    *,
    docker_host: str | None,
    docker_tls_ca: str | None,
    docker_tls_cert: str | None,
    docker_tls_key: str | None,
) -> tuple[str | None, str | None, str | None, str | None]:
    """Normalize and validate one optional profile-scoped Docker target."""
    host = (docker_host or "").strip() or None
    tls_values = tuple(
        (value or "").strip() or None
        for value in (docker_tls_ca, docker_tls_cert, docker_tls_key)
    )
    if host is None:
        if any(tls_values):
            raise WorkerProfileValidationError(
                "Docker TLS paths require a profile Docker host"
            )
        return None, None, None, None

    parsed = urlparse(host)
    if parsed.scheme not in {"unix", "tcp", "https"}:
        raise WorkerProfileValidationError(
            "docker_host must use unix, tcp, or https"
        )

    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise WorkerProfileValidationError(
            "docker_host must not contain credentials, query parameters, or fragments"
        )
    if parsed.scheme in {"tcp", "https"}:
        try:
            parsed.port
        except ValueError as exc:
            raise WorkerProfileValidationError("docker_host has an invalid port") from exc
        if parsed.hostname is None:
            raise WorkerProfileValidationError("docker_host must include a hostname")
        if parsed.path not in {"", "/"}:
            raise WorkerProfileValidationError("docker_host must not include a URL path")
    elif not parsed.path or not os.path.isabs(parsed.path):
        raise WorkerProfileValidationError(
            "unix docker_host must include an absolute socket path"
        )

    configured_tls_paths = sum(value is not None for value in tls_values)
    if configured_tls_paths not in {0, 3}:
        raise WorkerProfileValidationError(
            "Docker TLS CA, certificate, and key paths must be configured together"
        )
    if configured_tls_paths and parsed.scheme == "unix":
        raise WorkerProfileValidationError(
            f"Docker TLS file paths are not supported for {parsed.scheme} endpoints"
        )
    for path in tls_values:
        if path is not None and not os.path.isabs(path):
            raise WorkerProfileValidationError("Docker TLS paths must be absolute")
    try:
        canonicalize_docker_host(host, tls_enabled=configured_tls_paths == 3)
    except Exception as exc:
        raise WorkerProfileValidationError(f"Invalid docker_host: {exc}") from exc
    return host, tls_values[0], tls_values[1], tls_values[2]


def validate_worker_profile_mounts(raw_mounts: Any) -> list[dict[str, str]]:
    """Validate and normalize worker profile mount entries."""
    if raw_mounts in (None, ""):
        return []
    if not isinstance(raw_mounts, list):
        raise WorkerProfileValidationError("volume_mounts must be a list")

    normalized: list[dict[str, str]] = []
    seen_host_paths: set[str] = set()
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
        if not os.path.isabs(host_path):
            raise WorkerProfileValidationError("volume mount host_path must be absolute")
        if not os.path.isabs(container_path):
            raise WorkerProfileValidationError(
                "volume mount container_path must be absolute"
            )
        host_path = os.path.normpath(host_path)
        container_path = os.path.normpath(container_path)
        destination = PurePosixPath(container_path)
        for system_root in _SYSTEM_MOUNT_ROOTS:
            hides_system_root = destination == system_root or destination in system_root.parents
            enters_sealed_root = (
                system_root in _SEALED_SYSTEM_MOUNT_ROOTS
                and system_root in destination.parents
            )
            if hides_system_root or enters_sealed_root:
                raise WorkerProfileValidationError(
                    f"custom mount path {container_path} conflicts with Codify system path "
                    f"{system_root}"
                )
        if mode not in {"ro", "rw"}:
            raise WorkerProfileValidationError("volume mount mode must be ro or rw")
        if host_path in seen_host_paths:
            raise WorkerProfileValidationError(
                f"duplicate host mount path: {host_path}"
            )
        if container_path in seen_container_paths:
            raise WorkerProfileValidationError(
                f"duplicate container mount path: {container_path}"
            )
        seen_host_paths.add(host_path)
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


def serialize_worker_profile_for_api(
    profile: WorkerProfile,
    *,
    include_docker_target: bool = False,
) -> dict[str, Any]:
    """Serialize one worker profile for API responses."""
    payload = {
        "id": profile.id,
        "name": profile.name,
        "description": profile.description,
        "enabled": profile.enabled,
        "is_default": profile.is_default,
        "image": profile.image,
        "runtime_mode": getattr(profile, "runtime_mode", BAKED_IMAGE_MODE),
        "worker_kit_version": getattr(profile, "worker_kit_version", None),
        "worker_kit_path": getattr(profile, "worker_kit_path", None),
        "codegraph_enabled": bool(getattr(profile, "codegraph_enabled", False)),
        "volume_mounts": profile.volume_mounts or [],
        "environment_variables": [
            serialize_profile_environment_variable_for_api(row)
            for row in profile.environment_variables
        ],
        "default_skill_ids": [
            skill.id for skill in (getattr(profile, "default_skills", None) or [])
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
    if include_docker_target:
        payload.update(
            {
                "docker_host": getattr(profile, "docker_host", None),
                "docker_tls_ca": getattr(profile, "docker_tls_ca", None),
                "docker_tls_cert": getattr(profile, "docker_tls_cert", None),
                "docker_tls_key": getattr(profile, "docker_tls_key", None),
            }
        )
    return payload


def _profile_env_to_snapshot(row: WorkerProfileEnvironmentVariable) -> dict[str, Any]:
    return {
        "key": row.key,
        "value": row.value,
        "is_secret": row.is_secret,
    }


def build_worker_profile_environment_map(
    rows: Iterable[Any],
    *,
    include_secrets: bool = True,
) -> dict[str, str]:
    """Build runtime env from snapshot environment rows."""
    env: dict[str, str] = {}
    for row in rows:
        raw_key = str(_profile_value(row, "key"))
        if raw_key in _LEGACY_IGNORED_RUNTIME_ENVIRONMENT_KEYS:
            logger.warning("Ignoring legacy reserved worker environment variable %s", raw_key)
            continue
        key = _validate_environment_key(raw_key)
        value = str(_profile_value(row, "value") or "")
        is_secret = bool(_profile_value(row, "is_secret"))
        if is_secret and not include_secrets:
            continue
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


def build_worker_profile_volume_map(
    mounts: Iterable[Mapping[str, Any]],
) -> dict[str, dict[str, str]]:
    """Convert validated profile mounts to the Docker SDK volume mapping."""
    volumes: dict[str, dict[str, str]] = {}
    for mount in mounts:
        host_path = str(mount.get("host_path") or "")
        container_path = str(mount.get("container_path") or "")
        if host_path and container_path:
            volumes[host_path] = {
                "bind": container_path,
                "mode": str(mount.get("mode") or "ro"),
            }
    return volumes


async def list_worker_profiles(db: AsyncSession) -> list[WorkerProfile]:
    """Load all worker profiles for management screens."""
    result = await db.execute(
        select(WorkerProfile)
        .options(
            selectinload(WorkerProfile.environment_variables),
            selectinload(WorkerProfile.default_skills),
        )
        .order_by(WorkerProfile.is_default.desc(), WorkerProfile.name.asc())
    )
    return list(result.scalars().all())


async def get_default_worker_profile(db: AsyncSession) -> WorkerProfile | None:
    result = await db.execute(
        select(WorkerProfile)
        .where(WorkerProfile.is_default == True, WorkerProfile.enabled == True)
        .options(
            selectinload(WorkerProfile.environment_variables),
            selectinload(WorkerProfile.default_skills),
        )
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
    """Resolve the worker pinned to an Issue.

    ``explicit_worker_profile_id`` remains as a compatibility guard for internal callers. It
    may only repeat the Issue assignment; tasks cannot override the selected worker.
    """
    del allow_system_default
    candidate_id = getattr(issue, "worker_profile_id", None)
    if explicit_worker_profile_id is not None and explicit_worker_profile_id != candidate_id:
        raise WorkerProfileValidationError("Tasks must use the worker assigned to their issue")
    profile: WorkerProfile | None = None
    if candidate_id is not None:
        result = await db.execute(
            select(WorkerProfile)
            .where(WorkerProfile.id == candidate_id)
            .options(
                selectinload(WorkerProfile.environment_variables),
                selectinload(WorkerProfile.default_skills),
            )
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        profile = result.scalar_one_or_none()

    if profile is None:
        raise WorkerProfileValidationError("No worker is assigned to this issue")
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


def snapshot_from_profile(
    task: Task,
    profile: WorkerProfile,
    *,
    settings: Any | None = None,
) -> TaskWorkerProfileSnapshot:
    """Build an immutable task worker snapshot from a loaded profile."""
    try:
        runtime_mode, kit_version, kit_path = validate_worker_kit_config(
            runtime_mode=getattr(profile, "runtime_mode", BAKED_IMAGE_MODE),
            worker_kit_version=getattr(profile, "worker_kit_version", None),
            worker_kit_path=getattr(profile, "worker_kit_path", None),
        )
        mounts = parse_worker_profile_mounts(profile.volume_mounts)
        validate_worker_kit_mounts(runtime_mode, mounts)
    except WorkerKitValidationError as exc:
        raise WorkerProfileValidationError(str(exc)) from exc
    connection = (
        resolve_docker_connection(
            settings,
            docker_host=getattr(profile, "docker_host", None),
            docker_tls_ca=getattr(profile, "docker_tls_ca", None),
            docker_tls_cert=getattr(profile, "docker_tls_cert", None),
            docker_tls_key=getattr(profile, "docker_tls_key", None),
        )
        if settings is not None
        else None
    )
    return TaskWorkerProfileSnapshot(
        task_id=task.id,
        worker_profile_id=profile.id,
        profile_name=profile.name,
        image=profile.image,
        runtime_mode=runtime_mode,
        worker_kit_version=kit_version,
        worker_kit_path=kit_path,
        docker_host=(connection.host if connection else getattr(profile, "docker_host", None)),
        docker_tls_ca=(
            connection.tls_ca if connection else getattr(profile, "docker_tls_ca", None)
        ),
        docker_tls_cert=(
            connection.tls_cert if connection else getattr(profile, "docker_tls_cert", None)
        ),
        docker_tls_key=(
            connection.tls_key if connection else getattr(profile, "docker_tls_key", None)
        ),
        codegraph_enabled=bool(getattr(profile, "codegraph_enabled", False)),
        volume_mounts=mounts,
        environment_variables=[
            _profile_env_to_snapshot(row) for row in profile.environment_variables
        ],
        skill_references=[],
        skill_selection_source="profile",
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
    snapshot = snapshot_from_profile(task, profile, settings=get_effective_settings())
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
    try:
        skills_unloaded = "skill_references" in sa_inspect(snapshot).unloaded
    except Exception:
        # Lightweight test doubles do not expose SQLAlchemy inspection state.
        skills_unloaded = False
    if skills_unloaded:
        await db.refresh(snapshot, attribute_names=["skill_references"])
    try:
        hydrated_skills = await hydrate_skill_snapshots(
            db,
            skill_snapshots_from_task_snapshot(snapshot),
        )
    except SkillValidationError as exc:
        raise WorkerProfileValidationError(str(exc)) from exc
    try:
        runtime_mode, kit_version, kit_path = validate_worker_kit_config(
            runtime_mode=getattr(snapshot, "runtime_mode", BAKED_IMAGE_MODE),
            worker_kit_version=getattr(snapshot, "worker_kit_version", None),
            worker_kit_path=getattr(snapshot, "worker_kit_path", None),
        )
        mounts = parse_worker_profile_mounts(snapshot.volume_mounts)
        validate_worker_kit_mounts(runtime_mode, mounts)
        validate_runtime_supports_skills(snapshot, hydrated_skills)
    except (WorkerKitValidationError, SkillValidationError) as exc:
        raise WorkerProfileValidationError(str(exc)) from exc
    return TaskWorkerRuntime(
        image=snapshot.image,
        runtime_mode=runtime_mode,
        worker_kit_version=kit_version,
        worker_kit_path=kit_path,
        codegraph_enabled=bool(getattr(snapshot, "codegraph_enabled", False)),
        volume_mounts=mounts,
        environment=build_worker_profile_environment_map(snapshot.environment_variables),
        pre_script=snapshot.pre_script or "",
        post_script=snapshot.post_script or "",
        skills=hydrated_skills,
        docker_host=getattr(snapshot, "docker_host", None),
        docker_tls_ca=getattr(snapshot, "docker_tls_ca", None),
        docker_tls_cert=getattr(snapshot, "docker_tls_cert", None),
        docker_tls_key=getattr(snapshot, "docker_tls_key", None),
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
