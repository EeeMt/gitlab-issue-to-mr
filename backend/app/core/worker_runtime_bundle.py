"""Deterministic, content-addressed Worker Runtime Bundle construction."""

from __future__ import annotations

import hashlib
import io
import json
import os
import re
import tarfile
from copy import deepcopy
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
CLI_ARTIFACT_MANIFEST_ENV = "CODIFY_WORKER_CLI_ARTIFACT_MANIFEST"
RUNTIME_ARCHIVE_ROOT = PurePosixPath("codify-runtime/orchestration")

_CONTROLLED_FILES = (
    "deploy/entrypoint.worker.sh",
    "deploy/ci-claude.sh",
)
_CONTROLLED_TREES = ("deploy/worker-entrypoint",)
_ALLOWED_SUFFIXES = {".sh", ".py", ".json"}
_LINUX_PLATFORM_RE = re.compile(r"^linux/[A-Za-z0-9][A-Za-z0-9_.-]*$")
_IMAGE_REFERENCE_RE = re.compile(r"^[^@\s]+@sha256:[0-9a-f]{64}$")
_IMAGE_ID_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _is_linux_platform(value: object) -> bool:
    return isinstance(value, str) and _LINUX_PLATFORM_RE.fullmatch(value) is not None


def _validated_v2_worker_image_identity(identity: object) -> dict[str, str]:
    if not isinstance(identity, Mapping) or identity.get("schema") != "codify.worker-image-identity/v1":
        raise RuntimeError("explicit V2 Task has no verified Worker image identity")
    required = ("daemon_key", "image_reference", "image_id", "runtime_platform", "cli_artifact_lock_sha256")
    normalized = {key: identity.get(key) for key in required}
    if not all(isinstance(value, str) and value for value in normalized.values()):
        raise RuntimeError("explicit V2 Task has an incomplete Worker image identity")
    if any(character.isspace() for character in normalized["daemon_key"]):
        raise RuntimeError("explicit V2 Task has an invalid Worker image identity")
    if _IMAGE_REFERENCE_RE.fullmatch(normalized["image_reference"]) is None:
        raise RuntimeError("explicit V2 Task has an invalid Worker image identity")
    if _IMAGE_ID_RE.fullmatch(normalized["image_id"]) is None:
        raise RuntimeError("explicit V2 Task has an invalid Worker image identity")
    if not _is_linux_platform(normalized["runtime_platform"]):
        raise RuntimeError("explicit V2 Task has an invalid Worker image identity")
    lock_digest = normalized["cli_artifact_lock_sha256"]
    if _SHA256_RE.fullmatch(lock_digest) is None:
        raise RuntimeError("explicit V2 Task has an invalid Worker image CLI lock digest")
    return {"schema": "codify.worker-image-identity/v1", **normalized}


@dataclass(frozen=True, slots=True)
class BuiltRuntimeBundle:
    digest: str
    archive_bytes: bytes
    manifest: dict


@dataclass(frozen=True, slots=True)
class BuiltRuntimeBundleV2:
    """A content-addressed Runtime Bundle built from a V2 runtime-manifest.

    The top-level ``digest`` is the recursive bundle digest over the manifest
    ``files``.  The database row additionally persists an archive containing
    exactly those files; see ``get_or_create_runtime_bundle_v2``.
    """

    digest: str
    schema: str
    contract_version: str
    event_schema: str
    adapter_digests: dict[str, str]
    manifest: dict


_V2_ADAPTER_DIR_KEYS = ("directory", "dir")


def _v2_adapter_scope_paths(adapter_key: str, files: Iterable[Mapping[str, Any]]) -> set[str]:
    """Return the controlled, adapter-private paths for a built-in adapter.

    This is deliberately code-held rather than inferred from a checkout at
    execution time.  Adapter scripts and their legacy compatibility runner are
    private; all remaining controlled runtime files are shared orchestration.
    """
    adapter_prefix = f"worker-entrypoint/harness/adapters/{adapter_key}"
    legacy_path = f"legacy/{adapter_key}-run.sh"
    return {
        str(item.get("path"))
        for item in files
        if str(item.get("path")).startswith(adapter_prefix) or str(item.get("path")) == legacy_path
    }


def bundle_manifest_digest_from_files(
    manifest_files: Iterable[Mapping[str, Any]],
) -> str:
    """Recursive bundle digest over a V2 manifest's ``files`` list.

    The digest is SHA-256 of the canonical JSON (sorted keys, sorted by ``path``)
    of the file entries ``{path, size, sha256}``. Any change to any file's
    content (sha256), size or set of files changes this digest.
    """
    entries = sorted((str(item.get("path")), item) for item in manifest_files)
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


def _v2_bundle_digest(
    files: Iterable[Mapping[str, Any]], worker_image_identity: object,
    harness_verification_evidence: object | None = None,
) -> str:
    file_digest = bundle_manifest_digest_from_files(files)
    if worker_image_identity is None:
        raise RuntimeError("V2 Runtime Bundle requires a frozen Worker image identity")
    if harness_verification_evidence is None:
        raise RuntimeError("V2 Runtime Bundle requires frozen Harness verification evidence")
    payload = {
        "files_digest": file_digest,
        "worker_image_identity": worker_image_identity,
        "harness_verification_evidence": harness_verification_evidence,
    }
    return _sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    )


def adapter_digest_from_manifest_files(
    manifest_files: Iterable[Mapping[str, Any]],
    adapter_key: str,
    *,
    adapter_dir: str | None = None,
    shared_files: Iterable[Mapping[str, Any]] | None = None,
    adapter_paths: Iterable[str] | None = None,
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
    if adapter_paths is not None and shared_files is not None:
        own = [item for item in items if _file_entry_key(item) in set(adapter_paths)]
        shared = sorted(shared_files, key=lambda item: str(item.get("path")))
        subset = sorted(set(_file_entry_key(item) for item in own + shared), key=lambda path: path)
    elif adapter_dir and shared_files is not None:
        own = [item for item in items if str(item.get("path") or "").startswith(f"{adapter_dir}/")]
        shared = sorted(shared_files, key=lambda item: str(item.get("path")))
        subset = sorted(
            set(_file_entry_key(item) for item in own + shared),
            key=lambda path: path,
        )
    else:
        # Fallback: digest every file (no per-adapter partition declared).
        subset = sorted(set(_file_entry_key(item) for item in items), key=lambda path: path)
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
    runtime_platform = validated.get("runtime_platform")
    if not _is_linux_platform(runtime_platform):
        raise RuntimeError("Runtime Bundle requires a frozen linux/* platform")

    worker_image_identity = _validated_v2_worker_image_identity(
        validated.get("worker_image_identity")
    )
    # A V2 payload is executable only with the image identity frozen at bind
    # time. Include it in the row address so identical orchestration files from
    # two reviewed image releases cannot alias one database Bundle.
    harness_evidence = validated.get("harness_verification_evidence")
    if not isinstance(harness_evidence, Mapping):
        raise RuntimeError("V2 Runtime Bundle requires frozen Harness verification evidence")
    bundle_digest = _v2_bundle_digest(files, worker_image_identity, harness_evidence)

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

    # The source manifest can optionally declare directories, but its current
    # public shape predates the full V2 file inventory.  The built-in scope map
    # makes the partition unambiguous even before those optional annotations
    # land.  No adapter may receive an empty private scope.
    adapter_paths = {
        key: (
            {
                str(item.get("path"))
                for item in files
                if str(item.get("path") or "").startswith(f"{adapter_dirs[key]}/")
            }
            if adapter_dirs[key]
            else _v2_adapter_scope_paths(key, files)
        )
        for key in adapters
    }
    known_private_paths = set().union(*adapter_paths.values()) if adapter_paths else set()
    shared_files = [item for item in files if _file_entry_key(item) not in known_private_paths]

    adapter_digests: dict[str, str] = {}
    stamped_adapters: dict[str, dict[str, Any]] = {}
    for key in sorted(adapters):
        adapter = dict(adapters[key])
        validate_v2_manifest_adapter_capabilities(key, adapter.get("capabilities") or {})
        digest = adapter_digest_from_manifest_files(
            files,
            key,
            adapter_dir=adapter_dirs[key],
            shared_files=shared_files,
            adapter_paths=adapter_paths[key],
        )
        adapter_digests[key] = digest
        adapter_meta = dict(adapter.get("adapter") or {})
        adapter_meta["digest"] = digest
        adapter["adapter"] = adapter_meta
        stamped_adapters[key] = adapter

    _validate_evidence_adapter_identity(harness_evidence, stamped_adapters)

    v2_manifest = {
        "schema": "codify.worker.runtime-bundle/v2",
        "contract_version": HARNESS_CONTRACT_VERSION_V2,
        "event_schema": CANONICAL_EVENT_SCHEMA_V2,
        "adapters": stamped_adapters,
        "files": list(files),
        "bundle_digest": bundle_digest,
    }
    v2_manifest["runtime_platform"] = runtime_platform
    v2_manifest["worker_image_identity"] = worker_image_identity
    v2_manifest["harness_verification_evidence"] = dict(harness_evidence)
    return BuiltRuntimeBundleV2(
        digest=bundle_digest,
        schema="codify.worker.runtime-bundle/v2",
        contract_version=HARNESS_CONTRACT_VERSION_V2,
        event_schema=CANONICAL_EVENT_SCHEMA_V2,
        adapter_digests=adapter_digests,
        manifest=v2_manifest,
    )


def _validate_evidence_adapter_identity(
    evidence: Mapping[str, Any], adapters: Mapping[str, Mapping[str, Any]]
) -> None:
    """Bind verification evidence to the selected, frozen Adapter bytes."""
    harness_key = evidence.get("harness_key")
    if not isinstance(harness_key, str) or harness_key not in adapters:
        raise RuntimeError("V2 Runtime Bundle evidence Harness key has no frozen Adapter")
    actual = (adapters[harness_key].get("adapter") or {})
    expected = evidence.get("adapter")
    if not isinstance(expected, Mapping):
        raise RuntimeError("V2 Runtime Bundle evidence has no Adapter identity")
    for field in ("version", "digest"):
        if expected.get(field) != actual.get(field):
            raise RuntimeError(
                f"V2 Runtime Bundle evidence Adapter {field} does not match frozen Adapter"
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
        (path.relative_to(root).as_posix(), path.read_bytes()) for path in _controlled_paths(root)
    ]
    source_by_name = dict(source_files)
    harness_manifest = json.loads(source_by_name["deploy/worker-entrypoint/harness/manifest.json"])
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
            raise RuntimeError(f"Runtime source Adapter {adapter_key!r} is not an object")
        nested = metadata.get("adapter")
        adapter_version = str(nested.get("version")) if isinstance(nested, Mapping) else ""
        if not adapter_version:
            raise RuntimeError(f"Runtime source Adapter {adapter_key!r} has no adapter.version")
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
    cli_artifact_manifest_path: Path | None = None,
    worker_image_identity: Mapping[str, Any] | None = None,
    harness_verification_evidence: Mapping[str, Any] | None = None,
) -> WorkerRuntimeBundle:
    """Build and persist an immutable V2 runtime payload during Task binding.

    The repository manifest is a *template*, not execution truth.  We replace
    its ``files`` with the allowlisted source bytes while binding, stamp all
    digests, and persist the resulting deterministic archive.  Execution never
    reads the current checkout again.
    """
    root = (source_dir or default_runtime_source_dir()).resolve()
    source_files = _controlled_source_files(root)
    source_by_name = dict(source_files)
    manifest_source_name = "deploy/worker-entrypoint/harness/manifest.json"
    harness_manifest = json.loads(source_by_name[manifest_source_name])
    artifact_path = cli_artifact_manifest_path
    if artifact_path is None:
        configured_artifact_path = os.getenv(CLI_ARTIFACT_MANIFEST_ENV)
        artifact_path = Path(configured_artifact_path) if configured_artifact_path else None
    image_identity = _validated_v2_worker_image_identity(worker_image_identity)
    frozen_manifest = _freeze_cli_artifact_identities(
        harness_manifest,
        cli_artifact_manifest_path=artifact_path,
        worker_image_identity=image_identity,
    )
    if not isinstance(harness_verification_evidence, Mapping):
        raise RuntimeError("explicit V2 Task has no frozen Harness verification evidence")
    if harness_verification_evidence.get("image_identity") != image_identity:
        raise RuntimeError("explicit V2 Task Harness verification evidence does not match Worker image")
    # The stamped source manifest is itself a controlled Runtime Bundle file.
    # Replacing its template bytes before the file inventory is calculated
    # makes artifact version/SHA changes alter the Bundle and every Adapter
    # digest instead of only changing non-addressed metadata.
    stamped_manifest_source = json.dumps(
        frozen_manifest,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    source_files = [
        (name, stamped_manifest_source if name == manifest_source_name else payload)
        for name, payload in source_files
    ]
    frozen_manifest["files"] = [
        {
            "path": _archive_name(name).removeprefix(f"{RUNTIME_ARCHIVE_ROOT}/"),
            "sha256": _sha256(payload),
            "size": len(payload),
        }
        for name, payload in source_files
    ]
    # Evidence is DB/launcher execution authority, not a source file: including
    # its adapter digest in the source-manifest inventory would be recursive.
    frozen_manifest["harness_verification_evidence"] = deepcopy(dict(harness_verification_evidence))
    built = build_runtime_bundle_v2(frozen_manifest)
    archive_bytes = _build_v2_runtime_archive(built.manifest, source_files)
    archive_sha256 = _sha256(archive_bytes)
    stored_manifest = {**built.manifest, "archive_sha256": archive_sha256}
    existing = (
        await db.execute(
            select(WorkerRuntimeBundle).where(WorkerRuntimeBundle.digest == built.digest)
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    created = WorkerRuntimeBundle(
        digest=built.digest,
        bundle_bytes=archive_bytes,
        contract_version=built.contract_version,
        orchestration_version=ORCHESTRATION_VERSION,
        manifest=stored_manifest,
        size_bytes=len(archive_bytes),
    )
    try:
        async with db.begin_nested():
            db.add(created)
            await db.flush()
        return created
    except IntegrityError:
        return (
            await db.execute(
                select(WorkerRuntimeBundle).where(WorkerRuntimeBundle.digest == built.digest)
            )
        ).scalar_one()


def _freeze_cli_artifact_identities(
    manifest: Mapping[str, Any], *, cli_artifact_manifest_path: Path | None,
    worker_image_identity: Mapping[str, str],
) -> dict[str, Any]:
    """Stamp and validate the four release CLI identities before Bundle bind.

    ``deploy/worker-entrypoint/harness/manifest.json`` is a source template and
    deliberately carries placeholders.  A release exports the immutable
    ``codify.worker.cli-artifacts/v1`` document from its Worker image and points
    ``CODIFY_WORKER_CLI_ARTIFACT_MANIFEST`` at that file.  The lock is required
    for every V2 bind: source-embedded SHA values do not establish the Worker
    image or platform identity and therefore are never a production shortcut.
    Placeholder, missing, mismatched, or malformed identities fail closed.
    """
    frozen = deepcopy(dict(manifest))
    adapters = frozen.get("adapters")
    if not isinstance(adapters, dict) or not adapters:
        raise RuntimeError("Runtime source has no Adapter declarations")

    if cli_artifact_manifest_path is None:
        raise RuntimeError(
            f"V2 Runtime Bundle requires {CLI_ARTIFACT_MANIFEST_ENV} "
            "from the reviewed Worker image"
        )
    try:
        artifact_document = json.loads(cli_artifact_manifest_path.read_bytes())
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("Worker CLI artifact manifest is unreadable") from exc
    if artifact_document.get("schema") != "codify.worker.cli-artifacts/v1":
        raise RuntimeError("Worker CLI artifact manifest has an unsupported schema")
    raw_artifact_bytes = cli_artifact_manifest_path.read_bytes()
    if _sha256(raw_artifact_bytes) != worker_image_identity["cli_artifact_lock_sha256"]:
        raise RuntimeError("Worker CLI artifact lock bytes do not match the frozen Worker image")
    platform = artifact_document.get("platform")
    if not _is_linux_platform(platform):
        raise RuntimeError("Worker CLI artifact manifest has an invalid platform")
    if platform != worker_image_identity["runtime_platform"]:
        raise RuntimeError("Worker CLI artifact lock platform does not match the frozen Worker image")
    frozen["runtime_platform"] = platform
    frozen["worker_image_identity"] = dict(worker_image_identity)
    release_artifacts = artifact_document.get("artifacts")
    if not isinstance(release_artifacts, Mapping):
        raise RuntimeError("Worker CLI artifact manifest has no artifacts")

    expected_keys = set(adapters)
    if set(release_artifacts) != expected_keys:
        raise RuntimeError("Worker CLI artifact manifest must identify every Runtime Adapter")

    for key, adapter in adapters.items():
        if not isinstance(adapter, dict):
            raise RuntimeError(f"Runtime source Adapter {key!r} is not an object")
        source = adapter.get("source")
        if not isinstance(source, dict):
            raise RuntimeError(f"Runtime source Adapter {key!r} has no source identity")
        pinned_version = source.get("artifact_version")
        if not isinstance(pinned_version, str) or not pinned_version:
            raise RuntimeError(f"Runtime source Adapter {key!r} has no artifact version")
        released = release_artifacts.get(key)
        if not isinstance(released, Mapping):
            raise RuntimeError(f"Worker CLI artifact identity is missing for {key!r}")
        if released.get("version") != pinned_version:
            raise RuntimeError(
                f"Worker CLI artifact version mismatch for {key!r}: "
                f"Runtime={pinned_version!r}, image={released.get('version')!r}"
            )
        source["artifact_sha256"] = released.get("sha256")
        digest = source.get("artifact_sha256")
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(character not in "0123456789abcdef" for character in digest)
        ):
            raise RuntimeError(
                f"Runtime source Adapter {key!r} has no frozen artifact SHA-256; "
                f"set {CLI_ARTIFACT_MANIFEST_ENV} to the release image manifest"
            )
    runtime_platform = frozen.get("runtime_platform")
    if not _is_linux_platform(runtime_platform):
        raise RuntimeError("Runtime source requires a frozen linux/* platform")
    return frozen


def v2_launcher_manifest_bytes(bundle: WorkerRuntimeBundle) -> bytes:
    """Canonical bytes of the launcher-facing V2 manifest projection.

    The kit launcher expects ``adapters.<key> = {version, digest}``; the frozen
    V2 manifest nests them under an ``adapter`` object. Both the materialized
    ``orchestration/manifest.json`` and the ``CODIFY_RUNTIME_MANIFEST_DIGEST``
    env must derive from these exact bytes so the launcher's fileDigest
    comparison matches.
    """
    launcher_manifest = dict(bundle.manifest)
    # Archive checksum is DB transport integrity metadata.  Including it in the
    # embedded manifest would create a self-referential archive hash.
    launcher_manifest.pop("archive_sha256", None)
    flat_adapters: dict[str, Any] = {}
    for key, meta in (bundle.manifest.get("adapters") or {}).items():
        entry = dict(meta) if isinstance(meta, dict) else {}
        nested = entry.get("adapter") if isinstance(entry.get("adapter"), dict) else {}
        # The kit launcher reads version/digest at the top level; shell
        # adapters additionally rely on capabilities/options_schema/etc. Keep
        # the whole frozen entry and surface the nested identity beside it.
        entry["version"] = nested.get("version", "")
        entry["digest"] = nested.get("digest", "")
        flat_adapters[key] = entry
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
    # ``source_dir`` remains accepted for V1-compatible callers but is
    # intentionally ignored: a bound V2 Task must not be influenced by a newer
    # checkout.  Return the exact launcher manifest bytes embedded in its
    # persisted archive.
    del source_dir
    return _v2_archive_manifest_bytes(bundle)


def _controlled_source_files(root: Path) -> list[tuple[str, bytes]]:
    return [
        (path.relative_to(root).as_posix(), path.read_bytes()) for path in _controlled_paths(root)
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
    # Do not reconstruct from source_dir.  This payload was frozen at binding
    # and verified on load; returning it directly preserves retry semantics.
    del source_dir
    verify_bundle_bytes(bundle)
    return bundle.bundle_bytes


def _build_v2_runtime_archive(
    frozen_manifest: Mapping[str, Any], source_files: Iterable[tuple[str, bytes]]
) -> bytes:
    """Create a deterministic V2 archive from already-frozen source bytes."""
    launcher_manifest = v2_launcher_manifest_bytes(
        type("FrozenBundle", (), {"manifest": frozen_manifest})()
    )

    files: list[tuple[str, bytes]] = [
        ("codify-runtime/orchestration/manifest.json", launcher_manifest)
    ]
    files.extend((_archive_name(name), payload) for name, payload in source_files)
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


def _v2_archive_manifest_bytes(bundle: WorkerRuntimeBundle) -> bytes:
    """Read the embedded launcher manifest without consulting runtime source."""
    try:
        with tarfile.open(fileobj=io.BytesIO(bundle.bundle_bytes), mode="r:") as archive:
            member = archive.getmember(str(RUNTIME_ARCHIVE_ROOT / "manifest.json"))
            extracted = archive.extractfile(member)
            if extracted is None:
                raise RuntimeError("V2 Runtime Bundle manifest cannot be read")
            return extracted.read()
    except (KeyError, tarfile.TarError) as exc:
        raise RuntimeError("V2 Runtime Bundle archive is malformed") from exc


async def bind_runtime_bundle(
    db: AsyncSession,
    task: Task,
    *,
    source_task: Task | None = None,
    source_dir: Path | None = None,
    harness_key: str | None = None,
) -> WorkerRuntimeBundle:
    """Bind the immutable bundle during task creation or clone it for retry.

    Only a frozen Profile/Snapshot that explicitly requests harness/v2 binds a
    V2 bundle. A repository V2 manifest advertises built-ins but is never an
    implicit migration switch: dual-canary legacy Profiles continue binding V1
    bundles. Retry/clone always reuses the source binding so an attempt keeps
    its original contract.
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
    else:
        snapshot = getattr(task, "__dict__", {}).get("worker_profile_snapshot")
        frozen_harness_key = getattr(snapshot, "harness_key", None)
        if _task_explicitly_requests_v2(task):
            # The Snapshot is the immutable execution authority.  A caller
            # supplied key may only agree with it; otherwise a V2 opt-in could
            # silently take the V1 path below.
            if not isinstance(frozen_harness_key, str) or not frozen_harness_key:
                raise RuntimeError("explicit V2 Profile has no frozen Harness key")
            if harness_key is not None and harness_key != frozen_harness_key:
                raise RuntimeError(
                    "explicit V2 Profile Harness key does not match the frozen Snapshot"
                )
            _require_v2_manifest_adapter(source_dir, frozen_harness_key)
            config = getattr(snapshot, "harness_config_snapshot", None)
            identity = config.get("v2_worker_image_identity") if isinstance(config, dict) else None
            evidence = config.get("v2_harness_verification_evidence") if isinstance(config, dict) else None
            if not isinstance(evidence, Mapping):
                raise RuntimeError("explicit V2 Profile has no frozen Harness verification evidence")
            bundle = await get_or_create_runtime_bundle_v2(
                db, source_dir=source_dir, worker_image_identity=identity,
                harness_verification_evidence=evidence,
            )
        else:
            bundle = await get_or_create_runtime_bundle(db, source_dir=source_dir)
    task.runtime_bundle_id = bundle.id
    await db.flush()
    return bundle


def build_v2_verification_candidate(
    *, source_dir: Path | None, cli_artifact_manifest_path: Path | None,
    worker_image_identity: Mapping[str, Any], harness_verification_evidence: Mapping[str, Any],
) -> tuple[dict[str, Any], bytes]:
    """Freeze the exact V2 payload injected into a pre-start verifier container."""
    root = (source_dir or default_runtime_source_dir()).resolve()
    source_files = _controlled_source_files(root)
    source_by_name = dict(source_files)
    source_name = "deploy/worker-entrypoint/harness/manifest.json"
    frozen = _freeze_cli_artifact_identities(
        json.loads(source_by_name[source_name]), cli_artifact_manifest_path=cli_artifact_manifest_path,
        worker_image_identity=_validated_v2_worker_image_identity(worker_image_identity),
    )
    if harness_verification_evidence.get("image_identity") != frozen["worker_image_identity"]:
        raise RuntimeError("V2 verification evidence does not match frozen Worker image")
    source_manifest = json.dumps(frozen, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    source_files = [(name, source_manifest if name == source_name else value) for name, value in source_files]
    frozen["files"] = [
        {"path": _archive_name(name).removeprefix(f"{RUNTIME_ARCHIVE_ROOT}/"), "sha256": _sha256(value), "size": len(value)}
        for name, value in source_files
    ]
    frozen["harness_verification_evidence"] = deepcopy(dict(harness_verification_evidence))
    built = build_runtime_bundle_v2(frozen)
    return built.manifest, _build_v2_runtime_archive(built.manifest, source_files)


def frozen_v2_adapter_identity(
    harness_key: str,
    *,
    source_dir: Path | None = None,
    cli_artifact_manifest_path: Path | None = None,
    worker_image_identity: Mapping[str, Any] | None = None,
) -> dict[str, str]:
    """Resolve the selected Adapter identity from the exact bind source bytes.

    This is used while recording Profile verification evidence.  It performs the
    same release-lock stamping and controlled-file inventory as bind, then reads
    the selected stamped Adapter identity.  The synthetic evidence is only a
    construction aid; it never escapes this function or authorizes execution.
    """
    root = (source_dir or default_runtime_source_dir()).resolve()
    source_files = _controlled_source_files(root)
    source_by_name = dict(source_files)
    manifest_source_name = "deploy/worker-entrypoint/harness/manifest.json"
    manifest = json.loads(source_by_name[manifest_source_name])
    artifact_path = cli_artifact_manifest_path
    if artifact_path is None:
        configured = os.getenv(CLI_ARTIFACT_MANIFEST_ENV)
        artifact_path = Path(configured) if configured else None
    image_identity = _validated_v2_worker_image_identity(worker_image_identity)
    frozen = _freeze_cli_artifact_identities(
        manifest, cli_artifact_manifest_path=artifact_path, worker_image_identity=image_identity
    )
    stamped_manifest = json.dumps(frozen, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    source_files = [
        (name, stamped_manifest if name == manifest_source_name else payload)
        for name, payload in source_files
    ]
    frozen["files"] = [
        {"path": _archive_name(name).removeprefix(f"{RUNTIME_ARCHIVE_ROOT}/"), "sha256": _sha256(payload), "size": len(payload)}
        for name, payload in source_files
    ]
    frozen["harness_verification_evidence"] = {
        "harness_key": harness_key,
        "adapter": {"version": "__probe__", "digest": "__probe__"},
    }
    # Build once to calculate adapter digests. Its identity check is intentionally
    # bypassed only for this internal probe; no Bundle is persisted from it.
    adapters = frozen.get("adapters")
    if not isinstance(adapters, Mapping) or harness_key not in adapters:
        raise RuntimeError(f"V2 Runtime Bundle has no Adapter for {harness_key!r}")
    # Copy the digest calculation from build after immutable file inventory is fixed.
    adapter = adapters[harness_key]
    source = adapter.get("source") if isinstance(adapter, Mapping) else None
    adapter_dir = next(
        (source.get(k) for k in _V2_ADAPTER_DIR_KEYS if isinstance(source, Mapping) and isinstance(source.get(k), str) and source.get(k)),
        None,
    )
    all_paths = {
        key: (
            {str(item.get("path")) for item in frozen["files"] if str(item.get("path") or "").startswith(f"{(meta.get('source') or {}).get('directory')}/")}
            if isinstance(meta.get("source"), Mapping) and (meta.get("source") or {}).get("directory")
            else _v2_adapter_scope_paths(key, frozen["files"])
        )
        for key, meta in adapters.items()
    }
    shared = [item for item in frozen["files"] if _file_entry_key(item) not in set().union(*all_paths.values())]
    digest = adapter_digest_from_manifest_files(
        frozen["files"], harness_key, adapter_dir=adapter_dir, shared_files=shared,
        adapter_paths=all_paths[harness_key],
    )
    meta = adapter.get("adapter") if isinstance(adapter, Mapping) else None
    version = meta.get("version") if isinstance(meta, Mapping) else None
    if not isinstance(version, str) or not version:
        raise RuntimeError(f"V2 Runtime Bundle Adapter {harness_key!r} has no version")
    return {"version": version, "digest": digest}


def _require_v2_manifest_adapter(source_dir: Path | None, harness_key: str | None) -> None:
    """Fail closed when explicit V2 state has no matching source Adapter.

    This check deliberately happens before V2 bundle construction.  An explicit
    Profile is a release opt-in; a malformed/missing catalog must reject it,
    never cause an accidental V1 bind in dual-canary.
    """
    if not harness_key:
        raise RuntimeError("explicit V2 Profile has no frozen Harness key")
    root = (source_dir or default_runtime_source_dir()).resolve()
    path = root / "deploy/worker-entrypoint/harness/manifest.json"
    try:
        manifest = json.loads(path.read_bytes())
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("explicit V2 Profile has an unreadable Runtime manifest") from exc
    if not isinstance(manifest, dict):
        raise RuntimeError("explicit V2 Profile has an invalid Runtime manifest")
    adapters = manifest.get("adapters")
    if not isinstance(adapters, dict):
        raise RuntimeError("explicit V2 Profile Runtime manifest has no Adapter catalog")
    if not isinstance(adapters.get(harness_key), dict):
        raise RuntimeError(
            f"explicit V2 Profile Runtime manifest has no Adapter for {harness_key!r}"
        )


def _task_explicitly_requests_v2(task: Task) -> bool:
    """Return whether immutable Task state opted into harness/v2.

    Never consult the mutable Profile here. This keeps retry and worker-profile
    update paths frozen, and prevents the source manifest's catalog from
    silently converting every dual-canary Claude/Codex task to V2.
    """
    # Do not trigger a lazy relationship load here. Binding is also used by
    # historical/retry repair paths where no Snapshot was eagerly loaded; an
    # absent in-memory snapshot is conservatively V1, never an implicit V2.
    snapshot = getattr(task, "__dict__", {}).get("worker_profile_snapshot")
    if snapshot is None:
        return False
    config = getattr(snapshot, "harness_config_snapshot", None)
    return isinstance(config, dict) and config.get(
        "requested_runtime_contract_version"
    ) == HARNESS_CONTRACT_VERSION_V2


def verify_bundle_bytes(bundle: WorkerRuntimeBundle) -> None:
    if getattr(bundle, "contract_version", None) == HARNESS_CONTRACT_VERSION_V2:
        _verify_v2_bundle_bytes(bundle)
        return
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


def _verify_v2_bundle_bytes(bundle: WorkerRuntimeBundle) -> None:
    """Verify that V2's DB truth, launcher manifest, and payload are one set."""
    payload = bundle.bundle_bytes
    if not payload:
        raise RuntimeError("V2 Runtime Bundle has no persisted payload and is not executable")
    if bundle.size_bytes != len(payload):
        raise RuntimeError("V2 Runtime Bundle size does not match the database binding")
    runtime_platform = bundle.manifest.get("runtime_platform")
    if not _is_linux_platform(runtime_platform):
        raise RuntimeError("V2 Runtime Bundle has no frozen linux/* platform")
    identity = _validated_v2_worker_image_identity(bundle.manifest.get("worker_image_identity"))
    if identity["runtime_platform"] != runtime_platform:
        raise RuntimeError("V2 Runtime Bundle Worker image platform does not match manifest")
    expected_archive_sha = bundle.manifest.get("archive_sha256")
    if not isinstance(expected_archive_sha, str) or _sha256(payload) != expected_archive_sha:
        raise RuntimeError("V2 Runtime Bundle archive digest mismatch")
    files = bundle.manifest.get("files")
    if not isinstance(files, list) or not files:
        raise RuntimeError("V2 Runtime Bundle has no frozen files and is not executable")
    evidence = bundle.manifest.get("harness_verification_evidence")
    if not isinstance(evidence, Mapping):
        raise RuntimeError("V2 Runtime Bundle has no frozen Harness verification evidence")
    expected_digest = _v2_bundle_digest(
        files, bundle.manifest.get("worker_image_identity"), bundle.manifest.get("harness_verification_evidence")
    )
    if bundle.digest != expected_digest or bundle.manifest.get("bundle_digest") != bundle.digest:
        raise RuntimeError("V2 Runtime Bundle manifest digest does not match the database binding")
    try:
        with tarfile.open(fileobj=io.BytesIO(payload), mode="r:") as archive:
            members = archive.getmembers()
            file_members = [member for member in members if member.isfile()]
            names = [member.name for member in file_members]
            if len(names) != len(set(names)):
                raise RuntimeError("V2 Runtime Bundle contains duplicate archive paths")
            for member in members:
                path = PurePosixPath(member.name)
                if (
                    path.is_absolute()
                    or ".." in path.parts
                    or not (member.isfile() or member.isdir())
                ):
                    raise RuntimeError(f"Unsafe V2 Runtime Bundle member: {member.name}")
            manifest_name = str(RUNTIME_ARCHIVE_ROOT / "manifest.json")
            launcher_bytes = _v2_archive_manifest_bytes(bundle)
            launcher = json.loads(launcher_bytes)
            expected_launcher = json.loads(v2_launcher_manifest_bytes(bundle))
            if launcher != expected_launcher:
                raise RuntimeError("V2 Runtime Bundle launcher manifest is not frozen truth")
            expected_names = {manifest_name}
            for file_entry in files:
                relative = PurePosixPath(str(file_entry.get("path") or ""))
                if relative.is_absolute() or ".." in relative.parts or not relative.parts:
                    raise RuntimeError("V2 Runtime Bundle manifest contains an unsafe file path")
                name = str(RUNTIME_ARCHIVE_ROOT / relative)
                expected_names.add(name)
                member = archive.getmember(name)
                extracted = archive.extractfile(member)
                if extracted is None:
                    raise RuntimeError(f"V2 Runtime Bundle file cannot be read: {relative}")
                file_bytes = extracted.read()
                if len(file_bytes) != file_entry.get("size"):
                    raise RuntimeError(f"V2 Runtime Bundle file size mismatch: {relative}")
                if _sha256(file_bytes) != file_entry.get("sha256"):
                    raise RuntimeError(f"V2 Runtime Bundle file digest mismatch: {relative}")
            if set(names) != expected_names:
                raise RuntimeError("V2 Runtime Bundle archive and manifest file sets differ")
    except (KeyError, json.JSONDecodeError, tarfile.TarError) as exc:
        raise RuntimeError("V2 Runtime Bundle archive is malformed") from exc


async def load_bound_runtime_bundle(
    db: AsyncSession,
    task: Task,
) -> WorkerRuntimeBundle:
    """Load immutable execution truth; historical unbound tasks are read-only."""
    if task.runtime_bundle_id is None:
        raise RuntimeError("Task has no immutable Runtime Bundle; historical Tasks are read-only")
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
        _verify_v2_bundle_bytes(bundle)
        return bundle
    verify_bundle_bytes(bundle)
    return bundle
