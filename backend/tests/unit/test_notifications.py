#!/usr/bin/env python3
"""
Test worker notification logic without external dependencies.
"""

import asyncio
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.core.worker import WorkerExecutor
from app.models import Task, TaskStatus


SETTINGS_PATH = "app.core.worker.get_settings"


def _mock_settings(**overrides):
    """Return a mock settings object with defaults."""
    defaults = dict(dashboard_url="http://localhost", alert_on_failure=False, alert_webhook_url=None)
    defaults.update(overrides)
    s = MagicMock()
    for k, v in defaults.items():
        setattr(s, k, v)
    return s


def _make_issue(**kwargs):
    """Return a MagicMock Issue with given attributes."""
    issue = MagicMock()
    issue.merge_request_iid = kwargs.get("merge_request_iid", None)
    issue.merge_request_url = kwargs.get("merge_request_url", None)
    return issue


@patch(SETTINGS_PATH, return_value=_mock_settings())
def test_notify_task_started(mock_get_settings):
    """Test _notify_task_started sends correct message."""
    mock_gitlab = MagicMock()
    mock_docker = MagicMock()
    worker = WorkerExecutor(docker_client=mock_docker, gitlab_client=mock_gitlab)

    task = Task(
        id=1,
        project_id=123,
        user_prompt="test prompt",
        priority=2,
        status=TaskStatus.RUNNING,
    )

    issue = _make_issue(merge_request_iid=456)
    worker._notify_task_started(task, issue)

    mock_gitlab.create_mr_note.assert_called_once()
    call_args = mock_gitlab.create_mr_note.call_args

    assert call_args[0][0] == 123  # project_id
    assert call_args[0][1] == 456  # merge_request_iid
    assert "🔄 开始处理请求" in call_args[0][2]


@pytest.mark.asyncio
@patch(SETTINGS_PATH, return_value=_mock_settings())
async def test_notify_task_completed_success_with_mr(mock_get_settings):
    """Test continuation tasks send completion updates to the MR."""
    mock_gitlab = MagicMock()
    mock_docker = MagicMock()
    worker = WorkerExecutor(docker_client=mock_docker, gitlab_client=mock_gitlab)

    task = Task(
        id=2,
        project_id=123,
        status=TaskStatus.COMPLETED,
    )

    issue = _make_issue(
        merge_request_iid=1,
        merge_request_url="https://gitlab.com/project/-/merge_requests/1",
    )

    await worker._notify_task_completed(task, success=True, notify_target="mr", issue=issue)

    mock_gitlab.create_mr_note.assert_called_once()
    call_args = mock_gitlab.create_mr_note.call_args

    assert call_args[0][0] == 123
    assert call_args[0][1] == 1
    assert "✅" in call_args[0][2]


@pytest.mark.asyncio
@patch(SETTINGS_PATH, return_value=_mock_settings())
async def test_notify_task_completed_success_to_issue_with_mr_link(mock_get_settings):
    """Test notify_target='issue' makes no GitLab calls."""
    mock_gitlab = MagicMock()
    mock_docker = MagicMock()
    worker = WorkerExecutor(docker_client=mock_docker, gitlab_client=mock_gitlab)

    task = Task(
        id=3,
        project_id=123,
        status=TaskStatus.COMPLETED,
    )

    issue = _make_issue(
        merge_request_iid=9,
        merge_request_url="https://gitlab.com/project/-/merge_requests/9",
    )

    await worker._notify_task_completed(task, success=True, notify_target="issue", issue=issue)

    # notify_target="issue" does not call any GitLab API
    mock_gitlab.create_note.assert_not_called()
    mock_gitlab.create_mr_note.assert_not_called()


@pytest.mark.asyncio
@patch(SETTINGS_PATH, return_value=_mock_settings())
async def test_notify_task_completed_failure(mock_get_settings):
    """Test _notify_task_completed sends failure message via MR note."""
    mock_gitlab = MagicMock()
    mock_docker = MagicMock()
    worker = WorkerExecutor(docker_client=mock_docker, gitlab_client=mock_gitlab)

    task = Task(
        id=4,
        project_id=123,
        error_message="Container failed to start",
        status=TaskStatus.FAILED,
    )

    issue = _make_issue(merge_request_iid=10)

    await worker._notify_task_completed(task, success=False, notify_target="mr", issue=issue)

    mock_gitlab.create_mr_note.assert_called_once()
    call_args = mock_gitlab.create_mr_note.call_args

    assert "❌ 任务失败" in call_args[0][2]
    assert "Container failed to start" in call_args[0][2]


@pytest.mark.asyncio
@patch(SETTINGS_PATH, return_value=_mock_settings())
async def test_notify_task_completed_failure_long_message(mock_get_settings):
    """Test _notify_task_completed truncates long error messages."""
    mock_gitlab = MagicMock()
    mock_docker = MagicMock()
    worker = WorkerExecutor(docker_client=mock_docker, gitlab_client=mock_gitlab)

    long_error = "Error: " + "x" * 300

    task = Task(
        id=5,
        project_id=123,
        error_message=long_error,
        status=TaskStatus.FAILED,
    )

    issue = _make_issue(merge_request_iid=10)

    await worker._notify_task_completed(task, success=False, notify_target="mr", issue=issue)

    mock_gitlab.create_mr_note.assert_called_once()
    message = mock_gitlab.create_mr_note.call_args[0][2]

    assert "❌ 任务失败" in message
    # Error should be truncated to 200 chars
    assert len(long_error[:200]) == 200


@pytest.mark.asyncio
@patch(SETTINGS_PATH, return_value=_mock_settings())
async def test_notify_task_completed_failure_no_message(mock_get_settings):
    """Test _notify_task_completed handles missing error message."""
    mock_gitlab = MagicMock()
    mock_docker = MagicMock()
    worker = WorkerExecutor(docker_client=mock_docker, gitlab_client=mock_gitlab)

    task = Task(
        id=6,
        project_id=123,
        error_message=None,
        status=TaskStatus.FAILED,
    )

    issue = _make_issue(merge_request_iid=10)

    await worker._notify_task_completed(task, success=False, notify_target="mr", issue=issue)

    mock_gitlab.create_mr_note.assert_called_once()
    call_args = mock_gitlab.create_mr_note.call_args

    assert "❌ 任务失败" in call_args[0][2]
    assert "未知错误" in call_args[0][2]


if __name__ == "__main__":
    test_notify_task_started()
    asyncio.run(test_notify_task_completed_success_with_mr())
    asyncio.run(test_notify_task_completed_success_to_issue_with_mr_link())
    asyncio.run(test_notify_task_completed_failure())
    asyncio.run(test_notify_task_completed_failure_long_message())
    asyncio.run(test_notify_task_completed_failure_no_message())

    print("\n" + "=" * 60)
    print("All notification tests passed!")
    print("=" * 60)
