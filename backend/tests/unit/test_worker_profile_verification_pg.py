"""PostgreSQL transaction regressions for Profile verification epochs/lock order.

These use real row locks. They skip when the configured development test DB is
unreachable; SQLite cannot model either ``FOR UPDATE`` ordering or CAS races.
"""

from __future__ import annotations

import asyncio
import os
import uuid

import pytest
import sqlalchemy as sa
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool

from app.models import Base, WorkerProfile, WorkerSharedConfiguration

TEST_DATABASE_URL = os.environ.get(
    "CODIFY_TEST_DATABASE_URL",
    "postgresql+asyncpg://codify:codify_password@192.168.50.129:5432/codify_test",
)
HOST_BASE = TEST_DATABASE_URL.rsplit("/", 1)[0] + "/"


async def _create_database(dbname: str) -> None:
    admin_engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
    try:
        async with admin_engine.connect() as connection:
            await connection.execution_options(isolation_level="AUTOCOMMIT")
            await connection.execute(sa.text(f'CREATE DATABASE "{dbname}"'))
    finally:
        await admin_engine.dispose()


async def _drop_database(dbname: str) -> None:
    admin_engine = create_async_engine(TEST_DATABASE_URL, poolclass=NullPool)
    try:
        async with admin_engine.connect() as connection:
            await connection.execution_options(isolation_level="AUTOCOMMIT")
            # The deployed PostgreSQL is 16; FORCE closes leaked test sessions
            # before dropping the module-local database.
            await connection.execute(sa.text(f'DROP DATABASE IF EXISTS "{dbname}" WITH (FORCE)'))
    finally:
        await admin_engine.dispose()


@pytest.fixture(scope="module")
async def pg_engine():
    dbname = f"codify_profile_verification_{uuid.uuid4().hex[:8]}"
    database_url = HOST_BASE + dbname
    try:
        await _create_database(dbname)
    except Exception as exc:  # noqa: BLE001
        pytest.skip(f"PostgreSQL verification test DB unreachable: {exc!r}")

    engine = create_async_engine(database_url, pool_pre_ping=True, poolclass=NullPool)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
            await connection.execute(
                sa.text("ALTER TABLE worker_profiles ADD COLUMN IF NOT EXISTS v2_harness_verification_evidence JSON")
            )
            await connection.execute(
                sa.text("ALTER TABLE worker_profiles ADD COLUMN IF NOT EXISTS v2_worker_image_identity JSON")
            )
            await connection.execute(
                sa.text("ALTER TABLE worker_profiles ADD COLUMN IF NOT EXISTS worker_kit_identity JSON")
            )
            await connection.execute(
                sa.text("ALTER TABLE worker_profiles ADD COLUMN IF NOT EXISTS worker_kit_identity_generation INTEGER NOT NULL DEFAULT 0")
            )
            await connection.execute(
                sa.text("ALTER TABLE worker_runtime_readiness ADD COLUMN IF NOT EXISTS harness_inventory JSON")
            )
            await connection.execute(
                sa.text("ALTER TABLE worker_runtime_readiness ADD COLUMN IF NOT EXISTS kit_identity JSON")
            )
    except Exception as exc:  # noqa: BLE001
        await engine.dispose()
        await _drop_database(dbname)
        pytest.skip(f"PostgreSQL verification test DB unreachable: {exc!r}")
    try:
        yield engine
    finally:
        await engine.dispose()
        await _drop_database(dbname)


@pytest.fixture
async def pg_sessions(pg_engine):
    """Seed the shared test tables and restore them after every test."""
    maker = async_sessionmaker(pg_engine, expire_on_commit=False, autoflush=False)
    async with maker() as db:
        await db.execute(sa.text("TRUNCATE worker_profiles, worker_shared_configurations RESTART IDENTITY CASCADE"))
        shared = WorkerSharedConfiguration(id=1, revision=1)
        profile = WorkerProfile(name="pg-lock-worker", image="worker:test", enabled=True)
        db.add_all([shared, profile])
        await db.commit()
        profile_id = profile.id
    try:
        yield maker, profile_id
    finally:
        async with maker() as db:
            await db.execute(
                sa.text("TRUNCATE worker_profiles, worker_shared_configurations RESTART IDENTITY CASCADE")
            )
            await db.commit()


@pytest.mark.asyncio
async def test_shared_then_profile_lock_order_completes_without_deadlock(pg_sessions):
    """Both writers take Shared -> Profile; the second waits, then completes."""
    maker, profile_id = pg_sessions
    first_locked = asyncio.Event()
    release_first = asyncio.Event()

    async def writer_one():
        async with maker() as db:
            await db.execute(select(WorkerSharedConfiguration).where(WorkerSharedConfiguration.id == 1).with_for_update())
            await db.execute(select(WorkerProfile).where(WorkerProfile.id == profile_id).with_for_update())
            first_locked.set()
            await release_first.wait()
            await db.commit()

    async def writer_two():
        await first_locked.wait()
        async with maker() as db:
            await db.execute(select(WorkerSharedConfiguration).where(WorkerSharedConfiguration.id == 1).with_for_update())
            await db.execute(select(WorkerProfile).where(WorkerProfile.id == profile_id).with_for_update())
            await db.commit()

    one = asyncio.create_task(writer_one())
    two = asyncio.create_task(writer_two())
    try:
        await asyncio.wait_for(first_locked.wait(), timeout=5)
        await asyncio.sleep(0.05)
        assert not two.done()
        release_first.set()
        await asyncio.wait_for(asyncio.gather(one, two), timeout=5)
    finally:
        release_first.set()
        for task in (one, two):
            if not task.done():
                task.cancel()
        await asyncio.gather(one, two, return_exceptions=True)


@pytest.mark.asyncio
async def test_v1_slow_success_cas_cannot_restore_after_shared_invalidation(pg_sessions):
    """The verify success UPDATE must lose after shared invalidation increments epoch."""
    maker, profile_id = pg_sessions
    verify_started = asyncio.Event()
    release_verify = asyncio.Event()

    async def slow_verify():
        async with maker() as db:
            profile = await db.get(WorkerProfile, profile_id)
            generation = profile.v2_worker_image_identity_generation
            verify_started.set()
            await release_verify.wait()
            result = await db.execute(
                update(WorkerProfile)
                .where(
                    WorkerProfile.id == profile_id,
                    WorkerProfile.v2_worker_image_identity_generation == generation,
                )
                .values(verified_runtime_configuration_digest="stale-v1-success")
            )
            await db.commit()
            return result.rowcount

    task = asyncio.create_task(slow_verify())
    try:
        await asyncio.wait_for(verify_started.wait(), timeout=5)
        async with maker() as db:
            await db.execute(select(WorkerSharedConfiguration).where(WorkerSharedConfiguration.id == 1).with_for_update())
            await db.execute(
                update(WorkerProfile)
                .where(WorkerProfile.id == profile_id)
                .values(
                    verified_runtime_configuration_digest=None,
                    v2_harness_verification_evidence=None,
                    v2_worker_image_identity_generation=WorkerProfile.v2_worker_image_identity_generation + 1,
                )
            )
            await db.commit()
        release_verify.set()
        assert await asyncio.wait_for(task, timeout=5) == 0
    finally:
        release_verify.set()
        if not task.done():
            task.cancel()
        await asyncio.gather(task, return_exceptions=True)
    async with maker() as db:
        profile = await db.get(WorkerProfile, profile_id)
        assert profile.verified_runtime_configuration_digest is None
