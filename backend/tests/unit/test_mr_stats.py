#!/usr/bin/env python3
"""
Test: MR Change Stats - Get and save MR change statistics after commit.
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
from unittest.mock import MagicMock, patch, AsyncMock
from datetime import datetime


class MockContainer:
    """Mock Docker container."""
    def __init__(self):
        self.id = "mock-container-id"


def _make_mock_issue(**overrides):
    """Create a mock Issue with sensible defaults."""
    mock_issue = MagicMock()
    defaults = dict(
        id=1,
        branch_name="codify-branch",
        base_branch=None,
        target_branch="main",
        merge_request_iid=None,
        merge_request_url=None,
        claude_session_id=None,
        session_storage_path=None,
        project_id=123,
    )
    defaults.update(overrides)
    for k, v in defaults.items():
        setattr(mock_issue, k, v)
    return mock_issue


def create_mock_db(task, issue=None):
    """Create a properly configured mock database session."""
    mock_db = MagicMock()

    # db.execute is used for select(Task) and delete(TaskLog)
    task_result = MagicMock()
    task_result.scalar_one_or_none.return_value = task
    delete_result = MagicMock()
    delete_result.rowcount = 0

    call_count = [0]

    async def mock_execute(query, *args, **kwargs):
        call_count[0] += 1
        if call_count[0] == 1:
            return task_result
        return delete_result

    mock_db.execute = mock_execute
    mock_db.get = AsyncMock(return_value=issue)
    mock_db.commit = AsyncMock()
    mock_db.add = MagicMock()
    mock_db.refresh = AsyncMock()
    return mock_db


def test_worker_saves_mr_stats_after_completion():
    """Test that worker uses CODIFY_DIFF log line (primary) for MR change stats."""
    print("\n" + "=" * 60)
    print("Testing: Worker saves MR stats from CODIFY_DIFF log line (primary path)")
    print("=" * 60)

    mock_settings = MagicMock()
    mock_settings.gitlab_url = "http://gitlab.example.com"
    mock_settings.gitlab_bot_token = "test-token"
    mock_settings.worker_image = "test-worker:latest"
    mock_settings.task_timeout = 1800
    mock_settings.anthropic_base_url = "http://localhost:11434/v1"
    mock_settings.anthropic_api_key = "test-key"
    mock_settings.anthropic_model = "claude-sonnet-4-20250514"
    mock_settings.default_target_branch = "main"
    mock_settings.max_retries = 0
    mock_settings.backend_url = "http://localhost:8000"

    with patch('app.core.worker.get_settings', return_value=mock_settings):
        from app.core.worker import WorkerExecutor
        from app.models import Task, TaskStatus

        mock_gitlab = MagicMock()
        mock_docker = MagicMock()
        mock_container = MockContainer()
        mock_docker.create_container.return_value = mock_container

        mock_gitlab.get_merge_request_stats = MagicMock(return_value={"additions": 99, "deletions": 1, "total": 100})

        worker = WorkerExecutor(docker_client=mock_docker, gitlab_client=mock_gitlab)

        task = Task(
            id=3,
            project_id=123,
            issue_id=1,
            user_prompt="Add feature",
            priority=2,
            status=TaskStatus.PENDING,
            additions=0,
            deletions=0,
            total_changes=0,
        )

        mock_issue = _make_mock_issue(branch_name="codify-3-p123-i456", target_branch="main")
        mock_db = create_mock_db(task, issue=mock_issue)

        # Simulate logs that contain CODIFY_DIFF and an MR URL
        fake_logs = (
            "Cloning repo...\n"
            "Running claude...\n"
            "http://gitlab.example.com/project/-/merge_requests/42\n"
            "CODIFY_DIFF:+100-50\n"
            "CODIFY_STATS:{\"input_tokens\":1000,\"output_tokens\":200}\n"
        )

        async def run_test():
            with patch.object(worker, '_stream_logs_to_db', new=AsyncMock(return_value=(0, fake_logs, 1))):
                await worker.execute_task(mock_db, task.id)

        asyncio.run(run_test())

        # CODIFY_DIFF is present → no API call needed
        mock_gitlab.get_merge_request_stats.assert_not_called()

        assert task.additions == 100, f"Expected additions=100, got {task.additions}"
        assert task.deletions == 50, f"Expected deletions=50, got {task.deletions}"
        assert task.total_changes == 150, f"Expected total_changes=150, got {task.total_changes}"

        print("✓ Worker saves MR stats from CODIFY_DIFF log line")
        print(f"  - Additions: +{task.additions}")
        print(f"  - Deletions: -{task.deletions}")
        print(f"  - Total: {task.total_changes}")


def test_worker_handles_missing_mr_stats():
    """Test fallback to GitLab API when CODIFY_DIFF is absent; None API result leaves stats at 0."""
    print("\n" + "=" * 60)
    print("Testing: Worker falls back to GitLab API when CODIFY_DIFF absent")
    print("=" * 60)

    mock_settings = MagicMock()
    mock_settings.gitlab_url = "http://gitlab.example.com"
    mock_settings.gitlab_bot_token = "test-token"
    mock_settings.worker_image = "test-worker:latest"
    mock_settings.task_timeout = 1800
    mock_settings.anthropic_base_url = "http://localhost:11434/v1"
    mock_settings.anthropic_api_key = "test-key"
    mock_settings.anthropic_model = "claude-sonnet-4-20250514"
    mock_settings.default_target_branch = "main"
    mock_settings.max_retries = 0
    mock_settings.backend_url = "http://localhost:8000"

    with patch('app.core.worker.get_settings', return_value=mock_settings):
        from app.core.worker import WorkerExecutor
        from app.models import Task, TaskStatus

        mock_gitlab = MagicMock()
        mock_docker = MagicMock()
        mock_container = MockContainer()
        mock_docker.create_container.return_value = mock_container

        # API returns None (unavailable) — must be AsyncMock since it's awaited
        mock_gitlab.get_merge_request_stats = AsyncMock(return_value=None)

        worker = WorkerExecutor(docker_client=mock_docker, gitlab_client=mock_gitlab)

        task = Task(
            id=4,
            project_id=123,
            issue_id=1,
            user_prompt="Add feature",
            priority=2,
            status=TaskStatus.PENDING,
            additions=0,
            deletions=0,
            total_changes=0,
        )

        # target_branch=None skips MR creation; MR iid comes from log parsing
        mock_issue = _make_mock_issue(branch_name="codify-4-p123-i456", target_branch=None)
        mock_db = create_mock_db(task, issue=mock_issue)

        # Logs without CODIFY_DIFF → fallback to GitLab API
        fake_logs = (
            "Cloning repo...\n"
            "http://gitlab.example.com/project/-/merge_requests/42\n"
            "CODIFY_STATS:{\"input_tokens\":500,\"output_tokens\":100}\n"
        )

        async def run_test():
            with patch.object(worker, '_stream_logs_to_db', new=AsyncMock(return_value=(0, fake_logs, 1))):
                await worker.execute_task(mock_db, task.id)

        asyncio.run(run_test())

        # Fallback API was called
        mock_gitlab.get_merge_request_stats.assert_called_once_with(123, 42)

        # API returned None → stats remain 0
        assert task.additions == 0
        assert task.deletions == 0
        assert task.total_changes == 0

        print("✓ Worker falls back to API and leaves stats at 0 when API returns None")


if __name__ == "__main__":
    print("=" * 60)
    print("Running MR Change Stats Tests")
    print("=" * 60)

    test_gitlab_get_mr_stats_with_changes_count()
    test_gitlab_get_mr_stats_from_diff()
    test_worker_saves_mr_stats_after_completion()
    test_worker_handles_missing_mr_stats()

    print("\n" + "=" * 60)
    print("All MR Change Stats Tests Passed!")
    print("=" * 60)
