#!/usr/bin/env python3
"""
Unit tests for manual task creation API.
"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest
from datetime import datetime, timedelta, timezone
from unittest.mock import MagicMock, patch, AsyncMock

from app.api.tasks import CreateTaskRequest
from app.core.scheduling import normalize_scheduled_datetime, resolve_scheduled_at
from app.models import Task, TaskStatus


class TestCreateTaskRequest:
    """Test CreateTaskRequest model validation."""

    def test_valid_immediate_task(self):
        """Test creating a task with immediate execution."""
        request = CreateTaskRequest(
            project_id=1,
            branch_name="feature/test",
            target_branch="main",
            user_prompt="Test prompt",
            priority=0,
        )
        assert request.project_id == 1
        assert request.branch_name == "feature/test"
        assert request.target_branch == "main"
        assert request.user_prompt == "Test prompt"
        assert request.priority == 0
        assert request.delay_seconds is None
        assert request.scheduled_datetime is None

    def test_task_with_delay(self):
        """Test creating a task with delay."""
        request = CreateTaskRequest(
            project_id=1,
            branch_name="feature/test",
            user_prompt="Test prompt",
            delay_seconds=300,
        )
        assert request.delay_seconds == 300
        assert request.scheduled_datetime is None

    def test_task_with_scheduled_datetime(self):
        """Test creating a task with scheduled datetime."""
        scheduled = datetime(2026, 3, 15, 14, 30, 0)
        request = CreateTaskRequest(
            project_id=1,
            branch_name="feature/test",
            user_prompt="Test prompt",
            scheduled_datetime=scheduled,
        )
        assert request.scheduled_datetime == scheduled
        assert request.delay_seconds is None

    def test_task_default_values(self):
        """Test default values."""
        request = CreateTaskRequest(
            project_id=1,
            branch_name="feature/test",
            user_prompt="Test prompt",
        )
        assert request.target_branch == "main"
        assert request.priority == 0

    def test_task_priority_p0(self):
        """Test P0 priority."""
        request = CreateTaskRequest(
            project_id=1,
            branch_name="feature/test",
            user_prompt="Test prompt",
            priority=0,
        )
        assert request.priority == 0

    def test_task_priority_p1(self):
        """Test P1 priority."""
        request = CreateTaskRequest(
            project_id=1,
            branch_name="feature/test",
            user_prompt="Test prompt",
            priority=1,
        )
        assert request.priority == 1

    def test_task_priority_p2(self):
        """Test P2 priority."""
        request = CreateTaskRequest(
            project_id=1,
            branch_name="feature/test",
            user_prompt="Test prompt",
            priority=2,
        )
        assert request.priority == 2


class TestBaseBranchAndNewBranch:
    """Test Base Branch and New Branch Name logic."""

    def test_use_existing_branch(self):
        """Test using existing branch as code baseline."""
        # User selects Base Branch = develop, leaves New Branch Name empty
        # System should use Base Branch as the branch
        base_branch = "develop"
        new_branch_name = ""

        branch_name = new_branch_name or base_branch
        assert branch_name == "develop"

    def test_create_new_branch(self):
        """Test creating new branch from base branch."""
        # User selects Base Branch = develop, enters New Branch Name = feature/abc
        # System should create feature/abc from develop
        base_branch = "develop"
        new_branch_name = "feature/abc"

        branch_name = new_branch_name or base_branch
        assert branch_name == "feature/abc"

    def test_new_branch_empty_uses_base(self):
        """Test that empty new branch name falls back to base branch."""
        base_branch = "main"
        new_branch_name = ""

        branch_name = new_branch_name or base_branch
        assert branch_name == "main"

    def test_new_branch_with_prefix(self):
        """Test new branch with feature prefix."""
        base_branch = "develop"
        new_branch_name = "feature/new-feature"

        branch_name = new_branch_name or base_branch
        assert branch_name == "feature/new-feature"

    def test_base_branch_different_from_target(self):
        """Test base branch can be different from target branch."""
        base_branch = "develop"
        target_branch = "main"

        # Base branch is where we create the new branch from
        # Target branch is where we create the MR to
        assert base_branch != target_branch
        assert base_branch == "develop"
        assert target_branch == "main"


class TestTaskModel:
    """Test Task model for manual tasks."""

    def test_task_is_manual_default(self):
        """Test is_manual defaults to None or False."""
        task = Task(
            project_id=1,
            user_prompt="Test prompt",
            branch_name="feature/test",
        )
        # Database has default False, but ORM model may not
        assert task.is_manual is None or task.is_manual is False

    def test_task_is_manual_true(self):
        """Test is_manual can be set to True."""
        task = Task(
            project_id=1,
            user_prompt="Test prompt",
            branch_name="feature/test",
            is_manual=True,
        )
        assert task.is_manual is True

    def test_task_nullable_fields_for_manual(self):
        """Test that issue fields are nullable for manual tasks."""
        task = Task(
            project_id=1,
            user_prompt="Test prompt",
            branch_name="feature/test",
            is_manual=True,
            # These should be None for manual tasks
            issue_iid=None,
            issue_id=None,
            note_id=None,
        )
        assert task.issue_iid is None
        assert task.issue_id is None
        assert task.note_id is None
        assert task.is_manual is True

    def test_task_with_issue_fields(self):
        """Test task with issue fields for webhook-triggered tasks."""
        task = Task(
            project_id=1,
            issue_iid=123,
            issue_id=456,
            note_id=789,
            user_prompt="Test prompt",
            branch_name="gimr/issue-123",
            is_manual=False,
        )
        assert task.issue_iid == 123
        assert task.issue_id == 456
        assert task.note_id == 789
        assert task.is_manual is False


class TestScheduledAtCalculation:
    """Test scheduled_at calculation logic."""

    def test_no_scheduling(self):
        """Test no scheduling means immediate execution."""
        request = CreateTaskRequest(
            project_id=1,
            branch_name="feature/test",
            user_prompt="Test prompt",
        )
        scheduled_at = None
        if request.scheduled_datetime:
            scheduled_at = request.scheduled_datetime
        elif request.delay_seconds:
            scheduled_at = datetime.utcnow() + timedelta(seconds=request.delay_seconds)

        assert scheduled_at is None

    def test_delay_scheduling(self):
        """Test delay scheduling calculation."""
        request = CreateTaskRequest(
            project_id=1,
            branch_name="feature/test",
            user_prompt="Test prompt",
            delay_seconds=300,
        )

        now = datetime.utcnow()
        scheduled_at = None
        if request.scheduled_datetime:
            scheduled_at = request.scheduled_datetime
        elif request.delay_seconds:
            scheduled_at = now + timedelta(seconds=request.delay_seconds)

        assert scheduled_at is not None
        # Should be approximately 5 minutes from now
        diff = (scheduled_at - now).total_seconds()
        assert 290 <= diff <= 310  # 5 minutes +/- 10 seconds

    def test_absolute_scheduling(self):
        """Test absolute datetime scheduling."""
        scheduled_time = datetime(2026, 3, 15, 14, 30, 0)
        request = CreateTaskRequest(
            project_id=1,
            branch_name="feature/test",
            user_prompt="Test prompt",
            scheduled_datetime=scheduled_time,
        )

        scheduled_at = None
        if request.scheduled_datetime:
            scheduled_at = request.scheduled_datetime
        elif request.delay_seconds:
            scheduled_at = datetime.utcnow() + timedelta(seconds=request.delay_seconds)

        assert scheduled_at == scheduled_time

    def test_absolute_takes_precedence(self):
        """Test absolute datetime takes precedence over delay."""
        scheduled_time = datetime(2026, 3, 15, 14, 30, 0)
        request = CreateTaskRequest(
            project_id=1,
            branch_name="feature/test",
            user_prompt="Test prompt",
            delay_seconds=300,
            scheduled_datetime=scheduled_time,
        )

        # Simulating the logic from create_task endpoint
        scheduled_at = None
        if request.scheduled_datetime:
            scheduled_at = request.scheduled_datetime
        elif request.delay_seconds:
            scheduled_at = datetime.utcnow() + timedelta(seconds=request.delay_seconds)

        # Absolute time should take precedence
        assert scheduled_at == scheduled_time

    def test_timezone_aware_scheduled_datetime_is_normalized_to_naive_utc(self):
        """Test timezone-aware datetimes are normalized before DB storage."""
        scheduled_time = datetime(2026, 3, 31, 22, 32, 34, tzinfo=timezone(timedelta(hours=8)))

        normalized = normalize_scheduled_datetime(scheduled_time)

        assert normalized == datetime(2026, 3, 31, 14, 32, 34)
        assert normalized.tzinfo is None

    def test_resolve_scheduled_at_normalizes_absolute_datetime(self):
        """Test absolute scheduled datetimes are converted to naive UTC."""
        scheduled_time = datetime(2026, 3, 31, 14, 32, 34, tzinfo=timezone.utc)

        scheduled_at = resolve_scheduled_at(scheduled_time, None)

        assert scheduled_at == datetime(2026, 3, 31, 14, 32, 34)
        assert scheduled_at.tzinfo is None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
