"""Mock E2E tests for the Stats API endpoints.

Tests the full HTTP request/response cycle through the FastAPI app using a
real in-memory SQLite database.  Only authentication and project-access
dependencies are mocked — the actual SQL queries, aggregation logic, error
categorisation, and HTTP routing all execute for real.

Endpoints under test:
- GET /api/stats          — task statistics overview
- GET /api/stats/analytics — advanced analytics dashboard
"""

from __future__ import annotations

import os
from datetime import timedelta
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

# Ensure a usable encryption key is available before importing app modules.
os.environ.setdefault("CONFIG_ENCRYPTION_KEY", "test-stats-e2e-key-32chars!!!!")

from app.core.utcnow import utcnow
from app.database import get_db
from app.dependencies.auth import (
    AuthContext,
    get_optional_current_user,
    require_admin_user,
    require_authenticated_context,
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

    Registers compatibility shims for PostgreSQL-specific functions that
    the stats queries use:
    - ``pg_advisory_xact_lock`` — no-op (advisory locks are Postgres-only)
    - ``extract`` — returns its second argument as-is (datetime subtraction
      is not meaningful in SQLite text mode, but this prevents
      "no such function" errors so the SQL still executes)
    """
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

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


@pytest.fixture
async def session_factory(_test_engine):
    """Async session factory bound to the test engine."""
    return async_sessionmaker(
        _test_engine, class_=AsyncSession, expire_on_commit=False
    )


@pytest.fixture
async def db_session(session_factory):
    """Session for direct data manipulation inside tests (seeding, etc.)."""
    async with session_factory() as session:
        yield session


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
async def client(session_factory, _mock_admin_user):
    """``httpx.AsyncClient`` wired to the FastAPI app with auth overrides.

    * ``get_db`` → yields sessions from the in-memory test database
    * ``get_optional_current_user`` → mock admin user (stats endpoints use
      this for access scope resolution)
    * ``require_authenticated_user`` → mock admin
    * ``require_admin_user`` → mock admin
    * ``require_authenticated_context`` → mock AuthContext (needed for
      ``require_page_access("analytics")``)
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

    mock_auth_context = AuthContext(
        user=_mock_admin_user,
        session=MagicMock(),
        gitlab_access_token=None,
        gitlab_refresh_token=None,
    )

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_optional_current_user] = lambda: _mock_admin_user
    app.dependency_overrides[require_authenticated_user] = lambda: _mock_admin_user
    app.dependency_overrides[require_admin_user] = lambda: _mock_admin_user
    app.dependency_overrides[require_authenticated_context] = lambda: mock_auth_context
    app.dependency_overrides[require_project_access_scope] = lambda: access_scope

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest.fixture
async def restricted_client(session_factory, _mock_admin_user):
    """Like ``client``, but with project access restricted to project_id=1."""

    async def _override_get_db():
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    access_scope = ProjectAccessScope(
        is_unrestricted=False,
        accessible_projects=[
            {"id": 1, "name": "Project One", "path_with_namespace": "group/project-one"}
        ],
    )

    mock_auth_context = AuthContext(
        user=_mock_admin_user,
        session=MagicMock(),
        gitlab_access_token=None,
        gitlab_refresh_token=None,
    )

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_optional_current_user] = lambda: _mock_admin_user
    app.dependency_overrides[require_authenticated_user] = lambda: _mock_admin_user
    app.dependency_overrides[require_admin_user] = lambda: _mock_admin_user
    app.dependency_overrides[require_authenticated_context] = lambda: mock_auth_context
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
def _mock_gitlab_projects():
    """Prevent ``build_project_lookup`` from calling GitLab API.

    The analytics endpoint calls ``build_project_lookup`` which, for
    unrestricted access, hits ``get_cached_projects()`` → GitLab.  Return
    an empty list so project names fall back to "Project <id>".
    """
    with patch(
        "app.core.projects.get_cached_projects",
        new_callable=AsyncMock,
        return_value=[],
    ):
        yield


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


async def _seed_issue(db_session: AsyncSession, **overrides) -> Issue:
    """Create an issue directly in the test database."""
    defaults = dict(
        project_id=1,
        title="Test issue",
        description="Test description",
        branch_name="codify/test",
        target_branch="main",
        status="open",
    )
    defaults.update(overrides)
    issue = Issue(**defaults)
    db_session.add(issue)
    await db_session.commit()
    await db_session.refresh(issue)
    return issue


async def _seed_task(db_session: AsyncSession, issue: Issue = None, **overrides) -> Task:
    """Create a task directly in the test database."""
    if issue is None:
        issue = await _seed_issue(db_session)

    now = utcnow()
    defaults = dict(
        project_id=issue.project_id,
        issue_id=issue.id,
        user_prompt="Test prompt",
        status=TaskStatus.COMPLETED,
        priority=1,
        initiator_username="testuser",
        created_at=now,
        updated_at=now,
    )
    defaults.update(overrides)
    task = Task(**defaults)
    db_session.add(task)
    await db_session.commit()
    await db_session.refresh(task)
    return task


async def _seed_provider(db_session: AsyncSession, **overrides) -> AIProvider:
    """Create an AI provider directly in the test database."""
    defaults = dict(
        name="Claude Test",
        base_url="https://api.example.test",
        api_key="test-key",
        model="claude-sonnet-test",
        max_turns=20,
        is_default=False,
    )
    defaults.update(overrides)
    provider = AIProvider(**defaults)
    db_session.add(provider)
    await db_session.commit()
    await db_session.refresh(provider)
    return provider


# ---------------------------------------------------------------------------
# GET /api/stats
# ---------------------------------------------------------------------------


class TestGetStats:
    """Tests for GET /api/stats — task statistics overview."""

    async def test_empty_db_returns_all_zeros(self, client):
        """An empty database should return total=0 and all status counts=0."""
        resp = await client.get("/api/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 0
        assert data["pending"] == 0
        assert data["queued"] == 0
        assert data["running"] == 0
        assert data["completed"] == 0
        assert data["failed"] == 0
        assert data["cancelled"] == 0
        assert data["completed_24h"] == 0
        assert data["failed_cancelled_24h"] == 0
        assert data["running_long_30min"] == 0

    async def test_single_completed_task(self, client, db_session):
        """One completed task should yield total=1, completed=1."""
        await _seed_task(db_session, status=TaskStatus.COMPLETED)
        resp = await client.get("/api/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == 1
        assert data["completed"] == 1
        assert data["failed"] == 0

    async def test_all_status_counts(self, client, db_session):
        """One task per status — each counter should be exactly 1."""
        for status in TaskStatus:
            await _seed_task(db_session, status=status)
        resp = await client.get("/api/stats")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total"] == len(TaskStatus)
        for status in TaskStatus:
            assert data[status.value] == 1, f"Expected {status.value}=1"

    async def test_completed_24h_only_recent(self, client, db_session):
        """Only tasks created in the last 24h count towards completed_24h."""
        now = utcnow()
        # Recent completed task — should count
        await _seed_task(
            db_session,
            status=TaskStatus.COMPLETED,
            created_at=now - timedelta(hours=2),
        )
        # Old completed task — should NOT count
        await _seed_task(
            db_session,
            status=TaskStatus.COMPLETED,
            created_at=now - timedelta(hours=48),
        )
        resp = await client.get("/api/stats")
        data = resp.json()
        assert data["completed"] == 2  # both counted in total
        assert data["completed_24h"] == 1  # only the recent one

    async def test_completed_24h_excludes_non_completed(self, client, db_session):
        """completed_24h only counts COMPLETED tasks, not FAILED/PENDING."""
        now = utcnow()
        await _seed_task(
            db_session,
            status=TaskStatus.FAILED,
            created_at=now - timedelta(hours=1),
        )
        await _seed_task(
            db_session,
            status=TaskStatus.PENDING,
            created_at=now - timedelta(hours=1),
        )
        resp = await client.get("/api/stats")
        data = resp.json()
        assert data["completed_24h"] == 0

    async def test_failed_cancelled_24h(self, client, db_session):
        """failed_cancelled_24h counts FAILED + CANCELLED in the last 24h."""
        now = utcnow()
        await _seed_task(
            db_session,
            status=TaskStatus.FAILED,
            created_at=now - timedelta(hours=3),
        )
        await _seed_task(
            db_session,
            status=TaskStatus.CANCELLED,
            created_at=now - timedelta(hours=5),
        )
        # Old failed — should NOT count
        await _seed_task(
            db_session,
            status=TaskStatus.FAILED,
            created_at=now - timedelta(hours=48),
        )
        resp = await client.get("/api/stats")
        data = resp.json()
        assert data["failed_cancelled_24h"] == 2

    async def test_running_long_30min(self, client, db_session):
        """A RUNNING task started >30 min ago is counted as long-running."""
        now = utcnow()
        await _seed_task(
            db_session,
            status=TaskStatus.RUNNING,
            started_at=now - timedelta(minutes=45),
        )
        resp = await client.get("/api/stats")
        data = resp.json()
        assert data["running_long_30min"] == 1

    async def test_running_not_long_excluded(self, client, db_session):
        """A RUNNING task started <30 min ago is NOT counted as long-running."""
        now = utcnow()
        await _seed_task(
            db_session,
            status=TaskStatus.RUNNING,
            started_at=now - timedelta(minutes=10),
        )
        resp = await client.get("/api/stats")
        data = resp.json()
        assert data["running"] == 1
        assert data["running_long_30min"] == 0

    async def test_running_long_requires_started_at(self, client, db_session):
        """A RUNNING task with no started_at is NOT counted as long-running."""
        await _seed_task(
            db_session,
            status=TaskStatus.RUNNING,
            started_at=None,
        )
        resp = await client.get("/api/stats")
        data = resp.json()
        assert data["running"] == 1
        assert data["running_long_30min"] == 0

    async def test_multiple_projects_aggregated(self, client, db_session):
        """Tasks from different projects are aggregated together."""
        await _seed_task(db_session, project_id=1, status=TaskStatus.COMPLETED)
        await _seed_task(db_session, project_id=2, status=TaskStatus.COMPLETED)
        await _seed_task(db_session, project_id=3, status=TaskStatus.FAILED)
        resp = await client.get("/api/stats")
        data = resp.json()
        assert data["total"] == 3
        assert data["completed"] == 2
        assert data["failed"] == 1

    async def test_response_has_all_expected_fields(self, client):
        """Verify the response contains every expected top-level field."""
        resp = await client.get("/api/stats")
        assert resp.status_code == 200
        data = resp.json()
        expected_fields = {
            "total", "pending", "queued", "running", "completed",
            "failed", "cancelled", "completed_24h", "failed_cancelled_24h",
            "running_long_30min",
        }
        assert expected_fields.issubset(data.keys())

    async def test_restricted_scope_filters_projects(
        self, restricted_client, db_session
    ):
        """Restricted access scope only counts tasks for accessible projects."""
        # restricted_client only has access to project_id=1
        await _seed_task(db_session, project_id=1, status=TaskStatus.COMPLETED)
        await _seed_task(db_session, project_id=2, status=TaskStatus.COMPLETED)
        resp = await restricted_client.get("/api/stats")
        data = resp.json()
        assert data["total"] == 1
        assert data["completed"] == 1

    async def test_restricted_scope_no_projects(self, session_factory, _mock_admin_user):
        """Restricted scope with an empty project list returns all zeros."""

        async def _override_get_db():
            async with session_factory() as session:
                try:
                    yield session
                    await session.commit()
                except Exception:
                    await session.rollback()
                    raise

        empty_scope = ProjectAccessScope(
            is_unrestricted=False, accessible_projects=[]
        )
        mock_auth_context = AuthContext(
            user=_mock_admin_user,
            session=MagicMock(),
            gitlab_access_token=None,
            gitlab_refresh_token=None,
        )
        app.dependency_overrides[get_db] = _override_get_db
        app.dependency_overrides[get_optional_current_user] = lambda: _mock_admin_user
        app.dependency_overrides[require_authenticated_user] = lambda: _mock_admin_user
        app.dependency_overrides[require_admin_user] = lambda: _mock_admin_user
        app.dependency_overrides[require_authenticated_context] = lambda: mock_auth_context
        app.dependency_overrides[require_project_access_scope] = lambda: empty_scope

        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as ac:
            resp = await ac.get("/api/stats")

        app.dependency_overrides.clear()
        data = resp.json()
        assert data["total"] == 0


# ---------------------------------------------------------------------------
# GET /api/stats/analytics
# ---------------------------------------------------------------------------


class TestGetAnalytics:
    """Tests for GET /api/stats/analytics — advanced analytics dashboard.

    NOTE: SQLite does not support PostgreSQL ``EXTRACT(epoch FROM interval)``
    natively.  A compatibility shim is registered in the engine fixture that
    returns ``float(val)`` for any non-None argument.  Since SQLite datetime
    subtraction on text columns produces 0, execution-time and queue-wait
    values will be 0.0 rather than accurate durations.  Tests verify the
    *structure* and non-timing aggregate values; exact durations are not
    asserted.
    """

    async def test_empty_db_valid_response(self, client):
        """An empty database should return a valid response with zeroed metrics."""
        resp = await client.get("/api/stats/analytics")
        assert resp.status_code == 200
        data = resp.json()
        assert data["window_days"] == 30
        assert data["summary"]["total_tasks"] == 0
        assert data["summary"]["completed_tasks"] == 0
        assert data["summary"]["failed_tasks"] == 0
        assert data["projects"] == []
        assert data["initiators"] == []
        assert data["error_breakdown"] == []
        assert len(data["trends"]) == 30  # 30 day entries even when empty

    async def test_summary_with_completed_tasks(self, client, db_session):
        """Seeded completed tasks appear in the summary counts."""
        now = utcnow()
        for _ in range(3):
            await _seed_task(
                db_session,
                status=TaskStatus.COMPLETED,
                created_at=now - timedelta(days=1),
            )
        await _seed_task(
            db_session,
            status=TaskStatus.FAILED,
            created_at=now - timedelta(days=2),
            error_message="Something went wrong",
        )
        resp = await client.get("/api/stats/analytics")
        data = resp.json()
        s = data["summary"]
        assert s["total_tasks"] == 4
        assert s["completed_tasks"] == 3
        assert s["failed_tasks"] == 1
        assert s["finished_tasks"] == 4

    async def test_days_7_parameter(self, client, db_session):
        """days=7 limits trends to 7 entries."""
        now = utcnow()
        await _seed_task(db_session, created_at=now - timedelta(days=3))
        resp = await client.get("/api/stats/analytics?days=7")
        assert resp.status_code == 200
        data = resp.json()
        assert data["window_days"] == 7
        assert len(data["trends"]) == 7

    async def test_days_90_parameter(self, client, db_session):
        """days=90 limits trends to 90 entries."""
        now = utcnow()
        await _seed_task(db_session, created_at=now - timedelta(days=10))
        resp = await client.get("/api/stats/analytics?days=90")
        assert resp.status_code == 200
        data = resp.json()
        assert data["window_days"] == 90
        assert len(data["trends"]) == 90

    async def test_days_invalid_returns_400(self, client):
        """days=15 (not in {7, 30, 90}) should return 400."""
        resp = await client.get("/api/stats/analytics?days=15")
        assert resp.status_code == 400
        assert "days must be one of" in resp.json()["detail"]

    async def test_project_id_filter(self, client, db_session):
        """project_id filter restricts analytics to that project only."""
        now = utcnow()
        await _seed_task(db_session, project_id=1, created_at=now - timedelta(days=1))
        await _seed_task(db_session, project_id=2, created_at=now - timedelta(days=1))
        resp = await client.get("/api/stats/analytics?project_id=1")
        data = resp.json()
        assert data["summary"]["total_tasks"] == 1
        # Only project 1 should appear in the breakdown
        project_ids = [p["project_id"] for p in data["projects"]]
        assert project_ids == [1]

    async def test_initiator_username_filter(self, client, db_session):
        """initiator_username filter restricts analytics to that user only."""
        now = utcnow()
        await _seed_task(
            db_session,
            initiator_username="alice",
            created_at=now - timedelta(days=1),
        )
        await _seed_task(
            db_session,
            initiator_username="bob",
            created_at=now - timedelta(days=1),
        )
        resp = await client.get("/api/stats/analytics?initiator_username=alice")
        data = resp.json()
        assert data["summary"]["total_tasks"] == 1
        # Only alice in initiators list (since the filter is applied)
        usernames = [i["initiator_username"] for i in data["initiators"]]
        assert usernames == ["alice"]

    async def test_per_project_breakdown(self, client, db_session):
        """Projects section lists per-project task counts."""
        now = utcnow()
        # 3 tasks for project 10, 1 for project 20
        for _ in range(3):
            await _seed_task(
                db_session,
                project_id=10,
                status=TaskStatus.COMPLETED,
                created_at=now - timedelta(days=2),
            )
        await _seed_task(
            db_session,
            project_id=20,
            status=TaskStatus.FAILED,
            created_at=now - timedelta(days=3),
            error_message="Timeout exceeded",
        )
        resp = await client.get("/api/stats/analytics")
        data = resp.json()
        projects = {p["project_id"]: p for p in data["projects"]}
        assert 10 in projects
        assert projects[10]["task_count"] == 3
        assert projects[10]["completed_tasks"] == 3
        assert 20 in projects
        assert projects[20]["task_count"] == 1
        assert projects[20]["failed_tasks"] == 1

    async def test_per_initiator_breakdown(self, client, db_session):
        """Initiators section lists per-user task counts."""
        now = utcnow()
        for _ in range(2):
            await _seed_task(
                db_session,
                initiator_username="alice",
                initiator_gitlab_user_id=10,
                created_at=now - timedelta(days=1),
            )
        await _seed_task(
            db_session,
            initiator_username="bob",
            initiator_gitlab_user_id=20,
            created_at=now - timedelta(days=1),
        )
        resp = await client.get("/api/stats/analytics")
        data = resp.json()
        initiators = {i["initiator_username"]: i for i in data["initiators"]}
        assert "alice" in initiators
        assert initiators["alice"]["task_count"] == 2
        assert "bob" in initiators
        assert initiators["bob"]["task_count"] == 1

    async def test_trend_data_has_correct_day_count(self, client, db_session):
        """Trend array has exactly ``days`` entries with correct date range."""
        now = utcnow()
        await _seed_task(db_session, created_at=now - timedelta(days=5))
        resp = await client.get("/api/stats/analytics?days=30")
        data = resp.json()
        trends = data["trends"]
        assert len(trends) == 30
        # Each entry should have a date field
        for entry in trends:
            assert "date" in entry
            assert "task_count" in entry

    async def test_trend_data_contains_seeded_tasks(self, client, db_session):
        """Seeded tasks appear in the trend for their creation date."""
        now = utcnow()
        seed_date = now - timedelta(days=5)
        await _seed_task(db_session, status=TaskStatus.COMPLETED, created_at=seed_date)
        resp = await client.get("/api/stats/analytics?days=7")
        data = resp.json()
        expected_date = seed_date.date().isoformat()
        matching = [t for t in data["trends"] if t["date"] == expected_date]
        assert len(matching) == 1
        assert matching[0]["task_count"] == 1
        assert matching[0]["completed_tasks"] == 1

    async def test_error_breakdown_categorisation(self, client, db_session):
        """Failed tasks are categorised into error buckets."""
        now = utcnow()
        await _seed_task(
            db_session,
            status=TaskStatus.FAILED,
            error_message="Connection refused: timeout waiting for server",
            created_at=now - timedelta(days=1),
        )
        await _seed_task(
            db_session,
            status=TaskStatus.FAILED,
            error_message="docker: image pull failed",
            created_at=now - timedelta(days=1),
        )
        await _seed_task(
            db_session,
            status=TaskStatus.FAILED,
            error_message="docker: container exited with non-zero code",
            created_at=now - timedelta(days=1),
        )
        resp = await client.get("/api/stats/analytics")
        data = resp.json()
        categories = {e["category"]: e for e in data["error_breakdown"]}
        # "timeout" pattern → Timeout category
        assert "Timeout" in categories
        assert categories["Timeout"]["count"] == 1
        # "docker" pattern → Docker category (2 tasks)
        assert "Docker" in categories
        assert categories["Docker"]["count"] == 2

    async def test_error_breakdown_share_of_failed(self, client, db_session):
        """share_of_failed is calculated as count/total_failed."""
        now = utcnow()
        for _ in range(3):
            await _seed_task(
                db_session,
                status=TaskStatus.FAILED,
                error_message="Connection timeout",
                created_at=now - timedelta(days=1),
            )
        await _seed_task(
            db_session,
            status=TaskStatus.FAILED,
            error_message="SyntaxError in code",
            created_at=now - timedelta(days=1),
        )
        resp = await client.get("/api/stats/analytics")
        data = resp.json()
        categories = {e["category"]: e for e in data["error_breakdown"]}
        assert categories["Timeout"]["share_of_failed"] == pytest.approx(0.75)
        assert categories["Code"]["share_of_failed"] == pytest.approx(0.25)

    async def test_token_usage_totals(self, client, db_session):
        """Token counts are aggregated in the summary."""
        now = utcnow()
        await _seed_task(
            db_session,
            input_tokens=1000,
            output_tokens=500,
            created_at=now - timedelta(days=1),
        )
        await _seed_task(
            db_session,
            input_tokens=2000,
            output_tokens=800,
            created_at=now - timedelta(days=2),
        )
        resp = await client.get("/api/stats/analytics")
        data = resp.json()
        s = data["summary"]
        assert s["total_input_tokens"] == 3000
        assert s["total_output_tokens"] == 1300
        assert s["total_tokens"] == 4300
        assert s["token_tracked_tasks"] == 2

    async def test_token_usage_per_project(self, client, db_session):
        """Per-project token aggregation is included in the projects list."""
        now = utcnow()
        await _seed_task(
            db_session,
            project_id=1,
            input_tokens=500,
            output_tokens=200,
            created_at=now - timedelta(days=1),
        )
        await _seed_task(
            db_session,
            project_id=2,
            input_tokens=800,
            output_tokens=300,
            created_at=now - timedelta(days=1),
        )
        resp = await client.get("/api/stats/analytics")
        data = resp.json()
        projects = {p["project_id"]: p for p in data["projects"]}
        assert projects[1]["input_tokens"] == 500
        assert projects[1]["output_tokens"] == 200
        assert projects[1]["total_tokens"] == 700
        assert projects[2]["total_tokens"] == 1100

    async def test_success_failure_rates(self, client, db_session):
        """success_rate and failure_rate are computed correctly."""
        now = utcnow()
        # 3 completed, 1 failed → success=0.75, failure=0.25
        for _ in range(3):
            await _seed_task(
                db_session,
                status=TaskStatus.COMPLETED,
                created_at=now - timedelta(days=1),
            )
        await _seed_task(
            db_session,
            status=TaskStatus.FAILED,
            created_at=now - timedelta(days=1),
        )
        resp = await client.get("/api/stats/analytics")
        data = resp.json()
        s = data["summary"]
        assert s["success_rate"] == pytest.approx(0.75)
        assert s["failure_rate"] == pytest.approx(0.25)

    async def test_success_rate_none_when_no_finished(self, client):
        """success_rate is None when there are no finished tasks."""
        resp = await client.get("/api/stats/analytics")
        data = resp.json()
        assert data["summary"]["success_rate"] is None
        assert data["summary"]["failure_rate"] is None

    async def test_provider_analytics_excludes_unfinished_tasks(self, client, db_session):
        """Provider tab metrics should be based on finished tasks only."""
        now = utcnow()
        provider = await _seed_provider(db_session)
        for status in (
            TaskStatus.COMPLETED,
            TaskStatus.FAILED,
            TaskStatus.CANCELLED,
            TaskStatus.PENDING,
            TaskStatus.QUEUED,
            TaskStatus.RUNNING,
        ):
            await _seed_task(
                db_session,
                status=status,
                provider_id=provider.id,
                model_name="claude-sonnet-test",
                input_tokens=100,
                output_tokens=50,
                created_at=now - timedelta(days=1),
            )

        resp = await client.get("/api/stats/analytics")
        assert resp.status_code == 200
        data = resp.json()

        assert data["provider_summary"]["provider_covered_task_count"] == 3
        assert data["provider_summary"]["provider_covered_total_tokens"] == 450
        assert data["provider_summary"]["provider_success_rate"] == pytest.approx(1 / 3)

        provider = data["providers"][0]
        assert provider["task_count"] == 3
        assert provider["finished_task_count"] == 3
        assert provider["completed_task_count"] == 1
        assert provider["failed_task_count"] == 1
        assert provider["cancelled_task_count"] == 1
        assert provider["total_tokens"] == 450

    async def test_provider_analytics_uses_provider_model_and_ignores_unlinked_tasks(self, client, db_session):
        """Provider tab metrics should ignore tasks that cannot join to a provider row."""
        now = utcnow()
        provider = await _seed_provider(
            db_session,
            name="Claude Config",
            model="configured-claude-model",
        )
        await _seed_task(
            db_session,
            status=TaskStatus.COMPLETED,
            provider_id=provider.id,
            model_name=None,
            input_tokens=100,
            output_tokens=50,
            created_at=now - timedelta(days=1),
        )
        await _seed_task(
            db_session,
            status=TaskStatus.COMPLETED,
            provider_id=None,
            model_name="legacy-model",
            input_tokens=100,
            output_tokens=50,
            created_at=now - timedelta(days=1),
        )
        await _seed_task(
            db_session,
            status=TaskStatus.COMPLETED,
            provider_id=999,
            model_name="deleted-provider-model",
            input_tokens=100,
            output_tokens=50,
            created_at=now - timedelta(days=1),
        )

        resp = await client.get("/api/stats/analytics")
        assert resp.status_code == 200
        data = resp.json()

        assert data["provider_summary"]["provider_covered_task_count"] == 1
        assert len(data["providers"]) == 1
        assert data["providers"][0]["provider_name"] == "Claude Config"
        assert data["providers"][0]["provider_model"] == "configured-claude-model"
        assert data["providers"][0]["task_count"] == 1

    async def test_available_initiators_list(self, client, db_session):
        """available_initiators lists all initiators with task counts."""
        now = utcnow()
        for _ in range(3):
            await _seed_task(
                db_session,
                initiator_username="alice",
                initiator_gitlab_user_id=10,
                created_at=now - timedelta(days=1),
            )
        for _ in range(2):
            await _seed_task(
                db_session,
                initiator_username="bob",
                initiator_gitlab_user_id=20,
                created_at=now - timedelta(days=2),
            )
        resp = await client.get("/api/stats/analytics")
        data = resp.json()
        available = {i["initiator_username"]: i for i in data["available_initiators"]}
        assert "alice" in available
        assert available["alice"]["task_count"] == 3
        assert "bob" in available
        assert available["bob"]["task_count"] == 2

    async def test_priority_wait_stats(self, client, db_session):
        """Priority wait stats are grouped by task priority."""
        now = utcnow()
        await _seed_task(
            db_session,
            priority=0,
            started_at=now - timedelta(minutes=10),
            created_at=now - timedelta(minutes=15),
        )
        await _seed_task(
            db_session,
            priority=1,
            started_at=now - timedelta(minutes=5),
            created_at=now - timedelta(minutes=20),
        )
        resp = await client.get("/api/stats/analytics")
        data = resp.json()
        priorities = {p["priority"]: p for p in data["priority_waits"]}
        assert 0 in priorities
        assert priorities[0]["task_count"] == 1
        assert 1 in priorities
        assert priorities[1]["task_count"] == 1

    async def test_execution_time_fields_present(self, client, db_session):
        """Execution-time summary fields are present (even if zero in SQLite)."""
        now = utcnow()
        await _seed_task(
            db_session,
            status=TaskStatus.COMPLETED,
            started_at=now - timedelta(minutes=30),
            completed_at=now - timedelta(minutes=5),
            created_at=now - timedelta(minutes=35),
        )
        resp = await client.get("/api/stats/analytics")
        data = resp.json()
        s = data["summary"]
        # Fields exist and are numeric (value may be 0.0 in SQLite)
        assert "avg_execution_seconds" in s
        assert "max_execution_seconds" in s
        assert s["avg_execution_seconds"] is not None
        assert s["max_execution_seconds"] is not None

    async def test_change_stats_aggregation(self, client, db_session):
        """Code change statistics (additions, deletions) are aggregated."""
        now = utcnow()
        await _seed_task(
            db_session,
            additions=50,
            deletions=20,
            total_changes=70,
            created_at=now - timedelta(days=1),
        )
        await _seed_task(
            db_session,
            additions=30,
            deletions=10,
            total_changes=40,
            created_at=now - timedelta(days=2),
        )
        resp = await client.get("/api/stats/analytics")
        data = resp.json()
        s = data["summary"]
        assert s["total_additions"] == 80
        assert s["total_deletions"] == 30
        assert s["total_changes"] == 110

    async def test_restricted_scope_analytics(self, restricted_client, db_session):
        """Restricted access scope filters analytics to accessible projects."""
        now = utcnow()
        # restricted_client has access only to project_id=1
        await _seed_task(db_session, project_id=1, created_at=now - timedelta(days=1))
        await _seed_task(db_session, project_id=2, created_at=now - timedelta(days=1))
        resp = await restricted_client.get("/api/stats/analytics")
        data = resp.json()
        assert data["summary"]["total_tasks"] == 1

    async def test_restricted_scope_project_not_accessible(
        self, restricted_client, db_session
    ):
        """Querying analytics for a project not in scope returns 404."""
        resp = await restricted_client.get("/api/stats/analytics?project_id=999")
        assert resp.status_code == 404

    async def test_response_structure(self, client):
        """The analytics response has all expected top-level keys."""
        resp = await client.get("/api/stats/analytics")
        assert resp.status_code == 200
        data = resp.json()
        expected_keys = {
            "window_days",
            "generated_at",
            "summary",
            "available_initiators",
            "projects",
            "initiators",
            "trends",
            "priority_waits",
            "error_breakdown",
        }
        assert expected_keys.issubset(data.keys())

    async def test_old_tasks_outside_window_excluded(self, client, db_session):
        """Tasks created before the analytics window are excluded."""
        now = utcnow()
        # Task older than 30 days (default window)
        await _seed_task(
            db_session,
            created_at=now - timedelta(days=60),
        )
        resp = await client.get("/api/stats/analytics?days=30")
        data = resp.json()
        assert data["summary"]["total_tasks"] == 0
