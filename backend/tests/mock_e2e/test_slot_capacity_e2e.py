"""Mock E2E tests for the slot capacity feature.

Tests the full HTTP request/response cycle through the FastAPI app using a
real in-memory SQLite database.  Only authentication and project-access
dependencies are mocked — the actual slot-capacity SQL queries, config
persistence, and HTTP routing all execute for real.

External dependencies (GitLab, Docker, Mattermost) are either not involved
or are guarded by empty-default settings that cause early returns.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.pool import StaticPool

from app.database import get_db
from app.dependencies.auth import (
    get_optional_current_user,
    require_admin_user,
    require_authenticated_user,
)
from app.dependencies.project_access import (
    ProjectAccessScope,
    require_project_access_scope,
)
from app.main import app
from app.models import AIProvider, Base, Issue, Task, TaskStatus

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
async def _test_engine():
    """In-memory SQLite async engine with all tables created.

    Registers a no-op ``pg_advisory_xact_lock`` so that the PostgreSQL-
    specific advisory lock used for TOCTOU protection in
    :func:`~app.core.slot_capacity.check_slot_capacity` doesn't blow up
    on SQLite.
    """
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    # SQLite doesn't have pg_advisory_xact_lock — register a no-op stub
    @event.listens_for(engine.sync_engine, "connect")
    def _register_pg_compat(dbapi_conn, connection_record):
        dbapi_conn.create_function("pg_advisory_xact_lock", 1, lambda _key: None)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture
async def session_factory(_test_engine):
    """Async session factory bound to the test engine."""
    return async_sessionmaker(
        _test_engine, class_=AsyncSession, expire_on_commit=False
    )


@pytest.fixture
async def db_session(session_factory):
    """Session for *direct* data manipulation inside tests (seeding, etc.)."""
    async with session_factory() as session:
        yield session


@pytest.fixture
async def _default_provider(session_factory):
    """Seed a default AIProvider so task creation has a valid provider_id."""
    async with session_factory() as session:
        provider = AIProvider(
            name="Test Provider",
            base_url="https://api.example.com",
            api_key="test-key",
            model="test-model",
            is_default=True,
        )
        session.add(provider)
        await session.commit()
        return provider.id


@pytest.fixture
def _mock_admin_user():
    """A mock admin user returned by admin-gated auth overrides."""
    user = MagicMock()
    user.id = 1
    user.username = "testadmin"
    user.gitlab_user_id = 100
    user.platform_role = "platform_admin"
    return user


@pytest.fixture
async def client(session_factory, _mock_admin_user, _default_provider):
    """``httpx.AsyncClient`` wired to the FastAPI app.

    * ``get_db`` → yields sessions from the in-memory test database
    * ``get_optional_current_user`` → ``None`` (avoids FK issues)
    * ``require_authenticated_user`` → passthrough
    * ``require_admin_user`` → mock admin (for config endpoints)
    * ``require_project_access_scope`` → unrestricted
    """

    async def _override_get_db():
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    access_scope = ProjectAccessScope(
        is_unrestricted=True, accessible_projects=[]
    )

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_optional_current_user] = lambda: None
    app.dependency_overrides[require_authenticated_user] = lambda: None
    app.dependency_overrides[require_admin_user] = lambda: _mock_admin_user
    app.dependency_overrides[require_project_access_scope] = lambda: access_scope

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def _isolate_runtime_config():
    """Save / restore the module-level ``_runtime_config`` between tests."""
    from app.config import _runtime_config

    saved = dict(_runtime_config)
    yield
    _runtime_config.clear()
    _runtime_config.update(saved)


@pytest.fixture(autouse=True)
def _suppress_notifications():
    """Prevent Mattermost notifications from firing during tests."""
    with patch(
        "app.api.task_operations.notify_task_event",
        new_callable=AsyncMock,
    ):
        yield


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _future_dt(*, hours: int = 48, minute: int = 30) -> datetime:
    """Return a naive-UTC datetime *hours* from now, pinned to *minute*."""
    base = datetime.now(UTC).replace(tzinfo=None) + timedelta(hours=hours)
    return base.replace(minute=minute, second=0, microsecond=0)


async def _seed_tasks(
    session: AsyncSession,
    scheduled_at: datetime | None,
    *,
    count: int = 1,
    status: TaskStatus = TaskStatus.PENDING,
    project_id: int = 1,
) -> list[Task]:
    """Insert *count* tasks directly into the test database."""
    tasks: list[Task] = []
    for i in range(count):
        # Create an issue for each task
        issue = Issue(
            project_id=project_id,
            title=f"Test issue {i}",
            branch_name="test/branch",
            target_branch="main",
            status="open",
        )
        session.add(issue)
        await session.flush()

        task = Task(
            project_id=project_id,
            issue_id=issue.id,
            user_prompt="Seeded task",
            status=status,
            scheduled_at=scheduled_at,
        )
        session.add(task)
        tasks.append(task)
    await session.commit()
    for t in tasks:
        await session.refresh(t)
    return tasks


def _slot_settings(max_tasks: int = 5, enforce: bool = True):
    """Context-manager that patches ``get_effective_settings`` inside
    ``app.core.slot_capacity`` to return the desired slot config.

    Other callers of ``get_effective_settings`` (e.g. ``_can_manage_task``)
    see the real defaults — ``oidc_enabled=False`` ensures they pass through.
    """
    mock = MagicMock()
    mock.slot_max_tasks = max_tasks
    mock.slot_max_tasks_enforce = enforce
    return patch(
        "app.core.slot_capacity.get_effective_settings",
        return_value=mock,
    )


# ═══════════════════════════════════════════════════════════════════════════
# Tests: GET /api/tasks/slot-capacity
# ═══════════════════════════════════════════════════════════════════════════


class TestGetSlotCapacity:
    """GET /api/tasks/slot-capacity — query slot occupancy."""

    async def test_empty_slot_returns_zero_count(self, client):
        """An empty slot should report count=0 and is_full=False."""
        dt = _future_dt()
        with _slot_settings(max_tasks=5, enforce=True):
            resp = await client.get(
                "/api/tasks/slot-capacity",
                params={"scheduled_at": dt.isoformat()},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 0
        assert data["max"] == 5
        assert data["is_full"] is False
        assert data["enforce"] is True
        # Verify the hour boundaries are returned
        assert "hour_start" in data
        assert "hour_end" in data

    async def test_counts_tasks_in_same_hour(self, client, db_session):
        """Tasks scheduled within the same hour should be counted."""
        dt = _future_dt()
        await _seed_tasks(db_session, scheduled_at=dt, count=3)

        with _slot_settings(max_tasks=5, enforce=False):
            resp = await client.get(
                "/api/tasks/slot-capacity",
                params={"scheduled_at": dt.isoformat()},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 3
        assert data["max"] == 5
        assert data["is_full"] is False
        assert data["enforce"] is False

    async def test_full_slot(self, client, db_session):
        """A slot at capacity should report is_full=True."""
        dt = _future_dt()
        await _seed_tasks(db_session, scheduled_at=dt, count=5)

        with _slot_settings(max_tasks=5, enforce=True):
            resp = await client.get(
                "/api/tasks/slot-capacity",
                params={"scheduled_at": dt.isoformat()},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 5
        assert data["max"] == 5
        assert data["is_full"] is True
        assert data["enforce"] is True

    async def test_disabled_when_max_is_zero(self, client, db_session):
        """When slot_max_tasks=0 (disabled), is_full is always False."""
        dt = _future_dt()
        await _seed_tasks(db_session, scheduled_at=dt, count=10)

        with _slot_settings(max_tasks=0, enforce=True):
            resp = await client.get(
                "/api/tasks/slot-capacity",
                params={"scheduled_at": dt.isoformat()},
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 10
        assert data["max"] == 0
        assert data["is_full"] is False

    async def test_different_hour_not_counted(self, client, db_session):
        """Tasks in a *different* hour slot must not be counted."""
        dt = _future_dt(hours=48, minute=30)
        other_hour = dt.replace(minute=0) + timedelta(hours=2)
        await _seed_tasks(db_session, scheduled_at=other_hour, count=5)

        with _slot_settings(max_tasks=5, enforce=True):
            resp = await client.get(
                "/api/tasks/slot-capacity",
                params={"scheduled_at": dt.isoformat()},
            )

        assert resp.status_code == 200
        assert resp.json()["count"] == 0

    async def test_only_active_statuses_counted(self, client, db_session):
        """Only PENDING / QUEUED / RUNNING tasks count toward capacity."""
        dt = _future_dt()
        # Active statuses (should count)
        await _seed_tasks(db_session, scheduled_at=dt, count=1, status=TaskStatus.PENDING)
        await _seed_tasks(db_session, scheduled_at=dt, count=1, status=TaskStatus.QUEUED)
        await _seed_tasks(db_session, scheduled_at=dt, count=1, status=TaskStatus.RUNNING)
        # Inactive statuses (should NOT count)
        await _seed_tasks(db_session, scheduled_at=dt, count=1, status=TaskStatus.COMPLETED)
        await _seed_tasks(db_session, scheduled_at=dt, count=1, status=TaskStatus.FAILED)
        await _seed_tasks(db_session, scheduled_at=dt, count=1, status=TaskStatus.CANCELLED)

        with _slot_settings(max_tasks=10, enforce=False):
            resp = await client.get(
                "/api/tasks/slot-capacity",
                params={"scheduled_at": dt.isoformat()},
            )

        assert resp.status_code == 200
        assert resp.json()["count"] == 3


# ═══════════════════════════════════════════════════════════════════════════
# Tests: POST /api/tasks — slot enforcement on creation
# ═══════════════════════════════════════════════════════════════════════════


class TestTaskCreationSlotEnforcement:
    """POST /api/tasks — verify slot capacity enforcement."""

    async def _create_task(
        self,
        client: AsyncClient,
        *,
        scheduled_datetime: datetime | None = None,
        issue_id: int | None = None,
        **extra,
    ):
        """Helper: issue POST /api/tasks with sensible defaults."""
        # Create issue if not provided
        if issue_id is None:
            issue_resp = await client.post("/api/issues", json={
                "project_id": 1,
                "title": "Test issue for task creation",
                "target_branch": "main",
            })
            assert issue_resp.status_code == 200
            issue_id = issue_resp.json()["id"]

        payload: dict = {
            "issue_id": issue_id,
            "user_prompt": "Implement feature X",
            "priority": 0,
            "provider_id": 1,
            **extra,
        }
        if scheduled_datetime is not None:
            payload["scheduled_datetime"] = scheduled_datetime.isoformat()
        return await client.post("/api/tasks", json=payload)

    async def test_hard_reject_when_full_and_enforce(self, client, db_session):
        """409 Conflict when the slot is full and enforce=True."""
        dt = _future_dt()
        await _seed_tasks(db_session, scheduled_at=dt, count=5)

        with _slot_settings(max_tasks=5, enforce=True):
            resp = await self._create_task(client, scheduled_datetime=dt)

        assert resp.status_code == 409
        assert resp.json()["detail"]["code"] == "SLOT_FULL"

    async def test_soft_warning_when_full_and_not_enforced(self, client, db_session):
        """200 OK with ``slot_warning`` when enforce=False."""
        dt = _future_dt()
        await _seed_tasks(db_session, scheduled_at=dt, count=5)

        with _slot_settings(max_tasks=5, enforce=False):
            resp = await self._create_task(client, scheduled_datetime=dt)

        assert resp.status_code == 200
        data = resp.json()
        assert "slot_warning" in data
        assert data["slot_warning"]["code"] == "SLOT_FULL"
        # Task should still be created
        assert "id" in data
        assert data["status"] == "pending"

    async def test_unscheduled_task_bypasses_slot_check(self, client, db_session):
        """A task without ``scheduled_datetime`` should never be blocked."""
        dt = _future_dt()
        await _seed_tasks(db_session, scheduled_at=dt, count=10)

        with _slot_settings(max_tasks=5, enforce=True):
            resp = await self._create_task(client)  # no scheduled_datetime

        assert resp.status_code == 200
        data = resp.json()
        assert "slot_warning" not in data
        assert data["status"] == "pending"

    async def test_under_capacity_no_warning(self, client, db_session):
        """Creating in a non-full slot should produce no warning."""
        dt = _future_dt()
        await _seed_tasks(db_session, scheduled_at=dt, count=2)

        with _slot_settings(max_tasks=5, enforce=True):
            resp = await self._create_task(client, scheduled_datetime=dt)

        assert resp.status_code == 200
        data = resp.json()
        assert "slot_warning" not in data
        assert data["status"] == "pending"
        assert data["scheduled_at"] is not None

    async def test_create_fills_slot_incrementally(self, client, db_session):
        """Creating tasks one-by-one should fill the slot until 409."""
        dt = _future_dt()
        max_tasks = 3

        with _slot_settings(max_tasks=max_tasks, enforce=True):
            # Fill the slot (tasks 1..max_tasks)
            for i in range(max_tasks):
                resp = await self._create_task(
                    client,
                    scheduled_datetime=dt,
                    branch_name=f"feat/task-{i}",
                )
                assert resp.status_code == 200, (
                    f"Task {i + 1}/{max_tasks} should succeed"
                )

            # One more should be rejected
            resp = await self._create_task(client, scheduled_datetime=dt)

        assert resp.status_code == 409


# ═══════════════════════════════════════════════════════════════════════════
# Tests: POST /api/tasks/{id}/retry — slot enforcement on retry
# ═══════════════════════════════════════════════════════════════════════════


class TestRetrySlotEnforcement:
    """POST /api/tasks/{id}/retry — slot enforcement for retries."""

    async def test_retry_rejected_when_full_and_enforce(self, client, db_session):
        """409 when retrying into a full, enforced slot."""
        dt = _future_dt()
        # Create a FAILED task to retry
        [failed_task] = await _seed_tasks(
            db_session, scheduled_at=None, count=1, status=TaskStatus.FAILED,
        )
        # Fill the slot with other tasks
        await _seed_tasks(db_session, scheduled_at=dt, count=5)

        with _slot_settings(max_tasks=5, enforce=True):
            resp = await client.post(
                f"/api/tasks/{failed_task.id}/retry",
                json={"scheduled_datetime": dt.isoformat()},
            )

        assert resp.status_code == 409
        assert resp.json()["detail"]["code"] == "SLOT_FULL"

    async def test_retry_succeeds_when_not_enforced(self, client, db_session):
        """Retry into a full slot with enforce=False should succeed."""
        dt = _future_dt()
        [failed_task] = await _seed_tasks(
            db_session, scheduled_at=None, count=1, status=TaskStatus.FAILED,
        )
        await _seed_tasks(db_session, scheduled_at=dt, count=5)

        with _slot_settings(max_tasks=5, enforce=False):
            resp = await client.post(
                f"/api/tasks/{failed_task.id}/retry",
                json={"scheduled_datetime": dt.isoformat()},
            )

        assert resp.status_code == 200
        data = resp.json()
        # Retry returns the new task, which should have pending status
        assert data["status"] == "pending"
        assert data["is_retry"] is True

    async def test_retry_without_schedule_bypasses_slot(self, client, db_session):
        """Retry without scheduled_datetime ignores slot capacity entirely."""
        dt = _future_dt()
        [failed_task] = await _seed_tasks(
            db_session, scheduled_at=None, count=1, status=TaskStatus.FAILED,
        )
        await _seed_tasks(db_session, scheduled_at=dt, count=10)

        with _slot_settings(max_tasks=5, enforce=True):
            resp = await client.post(
                f"/api/tasks/{failed_task.id}/retry",
                json={},
            )

        assert resp.status_code == 200

    async def test_retry_excludes_own_task_from_count(self, client, db_session):
        """A failed task scheduled in the same slot should not count itself."""
        dt = _future_dt()
        # This failed task was previously scheduled at dt
        [failed_task] = await _seed_tasks(
            db_session, scheduled_at=dt, count=1, status=TaskStatus.FAILED,
        )
        # Fill the slot with (max - 1) *other* tasks → the failed task
        # should not push it over the limit.
        await _seed_tasks(db_session, scheduled_at=dt, count=4)

        with _slot_settings(max_tasks=5, enforce=True):
            resp = await client.post(
                f"/api/tasks/{failed_task.id}/retry",
                json={"scheduled_datetime": dt.isoformat()},
            )

        # 4 active tasks in slot + excluded self = 4 < 5 → should succeed
        assert resp.status_code == 200


# ═══════════════════════════════════════════════════════════════════════════
# Tests: PATCH / GET /api/config/runtime — config round-trip
# ═══════════════════════════════════════════════════════════════════════════


class TestConfigSlotRoundTrip:
    """PATCH + GET /api/config/runtime — slot settings round-trip."""

    async def test_set_and_read_slot_config(self, client):
        """PATCH slot_max_tasks → GET should reflect the new values."""
        # Set
        resp = await client.patch(
            "/api/config/runtime",
            json={"slot_max_tasks": 10, "slot_max_tasks_enforce": True},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["slot_max_tasks"] == 10
        assert data["slot_max_tasks_enforce"] is True

        # Read back
        resp = await client.get("/api/config/runtime")
        assert resp.status_code == 200
        data = resp.json()
        assert data["slot_max_tasks"] == 10
        assert data["slot_max_tasks_enforce"] is True

    async def test_slot_max_tasks_rejects_negative(self, client):
        """slot_max_tasks must be ≥ 0."""
        resp = await client.patch(
            "/api/config/runtime",
            json={"slot_max_tasks": -1},
        )
        assert resp.status_code == 400

    async def test_slot_max_tasks_rejects_over_100(self, client):
        """slot_max_tasks must be ≤ 100."""
        resp = await client.patch(
            "/api/config/runtime",
            json={"slot_max_tasks": 101},
        )
        assert resp.status_code == 400

    async def test_config_change_affects_slot_capacity(self, client, db_session):
        """End-to-end: change config → slot-capacity endpoint reflects it."""
        dt = _future_dt()
        await _seed_tasks(db_session, scheduled_at=dt, count=3)

        # Configure slot_max_tasks = 3 → slot should be full
        await client.patch(
            "/api/config/runtime",
            json={"slot_max_tasks": 3, "slot_max_tasks_enforce": True},
        )

        resp = await client.get(
            "/api/tasks/slot-capacity",
            params={"scheduled_at": dt.isoformat()},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["count"] == 3
        assert data["max"] == 3
        assert data["is_full"] is True
        assert data["enforce"] is True
