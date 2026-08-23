"""Safe display catalog for frozen Harness Runtime Bundles.

The catalog is deliberately a projection, rather than a raw manifest.  It is
the only Harness capability input intended for product surfaces: callers never
receive adapter source metadata, artifact locations, or executable paths.
"""

from __future__ import annotations

import json
from typing import Any, Mapping

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.task_operations import get_task_with_access_check
from app.core.harness_protocol import HARNESS_CONTRACT_VERSION_V2
from app.core.harness_registry import HarnessRegistryError, registry_catalog_from_manifest
from app.core.worker_runtime_bundle import default_runtime_source_dir
from app.database import get_db
from app.dependencies.auth import get_optional_current_user
from app.dependencies.project_access import ProjectAccessScope, require_project_access_scope
from app.models import Task, User, WorkerRuntimeBundle

router = APIRouter()


def _project_catalog(manifest: Mapping[str, Any]) -> list[dict[str, Any]]:
    try:
        return registry_catalog_from_manifest(manifest)
    except (HarnessRegistryError, ValueError, TypeError) as exc:
        # A frozen row that cannot satisfy the public V2 contract must not be
        # silently replaced with today's checkout manifest.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "code": "invalid_runtime_bundle_catalog",
                "message": "The task's frozen Runtime Bundle cannot provide a catalog.",
            },
        ) from exc


def _v2_catalog_response(bundle: WorkerRuntimeBundle, *, source: str) -> dict[str, Any]:
    return {
        "source": source,
        "contract_version": bundle.contract_version,
        "bundle_digest": bundle.digest,
        "legacy": False,
        "read_only": False,
        "catalog": _project_catalog(bundle.manifest),
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
    manifest_path = default_runtime_source_dir() / "harness" / "manifest.json"
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


@router.get("/harness-catalog")
async def get_current_harness_catalog() -> dict[str, Any]:
    """Return the catalog from the configured source manifest for new work."""
    manifest = _current_manifest()
    return {
        "source": "current_runtime_manifest",
        "contract_version": manifest.get("contract_version"),
        "bundle_digest": None,
        "legacy": False,
        "read_only": False,
        "catalog": _project_catalog(manifest),
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
    return _v2_catalog_response(bundle, source="task_runtime_bundle")
