import os
import sys
from datetime import UTC, datetime
from types import SimpleNamespace
from typing import Optional
from unittest.mock import AsyncMock, patch

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
            project_id=202,
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
