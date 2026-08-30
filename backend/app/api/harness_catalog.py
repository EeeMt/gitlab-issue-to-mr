"""Safe display catalog for frozen Harness Runtime Bundles.

The catalog is deliberately a projection, rather than a raw manifest.  It is
the only Harness capability input intended for product surfaces: callers never
receive adapter source metadata, artifact locations, or executable paths.
"""

from __future__ import annotations

import json
from typing import Any, Mapping

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.api.task_operations import get_task_with_access_check
from app.config import get_effective_settings
from app.core.harness_protocol import HARNESS_CONTRACT_VERSION_V2
from app.core.harness_registry import (
    HarnessRegistryError,
    registry_catalog_from_manifest,
)
from app.core.worker_kit_inventory import (
    ABSENT_REASON_CODES,
    AVAILABILITY_ABSENT,
    AVAILABILITY_PRESENT,
)
from app.core.worker_profiles import get_default_worker_profile
from app.core.worker_runtime_bundle import (
    default_runtime_source_dir,
    harness_manifest_from_bundle,
    load_bound_runtime_bundle,
)
from app.core.worker_runtime_readiness import (
    READINESS_READY,
    READINESS_UNAVAILABLE,
    RuntimeReadiness,
    read_runtime_readiness,
    readiness_for_profile,
)
from app.database import get_db
from app.dependencies.auth import get_optional_current_user
from app.dependencies.project_access import ProjectAccessScope, require_project_access_scope
from app.models import (
    Task,
    TaskWorkerProfileSnapshot,
    User,
    WorkerProfile,
    WorkerRuntimeBundle,
)

router = APIRouter()

CATALOG_AVAILABILITY_PRESENT = "present"
CATALOG_AVAILABILITY_UNAVAILABLE = "unavailable"
CATALOG_AVAILABILITY_UNKNOWN = "unknown"

REASON_PROFILE_UNAVAILABLE = "worker_profile_unavailable"
REASON_PROFILE_DISABLED = "profile_disabled"
REASON_HARNESS_DISABLED = "harness_disabled"
REASON_TASK_HARNESS_BOUND = "task_harness_bound"
REASON_RUNTIME_NOT_VERIFIED = "runtime_not_verified"
REASON_WORKER_KIT_UNAVAILABLE = "worker_kit_unavailable"
REASON_HOST_MOUNT = "host_mount"


def _catalog_availability(
    harness_key: str,
    readiness: RuntimeReadiness | None,
    runtime: Mapping[str, Any] | None,
) -> tuple[str, str | None]:
    """Project runtime facts into the public, path-free availability state."""
    if isinstance(runtime, Mapping) and runtime.get("source") == "host_mount":
        # host_mount is an explicit per-Harness source. Its executable path is
        # deliberately not returned by this API.
        return CATALOG_AVAILABILITY_PRESENT, REASON_HOST_MOUNT

    if readiness is None or readiness.status != READINESS_READY:
        if readiness is not None and readiness.status == READINESS_UNAVAILABLE:
            return CATALOG_AVAILABILITY_UNAVAILABLE, REASON_WORKER_KIT_UNAVAILABLE
        return CATALOG_AVAILABILITY_UNKNOWN, REASON_RUNTIME_NOT_VERIFIED

    inventory = readiness.harness_inventory
    if not isinstance(inventory, Mapping):
        return CATALOG_AVAILABILITY_UNKNOWN, REASON_RUNTIME_NOT_VERIFIED
    inventory_entry = inventory.get(harness_key)
    if not isinstance(inventory_entry, Mapping):
        return CATALOG_AVAILABILITY_UNAVAILABLE, REASON_WORKER_KIT_UNAVAILABLE
    if inventory_entry.get("availability") == AVAILABILITY_PRESENT:
        return CATALOG_AVAILABILITY_PRESENT, None
    if (
        inventory_entry.get("availability") == AVAILABILITY_ABSENT
        and inventory_entry.get("reason_code") in ABSENT_REASON_CODES
    ):
        return CATALOG_AVAILABILITY_UNAVAILABLE, inventory_entry["reason_code"]
    # Readiness records are validated before persistence. If an old or
    # malformed row gets here, fail closed without returning its contents.
    return CATALOG_AVAILABILITY_UNAVAILABLE, REASON_WORKER_KIT_UNAVAILABLE


def _catalog_with_runtime_state(
    catalog: list[dict[str, Any]],
    *,
    profile: Any | None = None,
    readiness: RuntimeReadiness | None = None,
    readiness_by_harness: Mapping[str, RuntimeReadiness] | None = None,
    bound_harness_key: str | None = None,
    runtime_overrides: Mapping[str, Mapping[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Add orthogonal Profile and runtime state to a safe adapter projection.

    ``enabled`` comes from the editable Profile only for the current catalog.
    A frozen Task instead supplies ``bound_harness_key`` so later Profile edits
    cannot change what its historical catalog reports. ``availability`` is
    derived from the Kit readiness observation; unknown remains selectable
    because the create gate intentionally lets the scheduler perform a fresh
    probe, while known unavailable entries are disabled.
    """
    runtime_overrides = runtime_overrides or {}
    readiness = readiness or RuntimeReadiness(status=CATALOG_AVAILABILITY_UNKNOWN)
    readiness_by_harness = readiness_by_harness or {}

    if bound_harness_key is not None:
        enabled_keys = {bound_harness_key}
        profile_available = True
    elif profile is None:
        enabled_keys = set()
        profile_available = False
    else:
        profile_available = True
        enabled_keys = {
            key
            for key in (getattr(profile, "enabled_harnesses", None) or ["claude"])
            if isinstance(key, str)
        }

    profile_enabled = profile_available and bool(getattr(profile, "enabled", True))
    runtimes = getattr(profile, "harness_runtimes", None) if profile is not None else None
    if not isinstance(runtimes, Mapping):
        runtimes = {}

    result: list[dict[str, Any]] = []
    for entry in catalog:
        key = entry["key"]
        if bound_harness_key is not None:
            enabled = key in enabled_keys
            enabled_reason = None if enabled else REASON_TASK_HARNESS_BOUND
        elif not profile_available:
            enabled = False
            enabled_reason = REASON_PROFILE_UNAVAILABLE
        elif not profile_enabled:
            enabled = False
            enabled_reason = REASON_PROFILE_DISABLED
        else:
            enabled = key in enabled_keys
            enabled_reason = None if enabled else REASON_HARNESS_DISABLED

        runtime = runtime_overrides.get(key) or runtimes.get(key)
        entry_readiness = readiness_by_harness.get(key, readiness)
        availability, availability_reason = _catalog_availability(
            key,
            entry_readiness,
            runtime,
        )
        selectable = enabled and availability != CATALOG_AVAILABILITY_UNAVAILABLE
        result.append(
            {
                **entry,
                "enabled": enabled,
                "availability": availability,
                "selectable": selectable,
                "disabled_reason": (
                    enabled_reason
                    if not enabled
                    else availability_reason
                    if availability == CATALOG_AVAILABILITY_UNAVAILABLE
                    else None
                ),
                "availability_reason": availability_reason,
                # ``reason_code`` is the compact stable reason for clients
                # that do not need to render both dimensions separately.
                "reason_code": enabled_reason or availability_reason,
            }
        )
    return result


def _project_catalog(manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    try:
        return registry_catalog_from_manifest(manifest)
    except (HarnessRegistryError, ValueError, TypeError) as exc:
        # A frozen row that cannot satisfy the public V2 contract must not be
        # silently replaced with today's checkout manifest.
        raise _invalid_runtime_bundle_catalog() from exc


def _invalid_runtime_bundle_catalog() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "code": "invalid_runtime_bundle_catalog",
            "message": "The task's frozen Runtime Bundle cannot provide a catalog.",
        },
    )


async def _task_catalog_bundle(
    db: AsyncSession,
    task: Task,
    bundle: WorkerRuntimeBundle,
) -> tuple[WorkerRuntimeBundle, Mapping[str, Any]]:
    """Load and resolve the immutable Harness manifest for a task catalog."""
    manifest = getattr(bundle, "manifest", None)
    if isinstance(manifest, Mapping) and "command_schema" in manifest:
        return bundle, manifest
    try:
        loaded_bundle = await load_bound_runtime_bundle(db, task)
    except RuntimeError as exc:
        raise _invalid_runtime_bundle_catalog() from exc
    manifest = harness_manifest_from_bundle(loaded_bundle)
    if not isinstance(manifest, Mapping):
        raise _invalid_runtime_bundle_catalog()
    return loaded_bundle, manifest


def _v2_catalog_response(
    bundle: WorkerRuntimeBundle,
    *,
    source: str,
    profile: Any | None = None,
    readiness: RuntimeReadiness | None = None,
    snapshot: TaskWorkerProfileSnapshot | None = None,
    catalog_manifest: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    bound_harness_key = getattr(snapshot, "harness_key", None) if snapshot is not None else None
    runtime_overrides = {}
    if bound_harness_key and getattr(snapshot, "cli_source", None):
        runtime_overrides[bound_harness_key] = {"source": snapshot.cli_source}
    return {
        "source": source,
        "contract_version": bundle.contract_version,
        "bundle_digest": bundle.digest,
        "legacy": False,
        "read_only": False,
        "catalog": _catalog_with_runtime_state(
            _project_catalog(
                catalog_manifest if catalog_manifest is not None else bundle.manifest
            ),
            profile=profile,
            readiness=readiness,
            bound_harness_key=bound_harness_key,
            runtime_overrides=runtime_overrides,
        ),
    }


def _legacy_catalog_response(bundle: WorkerRuntimeBundle | None) -> dict[str, Any]:
    return {
        "source": "legacy_task",
        "contract_version": getattr(bundle, "contract_version", None),
        "bundle_digest": getattr(bundle, "digest", None),
        "legacy": True,
        "read_only": True,
        "reason": "This historical task has no executable V2 Harness catalog.",
        "catalog": [],
    }


def _current_manifest() -> dict[str, Any]:
    manifest_path = (
        default_runtime_source_dir()
        / "deploy"
        / "worker-entrypoint"
        / "harness"
        / "manifest.json"
    )
    try:
        raw = manifest_path.read_text(encoding="utf-8")
        parsed = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "runtime_manifest_unavailable",
                "message": "The configured Runtime Bundle manifest is unavailable.",
            },
        ) from exc
    if not isinstance(parsed, dict):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "runtime_manifest_unavailable",
                "message": "The configured Runtime Bundle manifest is invalid.",
            },
        )
    return parsed


async def _load_catalog_profile(
    db: AsyncSession,
    worker_profile_id: int | None,
) -> WorkerProfile | None:
    if worker_profile_id is None:
        return await get_default_worker_profile(db)
    result = await db.execute(
        select(WorkerProfile)
        .where(WorkerProfile.id == worker_profile_id)
        .options(
            selectinload(WorkerProfile.environment_variables),
            selectinload(WorkerProfile.default_skills),
        )
    )
    profile = result.scalar_one_or_none()
    if profile is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Worker profile {worker_profile_id} not found",
        )
    return profile


async def _catalog_readiness_by_harness_for_profile(
    db: AsyncSession,
    profile: WorkerProfile,
    harness_keys: list[str],
) -> dict[str, RuntimeReadiness]:
    """Read each Harness against its own V1/V2 readiness scope.

    A dual-canary Profile may deliberately mix V1 and V2 Harnesses. V2
    content-inventory evidence is stored under a separate readiness key, so a
    V2 observation must never be reused for a V1 entry in the public catalog.
    """
    settings = get_effective_settings()
    return {
        key: await readiness_for_profile(
            db,
            profile,
            settings,
            harness_key=key,
        )
        for key in harness_keys
    }


def _snapshot_requires_content_inventory(snapshot: Any) -> bool:
    config = getattr(snapshot, "harness_config_snapshot", None)
    if isinstance(config, Mapping) and isinstance(config.get("worker_kit_identity"), Mapping):
        return True
    return (
        getattr(snapshot, "runtime_contract_version", None) == HARNESS_CONTRACT_VERSION_V2
        and getattr(snapshot, "runtime_mode", None) == "mounted_kit"
        and getattr(snapshot, "cli_source", None) != "host_mount"
    )


async def _catalog_readiness_for_snapshot(
    db: AsyncSession,
    snapshot: TaskWorkerProfileSnapshot,
) -> RuntimeReadiness:
    return await read_runtime_readiness(
        db,
        getattr(snapshot, "runtime_locator_fingerprint", None),
        require_content_inventory=_snapshot_requires_content_inventory(snapshot),
    )


@router.get("/harness-catalog")
async def get_current_harness_catalog(
    worker_profile_id: int | None = Query(default=None, ge=1),
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """Return the current manifest with Profile and runtime availability state."""
    manifest = _current_manifest()
    profile = await _load_catalog_profile(db, worker_profile_id)
    catalog = _project_catalog(manifest)
    readiness_by_harness = (
        await _catalog_readiness_by_harness_for_profile(
            db,
            profile,
            [entry["key"] for entry in catalog],
        )
        if profile is not None
        else {}
    )
    return {
        "source": "current_runtime_manifest",
        "contract_version": manifest.get("contract_version"),
        "bundle_digest": None,
        "legacy": False,
        "read_only": False,
        "catalog": _catalog_with_runtime_state(
            catalog,
            profile=profile,
            readiness_by_harness=readiness_by_harness,
        ),
    }


@router.get("/tasks/{task_id}/harness-catalog")
async def get_task_harness_catalog(
    task_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User | None = Depends(get_optional_current_user),
    access_scope: ProjectAccessScope = Depends(require_project_access_scope),
) -> dict[str, Any]:
    """Return a task's frozen V2 catalog, or a read-only legacy marker.

    Access is evaluated before looking at the task's immutable bundle.  The
    bundle relationship is eager-loaded by ``get_task_with_access_check``.
    """
    task: Task = await get_task_with_access_check(task_id, db, access_scope, current_user)
    bundle = task.runtime_bundle
    if bundle is None or bundle.contract_version != HARNESS_CONTRACT_VERSION_V2:
        return _legacy_catalog_response(bundle)
    bundle, catalog_manifest = await _task_catalog_bundle(db, task, bundle)
    snapshot = getattr(task, "worker_profile_snapshot", None)
    readiness = (
        await _catalog_readiness_for_snapshot(db, snapshot)
        if snapshot is not None
        else None
    )
    return _v2_catalog_response(
        bundle,
        source="task_runtime_bundle",
        readiness=readiness,
        snapshot=snapshot,
        catalog_manifest=catalog_manifest,
    )
