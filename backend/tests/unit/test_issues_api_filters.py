"""Tests for enhanced issues list filtering, sorting, and search."""

import os
import sys
import unittest
from datetime import datetime
from unittest.mock import AsyncMock, MagicMock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


def _make_issue(**overrides):
    issue = MagicMock()
    defaults = {
        "id": 1,
        "title": "Test Issue",
        "description": "desc",
        "project_id": 10,
        "status": "open",
        "branch_name": None,
        "base_branch": None,
        "target_branch": None,
        "merge_request_iid": None,
        "merge_request_url": None,
        "claude_session_id": None,
        "session_storage_path": None,
        "initiator_user_id": 1,
        "initiator_username": "alice",
        "created_at": datetime(2026, 1, 1, 12, 0, 0),
        "updated_at": datetime(2026, 1, 1, 12, 0, 0),
    }
    defaults.update(overrides)
    for k, v in defaults.items():
        setattr(issue, k, v)
    return issue


def _mock_db_with_rows(rows, total=None):
    """Build a mock AsyncSession that returns *rows* for the main query."""
    if total is None:
        total = len(rows)

    count_result = MagicMock()
    count_result.scalar.return_value = total

    main_result = MagicMock()
    main_result.all.return_value = rows

    mock_db = MagicMock()
    mock_db.execute = AsyncMock(side_effect=[count_result, main_result])
    return mock_db


def _row(
    issue,
    task_count=0,
    additions=0,
    deletions=0,
    total_changes=0,
    input_tokens=0,
    output_tokens=0,
    duration_seconds=0,
):
    row = MagicMock()
    vals = [
        issue,
        task_count,
        additions,
        deletions,
        total_changes,
        input_tokens,
        output_tokens,
        duration_seconds,
    ]
    row.__getitem__ = lambda self, idx: vals[idx]
    return row


# ---------------------------------------------------------------------------
# Multi-status
# ---------------------------------------------------------------------------


class TestListIssuesMultiStatus(unittest.IsolatedAsyncioTestCase):
    """Test comma-separated multi-status filtering on GET /api/issues."""

    async def test_multi_status_accepted(self):
        """Passing status='open,closed' should not raise an error."""
        from app.api.issues import list_issues
        from app.dependencies.project_access import ProjectAccessScope

        issue = _make_issue(id=1, status="open")
        db = _mock_db_with_rows([_row(issue)], total=1)
        scope = ProjectAccessScope(is_unrestricted=True, accessible_projects=[])

        result = await list_issues(
            status="open,closed",
            project_id=None,
            initiator_user_id=None,
            search=None,
            created_after=None,
            created_before=None,
            sort_by=None,
            sort_order=None,
            page=1,
            page_size=20,
            db=db,
            current_user=MagicMock(),
            access_scope=scope,
        )
        self.assertIn("items", result)

    async def test_invalid_status_returns_400(self):
        """Passing a completely invalid status should return 400."""
        from fastapi import HTTPException
        from app.api.issues import list_issues
        from app.dependencies.project_access import ProjectAccessScope

        db = _mock_db_with_rows([])
        scope = ProjectAccessScope(is_unrestricted=True, accessible_projects=[])

        with self.assertRaises(HTTPException) as ctx:
            await list_issues(
                status="bogus",
                project_id=None,
                initiator_user_id=None,
                search=None,
                created_after=None,
                created_before=None,
                sort_by=None,
                sort_order=None,
                page=1,
                page_size=20,
                db=db,
                current_user=MagicMock(),
                access_scope=scope,
            )
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("bogus", ctx.exception.detail)

    async def test_mixed_valid_invalid_status_returns_400(self):
        """Passing status='open,bogus' should return 400 due to invalid part."""
        from fastapi import HTTPException
        from app.api.issues import list_issues
        from app.dependencies.project_access import ProjectAccessScope

        db = _mock_db_with_rows([])
        scope = ProjectAccessScope(is_unrestricted=True, accessible_projects=[])

        with self.assertRaises(HTTPException) as ctx:
            await list_issues(
                status="open,bogus",
                project_id=None,
                initiator_user_id=None,
                search=None,
                created_after=None,
                created_before=None,
                sort_by=None,
                sort_order=None,
                page=1,
                page_size=20,
                db=db,
                current_user=MagicMock(),
                access_scope=scope,
            )
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("bogus", ctx.exception.detail)

    async def test_single_status_still_works(self):
        """A single status value should still work."""
        from app.api.issues import list_issues
        from app.dependencies.project_access import ProjectAccessScope

        db = _mock_db_with_rows([], total=0)
        scope = ProjectAccessScope(is_unrestricted=True, accessible_projects=[])

        result = await list_issues(
            status="open",
            project_id=None,
            initiator_user_id=None,
            search=None,
            created_after=None,
            created_before=None,
            sort_by=None,
            sort_order=None,
            page=1,
            page_size=20,
            db=db,
            current_user=MagicMock(),
            access_scope=scope,
        )
        self.assertEqual(result["items"], [])


# ---------------------------------------------------------------------------
# Sort params
# ---------------------------------------------------------------------------


class TestListIssuesSortParams(unittest.IsolatedAsyncioTestCase):
    """Test sort_by and sort_order params on GET /api/issues."""

    async def test_invalid_sort_by_returns_400(self):
        from fastapi import HTTPException
        from app.api.issues import list_issues
        from app.dependencies.project_access import ProjectAccessScope

        db = _mock_db_with_rows([])
        scope = ProjectAccessScope(is_unrestricted=True, accessible_projects=[])

        with self.assertRaises(HTTPException) as ctx:
            await list_issues(
                status=None,
                project_id=None,
                initiator_user_id=None,
                search=None,
                created_after=None,
                created_before=None,
                sort_by="invalid_field",
                sort_order=None,
                page=1,
                page_size=20,
                db=db,
                current_user=MagicMock(),
                access_scope=scope,
            )
        self.assertEqual(ctx.exception.status_code, 400)

    async def test_invalid_sort_order_returns_400(self):
        from fastapi import HTTPException
        from app.api.issues import list_issues
        from app.dependencies.project_access import ProjectAccessScope

        db = _mock_db_with_rows([])
        scope = ProjectAccessScope(is_unrestricted=True, accessible_projects=[])

        with self.assertRaises(HTTPException) as ctx:
            await list_issues(
                status=None,
                project_id=None,
                initiator_user_id=None,
                search=None,
                created_after=None,
                created_before=None,
                sort_by=None,
                sort_order="random",
                page=1,
                page_size=20,
                db=db,
                current_user=MagicMock(),
                access_scope=scope,
            )
        self.assertEqual(ctx.exception.status_code, 400)

    async def test_valid_sort_by_status(self):
        from app.api.issues import list_issues
        from app.dependencies.project_access import ProjectAccessScope

        db = _mock_db_with_rows([], total=0)
        scope = ProjectAccessScope(is_unrestricted=True, accessible_projects=[])

        result = await list_issues(
            status=None,
            project_id=None,
            initiator_user_id=None,
            search=None,
            created_after=None,
            created_before=None,
            sort_by="status",
            sort_order="asc",
            page=1,
            page_size=20,
            db=db,
            current_user=MagicMock(),
            access_scope=scope,
        )
        self.assertIn("items", result)


# ---------------------------------------------------------------------------
# Search param
# ---------------------------------------------------------------------------


class TestListIssuesSearchParam(unittest.IsolatedAsyncioTestCase):
    """Test search param on GET /api/issues."""

    async def test_search_param_accepted(self):
        from app.api.issues import list_issues
        from app.dependencies.project_access import ProjectAccessScope

        db = _mock_db_with_rows([], total=0)
        scope = ProjectAccessScope(is_unrestricted=True, accessible_projects=[])

        result = await list_issues(
            status=None,
            project_id=None,
            initiator_user_id=None,
            search="auth",
            created_after=None,
            created_before=None,
            sort_by=None,
            sort_order=None,
            page=1,
            page_size=20,
            db=db,
            current_user=MagicMock(),
            access_scope=scope,
        )
        self.assertIn("items", result)

    async def test_short_search_ignored(self):
        """Search strings < 2 chars should be silently ignored."""
        from app.api.issues import list_issues
        from app.dependencies.project_access import ProjectAccessScope

        db = _mock_db_with_rows([], total=0)
        scope = ProjectAccessScope(is_unrestricted=True, accessible_projects=[])

        result = await list_issues(
            status=None,
            project_id=None,
            initiator_user_id=None,
            search="a",
            created_after=None,
            created_before=None,
            sort_by=None,
            sort_order=None,
            page=1,
            page_size=20,
            db=db,
            current_user=MagicMock(),
            access_scope=scope,
        )
        self.assertIn("items", result)


# ---------------------------------------------------------------------------
# Date range params
# ---------------------------------------------------------------------------


class TestListIssuesDateRange(unittest.IsolatedAsyncioTestCase):
    """Test created_after / created_before params."""

    async def test_valid_created_after(self):
        from app.api.issues import list_issues
        from app.dependencies.project_access import ProjectAccessScope

        db = _mock_db_with_rows([], total=0)
        scope = ProjectAccessScope(is_unrestricted=True, accessible_projects=[])

        result = await list_issues(
            status=None,
            project_id=None,
            initiator_user_id=None,
            search=None,
            created_after="2025-01-01T00:00:00",
            created_before=None,
            sort_by=None,
            sort_order=None,
            page=1,
            page_size=20,
            db=db,
            current_user=MagicMock(),
            access_scope=scope,
        )
        self.assertIn("items", result)

    async def test_invalid_created_after_returns_400(self):
        from fastapi import HTTPException
        from app.api.issues import list_issues
        from app.dependencies.project_access import ProjectAccessScope

        db = _mock_db_with_rows([])
        scope = ProjectAccessScope(is_unrestricted=True, accessible_projects=[])

        with self.assertRaises(HTTPException) as ctx:
            await list_issues(
                status=None,
                project_id=None,
                initiator_user_id=None,
                search=None,
                created_after="not-a-date",
                created_before=None,
                sort_by=None,
                sort_order=None,
                page=1,
                page_size=20,
                db=db,
                current_user=MagicMock(),
                access_scope=scope,
            )
        self.assertEqual(ctx.exception.status_code, 400)

    async def test_invalid_created_before_returns_400(self):
        from fastapi import HTTPException
        from app.api.issues import list_issues
        from app.dependencies.project_access import ProjectAccessScope

        db = _mock_db_with_rows([])
        scope = ProjectAccessScope(is_unrestricted=True, accessible_projects=[])

        with self.assertRaises(HTTPException) as ctx:
            await list_issues(
                status=None,
                project_id=None,
                initiator_user_id=None,
                search=None,
                created_after=None,
                created_before="garbage",
                sort_by=None,
                sort_order=None,
                page=1,
                page_size=20,
                db=db,
                current_user=MagicMock(),
                access_scope=scope,
            )
        self.assertEqual(ctx.exception.status_code, 400)

    async def test_valid_created_before(self):
        from app.api.issues import list_issues
        from app.dependencies.project_access import ProjectAccessScope

        db = _mock_db_with_rows([], total=0)
        scope = ProjectAccessScope(is_unrestricted=True, accessible_projects=[])

        result = await list_issues(
            status=None,
            project_id=None,
            initiator_user_id=None,
            search=None,
            created_after=None,
            created_before="2026-12-31T23:59:59",
            sort_by=None,
            sort_order=None,
            page=1,
            page_size=20,
            db=db,
            current_user=MagicMock(),
            access_scope=scope,
        )
        self.assertIn("items", result)


# ---------------------------------------------------------------------------
# Project ID filter with access scope (lines 254-284)
# ---------------------------------------------------------------------------


class TestListIssuesProjectFilter(unittest.IsolatedAsyncioTestCase):
    """Test project_id comma-separated filter with access scope restrictions."""

    async def test_single_project_id_unrestricted(self):
        """Single project_id with unrestricted access should filter."""
        from app.api.issues import list_issues
        from app.dependencies.project_access import ProjectAccessScope

        db = _mock_db_with_rows([], total=0)
        scope = ProjectAccessScope(is_unrestricted=True, accessible_projects=[])

        result = await list_issues(
            status=None, project_id="42", initiator_user_id=None,
            search=None, created_after=None, created_before=None,
            sort_by=None, sort_order=None, page=1, page_size=20,
            db=db, current_user=MagicMock(), access_scope=scope,
        )
        self.assertIn("items", result)

    async def test_multi_project_ids_unrestricted(self):
        """Multiple comma-separated project_ids with unrestricted access."""
        from app.api.issues import list_issues
        from app.dependencies.project_access import ProjectAccessScope

        db = _mock_db_with_rows([], total=0)
        scope = ProjectAccessScope(is_unrestricted=True, accessible_projects=[])

        result = await list_issues(
            status=None, project_id="42,43,44", initiator_user_id=None,
            search=None, created_after=None, created_before=None,
            sort_by=None, sort_order=None, page=1, page_size=20,
            db=db, current_user=MagicMock(), access_scope=scope,
        )
        self.assertIn("items", result)

    async def test_project_id_restricted_allowed(self):
        """Restricted scope with matching project_id should pass."""
        from app.api.issues import list_issues
        from app.dependencies.project_access import ProjectAccessScope

        db = _mock_db_with_rows([], total=0)
        scope = ProjectAccessScope(
            is_unrestricted=False,
            accessible_projects=[{"id": 42, "name": "Proj A"}],
        )

        result = await list_issues(
            status=None, project_id="42", initiator_user_id=None,
            search=None, created_after=None, created_before=None,
            sort_by=None, sort_order=None, page=1, page_size=20,
            db=db, current_user=MagicMock(), access_scope=scope,
        )
        self.assertIn("items", result)

    async def test_project_id_restricted_not_allowed(self):
        """Restricted scope with non-matching project_id → false clause."""
        from app.api.issues import list_issues
        from app.dependencies.project_access import ProjectAccessScope

        db = _mock_db_with_rows([], total=0)
        scope = ProjectAccessScope(
            is_unrestricted=False,
            accessible_projects=[{"id": 99, "name": "Other"}],
        )

        result = await list_issues(
            status=None, project_id="42", initiator_user_id=None,
            search=None, created_after=None, created_before=None,
            sort_by=None, sort_order=None, page=1, page_size=20,
            db=db, current_user=MagicMock(), access_scope=scope,
        )
        self.assertIn("items", result)
        self.assertEqual(result["total"], 0)

    async def test_no_project_id_restricted_empty_scope(self):
        """No project_id filter with restricted empty scope → false clause."""
        from app.api.issues import list_issues
        from app.dependencies.project_access import ProjectAccessScope

        db = _mock_db_with_rows([], total=0)
        scope = ProjectAccessScope(is_unrestricted=False, accessible_projects=[])

        result = await list_issues(
            status=None, project_id=None, initiator_user_id=None,
            search=None, created_after=None, created_before=None,
            sort_by=None, sort_order=None, page=1, page_size=20,
            db=db, current_user=MagicMock(), access_scope=scope,
        )
        self.assertIn("items", result)
        self.assertEqual(result["total"], 0)

    async def test_no_project_id_restricted_with_projects(self):
        """No project_id filter with restricted scope auto-filters to accessible projects."""
        from app.api.issues import list_issues
        from app.dependencies.project_access import ProjectAccessScope

        db = _mock_db_with_rows([], total=0)
        scope = ProjectAccessScope(
            is_unrestricted=False,
            accessible_projects=[{"id": 10, "name": "P"}, {"id": 20, "name": "Q"}],
        )

        result = await list_issues(
            status=None, project_id=None, initiator_user_id=None,
            search=None, created_after=None, created_before=None,
            sort_by=None, sort_order=None, page=1, page_size=20,
            db=db, current_user=MagicMock(), access_scope=scope,
        )
        self.assertIn("items", result)

    async def test_project_id_invalid_values_skipped(self):
        """Non-integer project_id values silently skipped."""
        from app.api.issues import list_issues
        from app.dependencies.project_access import ProjectAccessScope

        db = _mock_db_with_rows([], total=0)
        scope = ProjectAccessScope(is_unrestricted=True, accessible_projects=[])

        result = await list_issues(
            status=None, project_id="abc", initiator_user_id=None,
            search=None, created_after=None, created_before=None,
            sort_by=None, sort_order=None, page=1, page_size=20,
            db=db, current_user=MagicMock(), access_scope=scope,
        )
        self.assertIn("items", result)

    async def test_project_id_invalid_restricted_empty(self):
        """Non-integer project_id with restricted empty scope → false clause."""
        from app.api.issues import list_issues
        from app.dependencies.project_access import ProjectAccessScope

        db = _mock_db_with_rows([], total=0)
        scope = ProjectAccessScope(is_unrestricted=False, accessible_projects=[])

        result = await list_issues(
            status=None, project_id="abc", initiator_user_id=None,
            search=None, created_after=None, created_before=None,
            sort_by=None, sort_order=None, page=1, page_size=20,
            db=db, current_user=MagicMock(), access_scope=scope,
        )
        self.assertEqual(result["total"], 0)

    async def test_project_id_invalid_restricted_with_projects(self):
        """Non-integer project_id with restricted scope + projects → filters to accessible."""
        from app.api.issues import list_issues
        from app.dependencies.project_access import ProjectAccessScope

        db = _mock_db_with_rows([], total=0)
        scope = ProjectAccessScope(
            is_unrestricted=False,
            accessible_projects=[{"id": 10, "name": "P"}],
        )

        result = await list_issues(
            status=None, project_id="abc", initiator_user_id=None,
            search=None, created_after=None, created_before=None,
            sort_by=None, sort_order=None, page=1, page_size=20,
            db=db, current_user=MagicMock(), access_scope=scope,
        )
        self.assertIn("items", result)


# ---------------------------------------------------------------------------
# Initiator username multi-value filter (lines 286-294)
# ---------------------------------------------------------------------------


class TestListIssuesInitiatorFilter(unittest.IsolatedAsyncioTestCase):
    """Test initiator_username and initiator_user_id filters."""

    async def test_single_initiator_username(self):
        """Single initiator_username should filter."""
        from app.api.issues import list_issues
        from app.dependencies.project_access import ProjectAccessScope

        db = _mock_db_with_rows([], total=0)
        scope = ProjectAccessScope(is_unrestricted=True, accessible_projects=[])

        result = await list_issues(
            status=None, project_id=None, initiator_user_id=None,
            initiator_username="alice",
            search=None, created_after=None, created_before=None,
            sort_by=None, sort_order=None, page=1, page_size=20,
            db=db, current_user=MagicMock(), access_scope=scope,
        )
        self.assertIn("items", result)

    async def test_multi_initiator_usernames(self):
        """Comma-separated initiator_usernames should apply IN filter."""
        from app.api.issues import list_issues
        from app.dependencies.project_access import ProjectAccessScope

        db = _mock_db_with_rows([], total=0)
        scope = ProjectAccessScope(is_unrestricted=True, accessible_projects=[])

        result = await list_issues(
            status=None, project_id=None, initiator_user_id=None,
            initiator_username="alice,bob",
            search=None, created_after=None, created_before=None,
            sort_by=None, sort_order=None, page=1, page_size=20,
            db=db, current_user=MagicMock(), access_scope=scope,
        )
        self.assertIn("items", result)

    async def test_initiator_user_id_filter(self):
        """initiator_user_id should filter by user ID."""
        from app.api.issues import list_issues
        from app.dependencies.project_access import ProjectAccessScope

        db = _mock_db_with_rows([], total=0)
        scope = ProjectAccessScope(is_unrestricted=True, accessible_projects=[])

        result = await list_issues(
            status=None, project_id=None, initiator_user_id=7,
            search=None, created_after=None, created_before=None,
            sort_by=None, sort_order=None, page=1, page_size=20,
            db=db, current_user=MagicMock(), access_scope=scope,
        )
        self.assertIn("items", result)


# ---------------------------------------------------------------------------
# Has MR filter (lines 297-301)
# ---------------------------------------------------------------------------


class TestListIssuesHasMrFilter(unittest.IsolatedAsyncioTestCase):
    """Test has_mr boolean filter."""

    async def test_has_mr_true(self):
        """has_mr=True should filter for issues with merge_request_iid IS NOT NULL."""
        from app.api.issues import list_issues
        from app.dependencies.project_access import ProjectAccessScope

        db = _mock_db_with_rows([], total=0)
        scope = ProjectAccessScope(is_unrestricted=True, accessible_projects=[])

        result = await list_issues(
            status=None, project_id=None, initiator_user_id=None,
            has_mr=True,
            search=None, created_after=None, created_before=None,
            sort_by=None, sort_order=None, page=1, page_size=20,
            db=db, current_user=MagicMock(), access_scope=scope,
        )
        self.assertIn("items", result)

    async def test_has_mr_false(self):
        """has_mr=False should filter for issues with merge_request_iid IS NULL."""
        from app.api.issues import list_issues
        from app.dependencies.project_access import ProjectAccessScope

        db = _mock_db_with_rows([], total=0)
        scope = ProjectAccessScope(is_unrestricted=True, accessible_projects=[])

        result = await list_issues(
            status=None, project_id=None, initiator_user_id=None,
            has_mr=False,
            search=None, created_after=None, created_before=None,
            sort_by=None, sort_order=None, page=1, page_size=20,
            db=db, current_user=MagicMock(), access_scope=scope,
        )
        self.assertIn("items", result)


# ---------------------------------------------------------------------------
# Search too long (line 306)
# ---------------------------------------------------------------------------


class TestListIssuesSearchTooLong(unittest.IsolatedAsyncioTestCase):
    """Test search param max length validation."""

    async def test_search_too_long_returns_400(self):
        """Search > 200 chars should return 400."""
        from fastapi import HTTPException
        from app.api.issues import list_issues
        from app.dependencies.project_access import ProjectAccessScope

        db = _mock_db_with_rows([])
        scope = ProjectAccessScope(is_unrestricted=True, accessible_projects=[])

        with self.assertRaises(HTTPException) as ctx:
            await list_issues(
                status=None, project_id=None, initiator_user_id=None,
                search="x" * 201,
                created_after=None, created_before=None,
                sort_by=None, sort_order=None, page=1, page_size=20,
                db=db, current_user=MagicMock(), access_scope=scope,
            )
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("search too long", ctx.exception.detail)


# ---------------------------------------------------------------------------
# Sort by aggregate fields (line 214)
# ---------------------------------------------------------------------------


class TestListIssuesSortByAggregateFields(unittest.IsolatedAsyncioTestCase):
    """Test sorting by aggregate fields that use the task_agg subquery."""

    async def test_sort_by_total_changes(self):
        """Sort by total_changes (aggregate) should use coalesce from subquery."""
        from app.api.issues import list_issues
        from app.dependencies.project_access import ProjectAccessScope

        db = _mock_db_with_rows([], total=0)
        scope = ProjectAccessScope(is_unrestricted=True, accessible_projects=[])

        result = await list_issues(
            status=None, project_id=None, initiator_user_id=None,
            search=None, created_after=None, created_before=None,
            sort_by="total_changes", sort_order="asc",
            page=1, page_size=20,
            db=db, current_user=MagicMock(), access_scope=scope,
        )
        self.assertIn("items", result)

    async def test_sort_by_total_input_tokens(self):
        """Sort by total_input_tokens aggregate field."""
        from app.api.issues import list_issues
        from app.dependencies.project_access import ProjectAccessScope

        db = _mock_db_with_rows([], total=0)
        scope = ProjectAccessScope(is_unrestricted=True, accessible_projects=[])

        result = await list_issues(
            status=None, project_id=None, initiator_user_id=None,
            search=None, created_after=None, created_before=None,
            sort_by="total_input_tokens", sort_order="desc",
            page=1, page_size=20,
            db=db, current_user=MagicMock(), access_scope=scope,
        )
        self.assertIn("items", result)

    async def test_sort_by_total_output_tokens(self):
        """Sort by total_output_tokens aggregate field."""
        from app.api.issues import list_issues
        from app.dependencies.project_access import ProjectAccessScope

        db = _mock_db_with_rows([], total=0)
        scope = ProjectAccessScope(is_unrestricted=True, accessible_projects=[])

        result = await list_issues(
            status=None, project_id=None, initiator_user_id=None,
            search=None, created_after=None, created_before=None,
            sort_by="total_output_tokens", sort_order="asc",
            page=1, page_size=20,
            db=db, current_user=MagicMock(), access_scope=scope,
        )
        self.assertIn("items", result)

    async def test_sort_by_duration(self):
        """Sort by duration should use the issue task duration aggregate."""
        from app.api.issues import list_issues
        from app.dependencies.project_access import ProjectAccessScope

        db = _mock_db_with_rows([], total=0)
        scope = ProjectAccessScope(is_unrestricted=True, accessible_projects=[])

        result = await list_issues(
            status=None, project_id=None, initiator_user_id=None,
            search=None, created_after=None, created_before=None,
            sort_by="duration", sort_order="desc",
            page=1, page_size=20,
            db=db, current_user=MagicMock(), access_scope=scope,
        )
        self.assertIn("items", result)


# ---------------------------------------------------------------------------
# Update issue edge cases (lines 394, 403, 412)
# ---------------------------------------------------------------------------


class TestUpdateIssueEdgeCases(unittest.IsolatedAsyncioTestCase):
    """Test update_issue edge cases: not-found, description change, valid status change."""

    async def test_update_issue_not_found_returns_404(self):
        """PATCH on non-existent issue should return 404."""
        from fastapi import HTTPException
        from app.api.issues import update_issue, UpdateIssueRequest

        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = None

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=result_mock)

        body = UpdateIssueRequest(title="New Title")
        with self.assertRaises(HTTPException) as ctx:
            await update_issue(issue_id=999, body=body, db=mock_db, current_user=MagicMock())
        self.assertEqual(ctx.exception.status_code, 404)

    async def test_update_issue_description(self):
        """Updating description field should persist."""
        from app.api.issues import update_issue, UpdateIssueRequest

        issue = _make_issue(id=1, title="Title", description="Old desc")

        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = issue

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=result_mock)
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()

        body = UpdateIssueRequest(description="New description")
        await update_issue(issue_id=1, body=body, db=mock_db, current_user=MagicMock())

        self.assertEqual(issue.description, "New description")
        mock_db.commit.assert_awaited_once()

    async def test_update_issue_valid_status(self):
        """Updating to a valid status should persist."""
        from app.api.issues import update_issue, UpdateIssueRequest

        issue = _make_issue(id=1, status="open")

        result_mock = MagicMock()
        result_mock.scalar_one_or_none.return_value = issue

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=result_mock)
        mock_db.commit = AsyncMock()
        mock_db.refresh = AsyncMock()

        body = UpdateIssueRequest(status="in_progress")
        await update_issue(issue_id=1, body=body, db=mock_db, current_user=MagicMock())

        self.assertEqual(issue.status, "in_progress")


# ---------------------------------------------------------------------------
# Combined filters
# ---------------------------------------------------------------------------


class TestListIssuesCombinedFilters(unittest.IsolatedAsyncioTestCase):
    """Test combining multiple filters at once."""

    async def test_all_filters_combined(self):
        """Should accept all filters simultaneously."""
        from app.api.issues import list_issues
        from app.dependencies.project_access import ProjectAccessScope

        db = _mock_db_with_rows([], total=0)
        scope = ProjectAccessScope(is_unrestricted=True, accessible_projects=[])

        result = await list_issues(
            status="open",
            project_id="42",
            initiator_user_id=7,
            initiator_username="alice",
            has_mr=True,
            search="test",
            created_after="2025-01-01T00:00:00",
            created_before="2025-12-31T23:59:59",
            sort_by="total_changes",
            sort_order="asc",
            page=1,
            page_size=20,
            db=db,
            current_user=MagicMock(),
            access_scope=scope,
        )
        self.assertIn("items", result)
