from __future__ import annotations

import io
import json
import os
import shutil
import tarfile
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

os.environ.setdefault("CONFIG_ENCRYPTION_KEY", "unit-test-key")

from app.core.worker_runtime_bundle import (  # noqa: E402
    bind_runtime_bundle,
    build_runtime_bundle,
    build_v2_runtime_materialization_archive,
    build_v2_runtime_materialization_manifest_bytes,
    get_or_create_runtime_bundle,
    get_or_create_runtime_bundle_v2,
    load_bound_runtime_bundle,
    verify_bundle_bytes,
)
from app.models import Base, Task, WorkerRuntimeBundle  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest_asyncio.fixture
async def session_factory():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:", poolclass=StaticPool)
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        await engine.dispose()


def test_runtime_bundle_is_byte_deterministic_and_manifested():
    source_manifest = json.loads(
        (REPO_ROOT / "deploy/worker-entrypoint/harness/manifest.json").read_text()
    )
    first = build_runtime_bundle(REPO_ROOT)
    second = build_runtime_bundle(REPO_ROOT)
    assert first.digest == second.digest
    assert first.archive_bytes == second.archive_bytes
    assert first.manifest["event_schema"] == "codify.worker.event/v1"
    assert (
        first.manifest["adapters"]["claude"]["version"]
        == source_manifest["adapters"]["claude"]["adapter"]["version"]
    )
    assert len(first.manifest["adapters"]["claude"]["digest"]) == 64
    assert first.manifest["bundle_digest"] == first.digest
    assert len(first.manifest["archive_manifest_digest"]) == 64

    with tarfile.open(fileobj=io.BytesIO(first.archive_bytes), mode="r:") as archive:
        names = archive.getnames()
    assert "codify-runtime/orchestration/manifest.json" in names
    assert "codify-runtime/orchestration/worker-entrypoint/harness/runner.sh" in names
    assert "codify-runtime/orchestration/worker-entrypoint/harness/adapters/claude.sh" in names


@pytest.mark.asyncio
async def test_bundle_get_or_create_deduplicates_by_digest(session_factory):
    async with session_factory() as db:
        first = await get_or_create_runtime_bundle(db, source_dir=REPO_ROOT)
        second = await get_or_create_runtime_bundle(db, source_dir=REPO_ROOT)
        assert first.id == second.id
        assert first.digest == second.digest
        verify_bundle_bytes(first)


def test_runtime_bundle_verification_rejects_bound_manifest_tampering():
    built = build_runtime_bundle(REPO_ROOT)
    bundle = type(
        "Bundle",
        (),
        {
            "bundle_bytes": built.archive_bytes,
            "digest": built.digest,
            "size_bytes": len(built.archive_bytes),
            "manifest": {**built.manifest, "archive_manifest_digest": "0" * 64},
        },
    )()
    with pytest.raises(RuntimeError, match="archive manifest digest mismatch"):
        verify_bundle_bytes(bundle)


@pytest.mark.asyncio
async def test_retry_reuses_source_bundle_reference(session_factory):
    async with session_factory() as db:
        source = Task(id=1, issue_id=1, project_id=1, user_prompt="source")
        retry = Task(id=2, issue_id=1, project_id=1, user_prompt="retry", is_retry=True)
        db.add_all([source, retry])
        await db.flush()
        source_bundle = await bind_runtime_bundle(db, source, source_dir=REPO_ROOT)
        retry_bundle = await bind_runtime_bundle(db, retry, source_task=source)
        assert retry.runtime_bundle_id == source.runtime_bundle_id
        assert retry_bundle.id == source_bundle.id


@pytest.mark.asyncio
async def test_retry_rejects_historical_source_without_runtime_bundle(session_factory):
    async with session_factory() as db:
        source = Task(id=1, issue_id=1, project_id=1, user_prompt="legacy")
        retry = Task(id=2, issue_id=1, project_id=1, user_prompt="retry", is_retry=True)
        db.add_all([source, retry])
        await db.flush()
        with pytest.raises(RuntimeError, match="retry source has no immutable Runtime Bundle"):
            await bind_runtime_bundle(
                db,
                retry,
                source_task=source,
                source_dir=REPO_ROOT,
            )
        assert source.runtime_bundle_id is None
        assert retry.runtime_bundle_id is None


@pytest.mark.asyncio
async def test_execution_rejects_historical_task_without_runtime_bundle(session_factory):
    async with session_factory() as db:
        task = Task(id=1, issue_id=1, project_id=1, user_prompt="historical")
        db.add(task)
        await db.flush()

        with pytest.raises(RuntimeError, match="historical Tasks are read-only"):
            await load_bound_runtime_bundle(db, task)


def _v2_test_runtime_source(tmp_path: Path) -> Path:
    """Copy controlled source and make the fixture obey current capability bounds."""
    root = tmp_path / "runtime-source"
    shutil.copytree(REPO_ROOT / "deploy", root / "deploy")
    manifest_path = root / "deploy/worker-entrypoint/harness/manifest.json"
    manifest = json.loads(manifest_path.read_text())
    # This test proves immutable bundle mechanics, not OpenCode resume support.
    manifest["adapters"]["opencode"]["capabilities"]["resume"] = False
    for adapter in manifest["adapters"].values():
        adapter["source"]["artifact_sha256"] = "a" * 64
    manifest_path.write_text(json.dumps(manifest))
    return root


def _write_cli_artifact_manifest(path: Path, source_manifest: dict, *, pi_digest: str) -> Path:
    document = {
        "schema": "codify.worker.cli-artifacts/v1",
        "platform": "linux/amd64",
        "artifacts": {
            key: {
                "path": f"/opt/{key}",
                "version": adapter["source"]["artifact_version"],
                "sha256": pi_digest if key == "pi" else "b" * 64,
            }
            for key, adapter in source_manifest["adapters"].items()
        },
    }
    path.write_text(json.dumps(document))
    return path


@pytest.mark.asyncio
async def test_v2_bundle_persists_frozen_payload_and_never_rescans_checkout(
    session_factory, tmp_path
):
    source = _v2_test_runtime_source(tmp_path)
    async with session_factory() as db:
        first = await get_or_create_runtime_bundle_v2(db, source_dir=source)
        assert first.bundle_bytes
        assert first.size_bytes == len(first.bundle_bytes)
        assert first.manifest["archive_sha256"]
        assert first.manifest["files"]
        verify_bundle_bytes(first)

        bound = Task(id=1, issue_id=1, project_id=1, user_prompt="v2")
        db.add(bound)
        await db.flush()
        await bind_runtime_bundle(db, bound, source_dir=source, harness_key="pi")
        frozen_archive = build_v2_runtime_materialization_archive(first, source_dir=source)
        frozen_manifest = build_v2_runtime_materialization_manifest_bytes(first, source_dir=source)

        # A post-bind checkout edit cannot affect the already bound Task.
        pi_adapter = source / "deploy/worker-entrypoint/harness/adapters/pi.sh"
        pi_adapter.write_text(pi_adapter.read_text() + "\n# post-bind mutation\n")
        loaded = await load_bound_runtime_bundle(db, bound)
        assert build_v2_runtime_materialization_archive(loaded, source_dir=source) == frozen_archive
        assert (
            build_v2_runtime_materialization_manifest_bytes(loaded, source_dir=source)
            == frozen_manifest
        )

        # A new binding observes the changed controlled source and gets a new
        # bundle/adapter digest while the old one remains executable.
        second = await get_or_create_runtime_bundle_v2(db, source_dir=source)
        assert second.digest != first.digest
        assert (
            second.manifest["adapters"]["pi"]["adapter"]["digest"]
            != first.manifest["adapters"]["pi"]["adapter"]["digest"]
        )


@pytest.mark.asyncio
async def test_v2_bundle_stamps_release_cli_sha_into_addressed_source(session_factory, tmp_path):
    source = _v2_test_runtime_source(tmp_path)
    manifest_path = source / "deploy/worker-entrypoint/harness/manifest.json"
    template = json.loads(manifest_path.read_text())
    template["adapters"]["pi"]["source"]["artifact_sha256"] = "<computed at freeze>"
    manifest_path.write_text(json.dumps(template))
    first_lock = _write_cli_artifact_manifest(
        tmp_path / "artifacts-first.json", template, pi_digest="1" * 64
    )
    second_lock = _write_cli_artifact_manifest(
        tmp_path / "artifacts-second.json", template, pi_digest="2" * 64
    )

    async with session_factory() as db:
        first = await get_or_create_runtime_bundle_v2(
            db,
            source_dir=source,
            cli_artifact_manifest_path=first_lock,
        )
        second = await get_or_create_runtime_bundle_v2(
            db,
            source_dir=source,
            cli_artifact_manifest_path=second_lock,
        )

    assert first.digest != second.digest
    assert first.manifest["adapters"]["pi"]["source"]["artifact_sha256"] == "1" * 64
    assert second.manifest["adapters"]["pi"]["source"]["artifact_sha256"] == "2" * 64
    assert (
        first.manifest["adapters"]["pi"]["adapter"]["digest"]
        != second.manifest["adapters"]["pi"]["adapter"]["digest"]
    )


@pytest.mark.asyncio
async def test_v2_bundle_rejects_unstamped_cli_artifact_identity(session_factory, tmp_path):
    source = _v2_test_runtime_source(tmp_path)
    manifest_path = source / "deploy/worker-entrypoint/harness/manifest.json"
    template = json.loads(manifest_path.read_text())
    template["adapters"]["pi"]["source"]["artifact_sha256"] = "<computed at freeze>"
    manifest_path.write_text(json.dumps(template))

    async with session_factory() as db:
        with pytest.raises(RuntimeError, match="no frozen artifact SHA-256"):
            await get_or_create_runtime_bundle_v2(db, source_dir=source)


@pytest.mark.asyncio
async def test_v2_empty_legacy_payload_fails_closed(session_factory):
    async with session_factory() as db:
        bundle = WorkerRuntimeBundle(
            digest="a" * 64,
            bundle_bytes=b"",
            contract_version="codify.worker.harness/v2",
            orchestration_version="1.0.0",
            manifest={"bundle_digest": "a" * 64, "files": []},
            size_bytes=0,
        )
        task = Task(id=1, issue_id=1, project_id=1, user_prompt="legacy v2")
        db.add_all([bundle, task])
        await db.flush()
        task.runtime_bundle_id = bundle.id
        await db.flush()
        with pytest.raises(RuntimeError, match="no persisted payload"):
            await load_bound_runtime_bundle(db, task)


def test_source_manifest_capabilities_pass_registry_upper_bound():
    """The frozen source manifest must never declare a capability above the
    system upper bound; the bundle build calls the same validation."""
    from app.core.harness_registry import validate_adapter_capabilities

    manifest = json.loads(
        (REPO_ROOT / "deploy/worker-entrypoint/harness/manifest.json").read_text()
    )
    for key, adapter in manifest["adapters"].items():
        validate_adapter_capabilities(key, adapter.get("capabilities") or {})
