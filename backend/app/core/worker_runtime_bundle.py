"""Deterministic, content-addressed Worker Runtime Bundle construction."""

from __future__ import annotations

import hashlib
import io
import json
import os
import tarfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterable

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import undefer

from app.core.harness_protocol import CANONICAL_EVENT_SCHEMA, HARNESS_CONTRACT_VERSION
from app.core.harness_registry import validate_adapter_capabilities
from app.models import Task, WorkerRuntimeBundle

ORCHESTRATION_VERSION = "1.0.0"
RUNTIME_SOURCE_ENV = "CODIFY_RUNTIME_SOURCE_DIR"
RUNTIME_ARCHIVE_ROOT = PurePosixPath("codify-runtime/orchestration")

_CONTROLLED_FILES = (
    "deploy/entrypoint.worker.sh",
    "deploy/ci-claude.sh",
)
_CONTROLLED_TREES = (
    "deploy/worker-entrypoint",
)
_ALLOWED_SUFFIXES = {".sh", ".py", ".json"}


@dataclass(frozen=True, slots=True)
class BuiltRuntimeBundle:
    digest: str
    archive_bytes: bytes
    manifest: dict


def default_runtime_source_dir() -> Path:
    configured = os.getenv(RUNTIME_SOURCE_ENV)
    if configured:
        return Path(configured).resolve()
    return Path(__file__).resolve().parents[3]


def _controlled_paths(source_dir: Path) -> list[Path]:
    paths: list[Path] = []
    for relative in _CONTROLLED_FILES:
        path = source_dir / relative
        if not path.is_file():
            raise RuntimeError(f"Runtime Bundle source is missing: {relative}")
        paths.append(path)
    for relative in _CONTROLLED_TREES:
        root = source_dir / relative
        if not root.is_dir():
            raise RuntimeError(f"Runtime Bundle source directory is missing: {relative}")
        paths.extend(
            path
            for path in root.rglob("*")
            if path.is_file()
            and path.suffix in _ALLOWED_SUFFIXES
            and "__pycache__" not in path.parts
        )
    return sorted(set(paths), key=lambda item: item.relative_to(source_dir).as_posix())


def _sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


_ADAPTER_DIGEST_FILES = (
    "deploy/ci-claude.sh",
    "deploy/worker-entrypoint/harness/version_range.py",
    "deploy/worker-entrypoint/harness/adapters/claude.sh",
    "deploy/worker-entrypoint/harness/adapters/claude_events.py",
    "deploy/worker-entrypoint/harness/adapters/codex.sh",
    "deploy/worker-entrypoint/harness/adapters/codex_events.py",
    "deploy/worker-entrypoint/harness/adapters/sanitize.py",
    "deploy/worker-entrypoint/legacy/codex-run.sh",
)


def _adapter_digest(files: Iterable[tuple[str, bytes]]) -> str:
    digest = hashlib.sha256()
    for name, payload in files:
        if name in _ADAPTER_DIGEST_FILES:
            digest.update(name.encode())
            digest.update(b"\0")
            digest.update(payload)
            digest.update(b"\0")
    return digest.hexdigest()


def _archive_name(source_name: str) -> str:
    if source_name == "deploy/entrypoint.worker.sh":
        relative = "entrypoint.sh"
    elif source_name == "deploy/ci-claude.sh":
        relative = "legacy/ci-claude.sh"
    elif source_name.startswith("deploy/worker-entrypoint/"):
        relative = source_name.removeprefix("deploy/")
    else:  # pragma: no cover - controlled source list prevents this
        raise RuntimeError(f"Unexpected Runtime Bundle source: {source_name}")
    return str(RUNTIME_ARCHIVE_ROOT / relative)


def _add_bytes(archive: tarfile.TarFile, name: str, payload: bytes, *, mode: int) -> None:
    info = tarfile.TarInfo(name=name)
    info.size = len(payload)
    info.mode = mode
    info.uid = 0
    info.gid = 0
    info.uname = ""
    info.gname = ""
    info.mtime = 0
    archive.addfile(info, io.BytesIO(payload))


def build_runtime_bundle(source_dir: Path | None = None) -> BuiltRuntimeBundle:
    root = (source_dir or default_runtime_source_dir()).resolve()
    source_files = [
        (path.relative_to(root).as_posix(), path.read_bytes())
        for path in _controlled_paths(root)
    ]
    source_by_name = dict(source_files)
    harness_manifest = json.loads(
        source_by_name["deploy/worker-entrypoint/harness/manifest.json"]
    )
    expected_protocol = {
        "contract_version": HARNESS_CONTRACT_VERSION,
        "event_schema": CANONICAL_EVENT_SCHEMA,
        "orchestration_version": ORCHESTRATION_VERSION,
    }
    for key, expected in expected_protocol.items():
        if harness_manifest.get(key) != expected:
            raise RuntimeError(f"Runtime source {key} does not match executable protocol")
    source_adapters = harness_manifest.get("adapters") or {}
    if not isinstance(source_adapters, dict) or not source_adapters:
        raise RuntimeError("Runtime source has no Adapter declarations")
    adapters: dict[str, dict[str, Any]] = {}
    for adapter_key, metadata in source_adapters.items():
        if not isinstance(metadata, dict) or not metadata.get("version"):
            raise RuntimeError(
                f"Runtime source Adapter {adapter_key!r} has no version"
            )
        capabilities = metadata.get("capabilities")
        if capabilities is not None:
            validate_adapter_capabilities(adapter_key, capabilities)
        adapter_metadata = dict(metadata)
        adapter_metadata["digest"] = _adapter_digest(source_files)
        adapters[adapter_key] = adapter_metadata
    manifest = {
        "schema": "codify.worker.runtime-bundle/v1",
        "contract_version": HARNESS_CONTRACT_VERSION,
        "event_schema": CANONICAL_EVENT_SCHEMA,
        "orchestration_version": ORCHESTRATION_VERSION,
        "adapters": adapters,
        "files": [
            {
                "path": _archive_name(name).removeprefix(f"{RUNTIME_ARCHIVE_ROOT}/"),
                "sha256": _sha256(payload),
                "size": len(payload),
            }
            for name, payload in source_files
        ],
    }
    manifest_bytes = json.dumps(
        manifest,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    manifest_digest = _sha256(manifest_bytes)
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w", format=tarfile.PAX_FORMAT) as archive:
        for name, payload in source_files:
            mode = 0o755 if name.endswith((".sh", ".py")) else 0o644
            _add_bytes(archive, _archive_name(name), payload, mode=mode)
        _add_bytes(
            archive,
            str(RUNTIME_ARCHIVE_ROOT / "manifest.json"),
            manifest_bytes,
            mode=0o644,
        )
    archive_bytes = buffer.getvalue()
    digest = _sha256(archive_bytes)
    manifest["archive_manifest_digest"] = manifest_digest
    manifest["bundle_digest"] = digest
    return BuiltRuntimeBundle(digest=digest, archive_bytes=archive_bytes, manifest=manifest)


async def get_or_create_runtime_bundle(
    db: AsyncSession,
    *,
    source_dir: Path | None = None,
) -> WorkerRuntimeBundle:
    built = build_runtime_bundle(source_dir)
    existing = (
        await db.execute(
            select(WorkerRuntimeBundle).where(WorkerRuntimeBundle.digest == built.digest)
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    created = WorkerRuntimeBundle(
        digest=built.digest,
        bundle_bytes=built.archive_bytes,
        contract_version=HARNESS_CONTRACT_VERSION,
        orchestration_version=ORCHESTRATION_VERSION,
        manifest=built.manifest,
        size_bytes=len(built.archive_bytes),
    )
    try:
        async with db.begin_nested():
            db.add(created)
            await db.flush()
        return created
    except IntegrityError:
        existing = (
            await db.execute(
                select(WorkerRuntimeBundle).where(WorkerRuntimeBundle.digest == built.digest)
            )
        ).scalar_one()
        return existing


async def bind_runtime_bundle(
    db: AsyncSession,
    task: Task,
    *,
    source_task: Task | None = None,
    source_dir: Path | None = None,
) -> WorkerRuntimeBundle:
    """Bind the immutable bundle during task creation or clone it for retry."""
    source_bundle_id = getattr(source_task, "runtime_bundle_id", None)
    if source_task is not None and source_bundle_id is None:
        raise RuntimeError(
            "retry source has no immutable Runtime Bundle; "
            "create a new Task after the release migration"
        )
    if source_bundle_id is not None:
        bundle = await db.get(WorkerRuntimeBundle, source_bundle_id)
        if bundle is None:
            raise RuntimeError("retry source references a missing Runtime Bundle")
    else:
        bundle = await get_or_create_runtime_bundle(db, source_dir=source_dir)
    task.runtime_bundle_id = bundle.id
    await db.flush()
    return bundle


def verify_bundle_bytes(bundle: WorkerRuntimeBundle) -> None:
    payload = bundle.bundle_bytes
    actual = _sha256(payload)
    if actual != bundle.digest:
        raise RuntimeError(
            f"Runtime Bundle digest mismatch: expected {bundle.digest}, received {actual}"
        )
    if bundle.manifest.get("bundle_digest") != bundle.digest:
        raise RuntimeError("Runtime Bundle manifest digest does not match the database binding")
    if bundle.size_bytes != len(payload):
        raise RuntimeError("Runtime Bundle size does not match the database binding")

    expected_manifest_digest = bundle.manifest.get("archive_manifest_digest")
    if not isinstance(expected_manifest_digest, str) or len(expected_manifest_digest) != 64:
        raise RuntimeError("Runtime Bundle has no frozen archive manifest digest")
    try:
        with tarfile.open(fileobj=io.BytesIO(payload), mode="r:") as archive:
            members = archive.getmembers()
            names = [member.name for member in members]
            if len(names) != len(set(names)):
                raise RuntimeError("Runtime Bundle contains duplicate archive paths")
            for member in members:
                path = PurePosixPath(member.name)
                if path.is_absolute() or ".." in path.parts or not member.isfile():
                    raise RuntimeError(f"Unsafe Runtime Bundle member: {member.name}")
            manifest_name = str(RUNTIME_ARCHIVE_ROOT / "manifest.json")
            manifest_member = archive.getmember(manifest_name)
            extracted_manifest = archive.extractfile(manifest_member)
            if extracted_manifest is None:
                raise RuntimeError("Runtime Bundle manifest cannot be read")
            manifest_bytes = extracted_manifest.read()
            if _sha256(manifest_bytes) != expected_manifest_digest:
                raise RuntimeError("Runtime Bundle archive manifest digest mismatch")
            embedded = json.loads(manifest_bytes)
            for key in ("schema", "contract_version", "event_schema", "orchestration_version"):
                if embedded.get(key) != bundle.manifest.get(key):
                    raise RuntimeError(f"Runtime Bundle embedded {key} is not frozen truth")
            if embedded.get("adapters") != bundle.manifest.get("adapters"):
                raise RuntimeError("Runtime Bundle embedded Adapter manifest is not frozen truth")
            expected_names = {manifest_name}
            for file_entry in embedded.get("files") or []:
                relative = PurePosixPath(str(file_entry.get("path") or ""))
                if relative.is_absolute() or ".." in relative.parts or not relative.parts:
                    raise RuntimeError("Runtime Bundle manifest contains an unsafe file path")
                name = str(RUNTIME_ARCHIVE_ROOT / relative)
                expected_names.add(name)
                member = archive.getmember(name)
                extracted = archive.extractfile(member)
                if extracted is None:
                    raise RuntimeError(f"Runtime Bundle file cannot be read: {relative}")
                file_bytes = extracted.read()
                if len(file_bytes) != file_entry.get("size"):
                    raise RuntimeError(f"Runtime Bundle file size mismatch: {relative}")
                if _sha256(file_bytes) != file_entry.get("sha256"):
                    raise RuntimeError(f"Runtime Bundle file digest mismatch: {relative}")
            if set(names) != expected_names:
                raise RuntimeError("Runtime Bundle archive and manifest file sets differ")
    except (KeyError, json.JSONDecodeError, tarfile.TarError) as exc:
        raise RuntimeError("Runtime Bundle archive is malformed") from exc


async def load_bound_runtime_bundle(
    db: AsyncSession,
    task: Task,
) -> WorkerRuntimeBundle:
    """Load immutable execution truth; historical unbound tasks are read-only."""
    if task.runtime_bundle_id is None:
        raise RuntimeError(
            "Task has no immutable Runtime Bundle; historical Tasks are read-only"
        )
    bundle = (
        await db.execute(
            select(WorkerRuntimeBundle)
            .where(WorkerRuntimeBundle.id == task.runtime_bundle_id)
            .options(undefer(WorkerRuntimeBundle.bundle_bytes))
        )
    ).scalar_one_or_none()
    if bundle is None:
        raise RuntimeError("Task Runtime Bundle binding is missing")
    verify_bundle_bytes(bundle)
    return bundle
