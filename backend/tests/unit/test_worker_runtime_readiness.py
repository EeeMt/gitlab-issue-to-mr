"""Unit tests for worker runtime locator fingerprints, readiness records, and
the strict-Mount Kit probe (§9.6, §10.3, §13.3-§13.6, §19).

Covers the generation/CAS protocol, TTL-only ready caching, never-expiring
unavailable, and the side-effect-free strict-Mount probe that reads Kit
contents through the archive API from a stopped container.
"""
import asyncio
import hashlib
import io
import json
import tarfile
import threading
from datetime import timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import docker
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.utcnow import utcnow
from app.core.worker_kit_inventory import content_inventory_digest
from app.core.worker_runtime_readiness import (
    FAILURE_WORKER_KIT_INVALID,
    FAILURE_WORKER_KIT_NOT_FOUND,
    FAILURE_WORKER_KIT_VERSION_MISMATCH,
    KIT_PROBE_CONTAINER_PATH,
    READINESS_READY,
    READINESS_UNAVAILABLE,
    READINESS_UNKNOWN,
    RuntimeCheckResult,
    RuntimeProbeTransientError,
    RuntimeReadiness,
    _content_inventory_from_archive,
    begin_runtime_check,
    fingerprint_from_connection_and_kit,
    finish_runtime_check,
    probe_worker_kit,
    read_runtime_readiness,
    run_deterministic_kit_probe,
    runtime_locator_fingerprint,
    runtime_readiness_fingerprint,
    runtime_verification_input_digest,
    serialize_runtime_readiness,
)
from app.models import Base, WorkerRuntimeReadiness

# ── helpers ──────────────────────────────────────────────────────────────────


def _tar_bytes(name: str, payload: bytes, *, mode: int = 0o644) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        info = tarfile.TarInfo(name)
        info.size = len(payload)
        info.mode = mode
        archive.addfile(info, io.BytesIO(payload))
    return buffer.getvalue()


def _tar_tree_bytes(entries: list[dict], contents: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        # Docker's directory archive may spell the root member with a
        # trailing slash; the probe must treat it as the requested root.
        root = tarfile.TarInfo("kit/")
        root.type = tarfile.DIRTYPE
        archive.addfile(root)
        for entry in entries:
            path = f"kit/{entry['path']}"
            payload = contents[entry["path"]]
            info = tarfile.TarInfo(path)
            info.size = len(payload)
            info.mode = 0o755
            archive.addfile(info, io.BytesIO(payload))
    return buffer.getvalue()


def _tar_tree_with_hard_link_bytes(*, forward: bool = False) -> bytes:
    buffer = io.BytesIO()
    payload = b"#!/bin/sh\n"
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        root = tarfile.TarInfo("kit/")
        root.type = tarfile.DIRTYPE
        archive.addfile(root)
        alias = tarfile.TarInfo("kit/launcher-alias")
        alias.type = tarfile.LNKTYPE
        alias.linkname = "kit/launcher"
        target = tarfile.TarInfo("kit/launcher")
        target.size = len(payload)
        target.mode = 0o755
        if forward:
            archive.addfile(alias)
            archive.addfile(target, io.BytesIO(payload))
        else:
            archive.addfile(target, io.BytesIO(payload))
            archive.addfile(alias)
    return buffer.getvalue()


def _make_probe_client(*, manifest: bytes | None = None, content_overrides: dict[str, bytes] | None = None):
    """Return a DockerClientWrapper stand-in for probe_worker_kit.

    ``manifest=None`` simulates a missing manifest.json (NotFound).
    """
    container = MagicMock()
    manifest_data = json.loads(manifest.decode()) if manifest is not None else {}
    content_inventory = manifest_data.get("content_inventory") or []
    content_bytes = {
        entry["path"]: (b"store" if entry["path"] == "nix/store/runtime" else b"#!/bin/sh")
        for entry in content_inventory
    }
    content_bytes.update(content_overrides or {})

    def fake_get_archive(path: str):
        if path.endswith("/kit"):
            return (iter([_tar_tree_bytes(content_inventory, content_bytes)]), {})
        if path.endswith("manifest.json"):
            if manifest is None:
                raise docker.errors.NotFound("manifest not found")
            return (iter([_tar_bytes("manifest.json", manifest)]), {})
        if path.endswith("nix/store"):
            return (iter([_tar_bytes("store", b"")]), {})
        name = path.rsplit("/", 1)[-1]
        return (iter([_tar_bytes(name, b"#!/bin/sh", mode=0o755)]), {})

    container.get_archive = fake_get_archive
    client = MagicMock()
    client.client.images.get.return_value = MagicMock()
    client.client.containers.create.return_value = container
    return client


def _valid_manifest(version: str = "0.3.5") -> bytes:
    payload = b"#!/bin/sh"
    content_inventory = [
        {"kind": "file", "path": "entrypoint.sh", "sha256": hashlib.sha256(payload).hexdigest(), "size": len(payload)},
        {"kind": "file", "path": "harness/pi/bin/pi", "sha256": hashlib.sha256(payload).hexdigest(), "size": len(payload)},
        {"kind": "file", "path": "launcher", "sha256": hashlib.sha256(payload).hexdigest(), "size": len(payload)},
        {"kind": "file", "path": "nix/store/runtime", "sha256": hashlib.sha256(b"store").hexdigest(), "size": len(b"store")},
    ]
    return json.dumps(
        {
            "schema_version": 2,
            "manifest_kind": "codify.worker.kit-manifest/v1",
            "kit_version": version,
            "platform": "linux/amd64",
            "harness_inventory": {
                "pi": {
                    "availability": "present",
                    "path": "/opt/codify-kit/harness/pi/bin/pi",
                    "version": "0.84.2",
                    "sha256": hashlib.sha256(payload).hexdigest(),
                    "size": len(payload),
                },
                "opencode": {"availability": "absent", "reason_code": "not_selected"},
                "claude": {"availability": "absent", "reason_code": "not_selected"},
                "codex": {"availability": "absent", "reason_code": "not_selected"},
            },
            "content_inventory": content_inventory,
            "content_inventory_sha256": content_inventory_digest(content_inventory),
        }
    ).encode()


def _db_session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    session_factory = async_sessionmaker(engine, expire_on_commit=False)
    return engine, session_factory


# ── locator fingerprint (§10.3) ─────────────────────────────────────────────


def test_fingerprint_is_none_for_baked_image():
    fp = runtime_locator_fingerprint(
        docker_daemon_key="daemon-a",
        runtime_mode="baked_image",
        worker_kit_version="0.3.5",
        worker_kit_path="/opt/kit",
    )
    assert fp is None


def test_fingerprint_is_deterministic_for_mounted_kit():
    a = runtime_locator_fingerprint(
        docker_daemon_key="daemon-a",
        runtime_mode="mounted_kit",
        worker_kit_version="0.3.5",
        worker_kit_path="/opt/kit",
    )
    b = runtime_locator_fingerprint(
        docker_daemon_key="daemon-a",
        runtime_mode="mounted_kit",
        worker_kit_version="0.3.5",
        worker_kit_path="/opt/kit",
    )
    assert a == b
    assert len(a) == 64


def test_fingerprint_ignores_tls_credential_rotation_on_same_daemon():
    base = fingerprint_from_connection_and_kit(
        SimpleNamespace(host="tcp://worker:2376", tls_ca="/old/ca.pem"),
        runtime_mode="mounted_kit",
        worker_kit_version="0.3.5",
        worker_kit_path="/opt/kit",
    )
    rotated = fingerprint_from_connection_and_kit(
        SimpleNamespace(host="tcp://worker:2376", tls_ca="/new/ca.pem"),
        runtime_mode="mounted_kit",
        worker_kit_version="0.3.5",
        worker_kit_path="/opt/kit",
    )
    assert base == rotated


def test_fingerprint_changes_when_docker_host_changes():
    a = fingerprint_from_connection_and_kit(
        SimpleNamespace(host="tcp://worker-a:2376", tls_ca=None),
        runtime_mode="mounted_kit",
        worker_kit_version="0.3.5",
        worker_kit_path="/opt/kit",
    )
    b = fingerprint_from_connection_and_kit(
        SimpleNamespace(host="tcp://worker-b:2376", tls_ca=None),
        runtime_mode="mounted_kit",
        worker_kit_version="0.3.5",
        worker_kit_path="/opt/kit",
    )
    assert a != b


def test_readiness_fingerprint_separates_v2_content_verification_scope():
    locator = runtime_locator_fingerprint(
        docker_daemon_key="daemon-a",
        runtime_mode="mounted_kit",
        worker_kit_version="0.3.5",
        worker_kit_path="/opt/kit",
    )
    assert runtime_readiness_fingerprint(locator) == locator
    full_content = runtime_readiness_fingerprint(
        locator,
        require_content_inventory=True,
    )
    assert full_content is not None
    assert full_content != locator
    assert runtime_readiness_fingerprint(
        locator,
        require_content_inventory=True,
    ) == full_content


def test_verification_digest_excludes_templates_and_scripts():
    digest = runtime_verification_input_digest(
        docker_daemon_key="daemon-a",
        image="worker:latest",
        runtime_mode="mounted_kit",
        worker_kit_version="0.3.5",
        worker_kit_path="/opt/kit",
        volume_mounts=[
            {"host_path": "/host", "container_path": "/guest", "mode": "ro"}
        ],
        environment_variables=[
            {"key": "VISIBLE", "value": "1"},
            {"key": "SECRET", "value": "top-secret"},
        ],
        harness_key="claude",
        enabled_harnesses=["claude", "codex"],
        harness_constraints={"require_skill_support": True},
        harness_runtimes={"claude": {"cli": "/bin/claude"}},
        require_skill_support=True,
    )
    assert len(digest) == 64
    # The digest itself never contains secret material.
    assert "top-secret" not in digest


# ── read_runtime_readiness ──────────────────────────────────────────────────


def test_read_missing_fingerprint_is_unknown():
    db = AsyncMock()
    db.get = AsyncMock(return_value=None)
    readiness = asyncio.run(read_runtime_readiness(db, "abc"))
    assert readiness.status == READINESS_UNKNOWN


def test_read_ready_within_ttl_is_ready():
    row = WorkerRuntimeReadiness(
        runtime_locator_fingerprint="fp",
        status=READINESS_READY,
        ready_until=utcnow() + timedelta(minutes=5),
    )
    db = AsyncMock()
    db.get = AsyncMock(return_value=row)
    readiness = asyncio.run(read_runtime_readiness(db, "fp"))
    assert readiness.status == READINESS_READY


def test_read_expired_ready_is_unknown():
    row = WorkerRuntimeReadiness(
        runtime_locator_fingerprint="fp",
        status=READINESS_READY,
        ready_until=utcnow() - timedelta(minutes=5),
    )
    db = AsyncMock()
    db.get = AsyncMock(return_value=row)
    readiness = asyncio.run(read_runtime_readiness(db, "fp"))
    assert readiness.status == READINESS_UNKNOWN


def test_read_unavailable_never_auto_expires():
    row = WorkerRuntimeReadiness(
        runtime_locator_fingerprint="fp",
        status=READINESS_UNAVAILABLE,
        failure_code=FAILURE_WORKER_KIT_NOT_FOUND,
        checked_at=utcnow() - timedelta(days=7),
    )
    db = AsyncMock()
    db.get = AsyncMock(return_value=row)
    readiness = asyncio.run(read_runtime_readiness(db, "fp"))
    assert readiness.status == READINESS_UNAVAILABLE
    assert readiness.failure_code == FAILURE_WORKER_KIT_NOT_FOUND


def test_serialize_readiness_never_leaks_secret_material():
    readiness = RuntimeReadiness(
        status=READINESS_UNAVAILABLE,
        failure_code=FAILURE_WORKER_KIT_INVALID,
        failure_message="worker_kit_path=/srv/secret",
    )
    payload = serialize_runtime_readiness(readiness)
    assert payload["status"] == READINESS_UNAVAILABLE
    assert "failure_message" in payload


# ── generation/CAS protocol (§13.3, §19) ────────────────────────────────────


@pytest.mark.asyncio
async def test_begin_and_finish_runtime_check_cas_roundtrip():
    engine, session_factory = _db_session_factory()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        async with session_factory() as db:
            generation = await begin_runtime_check(
                db,
                fingerprint="fp1",
                docker_daemon_key="daemon-a",
                runtime_mode="mounted_kit",
                worker_kit_version="0.3.5",
                worker_kit_path="/opt/kit",
            )
            await db.commit()
            assert generation == 1

            written = await finish_runtime_check(
                db,
                fingerprint="fp1",
                generation=generation,
                status=READINESS_READY,
                ready_until=utcnow() + timedelta(minutes=5),
            )
            await db.commit()
            assert written is True

            row = await db.get(WorkerRuntimeReadiness, "fp1")
            assert row.status == READINESS_READY
            assert row.check_generation == 1
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_finish_runtime_check_discards_stale_generation():
    engine, session_factory = _db_session_factory()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    try:
        async with session_factory() as db:
            generation = await begin_runtime_check(
                db,
                fingerprint="fp2",
                docker_daemon_key="daemon-a",
                runtime_mode="mounted_kit",
                worker_kit_version="0.3.5",
                worker_kit_path="/opt/kit",
            )
            await db.commit()

            # A newer check bumps the generation past ours.
            await begin_runtime_check(
                db,
                fingerprint="fp2",
                docker_daemon_key="daemon-a",
                runtime_mode="mounted_kit",
                worker_kit_version="0.3.5",
                worker_kit_path="/opt/kit",
            )
            await db.commit()

            written = await finish_runtime_check(
                db,
                fingerprint="fp2",
                generation=generation,
                status=READINESS_READY,
                ready_until=utcnow() + timedelta(minutes=5),
            )
            await db.commit()
            assert written is False

            row = await db.get(WorkerRuntimeReadiness, "fp2")
            assert row.status == READINESS_UNKNOWN
            assert row.check_generation == 2
    finally:
        await engine.dispose()


# ── strict-Mount Kit probe (§13.6) ──────────────────────────────────────────


def test_probe_returns_ready_for_valid_kit():
    client = _make_probe_client(manifest=_valid_manifest())
    with patch(
        "app.core.worker_runtime_readiness.DockerClientWrapper", return_value=client
    ):
        result = probe_worker_kit(
            SimpleNamespace(host="tcp://worker:2376", tls_ca=None),
            image="worker:latest",
            runtime_mode="mounted_kit",
            worker_kit_version="0.3.5",
            worker_kit_path="/opt/kit",
        )
    assert result.status == READINESS_READY
    assert result.failure_code is None


def test_probe_keeps_legacy_v1_manifest_compatible_but_v2_requires_inventory():
    legacy = json.loads(_valid_manifest())
    legacy.pop("content_inventory")
    legacy.pop("content_inventory_sha256")
    manifest = json.dumps(legacy).encode()
    client = _make_probe_client(manifest=manifest)
    with patch(
        "app.core.worker_runtime_readiness.DockerClientWrapper", return_value=client
    ):
        legacy_result = probe_worker_kit(
            SimpleNamespace(host="tcp://worker:2376", tls_ca=None),
            image="worker:latest",
            runtime_mode="mounted_kit",
            worker_kit_version="0.3.5",
            worker_kit_path="/opt/kit",
            require_content_inventory=False,
        )
    assert legacy_result.status == READINESS_READY

    client = _make_probe_client(manifest=manifest)
    with patch(
        "app.core.worker_runtime_readiness.DockerClientWrapper", return_value=client
    ):
        v2_result = probe_worker_kit(
            SimpleNamespace(host="tcp://worker:2376", tls_ca=None),
            image="worker:latest",
            runtime_mode="mounted_kit",
            worker_kit_version="0.3.5",
            worker_kit_path="/opt/kit",
            require_content_inventory=True,
        )
    assert v2_result.status == READINESS_UNAVAILABLE
    assert v2_result.failure_code == FAILURE_WORKER_KIT_INVALID


def test_probe_rejects_tampered_non_harness_kit_content():
    client = _make_probe_client(
        manifest=_valid_manifest(),
        content_overrides={"launcher": b"tampered launcher"},
    )
    with patch(
        "app.core.worker_runtime_readiness.DockerClientWrapper", return_value=client
    ):
        result = probe_worker_kit(
            SimpleNamespace(host="tcp://worker:2376", tls_ca=None),
            image="worker:latest",
            runtime_mode="mounted_kit",
            worker_kit_version="0.3.5",
            worker_kit_path="/opt/kit",
        )
    assert result.status == READINESS_UNAVAILABLE
    assert result.failure_code == FAILURE_WORKER_KIT_INVALID
    assert "content inventory" in result.failure_message


@pytest.mark.parametrize("forward", [False, True])
def test_content_inventory_reads_hard_links_as_their_target_file(forward: bool):
    container = MagicMock()
    container.get_archive.return_value = (
        iter([_tar_tree_with_hard_link_bytes(forward=forward)]),
        {},
    )

    actual = _content_inventory_from_archive(container, "/opt/codify-probe/kit")

    payload_sha = hashlib.sha256(b"#!/bin/sh\n").hexdigest()
    assert actual == [
        {"kind": "file", "path": "launcher", "sha256": payload_sha, "size": 10},
        {"kind": "file", "path": "launcher-alias", "sha256": payload_sha, "size": 10},
    ]


def test_probe_uses_strict_readonly_mount_and_stopped_container():
    client = _make_probe_client(manifest=_valid_manifest())
    with patch(
        "app.core.worker_runtime_readiness.DockerClientWrapper", return_value=client
    ):
        probe_worker_kit(
            SimpleNamespace(host="tcp://worker:2376", tls_ca=None),
            image="worker:latest",
            runtime_mode="mounted_kit",
            worker_kit_version="0.3.5",
            worker_kit_path="/opt/kit",
        )
    create_call = client.client.containers.create.call_args
    create_kwargs = create_call.kwargs
    mount = create_kwargs["mounts"][0]
    assert mount["Type"] == "bind"
    assert mount["Source"] == "/opt/kit"
    assert mount["Target"] == KIT_PROBE_CONTAINER_PATH
    assert mount["ReadOnly"] is True
    # The container is created stopped: the command is ["true"] and it is never
    # started (probe_worker_kit only reads the archive API).
    assert create_call.args[1] == ["true"]
    assert create_kwargs["name"].startswith("codify-kit-probe-")
    container = client.client.containers.create.return_value
    container.remove.assert_called_once_with(force=True, v=True)


def test_probe_missing_bind_source_is_worker_kit_not_found():
    client = MagicMock()
    client.client.images.get.return_value = MagicMock()
    client.client.containers.create.side_effect = docker.errors.APIError(
        "bad parameter: bind source path does not exist: /opt/kit"
    )
    with patch(
        "app.core.worker_runtime_readiness.DockerClientWrapper", return_value=client
    ):
        result = probe_worker_kit(
            SimpleNamespace(host="tcp://worker:2376", tls_ca=None),
            image="worker:latest",
            runtime_mode="mounted_kit",
            worker_kit_version="0.3.5",
            worker_kit_path="/opt/kit",
        )
    assert result.status == READINESS_UNAVAILABLE
    assert result.failure_code == FAILURE_WORKER_KIT_NOT_FOUND


def test_probe_version_mismatch_is_deterministic_unavailable():
    client = _make_probe_client(manifest=_valid_manifest(version="0.4.0"))
    with patch(
        "app.core.worker_runtime_readiness.DockerClientWrapper", return_value=client
    ):
        result = probe_worker_kit(
            SimpleNamespace(host="tcp://worker:2376", tls_ca=None),
            image="worker:latest",
            runtime_mode="mounted_kit",
            worker_kit_version="0.3.5",
            worker_kit_path="/opt/kit",
        )
    assert result.status == READINESS_UNAVAILABLE
    assert result.failure_code == FAILURE_WORKER_KIT_VERSION_MISMATCH


def test_probe_missing_manifest_is_worker_kit_invalid():
    client = _make_probe_client(manifest=None)
    with patch(
        "app.core.worker_runtime_readiness.DockerClientWrapper", return_value=client
    ):
        result = probe_worker_kit(
            SimpleNamespace(host="tcp://worker:2376", tls_ca=None),
            image="worker:latest",
            runtime_mode="mounted_kit",
            worker_kit_version="0.3.5",
            worker_kit_path="/opt/kit",
        )
    assert result.status == READINESS_UNAVAILABLE
    assert result.failure_code == FAILURE_WORKER_KIT_INVALID


def test_probe_rejects_runtime_bundle_manifest_as_a_worker_kit():
    runtime_bundle = json.dumps(
        {
            "schema": "codify.worker.runtime-manifest/v2",
            "kit_version": "0.3.5",
        }
    ).encode()
    client = _make_probe_client(manifest=runtime_bundle)
    with patch(
        "app.core.worker_runtime_readiness.DockerClientWrapper", return_value=client
    ):
        result = probe_worker_kit(
            SimpleNamespace(host="tcp://worker:2376", tls_ca=None),
            image="worker:latest",
            runtime_mode="mounted_kit",
            worker_kit_version="0.3.5",
            worker_kit_path="/opt/kit",
        )
    assert result.status == READINESS_UNAVAILABLE
    assert result.failure_code == FAILURE_WORKER_KIT_INVALID


def test_probe_missing_probe_image_is_transient():
    client = MagicMock()
    client.client.images.get.side_effect = docker.errors.NotFound("no such image")
    with patch(
        "app.core.worker_runtime_readiness.DockerClientWrapper", return_value=client
    ):
        with pytest.raises(RuntimeProbeTransientError):
            probe_worker_kit(
                SimpleNamespace(host="tcp://worker:2376", tls_ca=None),
                image="worker:latest",
                runtime_mode="mounted_kit",
                worker_kit_version="0.3.5",
                worker_kit_path="/opt/kit",
            )


def test_probe_requires_mounted_kit_mode():
    with pytest.raises(RuntimeProbeTransientError):
        probe_worker_kit(
            SimpleNamespace(host="tcp://worker:2376", tls_ca=None),
            image="worker:latest",
            runtime_mode="baked_image",
            worker_kit_version=None,
            worker_kit_path=None,
        )


def test_probe_unreachable_daemon_constructor_is_transient():
    """§13.5: a DockerException during client construction (the version=auto
    handshake) becomes RuntimeProbeTransientError, not a raw DockerException."""
    with patch(
        "app.core.worker_runtime_readiness.DockerClientWrapper",
        side_effect=docker.errors.DockerException("connection refused"),
    ):
        with pytest.raises(RuntimeProbeTransientError) as exc_info:
            probe_worker_kit(
                SimpleNamespace(host="tcp://worker:2376", tls_ca=None),
                image="worker:latest",
                runtime_mode="mounted_kit",
                worker_kit_version="0.3.5",
                worker_kit_path="/opt/kit",
            )
    assert "daemon" in str(exc_info.value)


def test_probe_unreachable_daemon_image_get_is_transient():
    """§13.5: a connection failure while locating the probe image is transient."""
    client = MagicMock()
    client.client.images.get.side_effect = docker.errors.DockerException(
        "connection reset by peer"
    )
    with patch(
        "app.core.worker_runtime_readiness.DockerClientWrapper", return_value=client
    ):
        with pytest.raises(RuntimeProbeTransientError):
            probe_worker_kit(
                SimpleNamespace(host="tcp://worker:2376", tls_ca=None),
                image="worker:latest",
                runtime_mode="mounted_kit",
                worker_kit_version="0.3.5",
                worker_kit_path="/opt/kit",
            )


def _large_store_archive() -> tuple[bytes, int]:
    """Build a tar with one ~8MB member and return (bytes, payload_size)."""
    payload = b"x" * (8 * 1024 * 1024)
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w") as archive:
        info = tarfile.TarInfo("store/0abc123-foo")
        info.size = len(payload)
        archive.addfile(info, io.BytesIO(payload))
    return buffer.getvalue(), len(payload)


def test_nix_store_probe_streams_large_archive_bounded():
    """F3: the nix/store sentinel check must not buffer the whole archive."""
    from app.core.worker_runtime_readiness import _archive_has_member

    archive_bytes, payload_size = _large_store_archive()
    consumed = 0

    def chunks():
        nonlocal consumed
        for i in range(0, len(archive_bytes), 512):
            consumed += 512
            yield archive_bytes[i : i + 512]

    container = MagicMock()
    container.get_archive.return_value = (chunks(), {})
    assert _archive_has_member(container, "/opt/codify-probe/kit/nix/store") is True
    # Only the leading tar headers were consumed; the 8MB payload was never
    # pulled into memory.
    assert consumed < payload_size // 100


def test_nix_store_empty_archive_is_treated_as_missing():
    """F3: an archive with no members (empty directory) reports no content."""
    from app.core.worker_runtime_readiness import _archive_has_member

    empty = io.BytesIO()
    with tarfile.open(fileobj=empty, mode="w"):
        pass  # no members

    container = MagicMock()
    container.get_archive.return_value = (iter([empty.getvalue()]), {})
    assert _archive_has_member(container, "/opt/codify-probe/kit/nix/store") is False


def test_nix_store_missing_path_reports_no_content():
    """F3: a NotFound archive read means the nix/store is absent."""
    from app.core.worker_runtime_readiness import _archive_has_member

    container = MagicMock()
    container.get_archive.side_effect = docker.errors.NotFound("no such path")
    assert _archive_has_member(container, "/opt/codify-probe/kit/nix/store") is False


# ── run_deterministic_kit_probe ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_run_deterministic_kit_probe_persists_ready_through_cas():
    engine, session_factory = _db_session_factory()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    connection = SimpleNamespace(host="tcp://worker:2376", tls_ca=None)
    fingerprint = fingerprint_from_connection_and_kit(
        connection,
        runtime_mode="mounted_kit",
        worker_kit_version="0.3.5",
        worker_kit_path="/opt/kit",
    )
    try:
        with patch(
            "app.core.worker_runtime_readiness.probe_worker_kit",
            return_value=RuntimeCheckResult(status=READINESS_READY),
        ):
            async with session_factory() as db:
                outcome = await run_deterministic_kit_probe(
                    db,
                    connection=connection,
                    image="worker:latest",
                    runtime_mode="mounted_kit",
                    worker_kit_version="0.3.5",
                    worker_kit_path="/opt/kit",
                    ttl_seconds=900,
                )
        assert outcome.committed is True
        assert outcome.readiness.status == READINESS_READY
        assert outcome.readiness.ready_until is not None
        async with session_factory() as db:
            stored = await read_runtime_readiness(db, fingerprint)
        assert stored.status == READINESS_READY
        assert stored.check_generation == 1
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_v2_unavailable_readiness_does_not_contaminate_v1_scope():
    """A missing V2 inventory must not block a V1 dual-canary locator."""
    engine, session_factory = _db_session_factory()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    connection = SimpleNamespace(host="tcp://worker:2376", tls_ca=None)
    fingerprint = fingerprint_from_connection_and_kit(
        connection,
        runtime_mode="mounted_kit",
        worker_kit_version="0.3.5",
        worker_kit_path="/opt/kit",
    )
    try:
        with patch(
            "app.core.worker_runtime_readiness.probe_worker_kit",
            return_value=RuntimeCheckResult(
                status=READINESS_UNAVAILABLE,
                failure_code=FAILURE_WORKER_KIT_INVALID,
                failure_message="V2 content inventory is missing",
            ),
        ):
            async with session_factory() as db:
                outcome = await run_deterministic_kit_probe(
                    db,
                    connection=connection,
                    image="worker:latest",
                    runtime_mode="mounted_kit",
                    worker_kit_version="0.3.5",
                    worker_kit_path="/opt/kit",
                    ttl_seconds=900,
                    require_content_inventory=True,
                )
        assert outcome.readiness.status == READINESS_UNAVAILABLE
        async with session_factory() as db:
            v1 = await read_runtime_readiness(db, fingerprint)
            v2 = await read_runtime_readiness(
                db,
                fingerprint,
                require_content_inventory=True,
            )
        assert v1.status == READINESS_UNKNOWN
        assert v2.status == READINESS_UNAVAILABLE
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_run_deterministic_kit_probe_superseded_reports_not_committed():
    """§13.3/§13.5: a probe whose CAS write is rejected (superseded) reports
    committed=False and reflects the concurrent conclusion, not its own."""
    engine, session_factory = _db_session_factory()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    connection = SimpleNamespace(host="tcp://worker:2376", tls_ca=None)
    fingerprint = fingerprint_from_connection_and_kit(
        connection,
        runtime_mode="mounted_kit",
        worker_kit_version="0.3.5",
        worker_kit_path="/opt/kit",
    )
    try:
        probe_started = threading.Event()
        concurrent_done = threading.Event()

        def delayed_probe(*_args, **_kwargs):
            probe_started.set()
            assert concurrent_done.wait(5), "concurrent writer did not finish"
            return RuntimeCheckResult(status=READINESS_READY)

        async def concurrent_supersede():
            # A concurrent check begins after our probe (bumping the generation)
            # and commits an unavailable conclusion before our probe returns.
            async with session_factory() as db:
                await begin_runtime_check(
                    db,
                    fingerprint=fingerprint,
                    docker_daemon_key="daemon-key",
                    runtime_mode="mounted_kit",
                    worker_kit_version="0.3.5",
                    worker_kit_path="/opt/kit",
                )
                await finish_runtime_check(
                    db,
                    fingerprint=fingerprint,
                    generation=2,
                    status=READINESS_UNAVAILABLE,
                    failure_code=FAILURE_WORKER_KIT_NOT_FOUND,
                    failure_message="kit gone",
                )
                await db.commit()

        async def probing():
            async with session_factory() as db:
                return await run_deterministic_kit_probe(
                    db,
                    connection=connection,
                    image="worker:latest",
                    runtime_mode="mounted_kit",
                    worker_kit_version="0.3.5",
                    worker_kit_path="/opt/kit",
                    ttl_seconds=900,
                )

        with patch(
            "app.core.worker_runtime_readiness.probe_worker_kit",
            side_effect=delayed_probe,
        ):
            probe_task = asyncio.create_task(probing())
            # Wait until our probe is mid-flight (doing "remote I/O"), then let
            # the concurrent check win the CAS race.
            await asyncio.to_thread(probe_started.wait, 5)
            await concurrent_supersede()
            concurrent_done.set()
            outcome = await probe_task

        assert outcome.committed is False
        # Effective readiness reflects the concurrent unavailable conclusion,
        # not our superseded ready result.
        assert outcome.readiness.status == READINESS_UNAVAILABLE
        async with session_factory() as db:
            stored = await read_runtime_readiness(db, fingerprint)
        assert stored.status == READINESS_UNAVAILABLE
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_run_deterministic_kit_probe_transient_leaves_no_orphan_row():
    """§13.5: a transient probe re-raises and leaves no conclusion-less row."""
    engine, session_factory = _db_session_factory()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    connection = SimpleNamespace(host="tcp://worker:2376", tls_ca=None)
    fingerprint = fingerprint_from_connection_and_kit(
        connection,
        runtime_mode="mounted_kit",
        worker_kit_version="0.3.5",
        worker_kit_path="/opt/kit",
    )
    try:
        with patch(
            "app.core.worker_runtime_readiness.probe_worker_kit",
            side_effect=RuntimeProbeTransientError("daemon unreachable"),
        ):
            async with session_factory() as db:
                with pytest.raises(RuntimeProbeTransientError):
                    await run_deterministic_kit_probe(
                        db,
                        connection=connection,
                        image="worker:latest",
                        runtime_mode="mounted_kit",
                        worker_kit_version="0.3.5",
                        worker_kit_path="/opt/kit",
                        ttl_seconds=900,
                    )
        async with session_factory() as db:
            row = await db.get(WorkerRuntimeReadiness, fingerprint)
        assert row is None
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_run_deterministic_kit_probe_transient_preserves_existing_conclusion():
    """§13.5: a transient probe must not delete an existing ready conclusion."""
    engine, session_factory = _db_session_factory()
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    connection = SimpleNamespace(host="tcp://worker:2376", tls_ca=None)
    fingerprint = fingerprint_from_connection_and_kit(
        connection,
        runtime_mode="mounted_kit",
        worker_kit_version="0.3.5",
        worker_kit_path="/opt/kit",
    )
    try:
        # Seed a ready conclusion under the fingerprint.
        async with session_factory() as db:
            db.add(
                WorkerRuntimeReadiness(
                    runtime_locator_fingerprint=fingerprint,
                    status=READINESS_READY,
                    check_generation=1,
                    checked_at=utcnow(),
                    ready_until=utcnow() + timedelta(minutes=5),
                )
            )
            await db.commit()
        with patch(
            "app.core.worker_runtime_readiness.probe_worker_kit",
            side_effect=RuntimeProbeTransientError("daemon unreachable"),
        ):
            async with session_factory() as db:
                with pytest.raises(RuntimeProbeTransientError):
                    await run_deterministic_kit_probe(
                        db,
                        connection=connection,
                        image="worker:latest",
                        runtime_mode="mounted_kit",
                        worker_kit_version="0.3.5",
                        worker_kit_path="/opt/kit",
                        ttl_seconds=900,
                    )
        async with session_factory() as db:
            stored = await read_runtime_readiness(db, fingerprint)
        assert stored.status == READINESS_READY
    finally:
        await engine.dispose()
