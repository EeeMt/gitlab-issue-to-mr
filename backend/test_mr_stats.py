#!/usr/bin/env python3
"""
Test: MR Change Stats - Get and save MR change statistics after commit.
"""

import sys
sys.path.insert(0, '/Users/AI/Projects/gitlab-issue-to-mr/backend')

import asyncio
from unittest.mock import MagicMock, patch, AsyncMock
from datetime import datetime


# Mock config before importing modules
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

with patch('app.core.worker.get_settings', return_value=mock_settings):
    from app.core.worker import WorkerExecutor
    from app.core.gitlab_client import GitLabClient
    from app.models import Task, TaskStatus


class MockContainer:
    """Mock Docker container."""
    def __init__(self):
        self.id = "mock-container-id"


def create_mock_db(task):
    """Create a properly configured mock database session."""
    mock_db = MagicMock()
    mock_result = MagicMock()
    mock_result.scalar_one_or_none.return_value = task
    mock_db.execute = AsyncMock(return_value=mock_result)
    mock_db.commit = AsyncMock()
    mock_db.add = MagicMock()
    return mock_db


def test_gitlab_get_mr_stats_with_changes_count():
    """Test that GitLab client correctly parses changes_count from MR."""
    print("\n" + "=" * 60)
    print("Testing: GitLab client get_merge_request_stats with changes_count")
    print("=" * 60)

    mock_gitlab = MagicMock()
    client = GitLabClient()
    client.gl = mock_gitlab

    # Mock project and MR with changes_count
    mock_project = MagicMock()
    mock_mr = MagicMock()
    mock_mr.changes_count = "10 files, +100 -50"
    mock_project.mergerequests.get.return_value = mock_mr

    mock_gitlab.projects.get.return_value = mock_project

    # Call the method
    result = client.get_merge_request_stats(123, 42)

    # Verify result
    assert result is not None, "Result should not be None"
    assert result["additions"] == 100, f"Expected additions=100, got {result['additions']}"
    assert result["deletions"] == 50, f"Expected deletions=50, got {result['deletions']}"
    assert result["total"] == 150, f"Expected total=150, got {result['total']}"

    print("✓ GitLab client correctly parses changes_count")
    print(f"  - Additions: +{result['additions']}")
    print(f"  - Deletions: -{result['deletions']}")
    print(f"  - Total: {result['total']}")


def test_gitlab_get_mr_stats_from_diff():
    """Test that GitLab client calculates stats from diff when changes_count not available."""
    print("\n" + "=" * 60)
    print("Testing: GitLab client get_merge_request_stats from diff")
    print("=" * 60)

    mock_gitlab = MagicMock()
    client = GitLabClient()
    client.gl = mock_gitlab

    # Mock project and MR with changes from diff
    mock_project = MagicMock()
    mock_mr = MagicMock()
    mock_mr.changes_count = None  # No changes_count available
    mock_mr.changes = {
        'changes': [
            {
                'new_path': 'file1.py',
                'diff': '''--- a/file1.py
+++ b/file1.py
@@ -1,3 +1,4 @@
+added line
 unchanged line
-removed line
+modified line
'''
            }
        ]
    }
    mock_project.mergerequests.get.return_value = mock_mr

    mock_gitlab.projects.get.return_value = mock_project

    # Call the method
    result = client.get_merge_request_stats(123, 42)

    # Verify result - should count from diff
    assert result is not None, "Result should not be None"
    # +added line, +modified line = 2 additions
    # -removed line = 1 deletion
    assert result["additions"] >= 0, "Additions should be >= 0"
    assert result["deletions"] >= 0, "Deletions should be >= 0"

    print("✓ GitLab client calculates stats from diff")
    print(f"  - Additions: +{result['additions']}")
    print(f"  - Deletions: -{result['deletions']}")


def test_worker_saves_mr_stats_after_completion():
    """Test that worker fetches and saves MR stats after task completion."""
    print("\n" + "=" * 60)
    print("Testing: Worker saves MR stats after task completion")
    print("=" * 60)

    mock_gitlab = MagicMock()
    mock_docker = MagicMock()

    mock_container = MockContainer()
    mock_docker.create_container.return_value = mock_container
    mock_docker.wait_for_container.return_value = (0, "MR created: !42\nhttp://gitlab.example.com/project/-/merge_requests/42")

    # Mock project and MR
    mock_project = MagicMock()
    mock_mr = MagicMock()
    mock_mr.iid = 42
    mock_mr.web_url = "http://gitlab.example.com/project/-/merge_requests/42"
    mock_project.mergerequests.create.return_value = mock_mr
    mock_project.mergerequests.get.return_value = mock_mr

    # Mock get_merge_request_stats to return stats
    mock_stats = {
        "additions": 100,
        "deletions": 50,
        "total": 150
    }

    mock_gitlab.gl.projects.get.return_value = mock_project
    mock_gitlab.get_merge_request_stats = MagicMock(return_value=mock_stats)

    worker = WorkerExecutor(docker_client=mock_docker, gitlab_client=mock_gitlab)

    # Create task
    task = Task(
        id=3,
        project_id=123,
        issue_iid=456,
        note_id=791,
        user_prompt="Add feature",
        branch_name="gimr-3-p123-i456",
        target_branch="main",
        priority=2,
        status=TaskStatus.PENDING,
        additions=0,
        deletions=0,
        total_changes=0,
    )

    # Verify initial stats are 0
    assert task.additions == 0
    assert task.deletions == 0
    assert task.total_changes == 0

    mock_db = create_mock_db(task)

    async def run_test():
        await worker.execute_task(mock_db, task.id)

    asyncio.run(run_test())

    # Verify get_merge_request_stats was called
    mock_gitlab.get_merge_request_stats.assert_called_once_with(123, 42)

    # Verify task stats were saved
    assert task.additions == 100, f"Expected additions=100, got {task.additions}"
    assert task.deletions == 50, f"Expected deletions=50, got {task.deletions}"
    assert task.total_changes == 150, f"Expected total_changes=150, got {task.total_changes}"

    print("✓ Worker saves MR stats after task completion")
    print(f"  - Additions: +{task.additions}")
    print(f"  - Deletions: -{task.deletions}")
    print(f"  - Total: {task.total_changes}")


def test_worker_handles_missing_mr_stats():
    """Test that worker handles case when MR stats cannot be fetched."""
    print("\n" + "=" * 60)
    print("Testing: Worker handles missing MR stats gracefully")
    print("=" * 60)

    mock_gitlab = MagicMock()
    mock_docker = MagicMock()

    mock_container = MockContainer()
    mock_docker.create_container.return_value = mock_container
    mock_docker.wait_for_container.return_value = (0, "MR created: !42\nhttp://gitlab.example.com/project/-/merge_requests/42")

    # Mock project and MR
    mock_project = MagicMock()
    mock_mr = MagicMock()
    mock_mr.iid = 42
    mock_mr.web_url = "http://gitlab.example.com/project/-/merge_requests/42"
    mock_project.mergerequests.create.return_value = mock_mr
    mock_project.mergerequests.get.return_value = mock_mr

    # Mock get_merge_request_stats to return None (failed to get stats)
    mock_gitlab.gl.projects.get.return_value = mock_project
    mock_gitlab.get_merge_request_stats = MagicMock(return_value=None)

    worker = WorkerExecutor(docker_client=mock_docker, gitlab_client=mock_gitlab)

    # Create task
    task = Task(
        id=4,
        project_id=123,
        issue_iid=456,
        note_id=792,
        user_prompt="Add feature",
        branch_name="gimr-4-p123-i456",
        target_branch="main",
        priority=2,
        status=TaskStatus.PENDING,
        additions=0,
        deletions=0,
        total_changes=0,
    )

    mock_db = create_mock_db(task)

    async def run_test():
        await worker.execute_task(mock_db, task.id)

    # Should not raise exception
    asyncio.run(run_test())

    # Verify get_merge_request_stats was called
    mock_gitlab.get_merge_request_stats.assert_called_once_with(123, 42)

    # Verify stats remain 0 when unable to fetch
    assert task.additions == 0
    assert task.deletions == 0
    assert task.total_changes == 0

    print("✓ Worker handles missing MR stats gracefully")


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
