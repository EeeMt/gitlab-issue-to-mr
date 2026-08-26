"""Worker runtime locator fingerprints, readiness records, and strict Kit probes.

Implements design §9.6, §10.3, §13.3-§13.6 and §19:

- ``runtime_locator_fingerprint()`` hashes only the Kit locator (daemon identity,
  ``runtime_mode``, ``worker_kit_version``, ``worker_kit_path``), so config edits
  that do not move the Kit never produce a new fingerprint.
- ``begin_runtime_check`` / ``finish_runtime_check`` implement the generation/CAS
  protocol: the check generation is incremented atomically before remote Docker
  I/O and a result is written only while the generation is still current. Later
  started checks win; late results are discarded.
- ``probe_worker_kit`` performs the side-effect-free strict-Mount probe (§13.6):
  a stopped container with ``Mount(type="bind", read_only=True)`` validates the
  bind source exists (missing source is rejected at create) and the Kit manifest
  and required files are read through the archive API. It never starts the
  container and never writes to the Kit path.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
import io
import json
import logging
import posixpath
import tarfile
import uuid
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import docker
from docker.types import Mount
from sqlalchemy import update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.docker_client import (
    DockerClientWrapper,
    DockerConnectionConfig,
    canonicalize_docker_host,
    resolve_docker_connection,
)
from app.core.harness_protocol import HARNESS_CONTRACT_VERSION_V2
from app.core.utcnow import utcnow
from app.core.worker_kit import BAKED_IMAGE_MODE, KIT_CONTAINER_PATH, MOUNTED_KIT_MODE
from app.core.worker_kit_inventory import (
    AVAILABILITY_PRESENT,
    HarnessInventoryError,
    content_inventory_digest,
    kit_identity_from_manifest_bytes,
    kit_relative_path,
    validate_content_inventory,
    validate_harness_inventory,
)
from app.models import WorkerRuntimeReadiness

logger = logging.getLogger(__name__)

READINESS_UNKNOWN = "unknown"
READINESS_READY = "ready"
READINESS_UNAVAILABLE = "unavailable"
READINESS_STATUSES = frozenset({READINESS_UNKNOWN, READINESS_READY, READINESS_UNAVAILABLE})

FAILURE_WORKER_KIT_NOT_FOUND = "worker_kit_not_found"
FAILURE_WORKER_KIT_INVALID = "worker_kit_invalid"
FAILURE_WORKER_KIT_VERSION_MISMATCH = "worker_kit_version_mismatch"

LOCATOR_SCHEMA = "codify.worker-runtime-locator/v1"
READINESS_SCOPE_SCHEMA = "codify.worker-runtime-readiness/v1"
VERIFICATION_SCHEMA = "codify.worker-runtime-verification/v1"
KIT_PROBE_CONTAINER_PATH = "/opt/codify-probe/kit"

_MISSING_BIND_SOURCE_HINT = "bind source path does not exist"


class RuntimeProbeTransientError(RuntimeError):
    """Raised when a Kit probe cannot reach a deterministic conclusion.

    Callers must treat this as "no new conclusion" and never persist
    ``unavailable`` from it (§13.5, §13.6).
    """


@dataclass(frozen=True)
class RuntimeCheckResult:
    """One deterministic probe outcome before it is persisted."""

    status: str
    failure_code: str | None = None
    failure_message: str | None = None
    harness_inventory: dict[str, Any] | None = None
    kit_identity: dict[str, Any] | None = None

    @property
    def is_unavailable(self) -> bool:
        return self.status == READINESS_UNAVAILABLE


@dataclass(frozen=True)
class RuntimeReadiness:
    """Derived readiness for one locator fingerprint at read time.

    ``status`` is the effective status: an expired ``ready`` is returned as
    ``unknown`` so callers never need to interpret ``ready_until`` themselves.
    """

    status: str
    docker_daemon_key: str | None = None
    runtime_mode: str | None = None
    worker_kit_version: str | None = None
    worker_kit_path: str | None = None
    failure_code: str | None = None
    failure_message: str | None = None
    checked_at: datetime | None = None
    ready_until: datetime | None = None
    check_generation: int = 0
    check_started_at: datetime | None = None
    updated_at: datetime | None = None

    harness_inventory: dict[str, Any] | None = None
    kit_identity: dict[str, Any] | None = None

    @property
    def is_ready(self) -> bool:
        return self.status == READINESS_READY

    @property
    def is_unavailable(self) -> bool:
        return self.status == READINESS_UNAVAILABLE


@dataclass(frozen=True)
class RuntimeProbeOutcome:
    """Effective readiness after a generation/CAS Kit probe, plus whether this
    probe's own conclusion was committed (§13.3/§13.5).

    ``committed=False`` means a later check superseded this probe (the CAS write
    was rejected); ``readiness`` then reflects the concurrent conclusion, and
    callers must not treat it as this probe's own deterministic failure. §13.5:
    only a *successfully committed* ``unavailable`` may fail the current task.
    """

    readiness: RuntimeReadiness
    committed: bool

    @property
    def is_ready(self) -> bool:
        return self.readiness.is_ready

    @property
    def is_unavailable(self) -> bool:
        return self.readiness.is_unavailable


def serialize_runtime_readiness(readiness: RuntimeReadiness) -> dict[str, Any]:
    """Serialize readiness for API responses (never secret material)."""
    return {
        "status": readiness.status,
        "failure_code": readiness.failure_code,
        "failure_message": readiness.failure_message,
        "checked_at": readiness.checked_at.isoformat() if readiness.checked_at else None,
        "ready_until": readiness.ready_until.isoformat() if readiness.ready_until else None,
        "harness_inventory": readiness.harness_inventory,
        "kit_identity": readiness.kit_identity,
    }


def runtime_locator_fingerprint(
    *,
    docker_daemon_key: str,
    runtime_mode: str | None,
    worker_kit_version: str | None,
    worker_kit_path: str | None,
) -> str | None:
    """Return the SHA-256 locator fingerprint (§10.3), or None for baked-image.

    Only ``mounted_kit`` targets locate a host Kit, so baked-image targets have
    no fingerprint and therefore no readiness row. The normalized JSON uses
    compact separators and sorted keys so equivalent inputs always hash equal.
    """
    mode = (runtime_mode or BAKED_IMAGE_MODE).strip()
    if mode != MOUNTED_KIT_MODE:
        return None
    payload = {
        "schema": LOCATOR_SCHEMA,
        "docker_daemon_key": docker_daemon_key,
        "runtime_mode": mode,
        "worker_kit_version": worker_kit_version,
        "worker_kit_path": worker_kit_path,
    }
    normalized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def runtime_readiness_fingerprint(
    locator_fingerprint: str | None,
    *,
    require_content_inventory: bool = False,
) -> str | None:
    """Return the readiness row key for one locator and verification level.

    V1 keeps using the historical locator key so existing readiness rows remain
    valid. V2's full content-identity probe gets a distinct key: a V2-only
    inventory failure must never make the same mounted Kit unavailable to a V1
    dual-canary Task (or vice versa).
    """
    if not locator_fingerprint:
        return None
    if not require_content_inventory:
        return locator_fingerprint
    payload = {
        "schema": READINESS_SCOPE_SCHEMA,
        "locator_fingerprint": locator_fingerprint,
        "require_content_inventory": True,
    }
    normalized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def profile_requires_content_inventory(profile: Any, harness_key: str | None = None) -> bool:
    """Return whether a profile's selected Harness requires V2 Kit identity."""
    selected_key = harness_key or getattr(profile, "default_harness_key", None) or "claude"
    runtimes = getattr(profile, "harness_runtimes", None) or {}
    runtime = runtimes.get(selected_key) if isinstance(runtimes, Mapping) else None
    return (
        isinstance(runtime, Mapping)
        and runtime.get("contract_version") == HARNESS_CONTRACT_VERSION_V2
    )


def runtime_verification_input_digest(
    *,
    docker_daemon_key: str,
    image: str,
    runtime_mode: str,
    worker_kit_version: str | None,
    worker_kit_path: str | None,
    volume_mounts: list[dict[str, Any]],
    environment_variables: list[dict[str, Any]],
    harness_key: str,
    enabled_harnesses: list[str],
    harness_constraints: dict[str, Any],
    harness_runtimes: dict[str, Any],
    require_skill_support: bool,
) -> str:
    """Compute the verification input digest (§10.2).

    Only inputs the validator actually reads or executes are included: the
    Docker daemon identity, image, mounts and non-secret environment passed to
    the verification container, the Worker Kit, the Harness/CLI runtime and
    constraints, and whether skills support is required. Run-instruction
    templates and pre/post scripts are deliberately excluded.
    """
    payload = {
        "schema": VERIFICATION_SCHEMA,
        "docker_daemon_key": docker_daemon_key,
        "image": image,
        "runtime_mode": (runtime_mode or BAKED_IMAGE_MODE).strip(),
        "worker_kit_version": worker_kit_version,
        "worker_kit_path": worker_kit_path,
        "volume_mounts": sorted(
            (
                {
                    "container_path": str(mount.get("container_path") or ""),
                    "host_path": str(mount.get("host_path") or ""),
                    "mode": str(mount.get("mode") or "ro"),
                }
                for mount in volume_mounts
            ),
            key=lambda item: item["container_path"],
        ),
        "environment_variables": sorted(
            (
                {
                    "key": str(item.get("key") or ""),
                    "value": str(item.get("value") or ""),
                }
                for item in environment_variables
            ),
            key=lambda item: item["key"],
        ),
        "harness_key": harness_key,
        "enabled_harnesses": sorted(enabled_harnesses),
        "harness_constraints": harness_constraints,
        "harness_runtimes": harness_runtimes,
        "require_skill_support": bool(require_skill_support),
    }
    normalized = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def _daemon_key_for_connection(connection: DockerConnectionConfig) -> str:
    return canonicalize_docker_host(
        connection.host,
        tls_enabled=connection.tls_ca is not None,
    )


def fingerprint_from_connection_and_kit(
    connection: DockerConnectionConfig,
    *,
    runtime_mode: str | None,
    worker_kit_version: str | None,
    worker_kit_path: str | None,
) -> str | None:
    """Compute the locator fingerprint for one resolved Docker target and Kit."""
    return runtime_locator_fingerprint(
        docker_daemon_key=_daemon_key_for_connection(connection),
        runtime_mode=runtime_mode,
        worker_kit_version=worker_kit_version,
        worker_kit_path=worker_kit_path,
    )


def fingerprint_from_docker_target(
    settings: Any,
    *,
    docker_host: str | None,
    docker_tls_ca: str | None,
    docker_tls_cert: str | None,
    docker_tls_key: str | None,
    runtime_mode: str | None,
    worker_kit_version: str | None,
    worker_kit_path: str | None,
) -> str | None:
    """Compute a locator fingerprint from profile/task Docker target fields."""
    connection = resolve_docker_connection(
        settings,
        docker_host=docker_host,
        docker_tls_ca=docker_tls_ca,
        docker_tls_cert=docker_tls_cert,
        docker_tls_key=docker_tls_key,
    )
    return fingerprint_from_connection_and_kit(
        connection,
        runtime_mode=runtime_mode,
        worker_kit_version=worker_kit_version,
        worker_kit_path=worker_kit_path,
    )


def fingerprint_from_snapshot(snapshot: Any, settings: Any) -> str | None:
    """Compute a locator fingerprint from a task snapshot."""
    return fingerprint_from_docker_target(
        settings,
        docker_host=getattr(snapshot, "docker_host", None),
        docker_tls_ca=getattr(snapshot, "docker_tls_ca", None),
        docker_tls_cert=getattr(snapshot, "docker_tls_cert", None),
        docker_tls_key=getattr(snapshot, "docker_tls_key", None),
        runtime_mode=getattr(snapshot, "runtime_mode", None) or BAKED_IMAGE_MODE,
        worker_kit_version=getattr(snapshot, "worker_kit_version", None),
        worker_kit_path=getattr(snapshot, "worker_kit_path", None),
    )


def fingerprint_from_profile(profile: Any, settings: Any) -> str | None:
    """Compute a locator fingerprint from an editable worker profile."""
    return fingerprint_from_docker_target(
        settings,
        docker_host=getattr(profile, "docker_host", None),
        docker_tls_ca=getattr(profile, "docker_tls_ca", None),
        docker_tls_cert=getattr(profile, "docker_tls_cert", None),
        docker_tls_key=getattr(profile, "docker_tls_key", None),
        runtime_mode=getattr(profile, "runtime_mode", None) or BAKED_IMAGE_MODE,
        worker_kit_version=getattr(profile, "worker_kit_version", None),
        worker_kit_path=getattr(profile, "worker_kit_path", None),
    )


async def read_runtime_readiness(
    db: AsyncSession,
    fingerprint: str | None,
    *,
    require_content_inventory: bool = False,
) -> RuntimeReadiness:
    """Return effective readiness for a locator and verification level."""
    readiness_fingerprint = runtime_readiness_fingerprint(
        fingerprint,
        require_content_inventory=require_content_inventory,
    )
    if not readiness_fingerprint:
        return RuntimeReadiness(status=READINESS_UNKNOWN)
    row = await db.get(WorkerRuntimeReadiness, readiness_fingerprint)
    if row is None:
        return RuntimeReadiness(status=READINESS_UNKNOWN)
    now = utcnow()
    if row.status == READINESS_READY:
        if row.ready_until is not None and row.ready_until > now:
            status = READINESS_READY
        else:
            status = READINESS_UNKNOWN
    elif row.status == READINESS_UNAVAILABLE:
        status = READINESS_UNAVAILABLE
    else:
        status = READINESS_UNKNOWN
    return RuntimeReadiness(
        status=status,
        docker_daemon_key=row.docker_daemon_key,
        runtime_mode=row.runtime_mode,
        worker_kit_version=row.worker_kit_version,
        worker_kit_path=row.worker_kit_path,
        failure_code=row.failure_code,
        failure_message=row.failure_message,
        checked_at=row.checked_at,
        ready_until=row.ready_until,
        check_generation=row.check_generation,
        check_started_at=row.check_started_at,
        updated_at=row.updated_at,
        harness_inventory=row.harness_inventory,
        kit_identity=row.kit_identity,
    )


async def readiness_for_profile(
    db: AsyncSession,
    profile: Any,
    settings: Any,
    *,
    shared: Any | None = None,
    harness_key: str | None = None,
) -> RuntimeReadiness:
    """Return the effective readiness for a profile's resolved Kit locator.

    Resolves the profile's effective configuration (including any shared
    baseline) so a ``system``-sourced Kit hashes the same fingerprint the
    snapshot would freeze (§12, §10.3). An unresolvable configuration has no
    known locator, so it returns ``unknown`` and never blocks: the gate only
    ever blocks on a *known* unavailable runtime, and profile validation stays
    with snapshot creation.

    ``shared`` is the caller's already-locked ``WorkerSharedConfigurationContext``
    (see ``load_shared_configuration(..., for_update=True)``). Passing it lets a
    task-create/F6-switch/CI-repair flow resolve the readiness gate and the
    frozen snapshot from the *same* locked baseline, so a concurrent shared PATCH
    cannot interleave between the two reads. When omitted the shared baseline is
    loaded unlocked (read-only callers such as verify-runtime, which must never
    hold the DB lock across Docker I/O).
    """
    from app.core.worker_profiles import WorkerProfileValidationError
    from app.core.worker_shared_configuration import (
        load_shared_configuration,
        resolve_effective_configuration,
    )

    try:
        if shared is None:
            shared = await load_shared_configuration(db)
        effective = resolve_effective_configuration(profile, shared)
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
    except WorkerProfileValidationError:
        # An unresolvable configuration has no known locator, so it returns
        # unknown and never blocks: the gate only ever blocks on a *known*
        # unavailable runtime, and profile validation stays with snapshot
        # creation. Programming errors (e.g. MissingGreenlet from an unloaded
        # lazy relationship) are NOT swallowed here — they must surface so a
        # caller bug cannot silently bypass the 409 gate.
        return RuntimeReadiness(status=READINESS_UNKNOWN)
    return await read_runtime_readiness(
        db,
        fingerprint,
        require_content_inventory=profile_requires_content_inventory(profile, harness_key),
    )


def runtime_unavailable_http_detail(readiness: RuntimeReadiness) -> dict[str, Any]:
    """Build the 409 ``worker_runtime_unavailable`` error detail (§16.3).

    Never includes TLS paths, cert contents, or secret environment values.
    """
    return {
        "code": "worker_runtime_unavailable",
        "message": "Worker runtime is currently unavailable; no task can be created for it",
        "failure_code": readiness.failure_code,
        "failure_message": readiness.failure_message,
        "checked_at": readiness.checked_at.isoformat() if readiness.checked_at else None,
    }


async def begin_runtime_check(
    db: AsyncSession,
    *,
    fingerprint: str,
    docker_daemon_key: str,
    runtime_mode: str,
    worker_kit_version: str | None,
    worker_kit_path: str | None,
    require_content_inventory: bool = False,
) -> int:
    """Atomically start a check: create/lock the row and increment the generation.

    The caller must release the DB transaction before performing remote Docker
    I/O and pass the returned generation to ``finish_runtime_check``. Existing
    readiness conclusions are preserved until the new result is written.
    """
    readiness_fingerprint = runtime_readiness_fingerprint(
        fingerprint,
        require_content_inventory=require_content_inventory,
    )
    if not readiness_fingerprint:
        raise ValueError("begin_runtime_check requires a locator fingerprint")
    row = await db.get(WorkerRuntimeReadiness, readiness_fingerprint, with_for_update=True)
    if row is None:
        row = WorkerRuntimeReadiness(
            runtime_locator_fingerprint=readiness_fingerprint,
            docker_daemon_key=docker_daemon_key,
            runtime_mode=runtime_mode,
            worker_kit_version=worker_kit_version,
            worker_kit_path=worker_kit_path,
            status=READINESS_UNKNOWN,
            check_generation=0,
        )
        db.add(row)
        try:
            async with db.begin_nested():
                await db.flush()
        except IntegrityError:
            # Another writer created the row between our SELECT and INSERT. The
            # savepoint rollback keeps the surrounding transaction usable.
            row = await db.get(
                WorkerRuntimeReadiness,
                readiness_fingerprint,
                with_for_update=True,
            )
            if row is None:  # pragma: no cover - defensive
                raise
    row.check_generation += 1
    row.check_started_at = utcnow()
    row.docker_daemon_key = docker_daemon_key
    row.runtime_mode = runtime_mode
    row.worker_kit_version = worker_kit_version
    row.worker_kit_path = worker_kit_path
    await db.flush()
    return row.check_generation


async def finish_runtime_check(
    db: AsyncSession,
    *,
    fingerprint: str,
    generation: int,
    status: str,
    failure_code: str | None = None,
    failure_message: str | None = None,
    ready_until: datetime | None = None,
    harness_inventory: dict[str, Any] | None = None,
    kit_identity: dict[str, Any] | None = None,
    require_content_inventory: bool = False,
) -> bool:
    """Write a check result only while the generation is still current (CAS).

    Returns True when written, False when superseded by a later check. A late
    result must never change readiness or any task state (§13.3, §19).
    """
    if status not in READINESS_STATUSES:
        raise ValueError(f"invalid readiness status: {status!r}")
    readiness_fingerprint = runtime_readiness_fingerprint(
        fingerprint,
        require_content_inventory=require_content_inventory,
    )
    if not readiness_fingerprint:
        raise ValueError("finish_runtime_check requires a locator fingerprint")
    # A read-then-write is not CAS across two sessions: a newer probe can bump
    # generation after the read and before flush. Put the generation predicate
    # on the SQL UPDATE itself and use rowcount as the sole success authority.
    result = await db.execute(
        update(WorkerRuntimeReadiness)
        .where(
            WorkerRuntimeReadiness.runtime_locator_fingerprint == readiness_fingerprint,
            WorkerRuntimeReadiness.check_generation == generation,
        )
        .values(
            status=status,
            checked_at=utcnow(),
            failure_code=failure_code,
            failure_message=failure_message,
            ready_until=ready_until if status == READINESS_READY else None,
            harness_inventory=harness_inventory,
            kit_identity=kit_identity,
        )
    )
    return result.rowcount == 1


def _ensure_probe_image(client: DockerClientWrapper, image: str) -> None:
    try:
        client.client.images.get(image)
    except docker.errors.NotFound as exc:
        raise RuntimeProbeTransientError(
            f"Probe image {image!r} is not present on the Docker host"
        ) from exc


def _read_archive_file(
    client: DockerClientWrapper,
    container: Any,
    path: str,
) -> bytes | None:
    """Read one file from a stopped container via the archive API.

    ``docker.errors.NotFound`` propagates unchanged (deterministic absence);
    any other failure is a transient probe error (§13.6 step 6).
    """
    try:
        bits, _stat = container.get_archive(path)
    except docker.errors.NotFound:
        raise
    except Exception as exc:  # noqa: BLE001 - connection/API incompatibility
        raise RuntimeProbeTransientError(
            f"Could not read {path!r} from probe container: {exc}"
        ) from exc
    buf = io.BytesIO()
    for chunk in bits:
        buf.write(chunk)
    buf.seek(0)
    with tarfile.open(fileobj=buf) as tar:
        members = tar.getmembers()
        if not members:
            return None
        extracted = tar.extractfile(members[0])
        if extracted is None:
            return None
        return extracted.read()


class _ChunkedReader:
    """Minimal ``read()``-only stream over an iterable of byte chunks.

    Tar streaming mode pulls only as many chunks as it needs to parse the next
    header, so a directory probe never buffers the full archive.
    """

    def __init__(self, chunks: Any) -> None:
        self._chunks = iter(chunks)
        self._buffer = b""

    def read(self, n: int = -1) -> bytes:
        if n < 0:
            data = b"".join(self._chunks)
            self._buffer, data = b"", self._buffer + data
            return data
        while len(self._buffer) < n:
            try:
                self._buffer += next(self._chunks)
            except StopIteration:
                break
        data, self._buffer = self._buffer[:n], self._buffer[n:]
        return data


def _archive_has_member(container: Any, path: str) -> bool:
    """Return True when the archive at ``path`` has at least one member.

    Streams only the leading tar headers (up to the first member) instead of
    buffering the whole archive, so the large ``nix/store`` tree is never pulled
    into memory (§13.6). A missing path (``NotFound``) or an archive with no
    members means the path has no usable content.
    """
    try:
        bits, _stat = container.get_archive(path)
    except docker.errors.NotFound:
        return False
    except Exception as exc:  # noqa: BLE001 - connection/API incompatibility
        raise RuntimeProbeTransientError(
            f"Could not read {path!r} from probe container: {exc}"
        ) from exc
    try:
        with tarfile.open(fileobj=_ChunkedReader(bits), mode="r|") as tar:
            return tar.next() is not None
    except tarfile.TarError:
        # A path that cannot be parsed as a tar is treated as absent content,
        # not a transient probe failure.
        return False


def _stat_and_hash_archive_file(
    client: DockerClientWrapper,
    container: Any,
    path: str,
) -> tuple[int, int, str] | None:
    """Return ``(mode, size, sha256)`` for one file via the archive API.

    Streams the tar member in chunks so multi-hundred-MB CLI payloads are
    never buffered whole. ``None`` means deterministic absence; anything else
    that prevents a conclusion raises ``RuntimeProbeTransientError``.
    """
    try:
        bits, _stat = container.get_archive(path)
    except docker.errors.NotFound:
        return None
    except Exception as exc:  # noqa: BLE001 - connection/API incompatibility
        raise RuntimeProbeTransientError(
            f"Could not read {path!r} from probe container: {exc}"
        ) from exc
    digest = hashlib.sha256()
    mode: int | None = None
    total = 0
    try:
        with tarfile.open(fileobj=_ChunkedReader(bits), mode="r|") as tar:
            member = tar.next()
            if member is None:
                return None
            extracted = tar.extractfile(member)
            if extracted is None:
                return None
            mode = member.mode
            while True:
                chunk = extracted.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
                total += len(chunk)
    except tarfile.TarError as exc:
        raise RuntimeProbeTransientError(
            f"Could not parse archive for {path!r} from probe container: {exc}"
        ) from exc
    return mode, total, digest.hexdigest()


def _content_inventory_from_archive(container: Any, root: str) -> list[dict[str, Any]] | None:
    """Stream every identity-bearing Kit file from a mounted archive tree."""
    try:
        bits, _stat = container.get_archive(root)
    except docker.errors.NotFound:
        return None
    except Exception as exc:  # noqa: BLE001 - connection/API incompatibility
        raise RuntimeProbeTransientError(
            f"Could not read complete Worker Kit content under {root!r}: {exc}"
        ) from exc

    root_name = posixpath.basename(root.rstrip("/"))
    excluded = {"manifest.json", ".install-receipt.json", ".smoke-passed"}
    entries: list[dict[str, Any]] = []
    file_entries: dict[str, dict[str, Any]] = {}
    hardlink_targets: dict[str, str] = {}
    seen: set[str] = set()
    member_paths: set[str] = set()
    symlink_targets: list[tuple[str, str]] = []

    def resolve_link_target(relative: str, target: object) -> str:
        if not isinstance(target, str) or not target or target.startswith("/") or "\\" in target:
            raise HarnessInventoryError(
                f"Worker Kit archive contains an unsafe link target: {relative!r}"
            )
        if target == root_name or target.startswith(f"{root_name}/"):
            candidate = target[len(root_name) :].lstrip("/")
        else:
            candidate = posixpath.join(posixpath.dirname(relative), target)
        resolved = posixpath.normpath(candidate)
        if (
            not resolved
            or resolved in {".", ".."}
            or resolved.startswith("../")
            or resolved.startswith("/")
            or "\\" in resolved
            or any(part in {"", ".", ".."} for part in resolved.split("/"))
        ):
            raise HarnessInventoryError(
                f"Worker Kit archive contains an unsafe link target: {relative!r}"
            )
        return resolved

    try:
        with tarfile.open(fileobj=_ChunkedReader(bits), mode="r|") as tar:
            for member in tar:
                name = member.name
                if name.rstrip("/") == root_name:
                    continue
                prefix = f"{root_name}/"
                if name.startswith(prefix):
                    relative = name[len(prefix) :]
                else:
                    relative = name
                relative = posixpath.normpath(relative)
                if relative in excluded:
                    continue
                if (
                    not relative
                    or relative in {".", ".."}
                    or relative.startswith("../")
                    or relative.startswith("/")
                    or "\\" in relative
                    or any(part in {"", ".", ".."} for part in relative.split("/"))
                ):
                    raise HarnessInventoryError(
                        f"Worker Kit archive contains an unsafe content path: {name!r}"
                    )
                if relative in seen:
                    raise HarnessInventoryError(
                        f"Worker Kit archive contains duplicate content path: {relative!r}"
                    )
                seen.add(relative)
                member_paths.add(relative)
                if member.isdir():
                    continue
                if member.issym():
                    resolved_target = resolve_link_target(relative, member.linkname)
                    symlink_targets.append((name, resolved_target))
                    entries.append({"kind": "symlink", "path": relative, "target": member.linkname})
                    continue
                if member.islnk():
                    resolved_target = resolve_link_target(relative, member.linkname)
                    hardlink_targets[relative] = resolved_target
                    continue
                if not member.isfile():
                    raise HarnessInventoryError(
                        f"Worker Kit archive contains unsupported content type: {name!r}"
                    )
                extracted = tar.extractfile(member)
                if extracted is None:
                    raise HarnessInventoryError(
                        f"Worker Kit archive content has no bytes: {name!r}"
                    )
                digest = hashlib.sha256()
                size = 0
                while True:
                    chunk = extracted.read(1024 * 1024)
                    if not chunk:
                        break
                    digest.update(chunk)
                    size += len(chunk)
                entry = {
                    "kind": "file",
                    "path": relative,
                    "sha256": digest.hexdigest(),
                    "size": size,
                }
                entries.append(entry)
                file_entries[relative] = entry
        def resolve_hardlink(relative: str, visiting: set[str]) -> dict[str, Any]:
            target_entry = file_entries.get(relative)
            if target_entry is not None:
                return target_entry
            target = hardlink_targets.get(relative)
            if target is None or relative in visiting:
                raise HarnessInventoryError(
                    "Worker Kit archive hard-link target is absent, cyclic, or not a file: "
                    f"{relative!r}"
                )
            target_entry = resolve_hardlink(target, visiting | {relative})
            entry = {
                "kind": "file",
                "path": relative,
                "sha256": target_entry["sha256"],
                "size": target_entry["size"],
            }
            file_entries[relative] = entry
            entries.append(entry)
            return entry

        for relative in hardlink_targets:
            resolve_hardlink(relative, set())
        for name, target in symlink_targets:
            if target not in member_paths:
                raise HarnessInventoryError(
                    f"Worker Kit archive symlink target is absent: {name!r}"
                )
    except tarfile.TarError as exc:
        raise RuntimeProbeTransientError(
            f"Could not parse complete Worker Kit content under {root!r}: {exc}"
        ) from exc
    return sorted(entries, key=lambda entry: entry["path"])


def _inspect_kit_contents(
    client: DockerClientWrapper,
    container: Any,
    *,
    worker_kit_version: str,
    worker_kit_path: str,
    root: str = KIT_PROBE_CONTAINER_PATH,
    require_content_inventory: bool = False,
) -> RuntimeCheckResult:
    try:
        manifest_bytes = _read_archive_file(client, container, f"{root}/manifest.json")
    except docker.errors.NotFound:
        return RuntimeCheckResult(
            status=READINESS_UNAVAILABLE,
            failure_code=FAILURE_WORKER_KIT_INVALID,
            failure_message=(f"Worker Kit manifest.json is missing under {worker_kit_path!r}"),
        )
    if not manifest_bytes:
        return RuntimeCheckResult(
            status=READINESS_UNAVAILABLE,
            failure_code=FAILURE_WORKER_KIT_INVALID,
            failure_message=(f"Worker Kit manifest.json is empty under {worker_kit_path!r}"),
        )
    try:
        manifest = json.loads(manifest_bytes.decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        return RuntimeCheckResult(
            status=READINESS_UNAVAILABLE,
            failure_code=FAILURE_WORKER_KIT_INVALID,
            failure_message=(
                f"Worker Kit manifest.json is not valid JSON under {worker_kit_path!r}"
            ),
        )
    if not isinstance(manifest, Mapping) or (
        manifest.get("schema_version") != 2
        or manifest.get("manifest_kind") != "codify.worker.kit-manifest/v1"
    ):
        return RuntimeCheckResult(
            status=READINESS_UNAVAILABLE,
            failure_code=FAILURE_WORKER_KIT_INVALID,
            failure_message=(
                "Worker Kit manifest has an unsupported schema or is not a "
                f"Kit manifest under {worker_kit_path!r}"
            ),
        )
    declared_version = manifest.get("kit_version")
    if declared_version != worker_kit_version:
        return RuntimeCheckResult(
            status=READINESS_UNAVAILABLE,
            failure_code=FAILURE_WORKER_KIT_VERSION_MISMATCH,
            failure_message=(
                f"Worker Kit version mismatch: expected {worker_kit_version!r}, "
                f"found {declared_version!r}"
            ),
        )
    for relative in ("launcher", "entrypoint.sh"):
        try:
            _read_archive_file(client, container, f"{root}/{relative}")
        except docker.errors.NotFound:
            return RuntimeCheckResult(
                status=READINESS_UNAVAILABLE,
                failure_code=FAILURE_WORKER_KIT_INVALID,
                failure_message=(
                    f"Worker Kit required file {relative!r} is missing under {worker_kit_path!r}"
                ),
            )
    if not _archive_has_member(container, f"{root}/nix/store"):
        return RuntimeCheckResult(
            status=READINESS_UNAVAILABLE,
            failure_code=FAILURE_WORKER_KIT_INVALID,
            failure_message=(
                f"Worker Kit nix/store directory is missing under {worker_kit_path!r}"
            ),
        )
    try:
        kit_identity = kit_identity_from_manifest_bytes(
            manifest_bytes,
            require_content_inventory=require_content_inventory,
        )
        inventory = validate_harness_inventory(manifest.get("harness_inventory"))
        if require_content_inventory or "content_inventory" in manifest:
            content_inventory = validate_content_inventory(manifest.get("content_inventory"))
            actual_content_inventory = _content_inventory_from_archive(container, root)
            if actual_content_inventory is None:
                raise HarnessInventoryError("Worker Kit content inventory archive is missing")
            if actual_content_inventory != content_inventory:
                raise HarnessInventoryError(
                    "Worker Kit content inventory does not match mounted bytes"
                )
            if manifest.get("content_inventory_sha256") != content_inventory_digest(
                content_inventory
            ):
                raise HarnessInventoryError(
                    "Worker Kit content inventory digest does not match manifest"
                )
    except HarnessInventoryError as exc:
        return RuntimeCheckResult(
            status=READINESS_UNAVAILABLE,
            failure_code=FAILURE_WORKER_KIT_INVALID,
            failure_message=(
                "Worker Kit harness inventory or identity is invalid under "
                f"{worker_kit_path!r}: {exc}"
            ),
        )
    # Fail closed on every present entry's actual bytes: missing, non-
    # executable, truncated or tampered payloads invalidate the whole Kit.
    for key, entry in inventory.items():
        if entry.get("availability") != AVAILABILITY_PRESENT:
            continue
        relative = kit_relative_path(str(entry["path"]))
        observed = _stat_and_hash_archive_file(client, container, f"{root}/{relative}")
        if observed is None:
            return RuntimeCheckResult(
                status=READINESS_UNAVAILABLE,
                failure_code=FAILURE_WORKER_KIT_INVALID,
                failure_message=(
                    f"Worker Kit inventory marks {key!r} present but its file "
                    f"{relative!r} is missing under {worker_kit_path!r}"
                ),
            )
        mode, size, sha256 = observed
        if not mode & 0o111:
            return RuntimeCheckResult(
                status=READINESS_UNAVAILABLE,
                failure_code=FAILURE_WORKER_KIT_INVALID,
                failure_message=(
                    f"Worker Kit inventory file for {key!r} ({relative!r}) is "
                    f"not executable under {worker_kit_path!r}"
                ),
            )
        if size != int(entry["size"]) or sha256 != str(entry["sha256"]):
            return RuntimeCheckResult(
                status=READINESS_UNAVAILABLE,
                failure_code=FAILURE_WORKER_KIT_INVALID,
                failure_message=(
                    f"Worker Kit integrity check failed for {key!r}: recorded "
                    f"bytes do not match the installed file {relative!r} under "
                    f"{worker_kit_path!r}"
                ),
            )
    return RuntimeCheckResult(
        status=READINESS_READY,
        harness_inventory=inventory,
        kit_identity=kit_identity,
    )


def inspect_mounted_kit_container(
    client: DockerClientWrapper,
    container: Any,
    *,
    worker_kit_version: str,
    worker_kit_path: str,
) -> RuntimeCheckResult:
    """Verify the Kit mounted in the actual stopped Worker container.

    This is the final V2 check immediately before ``start``. It reads the
    container's own ``/opt/codify-kit`` mount rather than a separate probe
    container, closing the probe-to-worker bind gap as far as Docker's stopped
    container API permits.
    """
    return _inspect_kit_contents(
        client,
        container,
        worker_kit_version=worker_kit_version,
        worker_kit_path=worker_kit_path,
        root=KIT_CONTAINER_PATH,
        require_content_inventory=True,
    )


def _missing_bind_source(exc: Exception) -> bool:
    return _MISSING_BIND_SOURCE_HINT in str(exc).lower()


def probe_worker_kit(
    connection: DockerConnectionConfig,
    *,
    image: str,
    runtime_mode: str,
    worker_kit_version: str,
    worker_kit_path: str,
    connect_timeout: int = 10,
    operation_timeout: int = 120,
    require_content_inventory: bool = False,
) -> RuntimeCheckResult:
    """Run the side-effect-free strict-Mount Kit probe (§13.6).

    Returns a deterministic ``RuntimeCheckResult`` (``ready`` or one of the
    ``unavailable`` failure codes) or raises ``RuntimeProbeTransientError`` when
    no deterministic conclusion is possible. The container is created stopped and
    always removed; the Kit path is mounted read-only and never written.
    """
    if (runtime_mode or BAKED_IMAGE_MODE).strip() != MOUNTED_KIT_MODE:
        raise RuntimeProbeTransientError("Kit probe requires mounted_kit mode")
    client = None
    container = None
    try:
        # Construct inside the try: ``version="auto"`` performs a Docker daemon
        # handshake during construction, which raises raw ``DockerException`` on
        # an unreachable daemon. §13.5/§13.6 treat connection failures as
        # transient — "no new conclusion" — never an unclassified 500/crash.
        client = DockerClientWrapper(
            connection,
            connect_timeout=connect_timeout,
            operation_timeout=operation_timeout,
        )
        _ensure_probe_image(client, image)
        try:
            container = client.client.containers.create(
                image,
                ["true"],
                mounts=[
                    Mount(
                        type="bind",
                        source=worker_kit_path,
                        target=KIT_PROBE_CONTAINER_PATH,
                        read_only=True,
                    )
                ],
                name=f"codify-kit-probe-{uuid.uuid4().hex[:8]}",
                labels={
                    "codify.kit_probe": "true",
                    "codify.worker_kit_version": worker_kit_version or "",
                },
            )
        except docker.errors.APIError as exc:
            if _missing_bind_source(exc):
                return RuntimeCheckResult(
                    status=READINESS_UNAVAILABLE,
                    failure_code=FAILURE_WORKER_KIT_NOT_FOUND,
                    failure_message=(
                        f"Worker Kit directory {worker_kit_path!r} does not exist "
                        "on the Docker host"
                    ),
                )
            raise RuntimeProbeTransientError(f"Could not create probe container: {exc}") from exc
        return _inspect_kit_contents(
            client,
            container,
            worker_kit_version=worker_kit_version,
            worker_kit_path=worker_kit_path,
            require_content_inventory=require_content_inventory,
        )
    except docker.errors.DockerException as exc:
        raise RuntimeProbeTransientError(
            f"Could not reach Docker daemon for Kit probe: {exc}"
        ) from exc
    finally:
        if container is not None:
            with contextlib.suppress(Exception):
                container.remove(force=True, v=True)
        if client is not None:
            with contextlib.suppress(Exception):
                client.close()


async def run_deterministic_kit_probe(
    db: AsyncSession,
    *,
    connection: DockerConnectionConfig,
    image: str,
    runtime_mode: str,
    worker_kit_version: str,
    worker_kit_path: str,
    ttl_seconds: int,
    require_content_inventory: bool = False,
) -> RuntimeProbeOutcome:
    """Run the full generation/CAS Kit probe and return the derived readiness.

    Begins a check, performs the remote probe, writes the result through the CAS
    protocol, and returns the post-check effective readiness together with
    whether this probe's conclusion was committed (§13.3/§13.5). A transient
    probe re-raises ``RuntimeProbeTransientError`` and leaves no new persistent
    state: a conclusion-less row it created (or reused) is removed
    (§13.5/§13.6). The caller owns the surrounding DB transaction/commit.
    """
    fingerprint = fingerprint_from_connection_and_kit(
        connection,
        runtime_mode=runtime_mode,
        worker_kit_version=worker_kit_version,
        worker_kit_path=worker_kit_path,
    )
    if fingerprint is None:
        return RuntimeProbeOutcome(
            readiness=RuntimeReadiness(status=READINESS_UNKNOWN),
            committed=False,
        )
    generation = await begin_runtime_check(
        db,
        fingerprint=fingerprint,
        docker_daemon_key=_daemon_key_for_connection(connection),
        runtime_mode=runtime_mode,
        worker_kit_version=worker_kit_version,
        worker_kit_path=worker_kit_path,
        require_content_inventory=require_content_inventory,
    )
    await db.commit()
    try:
        result = await asyncio.to_thread(
            probe_worker_kit,
            connection,
            image=image,
            runtime_mode=runtime_mode,
            worker_kit_version=worker_kit_version,
            worker_kit_path=worker_kit_path,
            require_content_inventory=require_content_inventory,
        )
    except RuntimeProbeTransientError:
        await _discard_incomplete_runtime_check(
            db,
            fingerprint,
            generation,
            require_content_inventory=require_content_inventory,
        )
        raise
    now = utcnow()
    ready_until = now + timedelta(seconds=ttl_seconds) if result.status == READINESS_READY else None
    committed = await finish_runtime_check(
        db,
        fingerprint=fingerprint,
        generation=generation,
        status=result.status,
        failure_code=result.failure_code,
        failure_message=result.failure_message,
        ready_until=ready_until,
        harness_inventory=result.harness_inventory,
        kit_identity=result.kit_identity,
        require_content_inventory=require_content_inventory,
    )
    await db.commit()
    return RuntimeProbeOutcome(
        readiness=await read_runtime_readiness(
            db,
            fingerprint,
            require_content_inventory=require_content_inventory,
        ),
        committed=committed,
    )


async def _discard_incomplete_runtime_check(
    db: AsyncSession,
    fingerprint: str,
    generation: int,
    *,
    require_content_inventory: bool = False,
) -> None:
    """Remove a conclusion-less readiness row abandoned by a transient probe.

    A transient probe never writes a conclusion (§13.5/§13.6), so the row it
    created via ``begin_runtime_check`` (or an already-unknown row it reused)
    would otherwise accumulate forever with ``status=unknown, checked_at=NULL``.
    The row is deleted only while it still carries no conclusion and no newer
    check has superseded our generation, so a concurrent conclusion or a newer
    check is never destroyed.
    """
    readiness_fingerprint = runtime_readiness_fingerprint(
        fingerprint,
        require_content_inventory=require_content_inventory,
    )
    if not readiness_fingerprint:
        await db.commit()
        return
    row = await db.get(WorkerRuntimeReadiness, readiness_fingerprint, with_for_update=True)
    if row is None:
        await db.commit()
        return
    if (
        row.check_generation == generation
        and row.status == READINESS_UNKNOWN
        and row.checked_at is None
    ):
        await db.delete(row)
    await db.commit()


FAILURE_HARNESS_CLI_UNAVAILABLE = "harness_cli_unavailable"
FAILURE_WORKER_KIT_UNAVAILABLE = "worker_kit_unavailable"


def is_harness_available(
    readiness: RuntimeReadiness, harness_key: str
) -> bool | None:
    """Return the observed availability of one Harness, or None when unknown.

    ``None`` means the last committed probe predates Kit inventory evidence or
    the locator was never probed; callers must not reject on unknown.
    ``True`` requires an explicit ``present`` entry; every other recorded
    state (absent for any reason, missing key) is unavailable.
    """
    inventory = getattr(readiness, "harness_inventory", None)
    if not isinstance(inventory, Mapping) or not inventory:
        return None
    if getattr(readiness, "status", None) == READINESS_UNAVAILABLE:
        return False
    entry = inventory.get(harness_key)
    if not isinstance(entry, Mapping):
        return False
    return entry.get("availability") == AVAILABILITY_PRESENT


def harness_cli_unavailable_detail(
    readiness: RuntimeReadiness,
    harness_key: str,
) -> dict[str, Any]:
    """Build the stable sanitized rejection detail for an absent Harness.

    Never includes tokens, environment values, payload paths outside the Kit
    contract, or native diagnostics. The absent reason code is surfaced so
    operators can distinguish a deliberate build exclusion from a degraded
    payload.
    """
    entry = (readiness.harness_inventory or {}).get(harness_key)
    reason_code = (
        entry.get("reason_code")
        if isinstance(entry, Mapping) and entry.get("availability") == "absent"
        else None
    )
    return {
        "code": FAILURE_HARNESS_CLI_UNAVAILABLE,
        "harness_key": harness_key,
        "message": (
            f"Harness {harness_key!r} is not available in Worker Kit "
            f"{readiness.worker_kit_version!r}; select a present Harness"
        ),
        "failure_code": FAILURE_HARNESS_CLI_UNAVAILABLE,
        "reason_code": reason_code,
        "kit_version": readiness.worker_kit_version,
        "checked_at": readiness.checked_at.isoformat() if readiness.checked_at else None,
    }


class WorkerRuntimeUnavailableError(RuntimeError):
    """A re-check after a container create/start Kit error found the Kit gone.

    Raised in the container error path (§13.4) when the strict probe
    deterministically concludes the frozen Kit locator is unavailable, so the
    task fails with a structured Kit error instead of a vague Docker message.
    """

    def __init__(
        self,
        *,
        failure_code: str | None,
        failure_message: str | None,
    ) -> None:
        self.failure_code = failure_code
        self.failure_message = failure_message
        super().__init__(failure_message or "Worker runtime is unavailable")


class HarnessCliUnavailableError(RuntimeError):
    """A Task selected a Harness that the frozen Kit inventory does not provide.

    Stable rejection for create/start/retry/resume/recovery choosing an absent
    Harness (§11.3): the attempt fails with ``harness_cli_unavailable`` and the
    sanitized absent reason; there is no image/PATH fallback and no automatic
    migration to another Harness.
    """

    def __init__(
        self,
        *,
        harness_key: str,
        reason_code: str | None,
        kit_version: str | None,
        message: str | None = None,
    ) -> None:
        self.harness_key = harness_key
        self.reason_code = reason_code
        self.kit_version = kit_version
        super().__init__(
            message
            or (
                f"Harness {harness_key!r} is not available in Worker Kit "
                f"{kit_version!r}"
            )
        )


_KIT_ERROR_HINTS = (
    "mount",
    "bind",
    "entrypoint",
    "not a directory",
    "no such file",
)


def is_kit_mount_error(exc: Exception, worker_kit_path: str | None) -> bool:
    """Best-effort classification of a create/start error as a Kit error (§13.4).

    The daemon's ``bind source path does not exist`` message is the strongest
    signal (missing bind source is rejected at create). Otherwise the error must
    mention the Kit path in a mount/bind/entrypoint context to avoid probing on
    unrelated image or network failures.
    """
    if not worker_kit_path:
        return False
    text = str(exc).lower()
    if _MISSING_BIND_SOURCE_HINT in text:
        return True
    if worker_kit_path.lower() not in text:
        return False
    return any(hint in text for hint in _KIT_ERROR_HINTS)


async def recheck_runtime_on_container_error(
    db: AsyncSession,
    *,
    connection: DockerConnectionConfig,
    image: str,
    runtime_mode: str,
    worker_kit_version: str,
    worker_kit_path: str,
    ttl_seconds: int,
    original_error: Exception,
    require_content_inventory: bool = False,
) -> Exception:
    """Re-probe the frozen Kit after a container create/start Kit error (§13.4).

    Runs the same strict probe used by the scheduler gate. When it
    deterministically concludes the Kit is gone (writing ``unavailable``), the
    caller is returned a structured ``WorkerRuntimeUnavailableError`` to replace
    the vague container error. Any other outcome (ready, unknown, transient)
    keeps ``original_error`` so the failure stays classified as a Profile/image
    runtime error.
    """
    try:
        outcome = await run_deterministic_kit_probe(
            db,
            connection=connection,
            image=image,
            runtime_mode=runtime_mode,
            worker_kit_version=worker_kit_version,
            worker_kit_path=worker_kit_path,
            ttl_seconds=ttl_seconds,
            require_content_inventory=require_content_inventory,
        )
    except RuntimeProbeTransientError:
        return original_error
    if outcome.is_unavailable:
        return WorkerRuntimeUnavailableError(
            failure_code=outcome.readiness.failure_code,
            failure_message=outcome.readiness.failure_message,
        )
    return original_error
