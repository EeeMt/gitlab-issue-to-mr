"""Fail-closed maintenance export of an already-bound V2 Runtime Bundle.

This module deliberately has no runtime-source imports: an L3 export is proof
of bytes stored with a Task, never a rebuild from the checkout currently used
by the backend container.
"""

from __future__ import annotations

import ctypes
import errno
import hashlib
import json
import os
import platform
import re
import shutil
import uuid
from pathlib import Path
from typing import Any, Mapping

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload, undefer

from app.core.harness_protocol import HARNESS_CONTRACT_VERSION_V2
from app.core.worker_runtime_bundle import _verify_v2_bundle_bytes, load_bound_runtime_bundle
from app.models import Task, WorkerRuntimeBundle

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_SECRET_KEY_RE = re.compile(
    r"(?:^|[_-])(?:secret|token|password|authorization|credential)(?:$|[_-])|api[_-]?key|accessToken",
    re.I,
)
_ARCHIVE_SECRET_PATTERNS = (
    re.compile(rb"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(rb"\b(?:sk|glpat)-[A-Za-z0-9_-]{12,}"),
    re.compile(rb"(?i:(?:authorization|x-api-key)\s*[:=]\s*(?:bearer\s+)?[^\s'\"${]{12,})"),
)


class RuntimeBundleExportError(RuntimeError):
    """The requested evidence cannot be exported safely."""


def _canonical_json(value: Mapping[str, Any]) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def _sha256(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _reject_secret_keys(value: Any, *, path: str = "manifest") -> None:
    if isinstance(value, Mapping):
        for key, item in value.items():
            if not isinstance(key, str):
                raise RuntimeBundleExportError(f"{path} has a non-string key")
            if _SECRET_KEY_RE.search(key):
                raise RuntimeBundleExportError(f"{path}.{key} is secret-shaped")
            _reject_secret_keys(item, path=f"{path}.{key}")
    elif isinstance(value, list):
        for index, item in enumerate(value):
            _reject_secret_keys(item, path=f"{path}[{index}]")


def _reject_archive_secrets(payload: bytes) -> None:
    for pattern in _ARCHIVE_SECRET_PATTERNS:
        if pattern.search(payload):
            raise RuntimeBundleExportError("stored Runtime Bundle archive contains secret-shaped bytes")


def _selected_task_evidence(task: Task, bundle: WorkerRuntimeBundle) -> None:
    snapshot = task.worker_profile_snapshot
    if snapshot is None:
        raise RuntimeBundleExportError("Task has no frozen Worker Profile Snapshot")
    config = snapshot.harness_config_snapshot
    if not isinstance(config, Mapping):
        raise RuntimeBundleExportError("Task has no frozen Harness configuration")
    if config.get("requested_runtime_contract_version") != HARNESS_CONTRACT_VERSION_V2:
        raise RuntimeBundleExportError("Task did not explicitly select the V2 Runtime Bundle contract")
    key = snapshot.harness_key
    evidence = config.get("v2_harness_verification_evidence")
    if not isinstance(key, str) or not key or not isinstance(evidence, Mapping):
        raise RuntimeBundleExportError("Task has no selected V2 Harness verification evidence")
    if evidence.get("harness_key") != key or evidence != bundle.manifest.get("harness_verification_evidence"):
        raise RuntimeBundleExportError("Task selected Harness evidence does not match its Runtime Bundle")
    adapter = evidence.get("adapter")
    frozen_adapter = (bundle.manifest.get("adapters") or {}).get(key)
    if not isinstance(adapter, Mapping) or not isinstance(frozen_adapter, Mapping):
        raise RuntimeBundleExportError("Task selected Harness Adapter is missing from Runtime Bundle")
    adapter_identity = frozen_adapter.get("adapter")
    if not isinstance(adapter_identity, Mapping) or any(
        adapter.get(field) != adapter_identity.get(field) for field in ("version", "digest")
    ):
        raise RuntimeBundleExportError("Task selected Harness Adapter identity does not match Runtime Bundle")
    identity = bundle.manifest.get("worker_image_identity")
    if evidence.get("image_identity") != identity:
        raise RuntimeBundleExportError("Task selected Harness image identity does not match Runtime Bundle")


def _validate_exportable_bundle(bundle: WorkerRuntimeBundle) -> None:
    if bundle.contract_version != HARNESS_CONTRACT_VERSION_V2:
        raise RuntimeBundleExportError("only codify.worker.harness/v2 bundles can be exported")
    if not isinstance(bundle.digest, str) or _SHA256_RE.fullmatch(bundle.digest) is None:
        raise RuntimeBundleExportError("Runtime Bundle has an invalid digest")
    try:
        _verify_v2_bundle_bytes(bundle)
    except RuntimeError as exc:
        raise RuntimeBundleExportError(str(exc)) from exc
    _reject_secret_keys(bundle.manifest)
    _reject_archive_secrets(bundle.bundle_bytes)


async def load_exportable_runtime_bundle(
    db: AsyncSession, *, task_id: int | None = None, bundle_digest: str | None = None
) -> WorkerRuntimeBundle:
    """Load a single selected V2 bundle and verify its immutable DB binding."""
    if (task_id is None) == (bundle_digest is None):
        raise RuntimeBundleExportError("supply exactly one of task_id or bundle_digest")
    if task_id is not None:
        if task_id < 1:
            raise RuntimeBundleExportError("task_id must be positive")
        task = (
            await db.execute(
                select(Task).where(Task.id == task_id).options(selectinload(Task.worker_profile_snapshot))
            )
        ).scalar_one_or_none()
        if task is None:
            raise RuntimeBundleExportError("Task was not found")
        try:
            bundle = await load_bound_runtime_bundle(db, task)
        except RuntimeError as exc:
            raise RuntimeBundleExportError(str(exc)) from exc
        _validate_exportable_bundle(bundle)
        _selected_task_evidence(task, bundle)
        return bundle
    if not isinstance(bundle_digest, str) or _SHA256_RE.fullmatch(bundle_digest) is None:
        raise RuntimeBundleExportError("bundle_digest must be a lowercase SHA-256 digest")
    bundle = (
        await db.execute(
            select(WorkerRuntimeBundle)
            .where(WorkerRuntimeBundle.digest == bundle_digest)
            .options(undefer(WorkerRuntimeBundle.bundle_bytes))
        )
    ).scalar_one_or_none()
    if bundle is None:
        raise RuntimeBundleExportError("Runtime Bundle was not found")
    _validate_exportable_bundle(bundle)
    return bundle


def _fsync_directory(path: Path) -> None:
    descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


def _rename_noreplace(source: Path, destination: Path) -> None:
    """Atomic Linux-only directory publication that never overwrites evidence."""
    if platform.system() != "Linux":
        raise RuntimeBundleExportError("Runtime Bundle export requires Linux renameat2(RENAME_NOREPLACE)")
    libc = ctypes.CDLL(None, use_errno=True)
    renameat2 = getattr(libc, "renameat2", None)
    if renameat2 is None:
        raise RuntimeBundleExportError("renameat2(RENAME_NOREPLACE) is unavailable; refusing export")
    renameat2.argtypes = [ctypes.c_int, ctypes.c_char_p, ctypes.c_int, ctypes.c_char_p, ctypes.c_uint]
    renameat2.restype = ctypes.c_int
    if renameat2(-100, os.fsencode(source), -100, os.fsencode(destination), 1) != 0:
        error = ctypes.get_errno()
        if error == errno.EEXIST:
            raise RuntimeBundleExportError("evidence directory already exists")
        raise RuntimeBundleExportError(f"renameat2(RENAME_NOREPLACE) failed: {os.strerror(error)}")


def export_runtime_bundle(bundle: WorkerRuntimeBundle, output_root: Path) -> dict[str, Any]:
    """Write original DB archive plus canonical DB manifest to ``<root>/runtime-bundle-v2-<digest>``.

    The final directory is published exactly once.  A retry sees it and fails,
    making an operator consciously compare existing evidence rather than silently
    replacing it.
    """
    _validate_exportable_bundle(bundle)
    root = output_root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    destination_name = f"runtime-bundle-v2-{bundle.digest}"
    destination = root / destination_name
    if os.path.lexists(destination):
        raise RuntimeBundleExportError("evidence directory already exists")
    staging = root / f".{destination_name}.staging-{uuid.uuid4().hex}"
    manifest_bytes = _canonical_json(bundle.manifest)
    archive_bytes = bytes(bundle.bundle_bytes)
    try:
        staging.mkdir(mode=0o700)
        contents = {
            "runtime-manifest.json": manifest_bytes,
            "runtime-manifest.json.sha256": f"{_sha256(manifest_bytes)}  runtime-manifest.json\n".encode(),
            "runtime-bundle.tar": archive_bytes,
            "runtime-bundle.tar.sha256": f"{_sha256(archive_bytes)}  runtime-bundle.tar\n".encode(),
        }
        for name, content in contents.items():
            target = staging / name
            with target.open("xb") as handle:
                handle.write(content)
                handle.flush()
                os.fsync(handle.fileno())
        _fsync_directory(staging)
        _rename_noreplace(staging, destination)
        _fsync_directory(root)
    except Exception:
        if staging.exists():
            shutil.rmtree(staging)
        raise
    return {
        "bundle_digest": bundle.digest,
        "contract_version": bundle.contract_version,
        "runtime_platform": bundle.manifest["runtime_platform"],
        "archive_sha256": _sha256(archive_bytes),
        "manifest_sha256": _sha256(manifest_bytes),
    }
