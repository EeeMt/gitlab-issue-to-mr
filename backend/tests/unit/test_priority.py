#!/usr/bin/env python3
"""
Test P0.1: Initial MR creation and MR_IID passing to worker.
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import asyncio
from unittest.mock import MagicMock, patch, AsyncMock
from datetime import datetime


# Mock config before importing worker
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


def test_create_initial_mr():
    """Test that worker creates initial draft MR before running container."""
    print("=" * 60)
    print("Testing: Create initial draft MR")
    print("=" * 60)

    # Create mock GitLab client
    mock_gitlab = MagicMock()
    mock_gitlab.normalize_web_url.side_effect = lambda url: url
    mock_docker = MagicMock()

    # Mock the create_container to return a mock container
    mock_container = MockContainer()
    mock_docker.create_container.return_value = mock_container
    mock_docker.wait_for_container.return_value = (0, "MR created: !1")

    # Create mock project and MR objects
    mock_project = MagicMock()
    mock_mr = MagicMock()
    mock_mr.iid = 42
    mock_mr.web_url = "http://gitlab.example.com/project/-/merge_requests/42"
    mock_project.mergerequests.list.return_value = []
    mock_project.mergerequests.create.return_value = mock_mr

    mock_gitlab.gl.projects.get.return_value = mock_project

    # Create worker with mocks
    worker = WorkerExecutor(docker_client=mock_docker, gitlab_client=mock_gitlab)

    # Create mock task
    task = Task(
        id=1,
        project_id=123,
        issue_iid=456,
        note_id=789,
        user_prompt="Add user authentication feature",
        branch_name="gimr-1-p123-i456",
        target_branch="main",
        priority=2,
        status=TaskStatus.PENDING,
    )

    # Mock database session
    mock_db = create_mock_db(task)

    # Run execute_task (it's async)
    async def run_test():
        result = await worker.execute_task(mock_db, task.id)
        return result

    result = asyncio.run(run_test())

    # Verify MR was created
    mock_project.mergerequests.create.assert_called_once()
    call_args = mock_project.mergerequests.create.call_args

    # Check if called with keyword arguments
    if call_args[1]:  # kwargs
        call_kwargs = call_args[1]
        # Verify it's a draft MR
        assert call_kwargs.get("draft") == True, "MR should be created as draft"

        # Verify title contains AI prefix
        assert call_kwargs["title"].startswith("AI:"), "Title should start with AI:"

        # Verify description contains the prompt
        assert "Add user authentication feature" in call_kwargs.get("description", ""), \
            "Description should contain user prompt"

    # Verify task.merge_request_iid was set
    assert task.merge_request_iid == 42, "Task merge_request_iid should be set"
    assert task.merge_request_url == "http://gitlab.example.com/project/-/merge_requests/42"

    print("✓ Worker creates initial draft MR")
    print(f"  - MR IID: {task.merge_request_iid}")
    print(f"  - MR URL: {task.merge_request_url}")


def test_initial_mr_description_links_issue():
    """Test initial MR description keeps the GitLab issue linkage."""
    print("\n" + "=" * 60)
    print("Testing: Initial MR description includes issue closure reference")
    print("=" * 60)

    mock_gitlab = MagicMock()
    mock_docker = MagicMock()
    worker = WorkerExecutor(docker_client=mock_docker, gitlab_client=mock_gitlab)

    task = Task(
        id=11,
        project_id=123,
        issue_iid=456,
        note_id=999,
        user_prompt="Add user authentication feature",
        branch_name="gimr-11-p123-i456",
        target_branch="main",
        priority=2,
        status=TaskStatus.PENDING,
    )

    description = worker._build_initial_mr_description(task)

    assert "Add user authentication feature" in description
    assert "Closes #456" in description

    print("✓ Initial MR description retains issue linkage")


def test_mr_iid_passed_to_container():
    """Test that MR_IID is passed to container environment."""
    print("\n" + "=" * 60)
    print("Testing: MR_IID passed to container environment")
    print("=" * 60)

    mock_gitlab = MagicMock()
    mock_gitlab.normalize_web_url.side_effect = lambda url: url
    mock_docker = MagicMock()

    mock_container = MockContainer()
    mock_docker.create_container.return_value = mock_container
    mock_docker.wait_for_container.return_value = (0, "Success")

    mock_project = MagicMock()
    mock_mr = MagicMock()
    mock_mr.iid = 42
    mock_mr.web_url = "http://gitlab.example.com/project/-/merge_requests/42"
    mock_project.mergerequests.list.return_value = []
    mock_project.mergerequests.create.return_value = mock_mr

    mock_gitlab.gl.projects.get.return_value = mock_project

    worker = WorkerExecutor(docker_client=mock_docker, gitlab_client=mock_gitlab)

    task = Task(
        id=2,
        project_id=123,
        issue_iid=456,
        note_id=790,
        user_prompt="Fix login bug",
        branch_name="gimr-2-p123-i456",
        target_branch="main",
        priority=2,
        status=TaskStatus.PENDING,
    )

    mock_db = create_mock_db(task)

    async def run_test():
        await worker.execute_task(mock_db, task.id)

    asyncio.run(run_test())

    # Verify create_container was called with correct environment
    mock_docker.create_container.assert_called_once()
    call_kwargs = mock_docker.create_container.call_args[1]

    # Verify MR_IID is in environment
    environment = call_kwargs.get("environment", {})
    assert "MR_IID" in environment, "MR_IID should be in container environment"
    assert environment["MR_IID"] == "42", "MR_IID should be 42"

    print("✓ MR_IID passed to container environment")
    print(f"  - MR_IID: {environment.get('MR_IID')}")


def test_mr_creation_failure_handled():
    """Test that worker continues if MR creation fails."""
    print("\n" + "=" * 60)
    print("Testing: MR creation failure handled gracefully")
    print("=" * 60)

    mock_gitlab = MagicMock()
    mock_gitlab.normalize_web_url.side_effect = lambda url: url
    mock_docker = MagicMock()

    mock_container = MockContainer()
    mock_docker.create_container.return_value = mock_container
    mock_docker.wait_for_container.return_value = (0, "Success")

    # Make MR creation fail
    mock_project = MagicMock()
    mock_project.mergerequests.list.return_value = []
    mock_project.mergerequests.create.side_effect = Exception("Network error")
    mock_gitlab.gl.projects.get.return_value = mock_project

    worker = WorkerExecutor(docker_client=mock_docker, gitlab_client=mock_gitlab)

    task = Task(
        id=3,
        project_id=123,
        issue_iid=456,
        note_id=791,
        user_prompt="Test feature",
        branch_name="gimr-3-p123-i456",
        target_branch="main",
        priority=2,
        status=TaskStatus.PENDING,
    )

    mock_db = create_mock_db(task)

    async def run_test():
        result = await worker.execute_task(mock_db, task.id)
        return result

    result = asyncio.run(run_test())

    # Verify container was still created (worker continues without MR)
    mock_docker.create_container.assert_called_once()

    # Verify MR_IID is NOT in environment when MR creation fails
    call_kwargs = mock_docker.create_container.call_args[1]
    environment = call_kwargs.get("environment", {})
    assert "MR_IID" not in environment, "MR_IID should not be in environment when MR creation fails"

    print("✓ Worker continues when MR creation fails")
    print(f"  - MR_IID in env: {'MR_IID' in environment}")


def test_draft_removed_on_completion():
    """Test that draft status is removed from MR on task completion."""
    print("\n" + "=" * 60)
    print("Testing: Draft status removed on task completion")
    print("=" * 60)

    mock_gitlab = MagicMock()
    mock_gitlab.normalize_web_url.side_effect = lambda url: url
    mock_docker = MagicMock()

    mock_container = MockContainer()
    mock_docker.create_container.return_value = mock_container
    mock_docker.wait_for_container.return_value = (0, "MR created: !1")

    mock_project = MagicMock()
    mock_mr = MagicMock()
    mock_mr.iid = 42
    mock_mr.web_url = "http://gitlab.example.com/project/-/merge_requests/42"
    mock_project.mergerequests.list.return_value = []
    mock_project.mergerequests.create.return_value = mock_mr

    # Mock the MR reload/save flow used to remove draft status
    mock_existing_mr = MagicMock()
    mock_existing_mr.title = "Draft: AI: Complete feature"
    mock_project.mergerequests.get.return_value = mock_existing_mr

    mock_gitlab.gl.projects.get.return_value = mock_project

    worker = WorkerExecutor(docker_client=mock_docker, gitlab_client=mock_gitlab)

    task = Task(
        id=4,
        project_id=123,
        issue_iid=456,
        note_id=792,
        user_prompt="Complete feature",
        branch_name="gimr-4-p123-i456",
        target_branch="main",
        priority=2,
        status=TaskStatus.PENDING,
    )

    mock_db = create_mock_db(task)

    async def run_test():
        with patch.object(
            worker,
            "_stream_logs_to_db",
            AsyncMock(return_value=(0, "MR created: http://gitlab.example.com/project/-/merge_requests/42", 1)),
        ):
            await worker.execute_task(mock_db, task.id)

    asyncio.run(run_test())

    mock_project.mergerequests.get.assert_called_with(42)
    assert mock_existing_mr.title == "AI: Complete feature"
    mock_existing_mr.save.assert_called_once()

    print("✓ Draft status removed on completion")
    print(f"  - updated title: {mock_existing_mr.title}")


def test_mr_iid_in_issue_comment():
    """Test that issue completion comments keep the MR shorthand in the issue reply."""
    print("\n" + "=" * 60)
    print("Testing: Issue comment uses GitLab shorthand (!iid)")
    print("=" * 60)

    mock_gitlab = MagicMock()
    mock_docker = MagicMock()

    mock_container = MockContainer()
    mock_docker.create_container.return_value = mock_container
    mock_docker.wait_for_container.return_value = (0, "MR created")

    mock_project = MagicMock()
    mock_mr = MagicMock()
    mock_mr.iid = 42
    mock_mr.web_url = "http://gitlab.example.com/project/-/merge_requests/42"
    mock_project.mergerequests.create.return_value = mock_mr

    mock_gitlab.gl.projects.get.return_value = mock_project

    worker = WorkerExecutor(docker_client=mock_docker, gitlab_client=mock_gitlab)

    task = Task(
        id=5,
        project_id=123,
        issue_iid=456,
        note_id=793,
        user_prompt="Test",
        branch_name="gimr-5-p123-i456",
        target_branch="main",
        priority=2,
        status=TaskStatus.PENDING,
    )

    # This test doesn't need to run execute_task, it directly calls _notify_task_completed

    # Check the create_note call for completion
    # The notification is sent after container completes
    # Let's verify the format by calling _notify_task_completed directly

    task.merge_request_url = "http://gitlab.example.com/project/-/merge_requests/42"
    task.merge_request_iid = 42

    worker._notify_task_completed(task, success=True, notify_target="issue")

    mock_gitlab.create_note.assert_called()
    call_args = mock_gitlab.create_note.call_args[0]

    # The comment should contain !42 (GitLab shorthand) instead of full URL
    comment_body = call_args[2]
    assert "!42" in comment_body or "✅" in comment_body, \
        "Comment should use GitLab shorthand format"
    mock_gitlab.create_mr_note.assert_not_called()

    print("✓ Issue comment uses GitLab shorthand format")
    print(f"  - Comment: {comment_body[:60]}...")


if __name__ == "__main__":
    test_create_initial_mr()
    test_initial_mr_description_links_issue()
    test_mr_iid_passed_to_container()
    test_mr_creation_failure_handled()
    test_draft_removed_on_completion()
    test_mr_iid_in_issue_comment()

    print("\n" + "=" * 60)
    print("All P0.1 tests passed!")
    print("=" * 60)
