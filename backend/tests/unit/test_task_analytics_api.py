#!/usr/bin/env python3
"""Unit tests for task initiator persistence and analytics API."""

import os
import sys
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.api.stats import get_analytics
from app.api.tasks import CreateTaskRequest, create_task
from app.api.webhook import _handle_generate_command
from app.core.parser import BotCommand
from app.dependencies.project_access import ProjectAccessScope
from app.models import TaskStatus


@pytest.mark.asyncio
async def test_create_task_persists_manual_initiator_metadata():
    request = CreateTaskRequest(
        project_id=101,
        branch_name="feature/analytics",
        target_branch="main",
        user_prompt="Build analytics page",
        priority=1,
    )
    db = MagicMock()
    db.add = MagicMock()
    db.commit = AsyncMock()

    async def refresh(task):
        task.id = 23
        task.status = TaskStatus.PENDING
        task.created_at = datetime(2026, 3, 14, 12, 0, 0)

    db.refresh = AsyncMock(side_effect=refresh)
    current_user = SimpleNamespace(id=7, gitlab_user_id=77, username="alice")
    access_scope = ProjectAccessScope(is_unrestricted=True, accessible_projects=[])

    result = await create_task(request=request, db=db, current_user=current_user, access_scope=access_scope)

    task = db.add.call_args.args[0]
    assert task.initiator_user_id == 7
    assert task.initiator_gitlab_user_id == 77
    assert task.initiator_username == "alice"
    assert result["id"] == 23


@pytest.mark.asyncio
async def test_handle_generate_command_persists_webhook_initiator_metadata():
    db = MagicMock()
    db.execute = AsyncMock(return_value=SimpleNamespace(scalar_one_or_none=lambda: None))
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.flush = AsyncMock()

    async def refresh(task):
        task.id = 88
        task.created_at = datetime(2026, 3, 14, 12, 0, 0)

    db.refresh = AsyncMock(side_effect=refresh)
    command = BotCommand(command="generate", args="Please update this issue", raw_mention="@ai-bot")
    initiator = {"id": 501, "username": "gitlab-user"}
    fake_gitlab = MagicMock()
    fake_gitlab.get_issue.return_value = {
        "title": "Analytics",
        "description": "Need reporting",
    }

    with patch("app.api.webhook.get_gitlab_client", return_value=fake_gitlab):
        result = await _handle_generate_command(
            db=db,
            project_id=11,
            issue_id=12,
            issue_iid=13,
            note_id=14,
            command=command,
            initiator=initiator,
        )

    task = db.add.call_args.args[0]
    assert task.initiator_user_id is None
    assert task.initiator_gitlab_user_id == 501
    assert task.initiator_username == "gitlab-user"
    assert result["task_id"] == 88


class MockResult:
    """Simple mock result that behaves like SQLAlchemy execute result."""
    def __init__(self, data):
        self._data = data

    def one(self):
        return tuple(self._data)

    def all(self):
        return self._data

    def scalars(self):
        return self

    def scalar(self):
        return self._data[0] if self._data else None


@pytest.mark.asyncio
async def test_get_analytics_returns_project_initiator_and_trend_breakdowns():
    fixed_now = datetime(2026, 3, 14, 12, 0, 0)

    # Create mock db
    db = MagicMock()

    # Track call count for side_effect
    call_count = [0]

    def execute_side_effect(query):
        call_count[0] += 1

        # Summary query (call 1)
        if call_count[0] == 1:
            return MockResult([
                4,      # total_tasks
                21,     # total_additions
                9,      # total_deletions
                30,     # total_changes
                1000,   # total_input_tokens
                2000,   # total_output_tokens
                3,      # completed_tasks
                1,      # failed_tasks
                0,      # cancelled_tasks
                4,      # finished_tasks
                2,      # tracked_initiator_tasks
                2,      # token_tracked_tasks
                datetime(2026, 3, 12, 8, 0, 0),  # initiator_tracking_started_at
                540.0,  # avg_execution_seconds
                900.0,  # max_execution_seconds
                180.0,  # avg_queue_wait_seconds
                300.0,  # max_queue_wait_seconds
                1500.0, # avg_total_tokens_per_tracked_task
                2000.0, # max_total_tokens_per_tracked_task
            ])

        # Project query (call 2)
        elif call_count[0] == 2:
            return MockResult([
                SimpleNamespace(
                    project_id=101,
                    task_count=3,
                    completed_tasks=2,
                    failed_tasks=1,
                    cancelled_tasks=0,
                    additions=16,
                    deletions=5,
                    total_changes=21,
                    input_tokens=800,
                    output_tokens=1600,
                    total_tokens=2400,
                    avg_execution_seconds=600.0,
                    avg_queue_wait_seconds=150.0,
                    last_task_at=datetime(2026, 3, 14, 9, 0, 0),
                )
            ])

        # Available initiators query (call 3)
        elif call_count[0] == 3:
            return MockResult([])

        # Initiators breakdown query (call 4)
        elif call_count[0] == 4:
            return MockResult([
                SimpleNamespace(
                    initiator_username="alice",
                    initiator_gitlab_user_id=77,
                    task_count=2,
                    completed_tasks=2,
                    failed_tasks=0,
                    cancelled_tasks=0,
                    additions=10,
                    deletions=4,
                    total_changes=14,
                    input_tokens=500,
                    output_tokens=1000,
                    total_tokens=1500,
                    avg_execution_seconds=420.0,
                    avg_queue_wait_seconds=120.0,
                    last_task_at=datetime(2026, 3, 14, 9, 0, 0),
                )
            ])

        # Trend query (call 5)
        elif call_count[0] == 5:
            return MockResult([
                SimpleNamespace(
                    day=date(2026, 3, 12),
                    task_count=1,
                    completed_tasks=1,
                    failed_tasks=0,
                    cancelled_tasks=0,
                    additions=4,
                    deletions=1,
                    total_changes=5,
                    input_tokens=100,
                    output_tokens=200,
                    total_tokens=300,
                    avg_execution_seconds=300.0,
                ),
                SimpleNamespace(
                    day=date(2026, 3, 14),
                    task_count=3,
                    completed_tasks=2,
                    failed_tasks=1,
                    cancelled_tasks=0,
                    additions=17,
                    deletions=8,
                    total_changes=25,
                    input_tokens=500,
                    output_tokens=1000,
                    total_tokens=1500,
                    avg_execution_seconds=720.0,
                ),
            ])

        # Priority wait query (call 6)
        elif call_count[0] == 6:
            return MockResult([
                SimpleNamespace(
                    priority=0,
                    task_count=2,
                    avg_queue_wait_seconds=90.0,
                    max_queue_wait_seconds=180.0,
                ),
                SimpleNamespace(
                    priority=2,
                    task_count=1,
                    avg_queue_wait_seconds=300.0,
                    max_queue_wait_seconds=300.0,
                ),
            ])

        # Error breakdown query (call 7)
        elif call_count[0] == 7:
            return MockResult([
                SimpleNamespace(error_message="Task timed out after 30m", count=2),
                SimpleNamespace(error_message="docker container exited unexpectedly", count=1),
            ])

        return MockResult([])

    db.execute = AsyncMock(side_effect=execute_side_effect)

    access_scope = ProjectAccessScope(is_unrestricted=True, accessible_projects=[])

    with patch("app.api.stats.datetime") as datetime_mock, patch(
        "app.api.stats._build_project_lookup",
        new=AsyncMock(
            return_value={
                101: {
                    "project_name": "Project Alpha",
                    "project_path_with_namespace": "team/project-alpha",
                }
            }
        ),
    ):
        datetime_mock.utcnow.return_value = fixed_now
        datetime_mock.now.return_value = fixed_now
        response = await get_analytics(days=7, project_id=None, initiator_username=None, db=db, _current_user=None, access_scope=access_scope)

    assert response["window_days"] == 7
    assert response["summary"]["total_tasks"] == 4
    assert response["summary"]["success_rate"] == pytest.approx(0.75)
    assert response["summary"]["avg_execution_seconds"] == pytest.approx(540.0)
    assert response["summary"]["avg_queue_wait_seconds"] == pytest.approx(180.0)
    assert response["summary"]["tracked_initiator_tasks"] == 2
    assert response["projects"][0]["project_name"] == "Project Alpha"
    assert response["projects"][0]["success_rate"] == pytest.approx(2 / 3)
    assert response["projects"][0]["avg_execution_seconds"] == pytest.approx(600.0)
    assert response["initiators"][0]["initiator_username"] == "alice"
    assert response["initiators"][0]["success_rate"] == pytest.approx(1.0)
    assert len(response["trends"]) == 7
    assert response["trends"][0]["date"] == "2026-03-08"
    assert response["trends"][-1]["date"] == "2026-03-14"
    assert response["trends"][-1]["task_count"] == 3
    assert response["trends"][-1]["avg_execution_seconds"] == pytest.approx(720.0)
    assert response["priority_waits"][0]["priority"] == 0
    assert response["priority_waits"][1]["avg_queue_wait_seconds"] == pytest.approx(300.0)
    assert response["error_breakdown"][0]["category"] == "Timeout"
    assert response["error_breakdown"][0]["count"] == 2
    assert response["error_breakdown"][1]["category"] == "Docker"
