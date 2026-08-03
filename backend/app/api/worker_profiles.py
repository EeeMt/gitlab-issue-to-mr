"""Worker profile management API."""

from __future__ import annotations

import asyncio
import contextlib
import inspect
import time
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, StrictInt, field_validator, model_validator
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import get_effective_settings
from app.core.docker_client import DockerClientWrapper, resolve_docker_connection
from app.core.harness_registry import (
    HarnessRegistryError,
    validate_enabled_harnesses,
    validate_harness_constraints,
    validate_harness_runtimes,
)
from app.core.skills import (
    SkillValidationError,
    acquire_worker_profile_skill_package_lock,
    load_enabled_skills,
    load_worker_profile_skills,
    normalize_skill_ids,
    runtime_uses_skill_capable_worker_kit,
    validate_runtime_supports_skills,
)
from app.core.task_prompt import (
    BUILT_IN_CI_AUTO_REPAIR_RUN_INSTRUCTION_TEMPLATE,
    BUILT_IN_EXECUTE_RUN_INSTRUCTION_TEMPLATE,
    BUILT_IN_PLAN_RUN_INSTRUCTION_TEMPLATE,
)
from app.core.worker_docker_targets import docker_daemon_key
from app.core.worker_kit import (
    BAKED_IMAGE_MODE,
    WorkerKitValidationError,
    validate_worker_kit_config,
    validate_worker_kit_mounts,
)
from app.core.worker_profiles import (
    TaskWorkerRuntime,
    WorkerProfileValidationError,
    build_worker_profile_environment_map,
    build_worker_profile_volume_map,
    parse_worker_profile_mounts,
    replace_profile_environment_variables,
    serialize_worker_profile_for_api,
    set_default_worker_profile,
    validate_profile_templates,
    validate_worker_profile_docker_target,
)
from app.core.worker_profiles import (
    disable_worker_profile as disable_worker_profile_domain,
)
from app.core.worker_profiles import (
    list_worker_profiles as list_worker_profiles_domain,
)
from app.database import get_db
from app.dependencies.auth import require_admin_user
from app.models import Issue, IssueStatus, WorkerProfile, WorkerProfileEnvironmentVariable

router = APIRouter()


class WorkerProfileEnvironmentVariableRequest(BaseModel):
    id: int | None = None
    key: str = Field(max_length=255)
    value: str = ""
    is_secret: bool = False


class WorkerProfileRequestBase(BaseModel):
    name: str | None = Field(default=None, max_length=100)
    description: str | None = None
    enabled: bool | None = None
    image: str | None = Field(default=None, max_length=255)
    runtime_mode: str | None = Field(default=None, max_length=32)
    worker_kit_version: str | None = Field(default=None, max_length=128)
    worker_kit_path: str | None = Field(default=None, max_length=1024)
    docker_host: str | None = Field(default=None, max_length=500)
    docker_tls_ca: str | None = Field(default=None, max_length=1024)
    docker_tls_cert: str | None = Field(default=None, max_length=1024)
    docker_tls_key: str | None = Field(default=None, max_length=1024)
    codegraph_enabled: bool | None = None
    volume_mounts: list[dict[str, Any]] | None = None
    environment_variables: list[WorkerProfileEnvironmentVariableRequest] | None = None
    default_skill_ids: list[StrictInt] | None = None
    pre_script: str | None = None
    post_script: str | None = None
    default_execute_run_instruction_template: str | None = None
    default_plan_run_instruction_template: str | None = None
    ci_auto_repair_run_instruction_template: str | None = None
    enabled_harnesses: list[str] | None = None
    default_harness_key: str | None = Field(default=None, max_length=32)
    harness_constraints: dict[str, Any] | None = None
    image_digest: str | None = Field(default=None, max_length=128)
    harness_runtimes: dict[str, Any] | None = None

    @field_validator("default_skill_ids")
    @classmethod
    def validate_default_skill_ids(cls, value: list[int] | None) -> list[int] | None:
        if value is None:
            return None
        try:
            return normalize_skill_ids(value)
        except SkillValidationError as exc:
            raise ValueError(str(exc)) from exc

    @model_validator(mode="after")
    def validate_harness_fields(self) -> "WorkerProfileRequestBase":
        enabled = self.enabled_harnesses
        default_key = self.default_harness_key
        if enabled is not None or default_key is not None:
            try:
                validate_enabled_harnesses(
                    enabled if enabled is not None else ["claude"],
                    default_harness_key=default_key or "claude",
                )
            except HarnessRegistryError as exc:
                raise ValueError(str(exc)) from exc
        if self.harness_constraints is not None:
            try:
                validate_harness_constraints(self.harness_constraints)
            except HarnessRegistryError as exc:
                raise ValueError(str(exc)) from exc
        if self.harness_runtimes is not None:
            try:
                validate_harness_runtimes(self.harness_runtimes)
            except HarnessRegistryError as exc:
                raise ValueError(str(exc)) from exc
        return self


class WorkerProfileCreateRequest(WorkerProfileRequestBase):
    name: str = Field(max_length=100)
    image: str = Field(max_length=255)
    runtime_mode: str = BAKED_IMAGE_MODE
    volume_mounts: list[dict[str, Any]] = Field(default_factory=list)
    environment_variables: list[WorkerProfileEnvironmentVariableRequest] = Field(
        default_factory=list
    )
    default_execute_run_instruction_template: str = (
        BUILT_IN_EXECUTE_RUN_INSTRUCTION_TEMPLATE
    )
    default_plan_run_instruction_template: str = BUILT_IN_PLAN_RUN_INSTRUCTION_TEMPLATE
    ci_auto_repair_run_instruction_template: str = (
        BUILT_IN_CI_AUTO_REPAIR_RUN_INSTRUCTION_TEMPLATE
    )


class WorkerProfileUpdateRequest(WorkerProfileRequestBase):
    pass


class DockerConnectionTestRequest(BaseModel):
    docker_host: str | None = Field(default=None, max_length=500)
    docker_tls_ca: str | None = Field(default=None, max_length=1024)
    docker_tls_cert: str | None = Field(default=None, max_length=1024)
    docker_tls_key: str | None = Field(default=None, max_length=1024)


class WorkerRuntimeVerificationRequest(BaseModel):
    smoke_command: str | None = Field(default=None, max_length=4000)


def _http_profile_error(exc: WorkerProfileValidationError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc))


async def _load_profile_or_404(
    db: AsyncSession,
    profile_id: int,
    *,
    for_update: bool = False,
) -> WorkerProfile:
    profile = await db.get(
        WorkerProfile,
        profile_id,
        options=[
            selectinload(WorkerProfile.environment_variables),
            selectinload(WorkerProfile.default_skills),
        ],
        with_for_update=for_update,
    )
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Worker profile not found",
        )
    return profile


async def _ensure_profile_name_available(
    db: AsyncSession,
    name: str,
    *,
    excluding_profile_id: int | None = None,
) -> None:
    result = await db.execute(select(WorkerProfile).where(WorkerProfile.name == name))
    existing = result.scalar_one_or_none()
    if existing is not None and existing.id != excluding_profile_id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Worker profile with name '{name}' already exists",
        )


async def _active_issue_assignment_count(db: AsyncSession, profile_id: int) -> int:
    result = await db.execute(
        select(func.count(Issue.id)).where(
            Issue.worker_profile_id == profile_id,
            Issue.status != IssueStatus.CLOSED.value,
        )
    )
    return int(result.scalar_one())


async def _issue_assignment_count(db: AsyncSession, profile_id: int) -> int:
    result = await db.execute(
        select(func.count(Issue.id)).where(Issue.worker_profile_id == profile_id)
    )
    return int(result.scalar_one())


async def _ensure_profile_can_stop_serving_issues(
    db: AsyncSession,
    profile: WorkerProfile,
) -> None:
    count = await _active_issue_assignment_count(db, profile.id)
    if count:
        raise WorkerProfileValidationError(
            f"Worker profile '{profile.name}' is assigned to {count} active issue(s)"
        )


async def _unique_copy_name(db: AsyncSession, source_name: str) -> str:
    base_name = f"{source_name} Copy"
    candidate = base_name
    suffix = 2
    while True:
        result = await db.execute(select(WorkerProfile.id).where(WorkerProfile.name == candidate))
        if result.scalar_one_or_none() is None:
            return candidate
        candidate = f"{base_name} {suffix}"
        suffix += 1


async def _rollback(db: AsyncSession) -> None:
    result = db.rollback()
    if inspect.isawaitable(result):
        await result


@router.get("/worker-profiles")
async def list_worker_profiles(db: AsyncSession = Depends(get_db)):
    """List all worker profiles."""
    profiles = await list_worker_profiles_domain(db)
    return [serialize_worker_profile_for_api(profile) for profile in profiles]


@router.get("/worker-profiles/admin")
async def list_worker_profiles_for_admin(
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_admin_user),
):
    """List worker profiles including administrator-only Docker target fields."""
    profiles = await list_worker_profiles_domain(db)
    return [
        serialize_worker_profile_for_api(profile, include_docker_target=True)
        for profile in profiles
    ]


@router.post("/worker-profiles/test-docker-connection")
async def test_worker_profile_docker_connection(
    request: DockerConnectionTestRequest,
    _admin=Depends(require_admin_user),
):
    """Test an unsaved profile Docker target and return daemon identity."""
    try:
        host, tls_ca, tls_cert, tls_key = validate_worker_profile_docker_target(
            docker_host=request.docker_host,
            docker_tls_ca=request.docker_tls_ca,
            docker_tls_cert=request.docker_tls_cert,
            docker_tls_key=request.docker_tls_key,
        )
    except (WorkerProfileValidationError, WorkerKitValidationError) as exc:
        raise _http_profile_error(exc) from exc

    connection = resolve_docker_connection(
        get_effective_settings(),
        docker_host=host,
        docker_tls_ca=tls_ca,
        docker_tls_cert=tls_cert,
        docker_tls_key=tls_key,
    )
    started_at = time.monotonic()

    def inspect_connection():
        client = DockerClientWrapper(
            connection,
            connect_timeout=3,
            operation_timeout=3,
        )
        try:
            return client.inspect_server()
        finally:
            with contextlib.suppress(Exception):
                client.close()

    try:
        server = await asyncio.wait_for(asyncio.to_thread(inspect_connection), timeout=10)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Unable to connect to Docker daemon {connection.host}: {exc}",
        ) from exc
    return {
        "docker_host": connection.host,
        "elapsed_ms": round((time.monotonic() - started_at) * 1000),
        **server,
    }


@router.post("/worker-profiles/{profile_id}/verify-runtime")
async def verify_worker_profile_runtime(
    profile_id: int,
    request: WorkerRuntimeVerificationRequest,
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_admin_user),
):
    """Run the mounted kit preflight on the profile's actual Docker target."""
    profile = await _load_profile_or_404(db, profile_id)
    try:
        runtime = TaskWorkerRuntime(
            image=profile.image,
            runtime_mode=getattr(profile, "runtime_mode", BAKED_IMAGE_MODE),
            worker_kit_version=getattr(profile, "worker_kit_version", None),
            worker_kit_path=getattr(profile, "worker_kit_path", None),
            codegraph_enabled=bool(getattr(profile, "codegraph_enabled", False)),
            volume_mounts=parse_worker_profile_mounts(profile.volume_mounts),
            environment=build_worker_profile_environment_map(
                profile.environment_variables,
                include_secrets=False,
            ),
            pre_script="",
            post_script="",
            docker_host=getattr(profile, "docker_host", None),
            docker_tls_ca=getattr(profile, "docker_tls_ca", None),
            docker_tls_cert=getattr(profile, "docker_tls_cert", None),
            docker_tls_key=getattr(profile, "docker_tls_key", None),
        )
        overrides = runtime.container_overrides()
        verification_volumes = build_worker_profile_volume_map(runtime.volume_mounts)
        verification_volumes.update(overrides["volumes"])
    except WorkerProfileValidationError as exc:
        raise _http_profile_error(exc) from exc
    if runtime.runtime_mode == BAKED_IMAGE_MODE:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Runtime verification requires mounted_kit mode",
        )

    command = ["--verify"]
    if runtime_uses_skill_capable_worker_kit(runtime):
        command.append("--require-skill-support")
    smoke_command = (request.smoke_command or "").strip()
    if smoke_command:
        command.extend(["--smoke", smoke_command])
    connection = runtime.docker_connection(get_effective_settings())
    started_at = time.monotonic()

    def verify_runtime() -> tuple[int, str]:
        client = DockerClientWrapper(connection)
        container = None
        try:
            client.client.images.get(runtime.image)
            container = client.create_container(
                image=runtime.image,
                command=command,
                environment={
                    **runtime.environment,
                    **overrides["environment"],
                    "CODIFY_RUNTIME_IMAGE": runtime.image,
                },
                volumes=verification_volumes,
                entrypoint=overrides["entrypoint"],
                user=overrides["user"],
                tmpfs={"/workspace": "rw,exec,mode=1777"},
                name=f"codify-worker-kit-verify-{profile.id}-{uuid.uuid4().hex[:8]}",
                labels={
                    "codify.worker_kit_verification": "true",
                    "codify.worker_kit_version": runtime.worker_kit_version or "",
                },
            )
            return client.wait_for_container(container, timeout=180)
        finally:
            if container is not None:
                with contextlib.suppress(Exception):
                    container.remove(force=True, v=True)
            with contextlib.suppress(Exception):
                client.close()

    try:
        exit_code, logs = await asyncio.wait_for(
            asyncio.to_thread(verify_runtime),
            timeout=200,
        )
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Worker runtime verification could not start: {exc}",
        ) from exc
    if exit_code != 0:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "message": "Worker runtime verification failed",
                "exit_code": exit_code,
                "logs": logs[-8000:],
            },
        )
    return {
        "ok": True,
        "image": runtime.image,
        "worker_kit_version": runtime.worker_kit_version,
        "docker_host": connection.host,
        "elapsed_ms": round((time.monotonic() - started_at) * 1000),
        "omitted_secret_environment_keys": sorted(
            str(row.key)
            for row in profile.environment_variables
            if bool(row.is_secret)
        ),
        "logs": logs[-8000:],
    }


@router.post("/worker-profiles", status_code=status.HTTP_201_CREATED)
async def create_worker_profile(
    request: WorkerProfileCreateRequest,
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_admin_user),
):
    """Create a worker profile."""
    try:
        await acquire_worker_profile_skill_package_lock(db)
        name = request.name.strip()
        if not name:
            raise WorkerProfileValidationError("Worker profile name cannot be blank")
        image = request.image.strip()
        if not image:
            raise WorkerProfileValidationError("Worker profile image cannot be blank")

        await _ensure_profile_name_available(db, name)
        execute_template, plan_template, ci_template = validate_profile_templates(
            execute_template=request.default_execute_run_instruction_template,
            plan_template=request.default_plan_run_instruction_template,
            ci_template=request.ci_auto_repair_run_instruction_template,
        )
        docker_host, tls_ca, tls_cert, tls_key = validate_worker_profile_docker_target(
            docker_host=request.docker_host,
            docker_tls_ca=request.docker_tls_ca,
            docker_tls_cert=request.docker_tls_cert,
            docker_tls_key=request.docker_tls_key,
        )
        runtime_mode, kit_version, kit_path = validate_worker_kit_config(
            runtime_mode=request.runtime_mode,
            worker_kit_version=request.worker_kit_version,
            worker_kit_path=request.worker_kit_path,
        )
        mounts = parse_worker_profile_mounts(request.volume_mounts)
        validate_worker_kit_mounts(runtime_mode, mounts)
        profile = WorkerProfile(
            name=name,
            description=request.description,
            enabled=True if request.enabled is None else request.enabled,
            is_default=False,
            image=image,
            runtime_mode=runtime_mode,
            worker_kit_version=kit_version,
            worker_kit_path=kit_path,
            docker_host=docker_host,
            docker_tls_ca=tls_ca,
            docker_tls_cert=tls_cert,
            docker_tls_key=tls_key,
            codegraph_enabled=bool(request.codegraph_enabled),
            volume_mounts=mounts,
            pre_script=request.pre_script or "",
            post_script=request.post_script or "",
            default_execute_run_instruction_template=execute_template,
            default_plan_run_instruction_template=plan_template,
            ci_auto_repair_run_instruction_template=ci_template,
            enabled_harnesses=(
                list(request.enabled_harnesses)
                if request.enabled_harnesses is not None
                else ["claude"]
            ),
            default_harness_key=request.default_harness_key or "claude",
            harness_constraints=request.harness_constraints or {},
            image_digest=request.image_digest,
            harness_runtimes=request.harness_runtimes or {},
            default_skills=[],
        )
        db.add(profile)
        await db.flush()
        profile.default_skills.extend(
            await load_enabled_skills(db, request.default_skill_ids or [])
        )
        validate_runtime_supports_skills(
            profile,
            getattr(profile, "default_skills", None) or [],
        )
        await replace_profile_environment_variables(
            db,
            profile,
            [item.model_dump() for item in request.environment_variables],
        )
        await db.commit()
        await db.refresh(
            profile,
            attribute_names=["environment_variables", "default_skills"],
        )
        return serialize_worker_profile_for_api(profile, include_docker_target=True)
    except HTTPException:
        await _rollback(db)
        raise
    except (WorkerProfileValidationError, WorkerKitValidationError, SkillValidationError) as exc:
        await _rollback(db)
        raise _http_profile_error(exc) from exc


@router.patch("/worker-profiles/{profile_id}")
async def update_worker_profile(
    profile_id: int,
    request: WorkerProfileUpdateRequest,
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_admin_user),
):
    """Update a worker profile."""
    fields = request.model_fields_set
    if "default_skill_ids" in fields:
        await acquire_worker_profile_skill_package_lock(db)
    profile = await _load_profile_or_404(db, profile_id, for_update=True)
    try:
        if "name" in fields and request.name is not None:
            name = request.name.strip()
            if not name:
                raise WorkerProfileValidationError("Worker profile name cannot be blank")
            await _ensure_profile_name_available(db, name, excluding_profile_id=profile.id)
            profile.name = name
        if "description" in fields:
            profile.description = request.description
        if "enabled" in fields and request.enabled is not None:
            if profile.is_default and request.enabled is False:
                raise WorkerProfileValidationError(
                    "Default worker profile cannot be disabled"
                )
            if request.enabled is False:
                await _ensure_profile_can_stop_serving_issues(db, profile)
            profile.enabled = request.enabled
        if "image" in fields and request.image is not None:
            profile.image = request.image.strip()
            if not profile.image:
                raise WorkerProfileValidationError("Worker profile image cannot be blank")
        kit_fields = {"runtime_mode", "worker_kit_version", "worker_kit_path"}
        if kit_fields & fields:
            runtime_mode, kit_version, kit_path = validate_worker_kit_config(
                runtime_mode=(
                    request.runtime_mode
                    if "runtime_mode" in fields
                    else getattr(profile, "runtime_mode", BAKED_IMAGE_MODE)
                ),
                worker_kit_version=(
                    request.worker_kit_version
                    if "worker_kit_version" in fields
                    else getattr(profile, "worker_kit_version", None)
                ),
                worker_kit_path=(
                    request.worker_kit_path
                    if "worker_kit_path" in fields
                    else getattr(profile, "worker_kit_path", None)
                ),
            )
            profile.runtime_mode = runtime_mode
            profile.worker_kit_version = kit_version
            profile.worker_kit_path = kit_path
        harness_fields = {
            "enabled_harnesses",
            "default_harness_key",
            "harness_constraints",
            "image_digest",
            "harness_runtimes",
        }
        if harness_fields & fields:
            # Partial updates revalidate the merged view so default_harness_key
            # can never end up outside enabled_harnesses.
            merged_enabled = (
                list(request.enabled_harnesses)
                if "enabled_harnesses" in fields
                and request.enabled_harnesses is not None
                else list(getattr(profile, "enabled_harnesses", None) or ["claude"])
            )
            merged_default = (
                request.default_harness_key
                if "default_harness_key" in fields
                and request.default_harness_key
                else getattr(profile, "default_harness_key", None) or "claude"
            )
            try:
                validate_enabled_harnesses(
                    merged_enabled, default_harness_key=merged_default
                )
            except HarnessRegistryError as exc:
                raise WorkerProfileValidationError(str(exc)) from exc
            if "enabled_harnesses" in fields:
                profile.enabled_harnesses = merged_enabled
            if "default_harness_key" in fields:
                profile.default_harness_key = merged_default
            if "harness_constraints" in fields:
                profile.harness_constraints = request.harness_constraints or {}
            if "image_digest" in fields:
                profile.image_digest = request.image_digest
            if "harness_runtimes" in fields:
                profile.harness_runtimes = request.harness_runtimes or {}
        docker_target_fields = {
            "docker_host",
            "docker_tls_ca",
            "docker_tls_cert",
            "docker_tls_key",
        }
        if docker_target_fields & fields:
            docker_host, tls_ca, tls_cert, tls_key = validate_worker_profile_docker_target(
                docker_host=(
                    request.docker_host if "docker_host" in fields else profile.docker_host
                ),
                docker_tls_ca=(
                    request.docker_tls_ca
                    if "docker_tls_ca" in fields
                    else profile.docker_tls_ca
                ),
                docker_tls_cert=(
                    request.docker_tls_cert
                    if "docker_tls_cert" in fields
                    else profile.docker_tls_cert
                ),
                docker_tls_key=(
                    request.docker_tls_key
                    if "docker_tls_key" in fields
                    else profile.docker_tls_key
                ),
            )
            settings = get_effective_settings()
            current_target = resolve_docker_connection(
                settings,
                docker_host=profile.docker_host,
                docker_tls_ca=profile.docker_tls_ca,
                docker_tls_cert=profile.docker_tls_cert,
                docker_tls_key=profile.docker_tls_key,
            )
            next_target = resolve_docker_connection(
                settings,
                docker_host=docker_host,
                docker_tls_ca=tls_ca,
                docker_tls_cert=tls_cert,
                docker_tls_key=tls_key,
            )
            # Issue affinity protects the physical daemon, not one certificate
            # filename. Credential rotation on the same endpoint must remain possible.
            if docker_daemon_key(next_target) != docker_daemon_key(current_target):
                await _ensure_profile_can_stop_serving_issues(db, profile)
            profile.docker_host = docker_host
            profile.docker_tls_ca = tls_ca
            profile.docker_tls_cert = tls_cert
            profile.docker_tls_key = tls_key
        if "codegraph_enabled" in fields and request.codegraph_enabled is not None:
            profile.codegraph_enabled = request.codegraph_enabled
        if "volume_mounts" in fields and request.volume_mounts is not None:
            profile.volume_mounts = parse_worker_profile_mounts(request.volume_mounts)
        validate_worker_kit_mounts(
            getattr(profile, "runtime_mode", BAKED_IMAGE_MODE),
            profile.volume_mounts or [],
        )
        if "pre_script" in fields:
            profile.pre_script = request.pre_script or ""
        if "post_script" in fields:
            profile.post_script = request.post_script or ""
        if {
            "default_execute_run_instruction_template",
            "default_plan_run_instruction_template",
            "ci_auto_repair_run_instruction_template",
        } & fields:
            execute_template, plan_template, ci_template = validate_profile_templates(
                execute_template=(
                    request.default_execute_run_instruction_template
                    if request.default_execute_run_instruction_template is not None
                    else profile.default_execute_run_instruction_template
                ),
                plan_template=(
                    request.default_plan_run_instruction_template
                    if request.default_plan_run_instruction_template is not None
                    else profile.default_plan_run_instruction_template
                ),
                ci_template=(
                    request.ci_auto_repair_run_instruction_template
                    if request.ci_auto_repair_run_instruction_template is not None
                    else profile.ci_auto_repair_run_instruction_template
                ),
            )
            profile.default_execute_run_instruction_template = execute_template
            profile.default_plan_run_instruction_template = plan_template
            profile.ci_auto_repair_run_instruction_template = ci_template
        if "environment_variables" in fields and request.environment_variables is not None:
            await replace_profile_environment_variables(
                db,
                profile,
                [item.model_dump() for item in request.environment_variables],
            )
        if "default_skill_ids" in fields and request.default_skill_ids is not None:
            existing_skill_ids = {skill.id for skill in profile.default_skills}
            profile.default_skills = await load_worker_profile_skills(
                db,
                request.default_skill_ids,
                retained_disabled_skill_ids=existing_skill_ids,
            )
        validate_runtime_supports_skills(
            profile,
            [
                skill
                for skill in (getattr(profile, "default_skills", None) or [])
                if skill.enabled
            ],
        )

        await db.commit()
        await db.refresh(
            profile,
            attribute_names=["environment_variables", "default_skills"],
        )
        return serialize_worker_profile_for_api(profile, include_docker_target=True)
    except HTTPException:
        await _rollback(db)
        raise
    except (WorkerProfileValidationError, WorkerKitValidationError, SkillValidationError) as exc:
        await _rollback(db)
        raise _http_profile_error(exc) from exc


@router.post("/worker-profiles/{profile_id}/set-default")
async def set_default_worker_profile_endpoint(
    profile_id: int,
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_admin_user),
):
    """Set one enabled worker profile as the system default."""
    profile = await _load_profile_or_404(db, profile_id, for_update=True)
    try:
        await set_default_worker_profile(db, profile)
        await db.commit()
        await db.refresh(
            profile,
            attribute_names=["environment_variables", "default_skills"],
        )
        return serialize_worker_profile_for_api(profile, include_docker_target=True)
    except WorkerProfileValidationError as exc:
        await _rollback(db)
        raise _http_profile_error(exc) from exc


@router.post("/worker-profiles/{profile_id}/disable")
async def disable_worker_profile(
    profile_id: int,
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_admin_user),
):
    """Disable a non-default worker profile."""
    profile = await _load_profile_or_404(db, profile_id, for_update=True)
    try:
        if profile.is_default:
            raise WorkerProfileValidationError("Default worker profile cannot be disabled")
        await _ensure_profile_can_stop_serving_issues(db, profile)
        await disable_worker_profile_domain(db, profile)
        await db.commit()
        await db.refresh(
            profile,
            attribute_names=["environment_variables", "default_skills"],
        )
        return serialize_worker_profile_for_api(profile, include_docker_target=True)
    except WorkerProfileValidationError as exc:
        await _rollback(db)
        raise _http_profile_error(exc) from exc


@router.delete("/worker-profiles/{profile_id}")
async def delete_worker_profile(
    profile_id: int,
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_admin_user),
):
    """Delete one unused, disabled, non-default worker profile."""
    profile = await _load_profile_or_404(db, profile_id, for_update=True)
    try:
        if profile.is_default:
            raise WorkerProfileValidationError("Default worker profile cannot be deleted")
        if profile.enabled:
            raise WorkerProfileValidationError(
                "Worker profile must be disabled before it can be deleted"
            )
        assignment_count = await _issue_assignment_count(db, profile.id)
        if assignment_count:
            raise WorkerProfileValidationError(
                f"Worker profile '{profile.name}' is assigned to "
                f"{assignment_count} issue(s) and cannot be deleted"
            )

        await db.delete(profile)
        await db.commit()
        return {"status": "deleted", "id": profile_id}
    except WorkerProfileValidationError as exc:
        await _rollback(db)
        raise _http_profile_error(exc) from exc


@router.post("/worker-profiles/{profile_id}/duplicate", status_code=status.HTTP_201_CREATED)
async def duplicate_worker_profile(
    profile_id: int,
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_admin_user),
):
    """Duplicate a worker profile, preserving encrypted secret values."""
    await acquire_worker_profile_skill_package_lock(db)
    source = await _load_profile_or_404(db, profile_id, for_update=True)
    try:
        source_skill_ids = [skill.id for skill in source.default_skills]
        default_skills = await load_worker_profile_skills(
            db,
            source_skill_ids,
            retained_disabled_skill_ids=source_skill_ids,
        )
        validate_runtime_supports_skills(
            source,
            [skill for skill in default_skills if skill.enabled],
        )
        copy = WorkerProfile(
            name=await _unique_copy_name(db, source.name),
            description=source.description,
            enabled=True,
            is_default=False,
            image=source.image,
            runtime_mode=getattr(source, "runtime_mode", BAKED_IMAGE_MODE),
            worker_kit_version=getattr(source, "worker_kit_version", None),
            worker_kit_path=getattr(source, "worker_kit_path", None),
            docker_host=getattr(source, "docker_host", None),
            docker_tls_ca=getattr(source, "docker_tls_ca", None),
            docker_tls_cert=getattr(source, "docker_tls_cert", None),
            docker_tls_key=getattr(source, "docker_tls_key", None),
            codegraph_enabled=bool(getattr(source, "codegraph_enabled", False)),
            volume_mounts=list(source.volume_mounts or []),
            pre_script=source.pre_script or "",
            post_script=source.post_script or "",
            default_execute_run_instruction_template=(
                source.default_execute_run_instruction_template
            ),
            default_plan_run_instruction_template=source.default_plan_run_instruction_template,
            ci_auto_repair_run_instruction_template=(
                source.ci_auto_repair_run_instruction_template
            ),
            environment_variables=[
                WorkerProfileEnvironmentVariable(
                    key=row.key,
                    value=row.value,
                    is_secret=row.is_secret,
                )
                for row in source.environment_variables
            ],
            default_skills=default_skills,
        )
        db.add(copy)
        await db.commit()
        await db.refresh(copy, attribute_names=["environment_variables", "default_skills"])
        return serialize_worker_profile_for_api(copy, include_docker_target=True)
    except (WorkerProfileValidationError, SkillValidationError) as exc:
        await _rollback(db)
        raise _http_profile_error(exc) from exc
