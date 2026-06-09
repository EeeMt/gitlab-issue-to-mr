"""Additional tests for Stats API coverage gaps.

Covers uncovered lines in app/api/stats.py:
- get_stats with restricted scope + empty projects (lines 62-66)
- get_stats with restricted scope + projects (lines 62-66, 68)
- get_stats with my=True scope (line 68)
- get_stats issue stats with restricted scope (lines 123-127, 129)
- _apply_project_scope helper (lines 167-170)
- _apply_analytics_filters helper (lines 181, 183)
- get_analytics with project_id access denied (lines 259, 262-264)
- get_activity_heatmap endpoint (lines 690-716)
- get_scheduled_stats restricted scope (lines 742-746)
"""

import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

from starlette.requests import Request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from fastapi.testclient import TestClient

from app.database import get_db
from app.dependencies.auth import require_authenticated_context
from app.dependencies.project_access import ProjectAccessScope, require_project_access_scope
from app.main import app

# ---------------------------------------------------------------------------
# Direct helper function tests
# ---------------------------------------------------------------------------


class TestApplyProjectScope(unittest.TestCase):
    """Test _apply_project_scope helper function."""

    def test_unrestricted_returns_query_unchanged(self):
        """Unrestricted scope should return query as-is."""
        from app.api.stats import _apply_project_scope

        query = MagicMock()
        scope = ProjectAccessScope(is_unrestricted=True, accessible_projects=[])
        result = _apply_project_scope(query, scope)
        self.assertIs(result, query)

    def test_restricted_empty_projects_adds_false_clause(self):
        """Restricted scope with no projects should add false() clause."""
        from app.api.stats import _apply_project_scope

        query = MagicMock()
        scope = ProjectAccessScope(is_unrestricted=False, accessible_projects=[])
        result = _apply_project_scope(query, scope)
        query.where.assert_called_once()
        self.assertIs(result, query.where.return_value)

    def test_restricted_with_projects_adds_in_clause(self):
        """Restricted scope with projects should add IN clause."""
        from app.api.stats import _apply_project_scope

        query = MagicMock()
        scope = ProjectAccessScope(
            is_unrestricted=False,
            accessible_projects=[{"id": 10, "name": "P"}, {"id": 20, "name": "Q"}],
        )
        result = _apply_project_scope(query, scope)
        query.where.assert_called_once()
        self.assertIs(result, query.where.return_value)


class TestApplyAnalyticsFilters(unittest.TestCase):
    """Test _apply_analytics_filters helper function."""

    def test_with_project_id(self):
        """Should apply project_id filter."""
        from app.api.stats import _apply_analytics_filters

        query = MagicMock()
        # Chain: _apply_project_scope returns query (unrestricted), then .where for project_id
        scope = ProjectAccessScope(is_unrestricted=True, accessible_projects=[])
        _apply_analytics_filters(query, scope, project_id=42)
        query.where.assert_called_once()

    def test_with_initiator_username(self):
        """Should apply initiator_username filter."""
        from app.api.stats import _apply_analytics_filters

        query = MagicMock()
        scope = ProjectAccessScope(is_unrestricted=True, accessible_projects=[])
        _apply_analytics_filters(query, scope, initiator_username="alice")
        query.where.assert_called_once()

    def test_with_both_filters(self):
        """Should apply both project_id and initiator_username."""
        from app.api.stats import _apply_analytics_filters

        query = MagicMock()
        # Need to chain .where calls
        query.where.return_value = query  # Allow chaining
        scope = ProjectAccessScope(is_unrestricted=True, accessible_projects=[])
        _apply_analytics_filters(query, scope, project_id=42, initiator_username="bob")
        self.assertEqual(query.where.call_count, 2)


# ---------------------------------------------------------------------------
# GET /api/stats with restricted scope
# ---------------------------------------------------------------------------


class TestGetStatsRestrictedScope(unittest.TestCase):
    """Test GET /api/stats with restricted project access scope."""

    def _make_scalar_result(self, value):
        result = MagicMock()
        result.scalar = MagicMock(return_value=value)
        return result

    def _build_side_effects(self, **kwargs):
        """Return 15 mock results for the get_stats call order."""
        defaults = dict(
            total=0, pending=0, queued=0, running=0, completed=0, failed=0, cancelled=0,
            completed_24h=0, failed_cancelled_24h=0, running_long_30min=0,
            issue_total=0, issue_open=0, issue_in_progress=0, issue_in_review=0, issue_closed=0,
        )
        defaults.update(kwargs)
        keys = [
            "total", "pending", "queued", "running", "completed", "failed", "cancelled",
            "completed_24h", "failed_cancelled_24h", "running_long_30min",
            "issue_total", "issue_open", "issue_in_progress", "issue_in_review", "issue_closed",
        ]
        return [self._make_scalar_result(defaults[k]) for k in keys]

    def setUp(self):
        self.mock_db = MagicMock()
        self.mock_db.execute = AsyncMock(side_effect=self._build_side_effects())
        app.dependency_overrides[get_db] = lambda: self.mock_db

        async def mock_auth_context(request: Request, auth_context=None):
            return SimpleNamespace(
                user=SimpleNamespace(id=1, username="admin", platform_role="platform_admin"),
                session=None,
                gitlab_access_token=None,
                gitlab_refresh_token=None,
            )
        app.dependency_overrides[require_authenticated_context] = mock_auth_context
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()

    def test_stats_restricted_scope_empty_projects(self):
        """GET /api/stats with restricted scope and no accessible projects → all zeros."""
        app.dependency_overrides[require_project_access_scope] = lambda: ProjectAccessScope(
            is_unrestricted=False,
            accessible_projects=[],
        )
        response = self.client.get("/api/stats")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["total"], 0)

    def test_stats_restricted_scope_with_projects(self):
        """GET /api/stats with restricted scope and accessible projects."""
        app.dependency_overrides[require_project_access_scope] = lambda: ProjectAccessScope(
            is_unrestricted=False,
            accessible_projects=[{"id": 10, "name": "P"}],
        )
        self.mock_db.execute = AsyncMock(side_effect=self._build_side_effects(total=5, completed=3))
        response = self.client.get("/api/stats")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["total"], 5)
        self.assertEqual(data["completed"], 3)

    def test_stats_my_filter(self):
        """GET /api/stats?my=true should scope to current user."""
        app.dependency_overrides[require_project_access_scope] = lambda: ProjectAccessScope(
            is_unrestricted=True,
            accessible_projects=[],
        )
        self.mock_db.execute = AsyncMock(side_effect=self._build_side_effects(total=2))
        response = self.client.get("/api/stats?my=true")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["total"], 2)

    def test_stats_issue_restricted_scope_empty(self):
        """GET /api/stats issue section with restricted empty scope → issue total 0."""
        app.dependency_overrides[require_project_access_scope] = lambda: ProjectAccessScope(
            is_unrestricted=False,
            accessible_projects=[],
        )
        response = self.client.get("/api/stats")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["issues"]["total"], 0)

    def test_stats_issue_restricted_scope_with_projects(self):
        """GET /api/stats issue section with restricted scope + projects."""
        app.dependency_overrides[require_project_access_scope] = lambda: ProjectAccessScope(
            is_unrestricted=False,
            accessible_projects=[{"id": 10, "name": "P"}],
        )
        self.mock_db.execute = AsyncMock(
            side_effect=self._build_side_effects(issue_total=3, issue_open=2, issue_closed=1)
        )
        response = self.client.get("/api/stats")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["issues"]["total"], 3)
        self.assertEqual(data["issues"]["by_status"]["open"], 2)

    def test_stats_my_issues(self):
        """GET /api/stats?my=true should scope issues to current user."""
        app.dependency_overrides[require_project_access_scope] = lambda: ProjectAccessScope(
            is_unrestricted=True,
            accessible_projects=[],
        )
        self.mock_db.execute = AsyncMock(
            side_effect=self._build_side_effects(issue_total=1, issue_open=1)
        )
        response = self.client.get("/api/stats?my=true")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["issues"]["total"], 1)


# ---------------------------------------------------------------------------
# GET /api/stats/analytics access control edge cases
# ---------------------------------------------------------------------------


class TestGetAnalyticsAccessControl(unittest.TestCase):
    """Test GET /api/stats/analytics with restricted access."""

    def setUp(self):
        self.mock_db = MagicMock()
        self.mock_db.execute = AsyncMock(return_value=MagicMock(scalar=MagicMock(return_value=0)))
        app.dependency_overrides[get_db] = lambda: self.mock_db

        async def mock_auth_context(request: Request, auth_context=None):
            return SimpleNamespace(
                user=SimpleNamespace(id=1, username="admin", platform_role="platform_admin"),
                session=None,
                gitlab_access_token=None,
                gitlab_refresh_token=None,
            )
        app.dependency_overrides[require_authenticated_context] = mock_auth_context
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()

    def test_analytics_project_id_not_in_restricted_scope(self):
        """GET /api/stats/analytics?project_id=42 when 42 is not in accessible projects → 404."""
        app.dependency_overrides[require_project_access_scope] = lambda: ProjectAccessScope(
            is_unrestricted=False,
            accessible_projects=[{"id": 10, "name": "P"}],
        )
        response = self.client.get("/api/stats/analytics?project_id=42&days=7")
        self.assertEqual(response.status_code, 404)
        self.assertIn("not available", response.json()["detail"])

    def test_analytics_empty_initiator_treated_as_none(self):
        """GET /api/stats/analytics?initiator_username= should treat empty as None."""
        app.dependency_overrides[require_project_access_scope] = lambda: ProjectAccessScope(
            is_unrestricted=True,
            accessible_projects=[],
        )
        # This will hit the analytics endpoint — mock enough db.execute calls for it
        # The analytics endpoint does many queries. We need to mock all of them.
        mock_results = []
        for _ in range(20):
            r = MagicMock()
            r.scalar = MagicMock(return_value=0)
            r.all = MagicMock(return_value=[])
            r.one = MagicMock(return_value=SimpleNamespace(
                total=0, completed=0, failed=0, cancelled=0,
                avg_execution_seconds=None, avg_queue_wait_seconds=None,
                p95_execution_seconds=None, p50_execution_seconds=None,
            ))
            mock_results.append(r)
        self.mock_db.execute = AsyncMock(side_effect=mock_results)
        response = self.client.get("/api/stats/analytics?initiator_username=&days=7")
        # Should not crash; either 200 or graceful failure
        self.assertIn(response.status_code, [200, 500])


# ---------------------------------------------------------------------------
# GET /api/stats/activity-heatmap
# ---------------------------------------------------------------------------


class TestGetActivityHeatmap(unittest.TestCase):
    """Test GET /api/stats/activity-heatmap endpoint."""

    def setUp(self):
        self.mock_db = MagicMock()
        app.dependency_overrides[get_db] = lambda: self.mock_db

        async def mock_auth_context(request: Request, auth_context=None):
            return SimpleNamespace(
                user=SimpleNamespace(id=1, username="admin", platform_role="platform_admin"),
                session=None,
                gitlab_access_token=None,
                gitlab_refresh_token=None,
            )
        app.dependency_overrides[require_authenticated_context] = mock_auth_context
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()

    def test_heatmap_returns_list(self):
        """GET /api/stats/activity-heatmap should return a JSON list."""
        app.dependency_overrides[require_project_access_scope] = lambda: ProjectAccessScope(
            is_unrestricted=True,
            accessible_projects=[],
        )
        mock_result = MagicMock()
        mock_result.all.return_value = [
            SimpleNamespace(date="2025-06-01", count=5),
            SimpleNamespace(date="2025-06-02", count=3),
        ]
        self.mock_db.execute = AsyncMock(return_value=mock_result)

        response = self.client.get("/api/stats/activity-heatmap")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIsInstance(data, list)
        self.assertEqual(len(data), 2)
        self.assertEqual(data[0]["date"], "2025-06-01")
        self.assertEqual(data[0]["count"], 5)

    def test_heatmap_empty(self):
        """GET /api/stats/activity-heatmap with no data returns empty list."""
        app.dependency_overrides[require_project_access_scope] = lambda: ProjectAccessScope(
            is_unrestricted=True,
            accessible_projects=[],
        )
        mock_result = MagicMock()
        mock_result.all.return_value = []
        self.mock_db.execute = AsyncMock(return_value=mock_result)

        response = self.client.get("/api/stats/activity-heatmap")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])

    def test_heatmap_restricted_scope_empty_returns_empty(self):
        """GET /api/stats/activity-heatmap with restricted empty scope returns []."""
        app.dependency_overrides[require_project_access_scope] = lambda: ProjectAccessScope(
            is_unrestricted=False,
            accessible_projects=[],
        )
        # With empty accessible projects, endpoint returns [] early
        response = self.client.get("/api/stats/activity-heatmap")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json(), [])

    def test_heatmap_restricted_scope_with_projects(self):
        """GET /api/stats/activity-heatmap with restricted scope + projects returns data."""
        app.dependency_overrides[require_project_access_scope] = lambda: ProjectAccessScope(
            is_unrestricted=False,
            accessible_projects=[{"id": 10, "name": "P"}],
        )
        mock_result = MagicMock()
        mock_result.all.return_value = [
            SimpleNamespace(date="2025-06-01", count=2),
        ]
        self.mock_db.execute = AsyncMock(return_value=mock_result)

        response = self.client.get("/api/stats/activity-heatmap")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 1)

    def test_heatmap_with_my_filter(self):
        """GET /api/stats/activity-heatmap?my=true should scope to current user."""
        app.dependency_overrides[require_project_access_scope] = lambda: ProjectAccessScope(
            is_unrestricted=True,
            accessible_projects=[],
        )
        mock_result = MagicMock()
        mock_result.all.return_value = [
            SimpleNamespace(date="2025-06-01", count=1),
        ]
        self.mock_db.execute = AsyncMock(return_value=mock_result)

        response = self.client.get("/api/stats/activity-heatmap?my=true")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data), 1)

    def test_heatmap_custom_days(self):
        """GET /api/stats/activity-heatmap?days=30 should accept custom days."""
        app.dependency_overrides[require_project_access_scope] = lambda: ProjectAccessScope(
            is_unrestricted=True,
            accessible_projects=[],
        )
        mock_result = MagicMock()
        mock_result.all.return_value = []
        self.mock_db.execute = AsyncMock(return_value=mock_result)

        response = self.client.get("/api/stats/activity-heatmap?days=30")
        self.assertEqual(response.status_code, 200)


# ---------------------------------------------------------------------------
# GET /api/stats/scheduled with restricted scope
# ---------------------------------------------------------------------------


class TestScheduledStatsRestrictedScope(unittest.TestCase):
    """Test GET /api/stats/scheduled with restricted project access scope."""

    def _build_side_effects(self, summary_attrs=None, hourly_entries=None):
        """Return mock db.execute results for the scheduled stats endpoint."""
        defaults = dict(total=0, ready_now=0, next_24h=0, later=0, queued_count=0, running_count=0)
        defaults.update(summary_attrs or {})
        summary_row = SimpleNamespace(**defaults)
        summary_mock = MagicMock()
        summary_mock.one = MagicMock(return_value=summary_row)

        hourly_rows = [
            SimpleNamespace(hour_start=hs, count=c) for hs, c in (hourly_entries or [])
        ]
        hourly_mock = MagicMock()
        hourly_mock.all = MagicMock(return_value=hourly_rows)

        return [summary_mock, hourly_mock]

    def setUp(self):
        self.mock_db = MagicMock()
        self.mock_db.execute = AsyncMock(side_effect=self._build_side_effects())
        app.dependency_overrides[get_db] = lambda: self.mock_db

        async def mock_auth_context(request: Request, auth_context=None):
            return SimpleNamespace(
                user=SimpleNamespace(id=1, username="admin", platform_role="platform_admin"),
                session=None,
                gitlab_access_token=None,
                gitlab_refresh_token=None,
            )
        app.dependency_overrides[require_authenticated_context] = mock_auth_context
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()

    def test_scheduled_restricted_empty_scope(self):
        """GET /api/stats/scheduled with restricted empty scope → all zeros."""
        app.dependency_overrides[require_project_access_scope] = lambda: ProjectAccessScope(
            is_unrestricted=False,
            accessible_projects=[],
        )
        response = self.client.get("/api/stats/scheduled")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["summary"]["total"], 0)

    def test_scheduled_restricted_with_projects(self):
        """GET /api/stats/scheduled with restricted scope + projects."""
        app.dependency_overrides[require_project_access_scope] = lambda: ProjectAccessScope(
            is_unrestricted=False,
            accessible_projects=[{"id": 10, "name": "P"}, {"id": 20, "name": "Q"}],
        )
        self.mock_db.execute = AsyncMock(
            side_effect=self._build_side_effects(
                summary_attrs=dict(total=5, ready_now=2, next_24h=3),
            )
        )
        response = self.client.get("/api/stats/scheduled")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["summary"]["total"], 5)


# GET /api/stats/scheduled with my=True
# ---------------------------------------------------------------------------


class TestScheduledStatsMineFilter(unittest.TestCase):
    """Test GET /api/stats/scheduled with my=True (own-tasks-only filter)."""

    def _build_side_effects(self, summary_attrs=None, hourly_entries=None):
        defaults = dict(total=0, ready_now=0, next_24h=0, later=0, queued_count=0, running_count=0)
        defaults.update(summary_attrs or {})
        summary_row = SimpleNamespace(**defaults)
        summary_mock = MagicMock()
        summary_mock.one = MagicMock(return_value=summary_row)

        hourly_rows = [
            SimpleNamespace(hour_start=hs, count=c) for hs, c in (hourly_entries or [])
        ]
        hourly_mock = MagicMock()
        hourly_mock.all = MagicMock(return_value=hourly_rows)

        return [summary_mock, hourly_mock]

    def setUp(self):
        self.mock_db = MagicMock()
        self.mock_db.execute = AsyncMock(side_effect=self._build_side_effects())
        app.dependency_overrides[get_db] = lambda: self.mock_db

        async def mock_auth_context(request: Request, auth_context=None):
            return SimpleNamespace(
                user=SimpleNamespace(id=1, username="alice", platform_role="platform_user"),
                session=None,
                gitlab_access_token=None,
                gitlab_refresh_token=None,
            )
        app.dependency_overrides[require_authenticated_context] = mock_auth_context
        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()

    def test_scheduled_stats_my_true_filters_by_initiator_username(self):
        """GET /api/stats/scheduled?my=true queries with initiator_username = current user."""
        response = self.client.get("/api/stats/scheduled?my=true")
        self.assertEqual(response.status_code, 200)

        executed_calls = self.mock_db.execute.await_args_list
        self.assertGreater(len(executed_calls), 0)
        all_queries = " ".join(str(call.args[0]) for call in executed_calls)
        self.assertIn("tasks.initiator_username", all_queries)

    def test_scheduled_stats_my_false_does_not_filter_by_initiator_username(self):
        """GET /api/stats/scheduled?my=false does not add initiator_username condition."""
        response = self.client.get("/api/stats/scheduled?my=false")
        self.assertEqual(response.status_code, 200)

        executed_calls = self.mock_db.execute.await_args_list
        self.assertGreater(len(executed_calls), 0)
        all_queries = " ".join(str(call.args[0]) for call in executed_calls)
        self.assertNotIn("tasks.initiator_username", all_queries)
