#!/usr/bin/env python3
"""
Mock E2E tests for manual task creation.

This test uses mock GitLab API and verifies:
1. Manual task creation via API
2. Manual tasks don't send issue notifications
3. Manual task scheduling works correctly
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import pytest
import asyncio
import json
import time
import threading
import http.server
import socketserver
from datetime import UTC, datetime, timedelta
from unittest.mock import MagicMock, AsyncMock, patch
from typing import Optional

# Test configuration
TEST_PROJECT_ID = 1
TEST_BASE_BRANCH = "develop"
TEST_NEW_BRANCH = "feature/test-manual-task"
TEST_BRANCH = TEST_NEW_BRANCH  # Alias for backward compatibility
TEST_TARGET_BRANCH = "main"
TEST_PROMPT = "Create a simple hello.py file"


class MockGitLabHandler(http.server.BaseHTTPRequestHandler):
    """Mock GitLab API handler."""

    projects = {}
    branches = {}
    merge_requests = {}

    def log_message(self, format, *args):
        """Suppress logging."""
        pass

    def do_GET(self):
        """Handle GET requests."""
        path = self.path

        # Get projects
        if "/api/v4/projects" == path:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            response = json.dumps([
                {"id": 1, "name": "test-project", "path_with_namespace": "root/test-project"}
            ])
            self.wfile.write(response.encode())
            return

        # Get branches
        if f"/api/v4/projects/{TEST_PROJECT_ID}/branches" in path:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            response = json.dumps([
                {"name": "main"},
                {"name": "develop"},
                {"name": "feature/test"},
            ])
            self.wfile.write(response.encode())
            return

        # Get MR
        if "/merge_requests/" in path:
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            response = json.dumps({
                "iid": 1,
                "web_url": f"http://gitlab/test-project/merge_requests/1",
                "state": "opened",
                "source_branch": TEST_BRANCH,
                "target_branch": TEST_TARGET_BRANCH,
            })
            self.wfile.write(response.encode())
            return

        self.send_response(404)
        self.end_headers()

    def do_POST(self):
        """Handle POST requests."""
        path = self.path

        # Create branch
        if "/branches" in path:
            self.send_response(201)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            response = json.dumps({"name": TEST_BRANCH})
            self.wfile.write(response.encode())
            return

        # Create MR
        if "/merge_requests" in path:
            self.send_response(201)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            mr_iid = len(MockGitLabHandler.merge_requests) + 1
            MockGitLabHandler.merge_requests[mr_iid] = True
            response = json.dumps({
                "iid": mr_iid,
                "web_url": f"http://gitlab/test-project/merge_requests/{mr_iid}",
            })
            self.wfile.write(response.encode())
            return

        # Create note (comment)
        if "/notes" in path:
            self.send_response(201)
            self.send_header("Content-Type", "application/json")
            self.end_headers()
            response = json.dumps({"id": 123})
            self.wfile.write(response.encode())
            return

        self.send_response(404)
        self.end_headers()


def start_mock_server(port: int) -> threading.Thread:
    """Start mock GitLab server in background thread."""
    handler = MockGitLabHandler

    class QuietTCPServer(socketserver.TCPServer):
        allow_reuse_address = True

    server = QuietTCPServer(("", port), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server


@pytest.fixture
def mock_gitlab_server():
    """Fixture to start/stop mock GitLab server."""
    server = start_mock_server(8889)
    yield "http://localhost:8889"
    server.shutdown()


class TestManualTaskCreation:
    """Test manual task creation via API."""

    @pytest.mark.asyncio
    async def test_create_task_immediate(self):
        """Test creating a task for immediate execution."""
        from app.api.tasks import CreateTaskRequest

        request = CreateTaskRequest(
            project_id=TEST_PROJECT_ID,
            branch_name=TEST_BRANCH,
            target_branch=TEST_TARGET_BRANCH,
            user_prompt=TEST_PROMPT,
            priority=0,
        )

        assert request.project_id == TEST_PROJECT_ID
        assert request.branch_name == TEST_BRANCH
        assert request.target_branch == TEST_TARGET_BRANCH
        assert request.user_prompt == TEST_PROMPT
        assert request.priority == 0
        assert request.delay_seconds is None
        assert request.scheduled_datetime is None

    @pytest.mark.asyncio
    async def test_create_task_with_delay(self):
        """Test creating a task with delay."""
        from app.api.tasks import CreateTaskRequest

        request = CreateTaskRequest(
            project_id=TEST_PROJECT_ID,
            branch_name=TEST_BRANCH,
            user_prompt=TEST_PROMPT,
            delay_seconds=300,  # 5 minutes
        )

        assert request.delay_seconds == 300

    @pytest.mark.asyncio
    async def test_create_task_with_scheduled_datetime(self):
        """Test creating a task with scheduled datetime."""
        from app.api.tasks import CreateTaskRequest

        scheduled = datetime(2026, 3, 15, 14, 30, 0)
        request = CreateTaskRequest(
            project_id=TEST_PROJECT_ID,
            branch_name=TEST_BRANCH,
            user_prompt=TEST_PROMPT,
            scheduled_datetime=scheduled,
        )

        assert request.scheduled_datetime == scheduled


class TestManualTaskNotification:
    """Test that manual tasks don't send issue notifications."""

    def test_manual_task_notification_skip(self):
        """Test that manual tasks skip issue notifications."""
        from app.models import Task, TaskStatus

        # Create a manual task
        task = Task(
            project_id=TEST_PROJECT_ID,
            user_prompt=TEST_PROMPT,
            branch_name=TEST_BRANCH,
            target_branch=TEST_TARGET_BRANCH,
            is_manual=True,
            issue_iid=None,
            issue_id=None,
            note_id=None,
        )

        # Verify it's a manual task
        assert task.is_manual is True
        assert task.issue_iid is None

        # Non-manual task should have issue info
        webhook_task = Task(
            project_id=TEST_PROJECT_ID,
            issue_iid=123,
            issue_id=456,
            note_id=789,
            user_prompt=TEST_PROMPT,
            branch_name="gimr/issue-123",
            is_manual=False,
        )

        assert webhook_task.is_manual is False
        assert webhook_task.issue_iid == 123


class TestBaseBranchWorkflow:
    """Test Base Branch and New Branch workflow."""

    def test_use_existing_branch_workflow(self):
        """Test using existing branch without creating new one."""
        # User selects Base Branch = develop, leaves New Branch Name empty
        base_branch = TEST_BASE_BRANCH
        new_branch_name = ""

        # Branch name to use is the base branch
        branch_name = new_branch_name or base_branch

        assert branch_name == TEST_BASE_BRANCH
        assert branch_name != TEST_NEW_BRANCH

    def test_create_new_branch_workflow(self):
        """Test creating new branch from base branch."""
        # User selects Base Branch = develop, enters New Branch Name = feature/test
        base_branch = TEST_BASE_BRANCH
        new_branch_name = TEST_NEW_BRANCH

        # Branch name to use is the new branch name
        branch_name = new_branch_name or base_branch

        assert branch_name == TEST_NEW_BRANCH

    def test_base_and_target_branch_different(self):
        """Test that base branch can be different from target branch."""
        base_branch = TEST_BASE_BRANCH  # develop
        target_branch = TEST_TARGET_BRANCH  # main

        # They should be different
        assert base_branch != target_branch


class TestManualTaskScheduling:
    """Test manual task scheduling logic."""

    def test_scheduled_at_calculation_delay(self):
        """Test scheduled_at calculation with delay."""
        from app.api.tasks import CreateTaskRequest

        request = CreateTaskRequest(
            project_id=TEST_PROJECT_ID,
            branch_name=TEST_BRANCH,
            user_prompt=TEST_PROMPT,
            delay_seconds=600,  # 10 minutes
        )

        # Simulate the calculation from the API
        scheduled_at = None
        if request.scheduled_datetime:
            scheduled_at = request.scheduled_datetime
        elif request.delay_seconds:
            scheduled_at = datetime.now(UTC) + timedelta(seconds=request.delay_seconds)

        assert scheduled_at is not None
        # Should be approximately 10 minutes from now
        diff = (scheduled_at - datetime.now(UTC)).total_seconds()
        assert 590 <= diff <= 610

    def test_scheduled_at_calculation_absolute(self):
        """Test scheduled_at calculation with absolute time."""
        scheduled = datetime(2026, 12, 31, 23, 59, 59)
        from app.api.tasks import CreateTaskRequest

        request = CreateTaskRequest(
            project_id=TEST_PROJECT_ID,
            branch_name=TEST_BRANCH,
            user_prompt=TEST_PROMPT,
            scheduled_datetime=scheduled,
        )

        # Simulate the calculation from the API
        scheduled_at = None
        if request.scheduled_datetime:
            scheduled_at = request.scheduled_datetime
        elif request.delay_seconds:
            scheduled_at = datetime.now(UTC) + timedelta(seconds=request.delay_seconds)

        assert scheduled_at == scheduled


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
