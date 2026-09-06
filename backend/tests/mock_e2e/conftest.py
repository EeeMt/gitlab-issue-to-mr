"""Shared fixtures for mock E2E tests.

The in-memory SQLite schema is built ONCE per worker session; an autouse
fixture deletes all rows after each test so every test still starts from a
clean database.  Previously every file rebuilt the full schema for every
test (~1.5s of setup per test — the dominant cost of this suite).
"""

from __future__ import annotations

import pytest
import sqlalchemy as sa
from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from app.models import Base


@pytest.fixture(scope="session")
async def _test_engine():
    """In-memory SQLite async engine with all tables created once per session."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    # SQLite doesn't have pg_advisory_xact_lock — register a no-op stub
    @event.listens_for(engine.sync_engine, "connect")
    def _register_pg_compat(dbapi_conn, connection_record):
        dbapi_conn.create_function("pg_advisory_xact_lock", 1, lambda _key: None)
        # SQLite lacks EXTRACT(epoch FROM interval).  Register a two-arg shim
        # that returns 0 for any non-None input (the actual datetime-difference
        # value is meaningless in SQLite text mode).
        dbapi_conn.create_function(
            "extract", 2, lambda _field, val: float(val) if val is not None else None
        )

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture(scope="session")
async def session_factory(_test_engine):
    """Async session factory bound to the shared in-memory test database."""
    return async_sessionmaker(
        _test_engine, class_=AsyncSession, expire_on_commit=False
    )


@pytest.fixture
async def db_session(session_factory):
    """Session for direct data manipulation inside tests (seeding, etc.)."""
    async with session_factory() as session:
        yield session


def _override_get_db_factory(session_factory):
    """Return an async generator compatible with FastAPI's Depends(get_db)."""

    async def _override_get_db():
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    return _override_get_db


@pytest.fixture
def override_get_db(session_factory):
    """FastAPI ``get_db`` dependency override for the shared test database."""
    return _override_get_db_factory(session_factory)


@pytest.fixture(autouse=True)
async def _clean_db(_test_engine):
    """Delete all rows after each test so tests see an empty database.

    SQLite runs with foreign keys off by default, so table order is
    irrelevant; iterating ``sorted_tables`` would emit a SAWarning because
    ``ci_failure_runs``/``tasks`` form an unresolvable FK cycle.
    """
    yield
    async with _test_engine.begin() as conn:
        for table in Base.metadata.tables.values():
            await conn.execute(sa.delete(table))


@pytest.fixture(autouse=True)
def _isolate_runtime_config():
    """Save / restore the module-level ``_runtime_config`` between tests."""
    from app.config import _runtime_config

    saved = dict(_runtime_config)
    yield
    _runtime_config.clear()
    _runtime_config.update(saved)