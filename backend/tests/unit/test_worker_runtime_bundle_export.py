from __future__ import annotations

import json
import os
import shutil
from copy import deepcopy
from pathlib import Path

import pytest
import pytest_asyncio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.orm import selectinload
from sqlalchemy.pool import StaticPool

os.environ.setdefault("CONFIG_ENCRYPTION_KEY", "unit-test-key")

from app.core.harness_protocol import HARNESS_CONTRACT_VERSION_V2  # noqa: E402
from app.core.worker_runtime_bundle import (  # noqa: E402
    frozen_v2_adapter_identity,
    get_or_create_runtime_bundle_v2,
)
from app.core.worker_runtime_bundle_export import (  # noqa: E402
    RuntimeBundleExportError,
    _reject_archive_secrets,
    _reject_secret_keys,
    export_runtime_bundle,
    load_exportable_runtime_bundle,
)
from app.models import Base, Task, TaskWorkerProfileSnapshot  # noqa: E402

ROOT = Path(__file__).resolve().parents[3]


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


def _source(tmp_path: Path) -> Path:
    target = tmp_path / "source"
    shutil.copytree(ROOT / "deploy", target / "deploy")
    manifest_path = target / "deploy/worker-entrypoint/harness/manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["adapters"]["opencode"]["capabilities"]["resume"] = False
    manifest_path.write_text(json.dumps(manifest))
    return target


def _worker_image_identity() -> dict[str, str]:
    return {
        "schema": "codify.worker-image-identity/v1", "daemon_key": "daemon",
        "image_reference": "registry.example/worker@sha256:" + "b" * 64,
        "image_id": "sha256:" + "c" * 64, "runtime_platform": "linux/amd64",
    }


def _kit_identity() -> dict[str, str]:
    return {
        "schema": "codify.worker.kit-identity/v1", "kit_version": "0.4.0",
        "platform": "linux/amd64", "manifest_sha256": "a" * 64,
    }


async def _bound(session_factory, tmp_path: Path, key: str = "pi"):
    source = _source(tmp_path)
    identity = _worker_image_identity()
    kit_identity = _kit_identity()
    evidence = {
        "schema": "codify.worker-harness-verification/v1", "harness_key": key,
        "contract_version": HARNESS_CONTRACT_VERSION_V2,
        "adapter": frozen_v2_adapter_identity(
            key, source_dir=source, worker_image_identity=identity, worker_kit_identity=kit_identity
        ),
        "verification_input_digest": "d" * 64, "image_identity": identity, "generation": 1,
        "verified_at": "2026-08-24T00:00:00+00:00",
    }
    async with session_factory() as db:
        bundle = await get_or_create_runtime_bundle_v2(
            db, source_dir=source, worker_image_identity=identity,
            worker_kit_identity=kit_identity, harness_verification_evidence=evidence
        )
        task = Task(id=1, issue_id=1, project_id=1, user_prompt="export")
        db.add(task)
        await db.flush()
        task.runtime_bundle_id = bundle.id
        task.worker_profile_snapshot = TaskWorkerProfileSnapshot(
            task_id=task.id, profile_name="p", image="worker", harness_key=key,
            default_execute_run_instruction_template="x", default_plan_run_instruction_template="x",
            ci_auto_repair_run_instruction_template="x",
            harness_config_snapshot={"requested_runtime_contract_version": HARNESS_CONTRACT_VERSION_V2,
                                     "v2_harness_verification_evidence": evidence,
                                     "worker_kit_identity": kit_identity},
        )
        await db.commit()
    return bundle.digest



@pytest.mark.asyncio
async def test_export_is_exact_db_archive_and_canonical_manifest(session_factory, tmp_path, monkeypatch):
    digest = await _bound(session_factory, tmp_path)
    monkeypatch.setattr("app.core.worker_runtime_bundle_export._rename_noreplace", lambda source, destination: source.rename(destination))
    async with session_factory() as db:
        bundle = await load_exportable_runtime_bundle(db, task_id=1)
        metadata = export_runtime_bundle(bundle, tmp_path / "out")
    directory = tmp_path / "out" / f"runtime-bundle-v2-{digest}"
    assert (directory / "runtime-bundle.tar").read_bytes() == bundle.bundle_bytes
    assert (directory / "runtime-manifest.json").read_bytes() == json.dumps(bundle.manifest, sort_keys=True, separators=(",", ":")).encode()
    assert metadata["bundle_digest"] == digest
    with pytest.raises(RuntimeBundleExportError, match="already exists"):
        export_runtime_bundle(bundle, tmp_path / "out")


@pytest.mark.asyncio
@pytest.mark.parametrize("key", ["pi", "opencode", "claude", "codex"])
async def test_selectors_and_selected_adapter_evidence_fail_closed(session_factory, tmp_path, key):
    digest = await _bound(session_factory, tmp_path, key)
    async with session_factory() as db:
        with pytest.raises(RuntimeBundleExportError, match="exactly one"):
            await load_exportable_runtime_bundle(db, task_id=1, bundle_digest=digest)
        loaded = await load_exportable_runtime_bundle(db, bundle_digest=digest)
        assert loaded.digest == digest
        task = (
            await db.execute(
                select(Task).where(Task.id == 1).options(selectinload(Task.worker_profile_snapshot))
            )
        ).scalar_one()
        config = deepcopy(task.worker_profile_snapshot.harness_config_snapshot)
        config["v2_harness_verification_evidence"]["adapter"]["digest"] = "0" * 64
        task.worker_profile_snapshot.harness_config_snapshot = config
        await db.commit()
        with pytest.raises(RuntimeBundleExportError, match="selected Harness evidence"):
            await load_exportable_runtime_bundle(db, task_id=1)


@pytest.mark.asyncio
async def test_tamper_and_secret_sentinel_never_publish_partial_directory(session_factory, tmp_path):
    await _bound(session_factory, tmp_path)
    async with session_factory() as db:
        bundle = await load_exportable_runtime_bundle(db, task_id=1)
        bundle.manifest["archive_sha256"] = "0" * 64
        with pytest.raises(RuntimeBundleExportError, match="digest"):
            export_runtime_bundle(bundle, tmp_path / "out")
        assert not (tmp_path / "out" / f"runtime-bundle-v2-{bundle.digest}").exists()
    with pytest.raises(RuntimeBundleExportError, match="secret-shaped"):
        _reject_secret_keys({"api_key": "sentinel-not-exported"})
    with pytest.raises(RuntimeBundleExportError, match="secret-shaped"):
        _reject_archive_secrets(b"prefix " + b"sk" + b"-test-secret-0123456789 suffix")


@pytest.mark.asyncio
async def test_failed_publication_removes_staging_directory(session_factory, tmp_path, monkeypatch):
    await _bound(session_factory, tmp_path)
    async with session_factory() as db:
        bundle = await load_exportable_runtime_bundle(db, task_id=1)
    monkeypatch.setattr(
        "app.core.worker_runtime_bundle_export._rename_noreplace",
        lambda source, destination: (_ for _ in ()).throw(RuntimeBundleExportError("simulated")),
    )
    with pytest.raises(RuntimeBundleExportError, match="simulated"):
        export_runtime_bundle(bundle, tmp_path / "out")
    assert not list((tmp_path / "out").glob(f".runtime-bundle-v2-{bundle.digest}.staging-*"))
