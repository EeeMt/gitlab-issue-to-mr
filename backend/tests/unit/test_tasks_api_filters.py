"""Tests for enhanced tasks list filtering, sorting, and search."""

import os
import sys
import unittest
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import app.api.tasks as tasks_api
from app.core.projects import build_project_lookup
from app.api.tasks import list_tasks
from app.api.projects import list_projects
from app.dependencies.project_access import ProjectAccessScope
from app.models import Task, TaskStatus


def _make_task(
    task_id: int,
    project_id: int,
    status: TaskStatus,
    initiator_username: Optional[str] = None,
) -> Task:
    now = datetime.now(UTC)
    return Task(
        id=task_id,
        project_id=project_id,
        issue_id=task_id,
        user_prompt=f"Prompt {task_id}",
        priority=task_id % 3,
        status=status,
        initiator_username=initiator_username,
        created_at=now,
        updated_at=now,
    )


def _mock_paginated_db(tasks, total=None):
    """Build a mock AsyncSession for paginated mode (page is not None)."""
    if total is None:
        total = len(tasks)
    count_result = MagicMock()
    count_result.scalar.return_value = total

    main_result = MagicMock()
    main_result.scalars.return_value = MagicMock(all=lambda: tasks)

    db = AsyncMock()
    db.execute = AsyncMock(side_effect=[count_result, main_result])
    return db


# ---------------------------------------------------------------------------
# Existing tests (preserved)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_list_tasks_serializes_initiator_fields():
    task = _make_task(1, 101, TaskStatus.PENDING, initiator_username="alice")
    task.initiator_user_id = 7
    task.initiator_gitlab_user_id = 77
    db = AsyncMock()
    db.execute.return_value = SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [task]))
    access_scope = ProjectAccessScope(is_unrestricted=True, accessible_projects=[])

    with patch(
        "app.core.projects.build_project_lookup",
        new=AsyncMock(
            return_value={
                101: {
                    "project_name": "Project Alpha",
                    "project_path_with_namespace": "group/project-alpha",
                }
            }
        ),
    ):
        result = await list_tasks(db=db, access_scope=access_scope)

    assert len(result) == 1
    assert result[0]["initiator_user_id"] == 7
    assert result[0]["initiator_gitlab_user_id"] == 77
    assert result[0]["initiator_username"] == "alice"


@pytest.mark.asyncio
async def test_list_tasks_applies_project_and_initiator_filters():
    task = _make_task(2, 202, TaskStatus.RUNNING, initiator_username="alice")
    db = AsyncMock()
    db.execute.return_value = SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [task]))
    access_scope = ProjectAccessScope(
        is_unrestricted=False,
        accessible_projects=[{"id": 202, "name": "Project Beta"}],
    )

    with patch("app.api.tasks.build_project_lookup", new=AsyncMock(return_value={})):
        result = await list_tasks(
            project_id="202",
            initiator_username="alice",
            db=db,
            access_scope=access_scope,
        )

    executed_query = db.execute.await_args.args[0]

    assert len(result) == 1
    assert "tasks.project_id =" in str(executed_query)
    assert "tasks.initiator_username =" in str(executed_query)


@pytest.mark.asyncio
async def test_build_project_lookup_reuses_access_scope_projects_without_gitlab_fetch():
    access_scope = ProjectAccessScope(
        is_unrestricted=False,
        accessible_projects=[
            {
                "id": 202,
                "name": "Project Beta",
                "path_with_namespace": "team/project-beta",
            }
        ],
    )

    with patch("app.core.projects.get_cached_projects", new=AsyncMock()) as get_cached:
        lookup = await build_project_lookup(
            accessible_projects=access_scope.accessible_projects,
            is_unrestricted=access_scope.is_unrestricted,
        )

    assert lookup == {
        202: {
            "project_name": "Project Beta",
            "project_path_with_namespace": "team/project-beta",
        }
    }
    get_cached.assert_not_awaited()


@pytest.mark.asyncio
async def test_list_projects_uses_ttl_cache_for_unrestricted_scope():
    import app.core.gitlab_client as gitlab_client

    access_scope = ProjectAccessScope(is_unrestricted=True, accessible_projects=[])
    fake_projects = [
        {
            "id": 101,
            "name": "Project Alpha",
            "path_with_namespace": "team/project-alpha",
        }
    ]
    # Reset cache in gitlab_client
    gitlab_client._project_list_cache = []
    gitlab_client._project_list_cache_expires_at = 0.0
    gitlab_client._project_list_refresh_task = None

    # Use a real time.time function to avoid issues with logging and other calls
    import time
    real_time = time.time

    with patch("app.core.gitlab_client.get_gitlab_client", return_value=SimpleNamespace(get_projects=object())), patch(
        "app.core.gitlab_client.asyncio.to_thread",
        new=AsyncMock(return_value=fake_projects),
    ) as to_thread:
        first = await list_projects(access_scope=access_scope)
        second = await list_projects(access_scope=access_scope)

    assert first == fake_projects
    assert second == fake_projects
    assert to_thread.await_count == 1


# ---------------------------------------------------------------------------
# New filter/sort/search tests
# ---------------------------------------------------------------------------


class TestListTasksMultiStatus(unittest.IsolatedAsyncioTestCase):
    """Test comma-separated multi-status filtering on GET /api/tasks."""

    async def test_invalid_status_returns_400(self):
        from fastapi import HTTPException

        db = _mock_paginated_db([])
        scope = ProjectAccessScope(is_unrestricted=True, accessible_projects=[])

        with patch("app.api.tasks.build_project_lookup", new=AsyncMock(return_value={})):
            with self.assertRaises(HTTPException) as ctx:
                await list_tasks(
                    status="bogus",
                    page=1,
                    page_size=20,
                    db=db,
                    access_scope=scope,
                )
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("bogus", ctx.exception.detail)

    async def test_mixed_valid_invalid_status_returns_400(self):
        from fastapi import HTTPException

        db = _mock_paginated_db([])
        scope = ProjectAccessScope(is_unrestricted=True, accessible_projects=[])

        with patch("app.api.tasks.build_project_lookup", new=AsyncMock(return_value={})):
            with self.assertRaises(HTTPException) as ctx:
                await list_tasks(
                    status="running,bogus",
                    page=1,
                    page_size=20,
                    db=db,
                    access_scope=scope,
                )
        self.assertEqual(ctx.exception.status_code, 400)
        self.assertIn("bogus", ctx.exception.detail)

    async def test_valid_multi_status_accepted(self):
        db = _mock_paginated_db([], total=0)
        scope = ProjectAccessScope(is_unrestricted=True, accessible_projects=[])

        with patch("app.api.tasks.build_project_lookup", new=AsyncMock(return_value={})):
            result = await list_tasks(
                status="running,pending",
                page=1,
                page_size=20,
                db=db,
                access_scope=scope,
            )
        self.assertIn("items", result)


class TestListTasksSortParams(unittest.IsolatedAsyncioTestCase):
    """Test sort_by and sort_order params on GET /api/tasks."""

    async def test_invalid_sort_by_returns_400(self):
        from fastapi import HTTPException

        db = _mock_paginated_db([])
        scope = ProjectAccessScope(is_unrestricted=True, accessible_projects=[])

        with patch("app.api.tasks.build_project_lookup", new=AsyncMock(return_value={})):
            with self.assertRaises(HTTPException) as ctx:
                await list_tasks(
                    sort_by="invalid_field",
                    page=1,
                    page_size=20,
                    db=db,
                    access_scope=scope,
                )
        self.assertEqual(ctx.exception.status_code, 400)

    async def test_invalid_sort_order_returns_400(self):
        from fastapi import HTTPException

        db = _mock_paginated_db([])
        scope = ProjectAccessScope(is_unrestricted=True, accessible_projects=[])

        with patch("app.api.tasks.build_project_lookup", new=AsyncMock(return_value={})):
            with self.assertRaises(HTTPException) as ctx:
                await list_tasks(
                    sort_order="random",
                    page=1,
                    page_size=20,
                    db=db,
                    access_scope=scope,
                )
        self.assertEqual(ctx.exception.status_code, 400)

    async def test_valid_sort_by_status(self):
        db = _mock_paginated_db([], total=0)
        scope = ProjectAccessScope(is_unrestricted=True, accessible_projects=[])

        with patch("app.api.tasks.build_project_lookup", new=AsyncMock(return_value={})):
            result = await list_tasks(
                sort_by="status",
                sort_order="asc",
                page=1,
                page_size=20,
                db=db,
                access_scope=scope,
            )
        self.assertIn("items", result)

    async def test_valid_sort_by_priority(self):
        db = _mock_paginated_db([], total=0)
        scope = ProjectAccessScope(is_unrestricted=True, accessible_projects=[])

        with patch("app.api.tasks.build_project_lookup", new=AsyncMock(return_value={})):
            result = await list_tasks(
                sort_by="priority",
                sort_order="asc",
                page=1,
                page_size=20,
                db=db,
                access_scope=scope,
            )
        self.assertIn("items", result)

    async def test_valid_sort_by_duration_asc(self):
        """duration sort should not raise and uses computed epoch expression."""
        db = _mock_paginated_db([], total=0)
        scope = ProjectAccessScope(is_unrestricted=True, accessible_projects=[])

        with patch("app.api.tasks.build_project_lookup", new=AsyncMock(return_value={})):
            result = await list_tasks(
                sort_by="duration",
                sort_order="asc",
                page=1,
                page_size=20,
                db=db,
                access_scope=scope,
            )
        self.assertIn("items", result)

    async def test_valid_sort_by_duration_desc(self):
        """duration sort desc should not raise."""
        db = _mock_paginated_db([], total=0)
        scope = ProjectAccessScope(is_unrestricted=True, accessible_projects=[])

        with patch("app.api.tasks.build_project_lookup", new=AsyncMock(return_value={})):
            result = await list_tasks(
                sort_by="duration",
                sort_order="desc",
                page=1,
                page_size=20,
                db=db,
                access_scope=scope,
            )
        self.assertIn("items", result)

    async def test_other_sort_fields_still_work_alongside_duration(self):
        """Regression: non-duration sort fields must still work (UnboundLocalError guard)."""
        scope = ProjectAccessScope(is_unrestricted=True, accessible_projects=[])

        for field in ("created_at", "status", "priority", "total_changes", "input_tokens", "output_tokens"):
            with self.subTest(sort_by=field):
                db = _mock_paginated_db([], total=0)
                with patch("app.api.tasks.build_project_lookup", new=AsyncMock(return_value={})):
                    result = await list_tasks(
                        sort_by=field,
                        sort_order="desc",
                        page=1,
                        page_size=20,
                        db=db,
                        access_scope=scope,
                    )
                self.assertIn("items", result)


class TestListTasksSearchParam(unittest.IsolatedAsyncioTestCase):
    """Test search param on GET /api/tasks."""

    async def test_search_param_accepted(self):
        db = _mock_paginated_db([], total=0)
        scope = ProjectAccessScope(is_unrestricted=True, accessible_projects=[])

        with patch("app.api.tasks.build_project_lookup", new=AsyncMock(return_value={})):
            result = await list_tasks(
                search="auth",
                page=1,
                page_size=20,
                db=db,
                access_scope=scope,
            )
        self.assertIn("items", result)

    async def test_short_search_ignored(self):
        """Search strings < 2 chars should be silently ignored."""
        db = _mock_paginated_db([], total=0)
        scope = ProjectAccessScope(is_unrestricted=True, accessible_projects=[])

        with patch("app.api.tasks.build_project_lookup", new=AsyncMock(return_value={})):
            result = await list_tasks(
                search="a",
                page=1,
                page_size=20,
                db=db,
                access_scope=scope,
            )
        self.assertIn("items", result)


class TestListTasksPriorityFilter(unittest.IsolatedAsyncioTestCase):
    """Test priority filter on GET /api/tasks."""

    async def test_priority_filter_accepted(self):
        db = _mock_paginated_db([], total=0)
        scope = ProjectAccessScope(is_unrestricted=True, accessible_projects=[])

        with patch("app.api.tasks.build_project_lookup", new=AsyncMock(return_value={})):
            result = await list_tasks(
                priority="0,1",
                page=1,
                page_size=20,
                db=db,
                access_scope=scope,
            )
        self.assertIn("items", result)

    async def test_single_priority_accepted(self):
        db = _mock_paginated_db([], total=0)
        scope = ProjectAccessScope(is_unrestricted=True, accessible_projects=[])

        with patch("app.api.tasks.build_project_lookup", new=AsyncMock(return_value={})):
            result = await list_tasks(
                priority="0",
                page=1,
                page_size=20,
                db=db,
                access_scope=scope,
            )
        self.assertIn("items", result)

    async def test_invalid_priority_silently_skipped(self):
        """Invalid priority values are silently skipped, not 400."""
        db = _mock_paginated_db([])
        scope = ProjectAccessScope(is_unrestricted=True, accessible_projects=[])

        with patch("app.api.tasks.build_project_lookup", new=AsyncMock(return_value={})):
            result = await list_tasks(
                priority="abc",
                page=1,
                page_size=20,
                db=db,
                access_scope=scope,
            )
        self.assertIn("items", result)

    async def test_mixed_valid_invalid_priority(self):
        """Mixed valid/invalid priority: valid kept, invalid silently dropped."""
        db = _mock_paginated_db([])
        scope = ProjectAccessScope(is_unrestricted=True, accessible_projects=[])

        with patch("app.api.tasks.build_project_lookup", new=AsyncMock(return_value={})):
            result = await list_tasks(
                priority="0,abc,1",
                page=1,
                page_size=20,
                db=db,
                access_scope=scope,
            )
        self.assertIn("items", result)


class TestListTasksDateRange(unittest.IsolatedAsyncioTestCase):
    """Test created_after / created_before params."""

    async def test_valid_created_after(self):
        db = _mock_paginated_db([], total=0)
        scope = ProjectAccessScope(is_unrestricted=True, accessible_projects=[])

        with patch("app.api.tasks.build_project_lookup", new=AsyncMock(return_value={})):
            result = await list_tasks(
                created_after="2025-01-01T00:00:00",
                page=1,
                page_size=20,
                db=db,
                access_scope=scope,
            )
        self.assertIn("items", result)

    async def test_valid_created_before(self):
        db = _mock_paginated_db([], total=0)
        scope = ProjectAccessScope(is_unrestricted=True, accessible_projects=[])

        with patch("app.api.tasks.build_project_lookup", new=AsyncMock(return_value={})):
            result = await list_tasks(
                created_before="2026-12-31T23:59:59",
                page=1,
                page_size=20,
                db=db,
                access_scope=scope,
            )
        self.assertIn("items", result)

    async def test_invalid_created_after_returns_400(self):
        from fastapi import HTTPException

        db = _mock_paginated_db([])
        scope = ProjectAccessScope(is_unrestricted=True, accessible_projects=[])

        with patch("app.api.tasks.build_project_lookup", new=AsyncMock(return_value={})):
            with self.assertRaises(HTTPException) as ctx:
                await list_tasks(
                    created_after="not-a-date",
                    page=1,
                    page_size=20,
                    db=db,
                    access_scope=scope,
                )
        self.assertEqual(ctx.exception.status_code, 400)

    async def test_invalid_created_before_returns_400(self):
        from fastapi import HTTPException

        db = _mock_paginated_db([])
        scope = ProjectAccessScope(is_unrestricted=True, accessible_projects=[])

        with patch("app.api.tasks.build_project_lookup", new=AsyncMock(return_value={})):
            with self.assertRaises(HTTPException) as ctx:
                await list_tasks(
                    created_before="garbage",
                    page=1,
                    page_size=20,
                    db=db,
                    access_scope=scope,
                )
        self.assertEqual(ctx.exception.status_code, 400)
