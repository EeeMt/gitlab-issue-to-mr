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


def _row(issue, task_count=0, additions=0, deletions=0, total_changes=0, input_tokens=0, output_tokens=0):
    row = MagicMock()
    vals = [issue, task_count, additions, deletions, total_changes, input_tokens, output_tokens]
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

