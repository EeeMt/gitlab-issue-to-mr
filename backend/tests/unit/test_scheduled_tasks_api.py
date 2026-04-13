import os
import sys
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.api.tasks import list_scheduled_tasks
from app.dependencies.project_access import ProjectAccessScope
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


@pytest.mark.asyncio
async def test_list_scheduled_tasks_serializes_active_scheduled_rows():
    scheduled_time = datetime.now(UTC) + timedelta(hours=2)
    task = _make_task(1, 101, scheduled_time, TaskStatus.PENDING)
    db = AsyncMock()
    db.execute.return_value = SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [task]))
    access_scope = ProjectAccessScope(is_unrestricted=True, accessible_projects=[])

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
async def test_list_scheduled_tasks_filters_by_project_id():
    task = _make_task(2, 202, datetime.now(UTC) + timedelta(hours=1), TaskStatus.QUEUED)
    db = AsyncMock()
    db.execute.return_value = SimpleNamespace(scalars=lambda: SimpleNamespace(all=lambda: [task]))

    with patch("app.api.tasks.build_project_lookup", new=AsyncMock(return_value={})):
        result = await list_scheduled_tasks(db=db, project_id=202, hour_start=None)

    executed_query = db.execute.await_args.args[0]

    assert len(result) == 1
    assert "scheduled_at IS NOT NULL" in str(executed_query)
    assert "tasks.project_id =" in str(executed_query)
