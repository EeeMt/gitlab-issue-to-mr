import os
import sys
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.api.tasks import list_scheduled_tasks
from app.models import Task, TaskStatus


def _make_task(task_id: int, project_id: int, scheduled_at: datetime, status: TaskStatus) -> Task:
    now = datetime.now(UTC)
    return Task(
        id=task_id,
        project_id=project_id,
        issue_id=task_id,
        user_prompt=f"Prompt {task_id}",
        priority=task_id % 3,
        scheduled_at=scheduled_at,
        status=status,
        created_at=now - timedelta(minutes=task_id),
        updated_at=now - timedelta(minutes=task_id),
        started_at=None,
        completed_at=None,
    )


def _execute_result(task):
    """Mock a db.execute result supporting both scalars().all() and scalar_one_or_none()."""
    result = MagicMock()
    result.scalars.return_value.all.return_value = [task]
    result.scalar_one_or_none.return_value = None
    return result


@pytest.mark.asyncio
async def test_list_scheduled_tasks_serializes_active_scheduled_rows():
    scheduled_time = datetime.now(UTC) + timedelta(hours=2)
    task = _make_task(1, 101, scheduled_time, TaskStatus.PENDING)
    db = AsyncMock()
    db.execute.return_value = _execute_result(task)

    with patch("app.api.tasks.build_project_lookup", new=AsyncMock(return_value={
        101: {
            "project_name": "Project Alpha",
            "project_path_with_namespace": "group/project-alpha",
        }
    })):
        result = await list_scheduled_tasks(db=db, hour_start=None)

    assert len(result) == 1
    assert result[0]["id"] == 1
    assert result[0]["status"] == "pending"
    assert result[0]["scheduled_at"] == scheduled_time.isoformat()
    assert result[0]["project_name"] == "Project Alpha"
    assert result[0]["project_path_with_namespace"] == "group/project-alpha"


@pytest.mark.asyncio
async def test_list_scheduled_tasks_returns_all_projects_unrestricted():
    """Schedule overview is a global view — no project-level filtering is applied."""
    task = _make_task(2, 202, datetime.now(UTC) + timedelta(hours=1), TaskStatus.QUEUED)
    db = AsyncMock()
    db.execute.return_value = _execute_result(task)

    with patch("app.api.tasks.build_project_lookup", new=AsyncMock(return_value={})) as mock_lookup:
        result = await list_scheduled_tasks(db=db, hour_start=None)

    # build_project_lookup must be called with is_unrestricted=True (global view)
    mock_lookup.assert_awaited_once_with(is_unrestricted=True)

    executed_query = db.execute.call_args_list[0].args[0]

    assert len(result) == 1
    assert "scheduled_at IS NOT NULL" in str(executed_query)
    # No project_id IN (...) clause — all projects are visible
    assert "tasks.project_id IN" not in str(executed_query)


@pytest.mark.asyncio
async def test_list_scheduled_tasks_my_true_adds_initiator_username_condition():
    """When my=True and current user has a username, query filters by initiator_username."""
    task = _make_task(3, 303, datetime.now(UTC) + timedelta(hours=1), TaskStatus.PENDING)
    db = AsyncMock()
    db.execute.return_value = _execute_result(task)
    current_user = SimpleNamespace(username="alice")

    with patch("app.api.tasks.build_project_lookup", new=AsyncMock(return_value={})):
        await list_scheduled_tasks(db=db, hour_start=None, my=True, _current_user=current_user)

    executed_query = db.execute.call_args_list[0].args[0]
    # "initiator_username = " appears only when a WHERE filter is applied
    assert "initiator_username = " in str(executed_query)


@pytest.mark.asyncio
async def test_list_scheduled_tasks_my_false_does_not_filter_by_username():
    """When my=False (default), no initiator_username filter is applied."""
    task = _make_task(4, 404, datetime.now(UTC) + timedelta(hours=1), TaskStatus.QUEUED)
    db = AsyncMock()
    db.execute.return_value = _execute_result(task)
    current_user = SimpleNamespace(username="alice")

    with patch("app.api.tasks.build_project_lookup", new=AsyncMock(return_value={})):
        await list_scheduled_tasks(db=db, hour_start=None, my=False, _current_user=current_user)

    executed_query = db.execute.call_args_list[0].args[0]
    # "initiator_username = " only appears in WHERE conditions, not in SELECT column list
    assert "initiator_username = " not in str(executed_query)
