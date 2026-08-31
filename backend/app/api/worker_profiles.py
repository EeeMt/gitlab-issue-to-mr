"""Worker profile management API."""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import inspect
import time
import uuid
from datetime import UTC
from types import SimpleNamespace
from typing import Any, Mapping

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, StrictInt, field_validator, model_validator
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import get_effective_settings
from app.core.docker_client import DockerClientWrapper, resolve_docker_connection
from app.core.harness_options import HarnessOptionsError, validate_namespaced_options
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
from app.core.utcnow import utcnow
from app.core.worker_docker_targets import docker_daemon_key
from app.core.worker_kit import (
    BAKED_IMAGE_MODE,
    WorkerKitValidationError,
    validate_worker_kit_config,
)
from app.core.worker_profiles import (
    TaskWorkerRuntime,
    WorkerProfileValidationError,
    build_worker_profile_environment_map,
    build_worker_profile_volume_map,
    current_runtime_verification_digest,
    eligible_v2_harness_keys,
    inspect_v2_worker_image_identity,
    parse_worker_profile_mounts,
    replace_profile_environment_variables,
    serialize_profile_environment_variable_for_api,
    serialize_worker_profile_for_api,
    set_default_worker_profile,
    validate_profile_templates,
    validate_worker_profile_docker_target,
    validate_worker_profile_mount_masks,
)
from app.core.worker_profiles import (
    disable_worker_profile as disable_worker_profile_domain,
)
from app.core.worker_profiles import (
    list_worker_profiles as list_worker_profiles_domain,
)
from app.core.worker_runtime_bundle import (
    build_v2_verification_candidate,
    frozen_v2_adapter_identity,
    v2_launcher_manifest_bytes,
)
from app.core.worker_runtime_readiness import (
    READINESS_UNKNOWN,
    RuntimeProbeTransientError,
    RuntimeReadiness,
    fingerprint_from_docker_target,
    read_runtime_readiness,
    run_deterministic_kit_probe,
    serialize_runtime_readiness,
)
from app.core.worker_shared_configuration import (
    WORKER_KIT_SOURCE_PROFILE,
    WORKER_KIT_SOURCE_SYSTEM,
    WORKER_KIT_SOURCES,
    EffectiveWorkerConfiguration,
    load_shared_configuration,
    resolve_effective_configuration,
    validate_effective_configuration,
)
from app.database import get_db
from app.dependencies.auth import require_admin_user
from app.models import Issue, IssueStatus, WorkerProfile, WorkerProfileEnvironmentVariable

router = APIRouter()


class WorkerProfileEnvironmentVariableRequest(BaseModel):
    id: int | None = None
    key: str = Field(max_length=255)
    value: str | None = None
    is_secret: bool = False
    operation: str = "set"


class WorkerProfileRequestBase(BaseModel):
    name: str | None = Field(default=None, max_length=100)
    description: str | None = None
    enabled: bool | None = None
    image: str | None = Field(default=None, max_length=255)
    worker_kit_source: str | None = Field(default=None, max_length=16)
    runtime_mode: str | None = Field(default=None, max_length=32)
    worker_kit_version: str | None = Field(default=None, max_length=128)
    worker_kit_path: str | None = Field(default=None, max_length=1024)
    docker_host: str | None = Field(default=None, max_length=500)
    docker_tls_ca: str | None = Field(default=None, max_length=1024)
    docker_tls_cert: str | None = Field(default=None, max_length=1024)
    docker_tls_key: str | None = Field(default=None, max_length=1024)
    codegraph_enabled: bool | None = None
    volume_mounts: list[dict[str, Any]] | None = None
    volume_mount_masks: list[str] | None = None
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
    harness_options: dict[str, Any] | None = None
    image_digest: str | None = Field(default=None, max_length=128)
    harness_runtimes: dict[str, Any] | None = None
    expected_shared_revision: int | None = None

    @field_validator("volume_mount_masks")
    @classmethod
    def validate_volume_mount_masks_type(
        cls, value: list[str] | None
    ) -> list[str] | None:
        if value is None:
            return None
        if any(not isinstance(item, str) for item in value):
            raise ValueError("volume_mount_masks must be a list of strings")
        return value

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
    def validate_harness_fields(self) -> WorkerProfileRequestBase:
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
        if self.harness_options is not None:
            try:
                validate_namespaced_options(self.harness_options)
            except HarnessOptionsError as exc:
                raise ValueError(str(exc)) from exc
        return self


class WorkerProfileCreateRequest(WorkerProfileRequestBase):
    name: str = Field(max_length=100)
    image: str = Field(max_length=255)
    worker_kit_source: str = WORKER_KIT_SOURCE_SYSTEM
    runtime_mode: str = BAKED_IMAGE_MODE
    volume_mounts: list[dict[str, Any]] = Field(default_factory=list)
    volume_mount_masks: list[str] = Field(default_factory=list)
    environment_variables: list[WorkerProfileEnvironmentVariableRequest] = Field(
        default_factory=list
    )
    # The three run-instruction templates stay nullable (inherited from
    # WorkerProfileRequestBase): NULL = inherit the shared baseline, matching the
    # update contract. Validation happens on the resolved effective configuration.


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


async def _load_shared_for_validation(
    db: AsyncSession,
    *,
    expected_shared_revision: int | None,
):
    """Load the shared baseline under lock and enforce the optimistic check (§11.2).

    The singleton row is locked with ``SELECT ... FOR UPDATE`` so the baseline
    read, the expected-revision check, and the static combination validation are
    one transactional unit: a concurrent shared-configuration PATCH cannot commit
    between the read and the check, and a Profile save cannot mix a row revision
    with environment variables from a different revision.
    """
    shared = await load_shared_configuration(db, for_update=True)
    if expected_shared_revision is not None and (
        shared.row is None or shared.revision != expected_shared_revision
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="shared_configuration_changed",
        )
    return shared


def _validate_combined_configuration(
    profile: WorkerProfile,
    shared,
    *,
    default_skills: list[Any],
) -> EffectiveWorkerConfiguration:
    """Resolve the profile's effective config and run static combination checks."""
    effective = resolve_effective_configuration(profile, shared)
    validate_effective_configuration(effective)
    validate_runtime_supports_skills(
        effective,
        [skill for skill in default_skills if bool(getattr(skill, "enabled", False))],
    )
    return effective


async def _load_profile_or_404(
    db: AsyncSession,
    profile_id: int,
    *,
    for_update: bool = False,
    populate_existing: bool = False,
) -> WorkerProfile:
    profile = await db.get(
        WorkerProfile,
        profile_id,
        options=[
            selectinload(WorkerProfile.environment_variables),
            selectinload(WorkerProfile.default_skills),
        ],
        with_for_update=for_update,
        populate_existing=populate_existing,
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
    """List worker profiles with admin-only Docker target fields and the §16.2
    overrides/effective/sources/shared_revision/runtime sections."""
    profiles = await list_worker_profiles_domain(db)
    settings = get_effective_settings()
    shared = await load_shared_configuration(db)
    return [
        await _admin_profile_payload(db, profile, settings=settings, shared=shared)
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


def _build_verification_runtime(
    profile: Any,
    effective: EffectiveWorkerConfiguration,
    settings: Any,
) -> TaskWorkerRuntime:
    """Build the resolved runtime the verification container executes (§15.1)."""
    return TaskWorkerRuntime(
        image=effective.image,
        runtime_mode=effective.runtime_mode,
        worker_kit_version=effective.worker_kit_version,
        worker_kit_path=effective.worker_kit_path,
        codegraph_enabled=bool(getattr(profile, "codegraph_enabled", False)),
        volume_mounts=list(effective.volume_mounts),
        environment=build_worker_profile_environment_map(
            effective.environment_variables,
            include_secrets=False,
        ),
        pre_script=effective.pre_script,
        post_script=effective.post_script,
        docker_host=getattr(profile, "docker_host", None),
        docker_tls_ca=getattr(profile, "docker_tls_ca", None),
        docker_tls_cert=getattr(profile, "docker_tls_cert", None),
        docker_tls_key=getattr(profile, "docker_tls_key", None),
    )


def _verification_digest(
    profile: Any,
    effective: EffectiveWorkerConfiguration,
    runtime: TaskWorkerRuntime,
    settings: Any,
) -> str:
    """Compute the verification input digest (§10.2) for the resolved config."""
    return current_runtime_verification_digest(profile, effective, settings)


def _profile_scalar_source(profile: Any, field: str) -> str:
    """Source vocabulary (§7.6) for one Profile scalar.

    ``None`` inherits the shared baseline (``system``); any explicit value,
    including an explicit empty disable, is a ``profile_override``.
    """
    if getattr(profile, field, None) is None:
        return "system"
    return "profile_override"


async def _profile_api_sections(
    db: AsyncSession,
    profile: WorkerProfile,
    *,
    settings: Any,
    shared: Any | None = None,
) -> dict[str, Any]:
    """Build the §16.2 overrides/effective/sources/shared_revision/runtime sections.

    ``matches_current_input`` recomputes the §10.2 verification input digest from
    the current shared baseline + Profile overrides + resolved Docker target and
    compares it to the stored digest, so a Profile whose verification inputs have
    changed since the last successful verification reports ``False`` without the
    client having to diff anything. ``runtime_readiness.status`` is the
    read-time derived status: an expired ``ready`` row reads as ``unknown``.
    """
    shared = shared if shared is not None else await load_shared_configuration(db)
    try:
        effective = resolve_effective_configuration(profile, shared)
        validate_effective_configuration(effective)
    except WorkerProfileValidationError:
        effective = None

    kit_source = (
        str(getattr(profile, "worker_kit_source", WORKER_KIT_SOURCE_PROFILE) or "")
        .strip()
        or WORKER_KIT_SOURCE_PROFILE
    )
    overrides = {
        "worker_kit": (
            None
            if kit_source == WORKER_KIT_SOURCE_SYSTEM
            else {
                "runtime_mode": getattr(profile, "runtime_mode", None),
                "worker_kit_version": getattr(profile, "worker_kit_version", None),
                "worker_kit_path": getattr(profile, "worker_kit_path", None),
            }
        ),
        "pre_script": getattr(profile, "pre_script", None),
        "post_script": getattr(profile, "post_script", None),
        "volume_mounts": list(getattr(profile, "volume_mounts", None) or []),
        "masked_volume_mount_paths": list(
            getattr(profile, "volume_mount_masks", None) or []
        ),
        "environment_variables": [
            serialize_profile_environment_variable_for_api(row)
            for row in (getattr(profile, "environment_variables", None) or [])
        ],
    }
    effective_section = (
        {
            "worker_kit_version": effective.worker_kit_version,
            "worker_kit_path": effective.worker_kit_path,
        }
        if effective is not None
        else {"worker_kit_version": None, "worker_kit_path": None}
    )
    sources = {
        "worker_kit": (
            "system" if kit_source == WORKER_KIT_SOURCE_SYSTEM else "profile_override"
        ),
        "pre_script": _profile_scalar_source(profile, "pre_script"),
        "post_script": _profile_scalar_source(profile, "post_script"),
    }

    stored_digest = getattr(profile, "verified_runtime_configuration_digest", None)
    matches_current_input = False
    if effective is not None and stored_digest:
        try:
            runtime = _build_verification_runtime(profile, effective, settings)
            current_digest = _verification_digest(profile, effective, runtime, settings)
            matches_current_input = current_digest == stored_digest
        except Exception:  # noqa: BLE001 - unresolvable inputs never match
            matches_current_input = False

    readiness = RuntimeReadiness(status=READINESS_UNKNOWN)
    if effective is not None:
        try:
            fingerprint = fingerprint_from_docker_target(
                settings,
                docker_host=getattr(profile, "docker_host", None),
                docker_tls_ca=getattr(profile, "docker_tls_ca", None),
                docker_tls_cert=getattr(profile, "docker_tls_cert", None),
                docker_tls_key=getattr(profile, "docker_tls_key", None),
                runtime_mode=effective.runtime_mode,
                worker_kit_version=effective.worker_kit_version,
                worker_kit_path=effective.worker_kit_path,
            )
            readiness = await read_runtime_readiness(
                db,
                fingerprint,
                # Profile verification probes the full Kit whenever any
                # enabled Harness opts into V2, so the admin summary must read
                # the same readiness scope even when the default Harness is V1.
                require_content_inventory=bool(eligible_v2_harness_keys(profile)),
            )
        except Exception:  # noqa: BLE001 - unresolvable locator is never a known state
            readiness = RuntimeReadiness(status=READINESS_UNKNOWN)

    return {
        "overrides": overrides,
        "effective": effective_section,
        "sources": sources,
        "shared_revision": shared.revision,
        "runtime_verification": {
            "verified_at": getattr(profile, "verified_at", None),
            "verified_runtime_configuration_digest": stored_digest,
            "matches_current_input": matches_current_input,
        },
        "runtime_readiness": {
            "status": readiness.status,
            "checked_at": readiness.checked_at.isoformat() if readiness.checked_at else None,
            "ready_until": readiness.ready_until.isoformat() if readiness.ready_until else None,
        },
    }


async def _admin_profile_payload(
    db: AsyncSession,
    profile: WorkerProfile,
    *,
    settings: Any,
    shared: Any | None = None,
) -> dict[str, Any]:
    """Admin Profile response: the flat fields plus the §16.2 sections."""
    payload = serialize_worker_profile_for_api(profile, include_docker_target=True)
    payload.update(
        await _profile_api_sections(db, profile, settings=settings, shared=shared)
    )
    return payload


def _runtime_unavailable_detail(
    readiness: RuntimeReadiness,
    *,
    worker_profile_id: int,
    worker_profile_name: str,
) -> dict[str, Any]:
    return {
        "code": "worker_runtime_unavailable",
        "message": "Worker runtime is unavailable; resolve the failure and re-verify",
        "worker_profile_id": worker_profile_id,
        "worker_profile_name": worker_profile_name,
        "failure_code": readiness.failure_code,
        "failure_message": readiness.failure_message,
        "checked_at": readiness.checked_at.isoformat() if readiness.checked_at else None,
    }


async def _clear_profile_verification(
    db: AsyncSession, profile: WorkerProfile, *, expected_generation: int | None = None
) -> None:
    """Clear the profile's verification state after a deterministic failure."""
    generation = int(getattr(profile, "v2_worker_image_identity_generation", 0) or 0)
    where = WorkerProfile.id == profile.id
    if expected_generation is not None:
        where = where & (WorkerProfile.v2_worker_image_identity_generation == expected_generation)
    result = await db.execute(
        update(WorkerProfile)
        .where(where)
        .values(
            verified_at=None,
            verified_runtime_configuration_digest=None,
            v2_worker_image_identity=None,
            v2_harness_verification_evidence=None,
            v2_worker_image_identity_generation=generation + 1,
            worker_kit_identity=None,
            worker_kit_identity_generation=generation + 1,
        )
    )
    if expected_generation is not None and result.rowcount != 1:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="worker_profile_verification_superseded")
    await db.commit()


def _profile_explicitly_requests_v2(profile: WorkerProfile) -> bool:
    return bool(eligible_v2_harness_keys(profile))


def _v2_harness_evidence(
    profile: WorkerProfile, *, harness_key: str, verification_digest: str,
    image_identity: dict[str, str], adapter_identity: dict[str, str], generation: int, verified_at,
) -> dict[str, Any]:
    return {
        "schema": "codify.worker-harness-verification/v1",
        "harness_key": harness_key,
        "contract_version": "codify.worker.harness/v2",
        "adapter": dict(adapter_identity),
        "verification_input_digest": verification_digest,
        "image_identity": dict(image_identity),
        "generation": generation,
        # The portable validator requires an explicit UTC offset; DB columns
        # stay naive UTC, so the evidence document carries the aware form.
        "verified_at": (
            verified_at.replace(tzinfo=UTC).isoformat()
            if verified_at.tzinfo is None
            else verified_at.isoformat()
        ),
    }


def _verification_cli_bin(
    readiness: Any, profile: WorkerProfile, harness_key: str,
) -> str:
    """Resolve the exact container CLI path for one verification container.

    ``worker_kit`` (the implicit default) resolves the executable from the
    frozen Kit manifest's harness inventory observed by the strict probe;
    ``host_mount`` is the explicit per-Harness break-glass and uses the
    declared executable path. An absent Kit entry is a deterministic
    ``harness_cli_unavailable`` rejection — there is no image/PATH fallback.
    """
    runtime = (getattr(profile, "harness_runtimes", None) or {}).get(harness_key)
    source = runtime.get("source") if isinstance(runtime, Mapping) else None
    if source == "host_mount":
        executable_path = runtime.get("executable_path")
        if not isinstance(executable_path, str) or not executable_path.startswith("/"):
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail={
                    "code": "harness_cli_unavailable",
                    "message": (
                        f"host_mount runtime for {harness_key!r} has no absolute "
                        "executable_path"
                    ),
                },
            )
        return executable_path
    inventory = getattr(readiness, "harness_inventory", None) or {}
    entry = inventory.get(harness_key)
    path = entry.get("path") if isinstance(entry, Mapping) else None
    if (
        not isinstance(entry, Mapping)
        or entry.get("availability") != "present"
        or not isinstance(path, str)
        or not path.startswith("/")
    ):
        reason = (
            entry.get("reason_code")
            if isinstance(entry, Mapping) and entry.get("availability") == "absent"
            else None
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "code": "harness_cli_unavailable",
                "message": (
                    f"Harness {harness_key!r} is not available in Worker Kit "
                    f"{getattr(readiness, 'worker_kit_version', None)!r}"
                ),
                "reason_code": reason,
            },
        )
    return path


@router.post("/worker-profiles/{profile_id}/verify-runtime")
async def verify_worker_profile_runtime(
    profile_id: int,
    request: WorkerRuntimeVerificationRequest,
    db: AsyncSession = Depends(get_db),
    _admin=Depends(require_admin_user),
):
    """Two-layer runtime verification (§15.1).

    Layer 1 runs the strict, side-effect-free Kit probe through the
    generation/CAS readiness service against the profile's resolved Docker
    target. Layer 2 runs the profile-specific ``--verify`` container (image,
    mounts, harness/CLI, optional smoke) and, on success, stores the immutable
    image digest, the verification timestamp, and the verification input digest.
    Re-verification is always explicit and always re-probes the Kit.
    """
    profile = await _load_profile_or_404(db, profile_id)
    shared = await load_shared_configuration(db)
    try:
        effective = resolve_effective_configuration(profile, shared)
        validate_effective_configuration(effective)
    except WorkerProfileValidationError as exc:
        raise _http_profile_error(exc) from exc
    if effective.runtime_mode == BAKED_IMAGE_MODE:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Runtime verification requires mounted_kit mode",
        )
    settings = get_effective_settings()
    runtime = _build_verification_runtime(profile, effective, settings)
    connection = runtime.docker_connection(settings)
    verification_digest = _verification_digest(profile, effective, runtime, settings)
    v2_harness_keys = eligible_v2_harness_keys(profile)
    requires_v2_identity = bool(v2_harness_keys)
    # A newer explicit verification supersedes this attempt even if the
    # configuration digest happens to be identical. Persist the generation
    # before Docker I/O so a late image observation cannot overwrite it.
    # Every verify attempt, including V1, owns one Profile epoch before any
    # Docker I/O.  Shared/Profile invalidation increments the same epoch, so a
    # slow V1 success cannot write stale values back after a configuration edit.
    prior_generation = int(getattr(profile, "v2_worker_image_identity_generation", 0) or 0)
    result = await db.execute(
        update(WorkerProfile)
        .where(
            WorkerProfile.id == profile.id,
            WorkerProfile.v2_worker_image_identity_generation == prior_generation,
        )
        .values(
            verified_at=None,
            verified_runtime_configuration_digest=None,
            v2_worker_image_identity=None,
            v2_harness_verification_evidence=None,
                       v2_worker_image_identity_generation=prior_generation + 1,
            worker_kit_identity=None,
            worker_kit_identity_generation=prior_generation + 1,
        )
    )
    if result.rowcount != 1:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="worker_profile_verification_superseded")
    identity_generation = prior_generation + 1
    await db.commit()
    started_at = time.monotonic()
    candidate_verified_at = utcnow()

    # Layer 1: strict Kit probe through the generation/CAS readiness service.
    try:
        outcome = await run_deterministic_kit_probe(
            db,
            connection=connection,
            image=runtime.image,
            runtime_mode=runtime.runtime_mode,
            worker_kit_version=runtime.worker_kit_version or "",
            worker_kit_path=runtime.worker_kit_path or "",
            ttl_seconds=settings.worker_runtime_readiness_ttl_seconds,
            require_content_inventory=requires_v2_identity,
        )
    except RuntimeProbeTransientError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "worker_runtime_verification_transient_failure",
                "message": f"Worker Kit probe could not reach a conclusion: {exc}",
            },
        ) from exc
    if outcome.is_unavailable:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=_runtime_unavailable_detail(
                outcome.readiness,
                worker_profile_id=profile_id,
                worker_profile_name=profile.name,
            ),
        )
    # The content-addressed Worker Kit identity observed by the strict probe is
    # frozen into the Profile and later into every Task snapshot/Bundle binding
    # (execution identity = image_identity + kit_identity + bundle_digest).
    worker_kit_identity = (
        dict(outcome.readiness.kit_identity)
        if isinstance(outcome.readiness.kit_identity, Mapping)
        else None
    )
    if requires_v2_identity and worker_kit_identity is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "worker_kit_identity_missing",
                "message": "The strict Kit probe did not record a Worker Kit identity; "
                "re-run the verification against a Kit-owned release",
            },
        )

    # Layer 2: profile-specific verification container.
    overrides = runtime.container_overrides()
    verification_volumes = build_worker_profile_volume_map(runtime.volume_mounts)
    verification_volumes.update(overrides["volumes"])
    base_command = ["--verify"]
    if runtime_uses_skill_capable_worker_kit(runtime):
        base_command.append("--require-skill-support")
    smoke_command = (request.smoke_command or "").strip()
    if smoke_command:
        base_command.extend(["--smoke", smoke_command])
    candidate_evidence_by_key: dict[str, dict[str, Any]] = {}

    def verify_runtime() -> tuple[int, str, str, dict[str, str] | None, dict[str, str]]:
        client = DockerClientWrapper(connection)
        container = None
        try:
            client.client.images.get(runtime.image)
            image_identity = None
            if requires_v2_identity:
                # The V2 identity is read from the same daemon image before the
                # verification container is created. It is intentionally not the
                # backend's mounted release lock.
                image_identity = inspect_v2_worker_image_identity(connection, runtime.image)
                repo_digest = image_identity["image_reference"]
            else:
                repo_digest = client.resolve_image_repo_digest(runtime.image)
            # V1-only Profiles retain one validation.  Every eligible V2
            # Harness is independently executed against the same frozen image;
            # a successful default Harness can never authorize another key.
            keys = v2_harness_keys or (profile.default_harness_key or "claude",)
            logs_by_key: dict[str, str] = {}
            for harness_key in keys:
                candidate_evidence = None
                candidate_archive = None
                if requires_v2_identity:
                    adapter_identity = frozen_v2_adapter_identity(
                        harness_key,
                        worker_image_identity=image_identity,
                        worker_kit_identity=worker_kit_identity,
                    )
                    candidate_evidence = _v2_harness_evidence(
                        profile, harness_key=harness_key,
                        verification_digest=current_runtime_verification_digest(
                            profile, effective, settings, harness_key=harness_key
                        ), image_identity=image_identity, adapter_identity=adapter_identity,
                        generation=identity_generation, verified_at=candidate_verified_at,
                    )
                    candidate_evidence_by_key[harness_key] = candidate_evidence
                    _candidate_manifest, candidate_archive = build_v2_verification_candidate(
                        source_dir=None,
                        worker_image_identity=image_identity,
                        worker_kit_identity=worker_kit_identity,
                        harness_verification_evidence=candidate_evidence,
                    )
                cli_bin = _verification_cli_bin(
                    outcome.readiness, profile, harness_key
                )
                candidate_bindings: dict[str, str] = {}
                if candidate_archive is not None:
                    # The verification candidate is a real frozen Bundle: the
                    # launcher requires the same digest/contract/Adapter
                    # bindings a Task execution would carry.
                    launcher_bytes = v2_launcher_manifest_bytes(
                        SimpleNamespace(manifest=_candidate_manifest)
                    )
                    candidate_bindings = {
                        "CODIFY_RUNTIME_MANIFEST_DIGEST": hashlib.sha256(
                            launcher_bytes
                        ).hexdigest(),
                        "CODIFY_RUNTIME_BUNDLE_DIGEST": str(
                            _candidate_manifest.get("bundle_digest") or ""
                        ),
                        "CODIFY_RUNTIME_CONTRACT_VERSION": str(
                            _candidate_manifest.get("contract_version") or ""
                        ),
                        "CODIFY_ADAPTER_VERSION": str(
                            (
                                (
                                    _candidate_manifest.get("adapters") or {}
                                )
                                .get(harness_key, {})
                                .get("adapter", {})
                            ).get("version")
                            or ""
                        ),
                                        }
                container = client.create_container(
                    image=(image_identity or {}).get("image_reference") or runtime.image,
                    command=list(base_command),
                    environment={
                        **runtime.environment, **overrides["environment"],
                        "CODIFY_HARNESS_KEY": harness_key, "CODIFY_RUNTIME_IMAGE": runtime.image,
                        "CODIFY_HARNESS_CLI_BIN": cli_bin,
                        **candidate_bindings,
                        **(
                            {
                                "CODIFY_ORCHESTRATION_DIR": "/tmp/codify-runtime/orchestration",
                                "CODIFY_RUNTIME_VERIFICATION_MANIFEST": "/tmp/codify-runtime/orchestration/manifest.json",
                            }
                            if candidate_archive is not None else {}
                        ),
                    },
                    volumes=verification_volumes, entrypoint=overrides["entrypoint"], user=overrides["user"],
                    tmpfs={"/workspace": "rw,exec,mode=1777"},
                    start=candidate_archive is None,
                    name=f"codify-worker-kit-verify-{profile_id}-{harness_key}-{uuid.uuid4().hex[:8]}",
                    labels={"codify.worker_kit_verification": "true", "codify.worker_kit_version": runtime.worker_kit_version or ""},
                )
                if candidate_archive is not None:
                    # The archive's top-level directory is codify-runtime/;
                    # extracting into the always-existing /tmp avoids the
                    # daemon's 404 for a missing destination directory.
                    client.put_archive(container, "/tmp", candidate_archive)
                    client.start_container(container)
                exit_code, logs = client.wait_for_container(container, timeout=180)
                logs_by_key[harness_key] = logs
                container.remove(force=True, v=True)
                container = None
                if exit_code != 0:
                    return exit_code, logs, repo_digest, image_identity, logs_by_key
            return 0, "\n".join(logs_by_key.values()), repo_digest, image_identity, logs_by_key
        finally:
            if container is not None:
                with contextlib.suppress(Exception):
                    container.remove(force=True, v=True)
            with contextlib.suppress(Exception):
                client.close()

    try:
        exit_code, logs, repo_digest, image_identity, logs_by_key = await asyncio.wait_for(
            asyncio.to_thread(verify_runtime),
            timeout=200,
        )
    except HTTPException:
        # Deterministic rejection (e.g. harness_cli_unavailable for a Harness
        # that is absent from the Kit inventory) keeps its own status code.
        raise
    except Exception as exc:
        # Transient: keep any previously verified digest/timestamp (§15.1).
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "worker_runtime_verification_transient_failure",
                "message": f"Worker runtime verification could not start: {exc}",
            },
        ) from exc
    if exit_code != 0:
        # Deterministic profile-specific failure: clear verification (§15.1).
        await _clear_profile_verification(db, profile, expected_generation=identity_generation)
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail={
                "message": "Worker runtime verification failed",
                "exit_code": exit_code,
                "logs": logs[-8000:],
            },
        )

    # Reload profile+shared and recompute the digest: if the verification
    # inputs changed while verifying, the result is superseded (§15.1).
    fresh_profile = await _load_profile_or_404(db, profile_id, populate_existing=True)
    fresh_shared = await load_shared_configuration(db, populate_existing=True)
    try:
        fresh_effective = resolve_effective_configuration(fresh_profile, fresh_shared)
        validate_effective_configuration(fresh_effective)
    except WorkerProfileValidationError as exc:
        raise _http_profile_error(exc) from exc
    fresh_runtime = _build_verification_runtime(fresh_profile, fresh_effective, settings)
    fresh_digest = _verification_digest(fresh_profile, fresh_effective, fresh_runtime, settings)
    if fresh_digest != verification_digest:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="worker_profile_verification_superseded",
        )
    where = (
        (WorkerProfile.id == profile.id)
        & (WorkerProfile.v2_worker_image_identity_generation == identity_generation)
    )
    verified_at = candidate_verified_at
    evidence_by_key = dict(candidate_evidence_by_key)
    if requires_v2_identity and set(evidence_by_key) != set(v2_harness_keys):
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="worker_profile_verification_superseded")
    result = await db.execute(
        update(WorkerProfile)
        .where(where)
        .values(
            verified_at=verified_at,
            verified_runtime_configuration_digest=verification_digest,
            image_digest=repo_digest,
            v2_worker_image_identity=image_identity if requires_v2_identity else None,
                        v2_harness_verification_evidence=evidence_by_key if requires_v2_identity else None,
            worker_kit_identity=(
                worker_kit_identity if requires_v2_identity else None
            ),
            worker_kit_identity_generation=identity_generation,
        )
    )
    if result.rowcount != 1:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="worker_profile_verification_superseded")
    await db.commit()

    profile.verified_at = verified_at
    profile.verified_runtime_configuration_digest = verification_digest
    profile.image_digest = repo_digest
    profile.v2_worker_image_identity = image_identity if requires_v2_identity else None
    profile.v2_harness_verification_evidence = evidence_by_key if requires_v2_identity else None
    profile.worker_kit_identity = worker_kit_identity if requires_v2_identity else None
    profile.worker_kit_identity_generation = identity_generation

    return {
        "ok": True,
        "image": runtime.image,
        "image_digest": repo_digest,
        "verified_at": profile.verified_at.isoformat() if profile.verified_at else None,
        "verified_runtime_configuration_digest": verification_digest,
        "worker_kit_version": runtime.worker_kit_version,
        "docker_host": connection.host,
        "elapsed_ms": round((time.monotonic() - started_at) * 1000),
        "omitted_secret_environment_keys": sorted(
            str(item.get("key") or "")
            for item in effective.environment_variables
            if bool(item.get("is_secret"))
        ),
        "logs": logs[-8000:],
        "runtime_readiness": serialize_runtime_readiness(outcome.readiness),
        "v2_harnesses_verified": list(v2_harness_keys),
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
        kit_source = request.worker_kit_source or WORKER_KIT_SOURCE_SYSTEM
        if kit_source not in WORKER_KIT_SOURCES:
            raise WorkerProfileValidationError(
                f"worker_kit_source must be one of: {', '.join(sorted(WORKER_KIT_SOURCES))}"
            )
        if all(
            template is not None
            for template in (
                request.default_execute_run_instruction_template,
                request.default_plan_run_instruction_template,
                request.ci_auto_repair_run_instruction_template,
            )
        ):
            execute_template, plan_template, ci_template = validate_profile_templates(
                execute_template=request.default_execute_run_instruction_template,
                plan_template=request.default_plan_run_instruction_template,
                ci_template=request.ci_auto_repair_run_instruction_template,
            )
        else:
            # A NULL template inherits the shared value; validation happens on the
            # resolved effective configuration below.
            execute_template = request.default_execute_run_instruction_template
            plan_template = request.default_plan_run_instruction_template
            ci_template = request.ci_auto_repair_run_instruction_template
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
        masks = validate_worker_profile_mount_masks(
            request.volume_mount_masks,
            volume_mounts=mounts,
        )
        profile = WorkerProfile(
            name=name,
            description=request.description,
            enabled=True if request.enabled is None else request.enabled,
            is_default=False,
            image=image,
            worker_kit_source=kit_source,
            runtime_mode=runtime_mode,
            worker_kit_version=kit_version,
            worker_kit_path=kit_path,
            docker_host=docker_host,
            docker_tls_ca=tls_ca,
            docker_tls_cert=tls_cert,
            docker_tls_key=tls_key,
            codegraph_enabled=bool(request.codegraph_enabled),
            volume_mounts=mounts,
            volume_mount_masks=masks,
            pre_script=request.pre_script,
            post_script=request.post_script,
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
            harness_options=validate_namespaced_options(request.harness_options),
            image_digest=request.image_digest,
            harness_runtimes=request.harness_runtimes or {},
            default_skills=[],
        )
        shared = await _load_shared_for_validation(
            db,
            expected_shared_revision=request.expected_shared_revision,
        )
        effective = _validate_combined_configuration(profile, shared, default_skills=[])
        db.add(profile)
        await db.flush()
        profile.default_skills.extend(
            await load_enabled_skills(db, request.default_skill_ids or [])
        )
        # The resolved effective configuration is unchanged by the environment
        # replacement below, so skills are validated against it directly to avoid
        # a lazy load of the freshly flushed relationship.
        validate_runtime_supports_skills(
            effective,
            [
                skill
                for skill in (getattr(profile, "default_skills", None) or [])
                if bool(getattr(skill, "enabled", False))
            ],
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
        return await _admin_profile_payload(
            db, profile, settings=get_effective_settings()
        )
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
    # Global lock order: Shared configuration before an individual Profile.
    # Shared PATCH invalidates Profiles under this same order, preventing the
    # Profile→Shared / Shared→Profile deadlock.
    shared = await _load_shared_for_validation(
        db, expected_shared_revision=request.expected_shared_revision
    )
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
            "harness_options",
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
            if "harness_options" in fields:
                profile.harness_options = validate_namespaced_options(request.harness_options)
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
        if "worker_kit_source" in fields:
            kit_source = request.worker_kit_source or WORKER_KIT_SOURCE_SYSTEM
            if kit_source not in WORKER_KIT_SOURCES:
                raise WorkerProfileValidationError(
                    "worker_kit_source must be one of: "
                    + ", ".join(sorted(WORKER_KIT_SOURCES))
                )
            profile.worker_kit_source = kit_source
        if "volume_mounts" in fields and request.volume_mounts is not None:
            profile.volume_mounts = parse_worker_profile_mounts(request.volume_mounts)
        if "volume_mount_masks" in fields and request.volume_mount_masks is not None:
            profile.volume_mount_masks = validate_worker_profile_mount_masks(
                request.volume_mount_masks,
                volume_mounts=profile.volume_mounts or [],
            )
        # §7.3/§24.17: a normalized container_path must never be both set and
        # masked. Revalidate the full set whenever either field is patched so a
        # mounts-only PATCH cannot leave a set/mask conflict behind.
        if "volume_mounts" in fields or "volume_mount_masks" in fields:
            profile.volume_mount_masks = validate_worker_profile_mount_masks(
                profile.volume_mount_masks,
                volume_mounts=profile.volume_mounts or [],
            )
        if "pre_script" in fields:
            # NULL inherits the shared script; "" is an explicit disable.
            profile.pre_script = request.pre_script
        if "post_script" in fields:
            profile.post_script = request.post_script
        template_fields = {
            "default_execute_run_instruction_template",
            "default_plan_run_instruction_template",
            "ci_auto_repair_run_instruction_template",
        }
        if template_fields & fields:
            merged_templates: dict[str, str | None] = {}
            for field in template_fields:
                if field in fields:
                    # A request value of None restores inheritance from the
                    # shared configuration; distinguish it from "not provided"
                    # (keep the profile's current value).
                    merged_templates[field] = getattr(request, field)
                else:
                    merged_templates[field] = getattr(profile, field)
            if all(merged_templates.values()):
                # All three are explicit: validate the merged non-NULL view now.
                execute_template, plan_template, ci_template = validate_profile_templates(
                    execute_template=merged_templates["default_execute_run_instruction_template"],
                    plan_template=merged_templates["default_plan_run_instruction_template"],
                    ci_template=merged_templates["ci_auto_repair_run_instruction_template"],
                )
                profile.default_execute_run_instruction_template = execute_template
                profile.default_plan_run_instruction_template = plan_template
                profile.ci_auto_repair_run_instruction_template = ci_template
            else:
                # At least one template inherits the shared value; apply the
                # explicit ones as-is and validate the resolved combination later.
                if "default_execute_run_instruction_template" in fields:
                    profile.default_execute_run_instruction_template = (
                        request.default_execute_run_instruction_template
                    )
                if "default_plan_run_instruction_template" in fields:
                    profile.default_plan_run_instruction_template = (
                        request.default_plan_run_instruction_template
                    )
                if "ci_auto_repair_run_instruction_template" in fields:
                    profile.ci_auto_repair_run_instruction_template = (
                        request.ci_auto_repair_run_instruction_template
                    )
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
        _validate_combined_configuration(
            profile,
            shared,
            default_skills=getattr(profile, "default_skills", None) or [],
        )

        # Changing the image, Kit, or Harness allowlist/constraints invalidates
        # the prior verification; existing Task snapshots are unaffected.
        stale_fields = {
            "image",
            "worker_kit_source",
            "runtime_mode",
            "worker_kit_version",
            "worker_kit_path",
            "volume_mounts",
            "volume_mount_masks",
            "enabled_harnesses",
            "default_harness_key",
            "harness_constraints",
            "harness_runtimes",
            "docker_host",
            "docker_tls_ca",
            "docker_tls_cert",
            "docker_tls_key",
            "environment_variables",
        }
        if stale_fields & fields:
            profile.image_digest = None
            profile.verified_at = None
            profile.verified_runtime_configuration_digest = None
            profile.v2_worker_image_identity = None
            profile.v2_harness_verification_evidence = None
            profile.v2_worker_image_identity_generation = (
                int(getattr(profile, "v2_worker_image_identity_generation", 0) or 0) + 1
            )
            profile.worker_kit_identity = None
            profile.worker_kit_identity_generation = (
                int(getattr(profile, "worker_kit_identity_generation", 0) or 0) + 1
            )

        await db.commit()
        await db.refresh(
            profile,
            attribute_names=["environment_variables", "default_skills"],
        )
        return await _admin_profile_payload(
            db, profile, settings=get_effective_settings()
        )
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
        return await _admin_profile_payload(
            db, profile, settings=get_effective_settings()
        )
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
        return await _admin_profile_payload(
            db, profile, settings=get_effective_settings()
        )
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
    # Keep the global Shared -> Profile lock order.  Shared PATCH invalidates
    # Profile verification evidence under the same order, so loading source
    # first would reintroduce the Profile -> Shared deadlock.
    shared = await load_shared_configuration(db, for_update=True)
    source = await _load_profile_or_404(db, profile_id, for_update=True)
    try:
        source_skill_ids = [skill.id for skill in source.default_skills]
        default_skills = await load_worker_profile_skills(
            db,
            source_skill_ids,
            retained_disabled_skill_ids=source_skill_ids,
        )
        copy = WorkerProfile(
            name=await _unique_copy_name(db, source.name),
            description=source.description,
            enabled=True,
            is_default=False,
            image=source.image,
            worker_kit_source=getattr(source, "worker_kit_source", WORKER_KIT_SOURCE_PROFILE),
            runtime_mode=getattr(source, "runtime_mode", BAKED_IMAGE_MODE),
            worker_kit_version=getattr(source, "worker_kit_version", None),
            worker_kit_path=getattr(source, "worker_kit_path", None),
            docker_host=getattr(source, "docker_host", None),
            docker_tls_ca=getattr(source, "docker_tls_ca", None),
            docker_tls_cert=getattr(source, "docker_tls_cert", None),
            docker_tls_key=getattr(source, "docker_tls_key", None),
            codegraph_enabled=bool(getattr(source, "codegraph_enabled", False)),
            volume_mounts=list(source.volume_mounts or []),
            volume_mount_masks=list(getattr(source, "volume_mount_masks", None) or []),
            pre_script=source.pre_script,
            post_script=source.post_script,
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
                    operation=getattr(row, "operation", "set") or "set",
                )
                for row in source.environment_variables
            ],
            # §11.3: the copy carries the source's Harness intent verbatim so a
            # duplicate of a non-default-Harness profile still executes with the
            # same adapter allowlist, default harness, constraints, and runtimes.
            enabled_harnesses=list(getattr(source, "enabled_harnesses", None) or ["claude"]),
            default_harness_key=getattr(source, "default_harness_key", None) or "claude",
            harness_constraints=dict(getattr(source, "harness_constraints", None) or {}),
            harness_options=dict(getattr(source, "harness_options", None) or {}),
            harness_runtimes=dict(getattr(source, "harness_runtimes", None) or {}),
            default_skills=default_skills,
        )
        # §11.3: the copy carries the source's inheritance/override/mask intent.
        # Re-validate its resolved effective configuration and its skills against
        # that resolved config (not the raw source columns), under the locked
        # shared baseline so it cannot change between validation and save.
        effective = resolve_effective_configuration(copy, shared)
        validate_effective_configuration(effective)
        validate_runtime_supports_skills(
            effective,
            [skill for skill in default_skills if bool(getattr(skill, "enabled", False))],
        )
        db.add(copy)
        await db.commit()
        await db.refresh(copy, attribute_names=["environment_variables", "default_skills"])
        return await _admin_profile_payload(
            db, copy, settings=get_effective_settings(), shared=shared
        )
    except (WorkerProfileValidationError, SkillValidationError) as exc:
        await _rollback(db)
        raise _http_profile_error(exc) from exc
