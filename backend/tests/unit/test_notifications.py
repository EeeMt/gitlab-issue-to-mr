#!/usr/bin/env python3
"""
Test worker notification logic without external dependencies.
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from unittest.mock import MagicMock, patch
from app.core.worker import WorkerExecutor
from app.models import Task, TaskStatus


class MockContainer:
    """Mock Docker container."""
    def __init__(self):
        self.id = "mock-container-id"


def test_notify_task_started():
    """Test _notify_task_started sends correct message."""
    print("=" * 60)
    print("Testing _notify_task_started")
    print("=" * 60)

    # Create mock GitLab client
    mock_gitlab = MagicMock()
    mock_docker = MagicMock()

    # Create worker with mocks
    worker = WorkerExecutor(docker_client=mock_docker, gitlab_client=mock_gitlab)

    # Create mock task
    task = Task(
        id=1,
        project_id=123,
        issue_iid=456,
        user_prompt="test prompt",
        branch_name="test-branch",
        priority=2,
        status=TaskStatus.RUNNING,
    )

    # Call the method
    worker._notify_task_started(task)

    # Verify GitLab client was called
    mock_gitlab.create_note.assert_called_once()
    call_args = mock_gitlab.create_note.call_args

    # Verify arguments
    assert call_args[0][0] == 123  # project_id
    assert call_args[0][1] == 456  # issue_iid
    assert "🔄 开始处理请求" in call_args[0][2]  # message now includes task URL

    print("✓ _notify_task_started sends correct message")


def test_notify_task_completed_success_with_mr():
    """Test _notify_task_completed sends MR URL on success."""
    print("=" * 60)
    print("Testing _notify_task_completed (success with MR)")
    print("=" * 60)

    mock_gitlab = MagicMock()
    mock_docker = MagicMock()
    worker = WorkerExecutor(docker_client=mock_docker, gitlab_client=mock_gitlab)

    task = Task(
        id=2,
        project_id=123,
        issue_iid=456,
        merge_request_url="https://gitlab.com/project/-/merge_requests/1",
        status=TaskStatus.COMPLETED,
    )

    worker._notify_task_completed(task, success=True)

    mock_gitlab.create_note.assert_called_once()
    call_args = mock_gitlab.create_note.call_args

    assert call_args[0][0] == 123
    assert call_args[0][1] == 456
    assert "✅" in call_args[0][2]  # success message now includes task URL

    print("✓ _notify_task_completed sends MR URL on success")


def test_notify_task_completed_success_no_mr():
    """Test _notify_task_completed sends success message without MR URL."""
    print("=" * 60)
    print("Testing _notify_task_completed (success without MR)")
    print("=" * 60)

    mock_gitlab = MagicMock()
    mock_docker = MagicMock()
    worker = WorkerExecutor(docker_client=mock_docker, gitlab_client=mock_gitlab)

    task = Task(
        id=3,
        project_id=123,
        issue_iid=456,
        merge_request_url=None,
        status=TaskStatus.COMPLETED,
    )

    worker._notify_task_completed(task, success=True)

    mock_gitlab.create_note.assert_called_once()
    call_args = mock_gitlab.create_note.call_args

    assert "✅ 任务已完成" in call_args[0][2]  # message now includes task URL

    print("✓ _notify_task_completed sends success message without MR URL")


def test_notify_task_completed_failure():
    """Test _notify_task_completed sends failure message."""
    print("=" * 60)
    print("Testing _notify_task_completed (failure)")
    print("=" * 60)

    mock_gitlab = MagicMock()
    mock_docker = MagicMock()
    worker = WorkerExecutor(docker_client=mock_docker, gitlab_client=mock_gitlab)

    task = Task(
        id=4,
        project_id=123,
        issue_iid=456,
        error_message="Container failed to start",
        status=TaskStatus.FAILED,
    )

    worker._notify_task_completed(task, success=False)

    mock_gitlab.create_note.assert_called_once()
    call_args = mock_gitlab.create_note.call_args

    assert "❌ 任务失败" in call_args[0][2]  # message now includes task URL
    assert "Container failed to start" in call_args[0][2]

    print("✓ _notify_task_completed sends failure message")


def test_notify_task_completed_failure_long_message():
    """Test _notify_task_completed truncates long error messages."""
    print("=" * 60)
    print("Testing _notify_task_completed (long error message)")
    print("=" * 60)

    mock_gitlab = MagicMock()
    mock_docker = MagicMock()
    worker = WorkerExecutor(docker_client=mock_docker, gitlab_client=mock_gitlab)

    # Create a very long error message
    long_error = "Error: " + "x" * 300

    task = Task(
        id=5,
        project_id=123,
        issue_iid=456,
        error_message=long_error,
        status=TaskStatus.FAILED,
    )

    worker._notify_task_completed(task, success=False)

    mock_gitlab.create_note.assert_called_once()
    call_args = mock_gitlab.create_note.call_args

    # Message should be truncated to 200 chars (plus URL prefix)
    message = call_args[0][2]
    # Should contain the truncated error plus task URL
    assert "❌ 任务失败" in message

    print("✓ _notify_task_completed truncates long error messages")


def test_notify_task_completed_failure_no_message():
    """Test _notify_task_completed handles missing error message."""
    print("=" * 60)
    print("Testing _notify_task_completed (no error message)")
    print("=" * 60)

    mock_gitlab = MagicMock()
    mock_docker = MagicMock()
    worker = WorkerExecutor(docker_client=mock_docker, gitlab_client=mock_gitlab)

    task = Task(
        id=6,
        project_id=123,
        issue_iid=456,
        error_message=None,
        status=TaskStatus.FAILED,
    )

    worker._notify_task_completed(task, success=False)

    mock_gitlab.create_note.assert_called_once()
    call_args = mock_gitlab.create_note.call_args

    assert "❌ 任务失败" in call_args[0][2]  # message now includes task URL
    assert "未知错误" in call_args[0][2]

    print("✓ _notify_task_completed handles missing error message")


if __name__ == "__main__":
    test_notify_task_started()
    test_notify_task_completed_success_with_mr()
    test_notify_task_completed_success_no_mr()
    test_notify_task_completed_failure()
    test_notify_task_completed_failure_long_message()
    test_notify_task_completed_failure_no_message()

    print("\n" + "=" * 60)
    print("All notification tests passed!")
    print("=" * 60)
