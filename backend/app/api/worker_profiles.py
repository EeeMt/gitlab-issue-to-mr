"""Worker profile management API."""

from __future__ import annotations

import inspect
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.task_prompt import (
    BUILT_IN_CI_AUTO_REPAIR_RUN_INSTRUCTION_TEMPLATE,
    BUILT_IN_EXECUTE_RUN_INSTRUCTION_TEMPLATE,
    BUILT_IN_PLAN_RUN_INSTRUCTION_TEMPLATE,
)
from app.core.worker_profiles import (
    WorkerProfileValidationError,
    parse_worker_profile_mounts,
    replace_profile_environment_variables,
    serialize_worker_profile_for_api,
    set_default_worker_profile,
    validate_profile_templates,
)
from app.core.worker_profiles import (
    disable_worker_profile as disable_worker_profile_domain,
)
from app.core.worker_profiles import (
    list_worker_profiles as list_worker_profiles_domain,
)
from app.database import get_db
from app.dependencies.auth import require_admin_user
from app.models import WorkerProfile, WorkerProfileEnvironmentVariable

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
    volume_mounts: list[dict[str, Any]] | None = None
    environment_variables: list[WorkerProfileEnvironmentVariableRequest] | None = None
    pre_script: str | None = None
    post_script: str | None = None
    default_execute_run_instruction_template: str | None = None
    default_plan_run_instruction_template: str | None = None
    ci_auto_repair_run_instruction_template: str | None = None


class WorkerProfileCreateRequest(WorkerProfileRequestBase):
    name: str = Field(max_length=100)
    image: str = Field(max_length=255)
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


def _http_profile_error(exc: WorkerProfileValidationError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc))


async def _load_profile_or_404(db: AsyncSession, profile_id: int) -> WorkerProfile:
    profile = await db.get(
        WorkerProfile,
        profile_id,
        options=[selectinload(WorkerProfile.environment_variables)],
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


@router.post("/worker-profiles", status_code=status.HTTP_201_CREATED)
async def create_worker_profile(
    request: WorkerProfileCreateRequest,
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_admin_user),
):
    """Create a worker profile."""
    try:
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
        profile = WorkerProfile(
            name=name,
            description=request.description,
            enabled=True if request.enabled is None else request.enabled,
            is_default=False,
            image=image,
            volume_mounts=parse_worker_profile_mounts(request.volume_mounts),
            pre_script=request.pre_script or "",
            post_script=request.post_script or "",
            default_execute_run_instruction_template=execute_template,
            default_plan_run_instruction_template=plan_template,
            ci_auto_repair_run_instruction_template=ci_template,
        )
        db.add(profile)
        await db.flush()
        await replace_profile_environment_variables(
            db,
            profile,
            [item.model_dump() for item in request.environment_variables],
        )
        await db.commit()
        await db.refresh(profile, attribute_names=["environment_variables"])
        return serialize_worker_profile_for_api(profile)
    except HTTPException:
        await _rollback(db)
        raise
    except WorkerProfileValidationError as exc:
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
    profile = await _load_profile_or_404(db, profile_id)
    try:
        fields = request.model_fields_set
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
            profile.enabled = request.enabled
        if "image" in fields and request.image is not None:
            profile.image = request.image.strip()
            if not profile.image:
                raise WorkerProfileValidationError("Worker profile image cannot be blank")
        if "volume_mounts" in fields and request.volume_mounts is not None:
            profile.volume_mounts = parse_worker_profile_mounts(request.volume_mounts)
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

        await db.commit()
        await db.refresh(profile, attribute_names=["environment_variables"])
        return serialize_worker_profile_for_api(profile)
    except HTTPException:
        await _rollback(db)
        raise
    except WorkerProfileValidationError as exc:
        await _rollback(db)
        raise _http_profile_error(exc) from exc


@router.post("/worker-profiles/{profile_id}/set-default")
async def set_default_worker_profile_endpoint(
    profile_id: int,
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_admin_user),
):
    """Set one enabled worker profile as the system default."""
    profile = await _load_profile_or_404(db, profile_id)
    try:
        await set_default_worker_profile(db, profile)
        await db.commit()
        await db.refresh(profile, attribute_names=["environment_variables"])
        return serialize_worker_profile_for_api(profile)
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
    profile = await _load_profile_or_404(db, profile_id)
    try:
        await disable_worker_profile_domain(db, profile)
        await db.commit()
        await db.refresh(profile, attribute_names=["environment_variables"])
        return serialize_worker_profile_for_api(profile)
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
    source = await _load_profile_or_404(db, profile_id)
    copy = WorkerProfile(
        name=await _unique_copy_name(db, source.name),
        description=source.description,
        enabled=True,
        is_default=False,
        image=source.image,
        volume_mounts=list(source.volume_mounts or []),
        pre_script=source.pre_script or "",
        post_script=source.post_script or "",
        default_execute_run_instruction_template=source.default_execute_run_instruction_template,
        default_plan_run_instruction_template=source.default_plan_run_instruction_template,
        ci_auto_repair_run_instruction_template=source.ci_auto_repair_run_instruction_template,
    )
    db.add(copy)
    await db.flush()
    for row in source.environment_variables:
        db.add(
            WorkerProfileEnvironmentVariable(
                worker_profile_id=copy.id,
                key=row.key,
                value=row.value,
                is_secret=row.is_secret,
            )
        )
    await db.commit()
    await db.refresh(copy, attribute_names=["environment_variables"])
    return serialize_worker_profile_for_api(copy)
