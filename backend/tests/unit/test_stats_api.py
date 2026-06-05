#!/usr/bin/env python3
"""Unit tests for Stats API endpoints."""

import os
import sys
import unittest
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from starlette.requests import Request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from fastapi.testclient import TestClient

from app.database import get_db
from app.dependencies.auth import require_authenticated_context
from app.dependencies.project_access import ProjectAccessScope, require_project_access_scope
from app.main import app


class StatsAPIValidationTests(unittest.TestCase):
    """Test /stats/analytics validation logic."""

    def setUp(self):
        self.mock_db = MagicMock()
        self.mock_db.execute = AsyncMock(return_value=MagicMock(scalar=MagicMock(return_value=0)))
        app.dependency_overrides[get_db] = lambda: self.mock_db

        # Override auth to return admin user
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

    def test_get_analytics_rejects_invalid_days(self):
        """GET /stats/analytics rejects days values other than 7, 30, 90."""
        # days=10 passes Pydantic validation (>=7 and <=90) but fails custom check
        response = self.client.get("/api/stats/analytics?days=10")
        self.assertEqual(response.status_code, 400)
        self.assertIn("days must be one of", response.json()["detail"])

    def test_get_analytics_rejects_invalid_days_string(self):
        """GET /stats/analytics rejects non-integer days."""
        response = self.client.get("/api/stats/analytics?days=abc")
        self.assertEqual(response.status_code, 422)  # Pydantic validation error


class StatsAPIHelpersTests(unittest.TestCase):
    """Test helper functions in stats module."""

    def test_categorize_error_message_timeout(self):
        """Error categorization: Timeout patterns."""
        from app.api.stats import _categorize_error_message

        result = _categorize_error_message("Task timeout deadline exceeded")
        self.assertEqual(result, "Timeout")

        result = _categorize_error_message("Execution timed out after 1800 seconds")
        self.assertEqual(result, "Timeout")

    def test_categorize_error_message_resource(self):
        """Error categorization: Resource patterns."""
        from app.api.stats import _categorize_error_message

        result = _categorize_error_message("Container out of memory")
        self.assertEqual(result, "Resource")

        result = _categorize_error_message("Disk quota exceeded")
        self.assertEqual(result, "Resource")

    def test_categorize_error_message_docker(self):
        """Error categorization: Docker patterns."""
        from app.api.stats import _categorize_error_message

        result = _categorize_error_message("docker container failed to start")
        self.assertEqual(result, "Docker")

        result = _categorize_error_message("OCI runtime error")
        self.assertEqual(result, "Docker")

    def test_categorize_error_message_auth(self):
        """Error categorization: Authentication patterns."""
        from app.api.stats import _categorize_error_message

        result = _categorize_error_message("GitLab unauthorized access")
        self.assertEqual(result, "Authentication")

        result = _categorize_error_message("Token expired permission denied")
        self.assertEqual(result, "Authentication")

    def test_categorize_error_message_network(self):
        """Error categorization: Network patterns."""
        from app.api.stats import _categorize_error_message

        result = _categorize_error_message("Connection refused to GitLab")
        self.assertEqual(result, "Network")

        result = _categorize_error_message("SSL certificate verify failed")
        self.assertEqual(result, "Network")

    def test_categorize_error_message_git(self):
        """Error categorization: Git patterns."""
        from app.api.stats import _categorize_error_message

        result = _categorize_error_message("Merge conflict in branch")
        self.assertEqual(result, "Git")

        result = _categorize_error_message("git push failed")
        self.assertEqual(result, "Git")

    def test_categorize_error_message_dependencies(self):
        """Error categorization: Dependencies patterns."""
        from app.api.stats import _categorize_error_message

        result = _categorize_error_message("ModuleNotFoundError: No module named 'requests'")
        self.assertEqual(result, "Dependencies")

        result = _categorize_error_message("pip install failed")
        self.assertEqual(result, "Dependencies")

    def test_categorize_error_message_tests(self):
        """Error categorization: Tests patterns."""
        from app.api.stats import _categorize_error_message

        result = _categorize_error_message("pytest test failed")
        self.assertEqual(result, "Tests")

        result = _categorize_error_message("AssertionError: expected 200 got 404")
        self.assertEqual(result, "Tests")

    def test_categorize_error_message_code(self):
        """Error categorization: Code patterns."""
        from app.api.stats import _categorize_error_message

        result = _categorize_error_message("SyntaxError: invalid syntax")
        self.assertEqual(result, "Code")

        result = _categorize_error_message("TypeError: unsupported operand type(s)")
        self.assertEqual(result, "Code")

    def test_categorize_error_message_other(self):
        """Error categorization: Unknown patterns."""
        from app.api.stats import _categorize_error_message

        result = _categorize_error_message("Something completely unexpected happened")
        self.assertEqual(result, "Other")

        result = _categorize_error_message(None)
        self.assertEqual(result, "Other")

    def test_summarize_error_message(self):
        """Test error message summarization."""
        from app.api.stats import _summarize_error_message

        # First 160 chars of first line
        long_message = "This is a very long error message that spans multiple lines\nSecond line here\nThird line here"
        result = _summarize_error_message(long_message)
        self.assertTrue(len(result) <= 160)
        self.assertEqual(result, "This is a very long error message that spans multiple lines")

    def test_summarize_error_message_empty(self):
        """Test summarization of empty/None messages."""
        from app.api.stats import _summarize_error_message

        result = _summarize_error_message(None)
        self.assertIsNone(result)

        result = _summarize_error_message("")
        self.assertIsNone(result)

        result = _summarize_error_message("   \n   \n   ")
        self.assertIsNone(result)


class StatsTimeWindowTests(unittest.TestCase):
    """Test the time-windowed fields (completed_24h, failed_cancelled_24h, running_long_30min) in GET /api/stats."""

    def _make_scalar_result(self, value):
        """Create a mock execute result whose .scalar() returns *value*."""
        result = MagicMock()
        result.scalar = MagicMock(return_value=value)
        return result

    def _build_side_effects(
        self,
        total=0,
        pending=0,
        queued=0,
        running=0,
        completed=0,
        failed=0,
        cancelled=0,
        completed_24h=0,
        failed_cancelled_24h=0,
        running_long_30min=0,
        issue_total=0,
        issue_open=0,
        issue_in_progress=0,
        issue_in_review=0,
        issue_closed=0,
    ):
        """Return a list of 15 mock results matching the db.execute call order in get_stats."""
        return [
            self._make_scalar_result(total),            # 1. total
            self._make_scalar_result(pending),           # 2. pending
            self._make_scalar_result(queued),            # 3. queued
            self._make_scalar_result(running),           # 4. running
            self._make_scalar_result(completed),         # 5. completed
            self._make_scalar_result(failed),            # 6. failed
            self._make_scalar_result(cancelled),         # 7. cancelled
            self._make_scalar_result(completed_24h),     # 8. completed_24h
            self._make_scalar_result(failed_cancelled_24h),  # 9. failed_cancelled_24h
            self._make_scalar_result(running_long_30min),    # 10. running_long_30min
            self._make_scalar_result(issue_total),           # 11. issue total
            self._make_scalar_result(issue_open),            # 12. issue open
            self._make_scalar_result(issue_in_progress),     # 13. issue in_progress
            self._make_scalar_result(issue_in_review),       # 14. issue in_review
            self._make_scalar_result(issue_closed),          # 15. issue closed
        ]

    def setUp(self):
        self.mock_db = MagicMock()
        self.mock_db.execute = AsyncMock(
            side_effect=self._build_side_effects()
        )
        app.dependency_overrides[get_db] = lambda: self.mock_db

        async def mock_auth_context(request: Request, auth_context=None):
            return SimpleNamespace(
                user=SimpleNamespace(id=1, username="admin", platform_role="platform_admin"),
                session=None,
                gitlab_access_token=None,
                gitlab_refresh_token=None,
            )

        app.dependency_overrides[require_authenticated_context] = mock_auth_context
        app.dependency_overrides[require_project_access_scope] = lambda: ProjectAccessScope(
            is_unrestricted=True,
            accessible_projects=[],
        )

        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()

    # ---- Test 1: keys are present ----
    def test_stats_includes_24h_fields(self):
        """GET /api/stats response includes completed_24h, failed_cancelled_24h, and running_long_30min keys."""
        response = self.client.get("/api/stats")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("completed_24h", data)
        self.assertIn("failed_cancelled_24h", data)
        self.assertIn("running_long_30min", data)

    # ---- Test 2: completed_24h value ----
    def test_stats_24h_completed_count(self):
        """GET /api/stats returns the correct completed_24h count from the database."""
        self.mock_db.execute = AsyncMock(
            side_effect=self._build_side_effects(
                total=50, completed=30, completed_24h=12,
            )
        )
        response = self.client.get("/api/stats")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["completed_24h"], 12)

    # ---- Test 3: failed_cancelled_24h value ----
    def test_stats_24h_failed_cancelled_count(self):
        """GET /api/stats returns the correct failed_cancelled_24h count from the database."""
        self.mock_db.execute = AsyncMock(
            side_effect=self._build_side_effects(
                total=100, failed=20, cancelled=5, failed_cancelled_24h=7,
            )
        )
        response = self.client.get("/api/stats")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["failed_cancelled_24h"], 7)

    # ---- Test 4: running_long_30min value ----
    def test_stats_running_long_30min(self):
        """GET /api/stats returns the correct running_long_30min count from the database."""
        self.mock_db.execute = AsyncMock(
            side_effect=self._build_side_effects(
                total=40, running=10, running_long_30min=3,
            )
        )
        response = self.client.get("/api/stats")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["running_long_30min"], 3)

    # ---- Test 5: zero when no matching tasks ----
    def test_stats_24h_fields_zero_when_empty(self):
        """All three time-windowed fields default to 0 when no matching tasks exist."""
        self.mock_db.execute = AsyncMock(
            side_effect=self._build_side_effects(
                total=0,
                completed_24h=0,
                failed_cancelled_24h=0,
                running_long_30min=0,
            )
        )
        response = self.client.get("/api/stats")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["completed_24h"], 0)
        self.assertEqual(data["failed_cancelled_24h"], 0)
        self.assertEqual(data["running_long_30min"], 0)


class ScheduledStatsTests(unittest.TestCase):
    """Tests for the GET /api/stats/scheduled endpoint."""

    def _build_summary_row(
        self,
        total=0,
        ready_now=0,
        next_24h=0,
        later=0,
        queued_count=0,
        running_count=0,
    ):
        """Create a mock Row-like object returned by summary_result.one()."""
        return SimpleNamespace(
            total=total,
            ready_now=ready_now,
            next_24h=next_24h,
            later=later,
            queued_count=queued_count,
            running_count=running_count,
        )

    def _build_hourly_rows(self, entries=None):
        """Create a list of mock Row-like objects for the hourly distribution query.

        Each entry is (hour_start_datetime, count).
        """
        if entries is None:
            entries = []
        return [
            SimpleNamespace(hour_start=hour_start, count=count)
            for hour_start, count in entries
        ]

    def _build_side_effects(self, summary_attrs=None, hourly_entries=None):
        """Return a list of two mock db.execute results for the scheduled stats endpoint.

        Call order:
          1. summary_result  → .one() returns named fields
          2. hourly_result   → .all() returns list of (hour_start, count) rows
        """
        summary_row = self._build_summary_row(**(summary_attrs or {}))
        summary_mock = MagicMock()
        summary_mock.one = MagicMock(return_value=summary_row)

        hourly_rows = self._build_hourly_rows(hourly_entries)
        hourly_mock = MagicMock()
        hourly_mock.all = MagicMock(return_value=hourly_rows)

        return [summary_mock, hourly_mock]

    def setUp(self):
        self.mock_db = MagicMock()
        self.mock_db.execute = AsyncMock(
            side_effect=self._build_side_effects()
        )
        app.dependency_overrides[get_db] = lambda: self.mock_db

        async def mock_auth_context(request: Request, auth_context=None):
            return SimpleNamespace(
                user=SimpleNamespace(id=1, username="admin", platform_role="platform_admin"),
                session=None,
                gitlab_access_token=None,
                gitlab_refresh_token=None,
            )

        app.dependency_overrides[require_authenticated_context] = mock_auth_context
        app.dependency_overrides[require_project_access_scope] = lambda: ProjectAccessScope(
            is_unrestricted=True,
            accessible_projects=[],
        )

        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()

    def test_scheduled_stats_returns_summary_fields(self):
        """GET /api/stats/scheduled response includes summary, hourly_distribution, and max_count keys."""
        response = self.client.get("/api/stats/scheduled")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("summary", data)
        self.assertIn("hourly_distribution", data)
        self.assertIn("max_count", data)

    def test_scheduled_stats_summary_has_required_fields(self):
        """The summary object has all required fields: total, ready_now, next_24h, later, queued_count, running_count, busiest_hour_count, busiest_hour_label."""
        self.mock_db.execute = AsyncMock(
            side_effect=self._build_side_effects(
                summary_attrs=dict(
                    total=145, ready_now=12, next_24h=89, later=44,
                    queued_count=5, running_count=2,
                ),
            )
        )
        response = self.client.get("/api/stats/scheduled")
        self.assertEqual(response.status_code, 200)
        summary = response.json()["summary"]
        expected_keys = {
            "total", "ready_now", "next_24h", "later",
            "queued_count", "running_count",
            "busiest_hour_count", "busiest_hour_label",
        }
        self.assertEqual(set(summary.keys()), expected_keys)
        # Verify values from the summary query match
        self.assertEqual(summary["total"], 145)
        self.assertEqual(summary["ready_now"], 12)
        self.assertEqual(summary["next_24h"], 89)
        self.assertEqual(summary["later"], 44)
        self.assertEqual(summary["queued_count"], 5)
        self.assertEqual(summary["running_count"], 2)

    def test_scheduled_stats_hourly_distribution_has_24_items(self):
        """hourly_distribution array has exactly 24 items (one per hour bucket)."""
        response = self.client.get("/api/stats/scheduled")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(len(data["hourly_distribution"]), 24)

    def test_scheduled_stats_hourly_items_have_correct_shape(self):
        """Each item in hourly_distribution has 'hour_start' (string) and 'count' (int) keys."""
        response = self.client.get("/api/stats/scheduled")
        self.assertEqual(response.status_code, 200)
        for item in response.json()["hourly_distribution"]:
            self.assertIn("hour_start", item)
            self.assertIn("count", item)
            self.assertIsInstance(item["hour_start"], str)
            self.assertIsInstance(item["count"], int)

    def test_scheduled_stats_max_count_matches_distribution(self):
        """max_count equals the largest count in hourly_distribution."""
        now = datetime.now(UTC).replace(tzinfo=None)
        now_hour = now.replace(minute=0, second=0, microsecond=0)
        # Simulate some tasks in two hourly buckets
        hourly_entries = [
            (now_hour + timedelta(hours=1), 5),
            (now_hour + timedelta(hours=3), 18),
        ]
        self.mock_db.execute = AsyncMock(
            side_effect=self._build_side_effects(
                summary_attrs=dict(total=23, ready_now=0, next_24h=23, later=0,
                                   queued_count=0, running_count=0),
                hourly_entries=hourly_entries,
            )
        )
        response = self.client.get("/api/stats/scheduled")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["max_count"], 18)
        # Verify the busiest hour in summary
        self.assertEqual(data["summary"]["busiest_hour_count"], 18)

    def test_scheduled_stats_empty_db_returns_zero_counts(self):
        """With no scheduled tasks, all summary counts are 0 and hourly_distribution is all zeros."""
        self.mock_db.execute = AsyncMock(
            side_effect=self._build_side_effects(
                summary_attrs=dict(total=0, ready_now=0, next_24h=0, later=0,
                                   queued_count=0, running_count=0),
                hourly_entries=[],
            )
        )
        response = self.client.get("/api/stats/scheduled")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertEqual(data["summary"]["total"], 0)
        self.assertEqual(data["max_count"], 0)
        self.assertTrue(all(item["count"] == 0 for item in data["hourly_distribution"]))

    def test_scheduled_stats_accepts_project_id(self):
        """GET /api/stats/scheduled?project_id=42 returns 200 with valid response."""
        self.mock_db.execute = AsyncMock(
            side_effect=self._build_side_effects()
        )
        response = self.client.get("/api/stats/scheduled?project_id=42")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("summary", data)
        self.assertEqual(len(data["hourly_distribution"]), 24)

    def test_scheduled_stats_includes_slot_capacity(self):
        """GET /api/stats/scheduled response includes slot_max_tasks and slot_max_tasks_enforce."""
        self.mock_db.execute = AsyncMock(
            side_effect=self._build_side_effects()
        )
        response = self.client.get("/api/stats/scheduled")
        self.assertEqual(response.status_code, 200)
        data = response.json()
        self.assertIn("slot_max_tasks", data)
        self.assertIn("slot_max_tasks_enforce", data)
        self.assertIsInstance(data["slot_max_tasks"], int)
        self.assertIsInstance(data["slot_max_tasks_enforce"], bool)


class ScheduledTasksHourFilterTests(unittest.TestCase):
    """Tests for the hour_start query parameter on GET /api/tasks/scheduled."""

    def setUp(self):
        self.mock_db = MagicMock()
        # Default: db.execute returns result.scalars().all() → empty list
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        self.mock_db.execute = AsyncMock(return_value=mock_result)

        app.dependency_overrides[get_db] = lambda: self.mock_db

        async def mock_auth_context(request: Request, auth_context=None):
            return SimpleNamespace(
                user=SimpleNamespace(id=1, username="admin", platform_role="platform_admin"),
                session=None,
                gitlab_access_token=None,
                gitlab_refresh_token=None,
            )

        app.dependency_overrides[require_authenticated_context] = mock_auth_context
        app.dependency_overrides[require_project_access_scope] = lambda: ProjectAccessScope(
            is_unrestricted=True,
            accessible_projects=[],
        )

        self.client = TestClient(app)

    def tearDown(self):
        app.dependency_overrides.clear()

    @patch("app.api.tasks.build_project_lookup", new_callable=AsyncMock, return_value={})
    def test_scheduled_tasks_with_hour_start_returns_200(self, _mock_lookup):
        """GET /api/tasks/scheduled?hour_start=<valid ISO> returns 200."""
        response = self.client.get("/api/tasks/scheduled?hour_start=2024-12-25T15:00:00")
        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(response.json(), list)

    @patch("app.api.tasks.build_project_lookup", new_callable=AsyncMock, return_value={})
    def test_scheduled_tasks_invalid_hour_start_returns_400(self, _mock_lookup):
        """GET /api/tasks/scheduled?hour_start=not-a-date returns 400."""
        response = self.client.get("/api/tasks/scheduled?hour_start=not-a-date")
        self.assertEqual(response.status_code, 400)
        self.assertIn("Invalid hour_start format", response.json()["detail"])

    @patch("app.api.tasks.build_project_lookup", new_callable=AsyncMock, return_value={})
    def test_scheduled_tasks_without_hour_start_returns_200(self, _mock_lookup):
        """GET /api/tasks/scheduled without hour_start still returns 200 (parameter is optional)."""
        response = self.client.get("/api/tasks/scheduled")
        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(response.json(), list)

    @patch("app.api.tasks.build_project_lookup", new_callable=AsyncMock, return_value={})
    def test_scheduled_tasks_hour_start_with_timezone_returns_200(self, _mock_lookup):
        """GET /api/tasks/scheduled?hour_start=<ISO with Z> returns 200 (timezone stripped)."""
        response = self.client.get("/api/tasks/scheduled?hour_start=2024-12-25T15:00:00Z")
        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(response.json(), list)

    @patch("app.api.tasks.build_project_lookup", new_callable=AsyncMock, return_value={})
    def test_scheduled_tasks_hour_start_empty_string_returns_200(self, _mock_lookup):
        """GET /api/tasks/scheduled?hour_start= (empty) is treated as no filter → 200."""
        response = self.client.get("/api/tasks/scheduled?hour_start=")
        self.assertEqual(response.status_code, 200)
        self.assertIsInstance(response.json(), list)
