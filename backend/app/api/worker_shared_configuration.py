"""Shared worker configuration management API.

Administrators read and patch the single system shared configuration. Saving a
patch validates the shared layer itself and then statically validates every
enabled Profile's *combined* effective configuration before committing, so a
shared change can never leave an inheriting Profile statically invalid
(design §11.1). Phase 1 does not touch Docker hosts or readiness records.
"""

from __future__ import annotations

import inspect
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.harness_registry import capability_policy
from app.core.skills import SkillValidationError, validate_runtime_supports_skills
from app.core.worker_environment_variables import (
    serialize_worker_environment_variable_value,
    validate_worker_environment_variable_key,
)
from app.core.worker_kit import (
    BAKED_IMAGE_MODE,
    WorkerKitValidationError,
    validate_worker_kit_config,
    validate_worker_kit_mounts,
)
from app.core.worker_profiles import (
    WorkerProfileValidationError,
    parse_worker_profile_mounts,
    validate_profile_templates,
)
from app.core.worker_shared_configuration import (
    WorkerSharedConfigurationContext,
    effective_configuration_digest,
    resolve_effective_configuration,
    validate_effective_configuration,
)
from app.database import get_db
from app.dependencies.auth import require_admin_user
from app.models import (
    Skill,
    WorkerProfile,
    WorkerSharedConfiguration,
    WorkerSharedEnvironmentVariable,
)

router = APIRouter()


class SharedEnvironmentVariableRequest(BaseModel):
    key: str = Field(max_length=255)
    value: str = ""
    is_secret: bool = False


class WorkerSharedConfigurationPatchRequest(BaseModel):
    expected_revision: int
    runtime_mode: str | None = Field(default=None, max_length=32)
    worker_kit_version: str | None = Field(default=None, max_length=128)
    worker_kit_path: str | None = Field(default=None, max_length=1024)
    volume_mounts: list[dict[str, Any]] | None = None
    pre_script: str | None = None
    post_script: str | None = None
    default_execute_run_instruction_template: str | None = None
    default_plan_run_instruction_template: str | None = None
    ci_auto_repair_run_instruction_template: str | None = None
    environment_variables: list[SharedEnvironmentVariableRequest] | None = None


def serialize_shared_environment_variable_for_api(
    row: WorkerSharedEnvironmentVariable,
) -> dict[str, Any]:
    """Serialize one shared env var without leaking secret values."""
    return {
        "id": row.id,
        "key": row.key,
        "value": None if row.is_secret else row.value,
        "is_secret": row.is_secret,
        "value_configured": row.value is not None,
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


def serialize_shared_configuration_for_api(
    row: WorkerSharedConfiguration,
    environment_variables: list[WorkerSharedEnvironmentVariable],
) -> dict[str, Any]:
    return {
        "id": row.id,
        "revision": row.revision,
        "runtime_mode": row.runtime_mode,
        "worker_kit_version": row.worker_kit_version,
        "worker_kit_path": row.worker_kit_path,
        "volume_mounts": row.volume_mounts or [],
        "pre_script": row.pre_script,
        "post_script": row.post_script,
        "default_execute_run_instruction_template": (
            row.default_execute_run_instruction_template
        ),
        "default_plan_run_instruction_template": row.default_plan_run_instruction_template,
        "ci_auto_repair_run_instruction_template": (
            row.ci_auto_repair_run_instruction_template
        ),
        "environment_variables": [
            serialize_shared_environment_variable_for_api(item)
            for item in environment_variables
        ],
        "created_at": row.created_at,
        "updated_at": row.updated_at,
    }


async def _load_shared_or_404(db: AsyncSession) -> WorkerSharedConfiguration:
    row = await db.get(WorkerSharedConfiguration, 1, with_for_update=True)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Shared worker configuration is not seeded",
        )
    return row


async def _load_shared_environment_variables(
    db: AsyncSession,
    config_id: int,
) -> list[WorkerSharedEnvironmentVariable]:
    result = await db.execute(
        select(WorkerSharedEnvironmentVariable)
        .where(WorkerSharedEnvironmentVariable.worker_shared_configuration_id == config_id)
        .order_by(WorkerSharedEnvironmentVariable.key.asc())
    )
    return list(result.scalars().all())


async def _rollback(db: AsyncSession) -> None:
    result = db.rollback()
    if inspect.isawaitable(result):
        await result


def _http_shared_error(exc: Exception) -> HTTPException:
    if isinstance(exc, (WorkerProfileValidationError, WorkerKitValidationError)):
        return HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=str(exc),
        )
    return HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail=str(exc),
    )


@router.get("/worker-shared-configuration")
async def get_shared_configuration(
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_admin_user),
):
    """Return the system shared worker configuration."""
    row = await db.get(WorkerSharedConfiguration, 1)
    if row is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Shared worker configuration is not seeded",
        )
    environment_variables = await _load_shared_environment_variables(db, row.id)
    return serialize_shared_configuration_for_api(row, environment_variables)


@router.patch("/worker-shared-configuration")
async def update_shared_configuration(
    request: WorkerSharedConfigurationPatchRequest,
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_admin_user),
):
    """Validate and persist a shared configuration patch (§11.1)."""
    fields = request.model_fields_set
    row = await _load_shared_or_404(db)
    existing_environment = await _load_shared_environment_variables(db, row.id)
    try:
        if request.expected_revision != row.revision:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="shared_configuration_changed",
            )

        runtime_mode, kit_version, kit_path = validate_worker_kit_config(
            runtime_mode=(
                request.runtime_mode
                if "runtime_mode" in fields
                else getattr(row, "runtime_mode", BAKED_IMAGE_MODE)
            ),
            worker_kit_version=(
                request.worker_kit_version
                if "worker_kit_version" in fields
                else getattr(row, "worker_kit_version", None)
            ),
            worker_kit_path=(
                request.worker_kit_path
                if "worker_kit_path" in fields
                else getattr(row, "worker_kit_path", None)
            ),
        )
        mounts = parse_worker_profile_mounts(
            request.volume_mounts
            if "volume_mounts" in fields
            else getattr(row, "volume_mounts", None) or []
        )
        validate_worker_kit_mounts(runtime_mode, mounts)
        execute_template, plan_template, ci_template = validate_profile_templates(
            execute_template=(
                request.default_execute_run_instruction_template
                if "default_execute_run_instruction_template" in fields
                else getattr(row, "default_execute_run_instruction_template", "")
            ),
            plan_template=(
                request.default_plan_run_instruction_template
                if "default_plan_run_instruction_template" in fields
                else getattr(row, "default_plan_run_instruction_template", "")
            ),
            ci_template=(
                request.ci_auto_repair_run_instruction_template
                if "ci_auto_repair_run_instruction_template" in fields
                else getattr(row, "ci_auto_repair_run_instruction_template", "")
            ),
        )

        environment_variables = (
            _normalize_shared_environment(
                request.environment_variables,
                {item.key: item for item in existing_environment},
            )
            if "environment_variables" in fields
            else [
                {"key": item.key, "value": item.value, "is_secret": item.is_secret}
                for item in existing_environment
            ]
        )

        # Construct the prospective shared baseline in memory and statically
        # validate every enabled Profile's combined effective configuration.
        prospective = WorkerSharedConfiguration(
            id=row.id,
            revision=row.revision + 1,
            runtime_mode=runtime_mode,
            worker_kit_version=kit_version,
            worker_kit_path=kit_path,
            volume_mounts=mounts,
            pre_script=(
                request.pre_script
                if "pre_script" in fields
                else getattr(row, "pre_script", "")
            ),
            post_script=(
                request.post_script
                if "post_script" in fields
                else getattr(row, "post_script", "")
            ),
            default_execute_run_instruction_template=execute_template,
            default_plan_run_instruction_template=plan_template,
            ci_auto_repair_run_instruction_template=ci_template,
        )
        shared_context = WorkerSharedConfigurationContext(
            row=prospective,
            environment_variables=tuple(
                WorkerSharedEnvironmentVariable(
                    worker_shared_configuration_id=row.id,
                    key=item["key"],
                    value=item["value"],
                    is_secret=item["is_secret"],
                )
                for item in environment_variables
            ),
        )
        result = await db.execute(
            select(WorkerProfile)
            .where(WorkerProfile.enabled.is_(True))
            .options(
                selectinload(WorkerProfile.default_skills).selectinload(
                    Skill.current_version
                ),
                selectinload(WorkerProfile.environment_variables),
            )
        )
        errors: list[str] = []
        profiles: list[dict[str, Any]] = []
        for profile in result.scalars().all():
            # §7.2/§7.3 (F1): shared environment variables and volume mounts
            # merge per-item into every enabled Profile; a Profile's own
            # set/override/mask rows hide specific shared items. A shared change
            # is therefore validated against every Profile's merged effective
            # configuration, not just profiles that declared inheritance.
            profile_shared = shared_context
            effective = resolve_effective_configuration(profile, profile_shared)
            try:
                validate_effective_configuration(effective)
                validate_runtime_supports_skills(
                    effective,
                    [skill for skill in profile.default_skills if skill.enabled],
                )
            except (WorkerProfileValidationError, SkillValidationError) as exc:
                errors.append(f"Worker Profile '{profile.name}': {exc}")
                continue
            constraints = dict(getattr(profile, "harness_constraints", None) or {})
            harness_key = getattr(profile, "default_harness_key", None) or "claude"
            capabilities = capability_policy(harness_key, constraints)
            skills = [
                {
                    "skill_id": skill.id,
                    "skill_version_id": getattr(
                        getattr(skill, "current_version", None), "id", None
                    ),
                }
                for skill in profile.default_skills
                if bool(getattr(skill, "enabled", False))
            ]
            profiles.append(
                {
                    "id": profile.id,
                    "name": profile.name,
                    "effective_configuration_digest": effective_configuration_digest(
                        effective,
                        docker_host=getattr(profile, "docker_host", None),
                        codegraph_enabled=bool(
                            getattr(profile, "codegraph_enabled", False)
                        ),
                        harness_key=harness_key,
                        harness_config={
                            "capabilities": capabilities,
                            "sandbox_mode": capabilities.get("sandbox_mode"),
                            "constraints": constraints,
                        },
                        skills=skills,
                    ),
                    "valid": True,
                }
            )
        if errors:
            raise WorkerProfileValidationError(
                "Shared configuration is statically invalid for: " + "; ".join(errors)
            )

        row.runtime_mode = runtime_mode
        row.worker_kit_version = kit_version
        row.worker_kit_path = kit_path
        row.volume_mounts = mounts
        row.pre_script = prospective.pre_script
        row.post_script = prospective.post_script
        row.default_execute_run_instruction_template = execute_template
        row.default_plan_run_instruction_template = plan_template
        row.ci_auto_repair_run_instruction_template = ci_template
        row.revision += 1
        await _replace_shared_environment_variables(db, row, environment_variables)
        await db.commit()

        persisted_environment = await _load_shared_environment_variables(db, row.id)
        return {
            **serialize_shared_configuration_for_api(row, persisted_environment),
            "profiles": profiles,
        }
    except HTTPException:
        await _rollback(db)
        raise
    except (WorkerProfileValidationError, WorkerKitValidationError, SkillValidationError) as exc:
        await _rollback(db)
        raise _http_shared_error(exc) from exc


def _normalize_shared_environment(
    items: list[Any],
    existing_by_key: dict[str, WorkerSharedEnvironmentVariable],
) -> list[dict[str, Any]]:
    """Validate and normalize the submitted shared environment list.

    Mirrors the Profile env flow: a blank secret reuses the existing stored
    ciphertext so an admin never needs to resubmit the secret value.
    """
    environment: list[dict[str, Any]] = []
    seen_keys: set[str] = set()
    for item in items:
        key = str(getattr(item, "key", "") or "").strip()
        try:
            validate_worker_environment_variable_key(key)
        except ValueError as exc:
            raise WorkerProfileValidationError(str(exc)) from exc
        if key in seen_keys:
            raise WorkerProfileValidationError(
                f"Duplicate shared environment variable key: {key}"
            )
        seen_keys.add(key)
        is_secret = bool(getattr(item, "is_secret", False))
        value = str(getattr(item, "value", "") or "")
        if is_secret and not value:
            existing_row = existing_by_key.get(key)
            if existing_row is None or not existing_row.is_secret:
                raise WorkerProfileValidationError(
                    f"New secret shared environment variable {key} cannot use a blank value"
                )
            stored_value = existing_row.value
        else:
            stored_value = serialize_worker_environment_variable_value(
                value,
                is_secret=is_secret,
            )
        environment.append(
            {
                "key": key,
                "value": stored_value,
                "is_secret": is_secret,
            }
        )
    return environment


async def _replace_shared_environment_variables(
    db: AsyncSession,
    config: WorkerSharedConfiguration,
    items: list[dict[str, Any]],
) -> None:
    """Replace the shared environment set in place (update/insert, delete stale).

    Mirrors the Profile env replacement so the unique (config_id, key) index is
    never violated within a single flush: existing rows are updated, rows whose
    key is absent are deleted, and only truly new keys are inserted.
    """
    result = await db.execute(
        select(WorkerSharedEnvironmentVariable).where(
            WorkerSharedEnvironmentVariable.worker_shared_configuration_id == config.id
        )
    )
    existing_rows = list(result.scalars().all())
    existing_by_key = {row.key: row for row in existing_rows}
    seen_keys: set[str] = set()
    for item in items:
        key = item["key"]
        seen_keys.add(key)
        existing_row = existing_by_key.get(key)
        if existing_row is None:
            db.add(
                WorkerSharedEnvironmentVariable(
                    worker_shared_configuration_id=config.id,
                    key=key,
                    value=item["value"],
                    is_secret=item["is_secret"],
                )
            )
        else:
            existing_row.value = item["value"]
            existing_row.is_secret = item["is_secret"]
    for row in existing_rows:
        if row.key not in seen_keys:
            await db.delete(row)
    await db.flush()
