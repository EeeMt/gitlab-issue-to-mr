from __future__ import annotations

import io
import os
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
    get_or_create_runtime_bundle,
    load_bound_runtime_bundle,
    verify_bundle_bytes,
)
from app.models import Base, Task  # noqa: E402

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
    first = build_runtime_bundle(REPO_ROOT)
    second = build_runtime_bundle(REPO_ROOT)
    assert first.digest == second.digest
    assert first.archive_bytes == second.archive_bytes
    assert first.manifest["event_schema"] == "codify.worker.event/v1"
    assert first.manifest["adapters"]["claude"]["version"] == "1.0.0"
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
