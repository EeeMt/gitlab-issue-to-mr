"""Deterministic, content-addressed Worker Runtime Bundle construction."""

from __future__ import annotations

import hashlib
import io
import json
import os
import tarfile
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import undefer

from app.core.harness_protocol import (
    CANONICAL_EVENT_SCHEMA,
    CANONICAL_EVENT_SCHEMA_V2,
    HARNESS_CONTRACT_VERSION,
    HARNESS_CONTRACT_VERSION_V2,
    validate_manifest,
)
from app.core.harness_registry import (
    validate_adapter_capabilities,
    validate_v2_manifest_adapter_capabilities,
)
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


@dataclass(frozen=True, slots=True)
class BuiltRuntimeBundleV2:
    """A content-addressed Runtime Bundle built from a V2 runtime-manifest.

    Unlike the V1 archive bundle, a V2 bundle is manifest-only (no code archive
    in this phase): the top-level ``digest`` is the recursive bundle digest over
    the manifest ``files``, and each adapter carries an independent digest
    derived from the file subset it references.
    """

    digest: str
    schema: str
    contract_version: str
    event_schema: str
    adapter_digests: dict[str, str]
    manifest: dict


_V2_ADAPTER_DIR_KEYS = ("directory", "dir")


def bundle_manifest_digest_from_files(
    manifest_files: Iterable[Mapping[str, Any]],
) -> str:
    """Recursive bundle digest over a V2 manifest's ``files`` list.

    The digest is SHA-256 of the canonical JSON (sorted keys, sorted by ``path``)
    of the file entries ``{path, size, sha256}``. Any change to any file's
    content (sha256), size or set of files changes this digest.
    """
    entries = sorted(
        (str(item.get("path")), item) for item in manifest_files
    )
    canonical = [
        {
            "path": item.get("path"),
            "size": item.get("size"),
            "sha256": item.get("sha256"),
        }
        for _, item in entries
    ]
    payload = json.dumps(
        canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    return _sha256(payload)


def adapter_digest_from_manifest_files(
    manifest_files: Iterable[Mapping[str, Any]],
    adapter_key: str,
    *,
    adapter_dir: str | None = None,
    shared_files: Iterable[Mapping[str, Any]] | None = None,
) -> str:
    """Independent per-adapter digest over a V2 manifest's file subset.

    Deterministic rule:
      * Files whose ``path`` is under ``adapter_dir`` belong only to this
        adapter (its own source/bridge/events files).
      * ``shared_files`` — files not under ANY declared adapter directory (shared
        libraries, schema, common runtime) — are referenced by every adapter and
        therefore contribute to every adapter's digest.
      * The adapter's digest is SHA-256 of the canonical JSON of the union
        ``own ∪ shared``, ordered by ``path``.
    Because shared files are digested by every adapter, a shared-library change
    alters every adapter digest, while changing an adapter's own file alters only
    that adapter's digest (and the recursive bundle digest).

    If neither ``adapter_dir`` nor ``shared_files`` is given (the frozen V2
    schema declares no per-adapter directory and no partition), the rule falls
    back to hashing ALL manifest files for the adapter — a shared change then
    still alters every adapter digest.
    """
    items = list(manifest_files)
    if adapter_dir and shared_files is not None:
        own = [
            item
            for item in items
            if str(item.get("path") or "").startswith(f"{adapter_dir}/")
        ]
        shared = sorted(shared_files, key=lambda item: str(item.get("path")))
        subset = sorted(
            set(_file_entry_key(item) for item in own + shared),
            key=lambda path: path,
        )
    else:
        # Fallback: digest every file (no per-adapter partition declared).
        subset = sorted(
            set(_file_entry_key(item) for item in items), key=lambda path: path
        )
    found = {_file_entry_key(item): item for item in items}
    canonical = [
        {
            "path": item.get("path"),
            "size": item.get("size"),
            "sha256": item.get("sha256"),
        }
        for item in (found[path] for path in subset)
    ]
    payload = json.dumps(
        canonical, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()
    return _sha256(payload)


def _file_entry_key(item: Mapping[str, Any]) -> str:
    return str(item.get("path"))


def build_runtime_bundle_v2(manifest: Mapping[str, Any]) -> BuiltRuntimeBundleV2:
    """Build a V2 Runtime Bundle from a validated V2 runtime-manifest.

    Validates the manifest via ``harness_protocol.validate_manifest`` (approved
    adapter keys, control_transport kinds, model protocols, capability keys),
    enforces the code-held V2 capability upper bound per adapter, and stamps an
    independent ``adapter.digest`` per adapter plus a recursive top-level
    ``bundle_digest`` over ``files``.

    This is Phase-1 machinery and is deliberately NOT wired into the V1
    ``get_or_create_runtime_bundle``/``bind_runtime_bundle`` path — V1 tasks keep
    receiving V1 bundles; the V2 bundle is selected later for explicit V2
    profiles.
    """
    validated = validate_manifest(manifest)
    adapters = validated["adapters"]
    files = validated["files"]

    bundle_digest = bundle_manifest_digest_from_files(files)

    # Resolve each adapter's declared source directory so shared files (those
    # not under ANY adapter directory) can be attributed to every adapter.
    adapter_dirs: dict[str, str | None] = {}
    for key in adapters:
        source = adapters[key].get("source") or {}
        adapter_dir = None
        if isinstance(source, Mapping):
            for dir_key in _V2_ADAPTER_DIR_KEYS:
                candidate = source.get(dir_key)
                if isinstance(candidate, str) and candidate:
                    adapter_dir = candidate
                    break
        adapter_dirs[key] = adapter_dir

    declared_dirs = [d for d in adapter_dirs.values() if d]
    if declared_dirs:
        shared_files = [
            item
            for item in files
            if not any(
                str(item.get("path") or "").startswith(f"{d}/") for d in declared_dirs
            )
        ]
    else:
        shared_files = None

    adapter_digests: dict[str, str] = {}
    stamped_adapters: dict[str, dict[str, Any]] = {}
    for key in sorted(adapters):
        adapter = dict(adapters[key])
        validate_v2_manifest_adapter_capabilities(key, adapter.get("capabilities") or {})
        digest = adapter_digest_from_manifest_files(
            files, key, adapter_dir=adapter_dirs[key], shared_files=shared_files
        )
        adapter_digests[key] = digest
        adapter_meta = dict(adapter.get("adapter") or {})
        adapter_meta["digest"] = digest
        adapter["adapter"] = adapter_meta
        stamped_adapters[key] = adapter

    v2_manifest = {
        "schema": "codify.worker.runtime-bundle/v2",
        "contract_version": HARNESS_CONTRACT_VERSION_V2,
        "event_schema": CANONICAL_EVENT_SCHEMA_V2,
        "adapters": stamped_adapters,
        "files": list(files),
        "bundle_digest": bundle_digest,
    }
    return BuiltRuntimeBundleV2(
        digest=bundle_digest,
        schema="codify.worker.runtime-bundle/v2",
        contract_version=HARNESS_CONTRACT_VERSION_V2,
        event_schema=CANONICAL_EVENT_SCHEMA_V2,
        adapter_digests=adapter_digests,
        manifest=v2_manifest,
    )


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
    "deploy/worker-entrypoint/harness/adapters/pi.sh",
    "deploy/worker-entrypoint/harness/adapters/pi_events.py",
    "deploy/worker-entrypoint/harness/adapters/pi_bridge.py",
    "deploy/worker-entrypoint/legacy/pi-run.sh",
    "deploy/worker-entrypoint/harness/adapters/opencode.sh",
    "deploy/worker-entrypoint/harness/adapters/opencode_events.py",
    "deploy/worker-entrypoint/harness/adapters/opencode_bridge.py",
    "deploy/worker-entrypoint/legacy/opencode-run.sh",
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
    # The frozen source manifest is now runtime-manifest/v2; validate the full
    # V2 envelope (approved adapter keys, control transport, model protocols,
    # capability keys) before projecting it into the stable V1 bundle shape.
    validate_manifest(harness_manifest)
    source_adapters = harness_manifest.get("adapters") or {}
    if not isinstance(source_adapters, dict) or not source_adapters:
        raise RuntimeError("Runtime source has no Adapter declarations")
    adapters: dict[str, dict[str, Any]] = {}
    for adapter_key, metadata in source_adapters.items():
        if not isinstance(metadata, dict):
            raise RuntimeError(
                f"Runtime source Adapter {adapter_key!r} is not an object"
            )
        nested = metadata.get("adapter")
        adapter_version = (
            str(nested.get("version")) if isinstance(nested, Mapping) else ""
        )
        if not adapter_version:
            raise RuntimeError(
                f"Runtime source Adapter {adapter_key!r} has no adapter.version"
            )
        capabilities = metadata.get("capabilities")
        if capabilities is not None:
            validate_adapter_capabilities(adapter_key, capabilities)
        del metadata["adapter"]
        adapter_metadata = dict(metadata)
        adapter_metadata["version"] = adapter_version
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


async def get_or_create_runtime_bundle_v2(
    db: AsyncSession,
    *,
    source_dir: Path | None = None,
) -> WorkerRuntimeBundle:
    """Build/bind a manifest-only V2 bundle for V2-contract tasks (plan §4.3).

    The V2 bundle has no code archive: ``bundle_bytes`` is empty and the
    authoritative content is the frozen manifest itself, digest-addressed by
    the recursive files digest. The worker materializes its runtime from the
    mounted kit; the bundle supplies contract identity + adapter digests.
    """
    root = (source_dir or default_runtime_source_dir()).resolve()
    harness_manifest = json.loads(
        (root / "deploy/worker-entrypoint/harness/manifest.json").read_bytes()
    )
    built = build_runtime_bundle_v2(harness_manifest)
    existing = (
        await db.execute(
            select(WorkerRuntimeBundle).where(WorkerRuntimeBundle.digest == built.digest)
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    created = WorkerRuntimeBundle(
        digest=built.digest,
        bundle_bytes=b"",
        contract_version=built.contract_version,
        orchestration_version=ORCHESTRATION_VERSION,
        manifest=built.manifest,
        size_bytes=0,
    )
    try:
        async with db.begin_nested():
            db.add(created)
            await db.flush()
        return created
    except IntegrityError:
        return (
            await db.execute(
                select(WorkerRuntimeBundle).where(
                    WorkerRuntimeBundle.digest == built.digest
                )
            )
        ).scalar_one()


def v2_launcher_manifest_bytes(bundle: WorkerRuntimeBundle) -> bytes:
    """Canonical bytes of the launcher-facing V2 manifest projection.

    The kit launcher expects ``adapters.<key> = {version, digest}``; the frozen
    V2 manifest nests them under an ``adapter`` object. Both the materialized
    ``orchestration/manifest.json`` and the ``CODIFY_RUNTIME_MANIFEST_DIGEST``
    env must derive from these exact bytes so the launcher's fileDigest
    comparison matches.
    """
    launcher_manifest = dict(bundle.manifest)
    flat_adapters: dict[str, Any] = {}
    for key, meta in (bundle.manifest.get("adapters") or {}).items():
        nested = (meta or {}).get("adapter") if isinstance(meta, dict) else None
        flat_adapters[key] = {
            "version": (nested or {}).get("version", ""),
            "digest": (nested or {}).get("digest", ""),
        }
    launcher_manifest["adapters"] = flat_adapters
    return json.dumps(
        launcher_manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()


def build_v2_runtime_materialization_manifest_bytes(
    bundle: WorkerRuntimeBundle, *, source_dir: Path | None = None
) -> bytes:
    """Exact bytes of the materialized ``orchestration/manifest.json``.

    ``CODIFY_RUNTIME_MANIFEST_DIGEST`` must hash these bytes so the kit
    launcher's fileDigest comparison matches what the container receives.
    """
    root = (source_dir or default_runtime_source_dir()).resolve()
    source_files = _controlled_source_files(root)
    manifest = json.loads(v2_launcher_manifest_bytes(bundle))
    manifest["files"] = [
        {
            "path": _archive_name(name).removeprefix(f"{RUNTIME_ARCHIVE_ROOT}/"),
            "sha256": _sha256(payload),
            "size": len(payload),
        }
        for name, payload in source_files
    ]
    return json.dumps(
        manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode()


def _controlled_source_files(root: Path) -> list[tuple[str, bytes]]:
    return [
        (path.relative_to(root).as_posix(), path.read_bytes())
        for path in _controlled_paths(root)
    ]


def build_v2_runtime_materialization_archive(
    bundle: WorkerRuntimeBundle, *, source_dir: Path | None = None
) -> bytes:
    """Tar the full controlled runtime source under a V2-contract manifest.

    The worker entrypoint verifies its orchestration snapshot exactly like
    V1 (every file listed with size + sha256, ``entrypoint.sh`` manifested),
    so the V2 materialization ships the same controlled file set as the V1
    bundle — only ``manifest.json`` differs: it carries the frozen V2 identity
    (contract/event schema, flattened adapter digests) that the digest env
    vars are computed from.
    """
    root = (source_dir or default_runtime_source_dir()).resolve()
    source_files = _controlled_source_files(root)
    launcher_manifest = build_v2_runtime_materialization_manifest_bytes(
        bundle, source_dir=root
    )

    files: list[tuple[str, bytes]] = [
        ("codify-runtime/orchestration/manifest.json", launcher_manifest)
    ]
    files.extend(
        (_archive_name(name), payload) for name, payload in source_files
    )
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w", format=tarfile.PAX_FORMAT) as archive:
        seen_dirs: set[str] = set()
        for name, payload in files:
            parts = name.split("/")
            for i in range(1, len(parts)):
                dir_name = "/".join(parts[:i])
                if dir_name in seen_dirs:
                    continue
                seen_dirs.add(dir_name)
                info = tarfile.TarInfo(name=dir_name)
                info.type = tarfile.DIRTYPE
                info.mode = 0o755
                info.mtime = 0
                archive.addfile(info)
            mode = 0o755 if name.endswith((".sh", ".py")) else 0o644
            _add_bytes(archive, name, payload, mode=mode)
    return buffer.getvalue()



async def bind_runtime_bundle(
    db: AsyncSession,
    task: Task,
    *,
    source_task: Task | None = None,
    source_dir: Path | None = None,
    harness_key: str | None = None,
) -> WorkerRuntimeBundle:
    """Bind the immutable bundle during task creation or clone it for retry.

    A task whose frozen harness is declared in the V2 runtime manifest binds a
    V2 (manifest-only) bundle; retry/clone always reuses the source binding so
    an attempt keeps its original contract.
    """
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
    elif harness_key and _manifest_declares_adapter(source_dir, harness_key):
        bundle = await get_or_create_runtime_bundle_v2(db, source_dir=source_dir)
    else:
        bundle = await get_or_create_runtime_bundle(db, source_dir=source_dir)
    task.runtime_bundle_id = bundle.id
    await db.flush()
    return bundle


def _manifest_declares_adapter(
    source_dir: Path | None, harness_key: str
) -> bool:
    """True when the frozen V2 runtime-manifest declares ``harness_key``."""
    root = (source_dir or default_runtime_source_dir()).resolve()
    try:
        manifest = json.loads(
            (root / "deploy/worker-entrypoint/harness/manifest.json").read_bytes()
        )
    except (OSError, json.JSONDecodeError):
        return False
    adapters = manifest.get("adapters")
    return isinstance(adapters, dict) and harness_key in adapters


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
    if bundle.contract_version == HARNESS_CONTRACT_VERSION_V2:
        # Manifest-only V2 bundle: verify the recursive files digest against
        # the stored manifest instead of unpacking a code archive.
        expected = bundle_manifest_digest_from_files(bundle.manifest.get("files") or [])
        if expected != bundle.digest or bundle.manifest.get("bundle_digest") != bundle.digest:
            raise RuntimeError(
                "V2 Runtime Bundle manifest digest mismatch: "
                f"expected {bundle.digest}, manifest says {expected}"
            )
        return bundle
    verify_bundle_bytes(bundle)
    return bundle
