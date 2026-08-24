#!/usr/bin/env python3
"""
Unit tests for manual task creation API.
"""

import hashlib
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import UTC, datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

from app.api.tasks import (
    CreateTaskRequest,
    RescheduleTaskRequest,
    reschedule_task,
)
from app.core.harness_protocol import HARNESS_CONTRACT_VERSION_V2
from app.core.scheduling import normalize_scheduled_datetime, resolve_scheduled_at
from app.core.task_helpers import _can_manage_task
from app.core.worker_runtime_bundle import (
    adapter_digest_from_manifest_files,
    bundle_manifest_digest_from_files,
)
from app.dependencies.project_access import ProjectAccessScope
from app.models import Task, TaskStatus, TaskWorkerProfileSnapshot, User, WorkerRuntimeBundle

_V2_IMAGE_IDENTITY = {
    "schema": "codify.worker-image-identity/v1",
    "daemon_key": "tcp://worker.example:2376",
    "image_reference": "registry.example/worker@sha256:" + "c" * 64,
    "image_id": "sha256:" + "d" * 64,
    "runtime_platform": "linux/amd64",
    "cli_artifact_lock_sha256": "e" * 64,
}
_V2_FILES = [
    {
        "path": "worker-entrypoint/harness/runner.sh",
        "size": 0,
        "sha256": hashlib.sha256(b"").hexdigest(),
    }
]


def _v2_evidence(harness_key: str) -> dict[str, object]:
    return {
        "schema": "codify.worker-harness-verification/v1",
        "harness_key": harness_key,
        "contract_version": HARNESS_CONTRACT_VERSION_V2,
        "adapter": {
            "version": "1.0.0",
            "digest": adapter_digest_from_manifest_files(_V2_FILES, harness_key),
        },
        "verification_input_digest": "f" * 64,
        "image_identity": dict(_V2_IMAGE_IDENTITY),
        "generation": 1,
        "verified_at": "2026-08-24T00:00:00+00:00",
    }


def _v2_bundle_digest(harness_key: str) -> str:
    payload = {
        "files_digest": bundle_manifest_digest_from_files(_V2_FILES),
        "worker_image_identity": _V2_IMAGE_IDENTITY,
        "harness_verification_evidence": _v2_evidence(harness_key),
    }
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def _attach_v2_execution_contract(task: Task) -> None:
    """Attach the immutable V2 snapshot and bundle required by writers."""
    harness_key = "claude"
    evidence = _v2_evidence(harness_key)
    bundle_digest = _v2_bundle_digest(harness_key)
    snapshot = TaskWorkerProfileSnapshot(
        task_id=task.id,
        worker_profile_id=1,
        profile_name="Test worker",
        image=_V2_IMAGE_IDENTITY["image_reference"],
        harness_key=harness_key,
        harness_config_snapshot={
            "requested_runtime_contract_version": HARNESS_CONTRACT_VERSION_V2,
            "v2_worker_image_identity": dict(_V2_IMAGE_IDENTITY),
            "v2_harness_verification_evidence": evidence,
        },
        effective_configuration_digest=evidence["verification_input_digest"],
        runtime_contract_version=HARNESS_CONTRACT_VERSION_V2,
        orchestration_version="1.0.0",
        runtime_bundle_digest=bundle_digest,
    )
    bundle = WorkerRuntimeBundle(
        id=1,
        digest=bundle_digest,
        bundle_bytes=b"",
        contract_version=HARNESS_CONTRACT_VERSION_V2,
        orchestration_version="1.0.0",
        manifest={
            "schema": "codify.worker.runtime-manifest/v2",
            "runtime_platform": "linux/amd64",
            "worker_image_identity": dict(_V2_IMAGE_IDENTITY),
            "harness_verification_evidence": evidence,
            "files": [dict(item) for item in _V2_FILES],
            "bundle_digest": bundle_digest,
            "adapters": {
                "claude": {
                    "adapter": dict(evidence["adapter"])
                }
            },
        },
        size_bytes=0,
    )
    task.worker_profile_snapshot = snapshot
    task.runtime_bundle = bundle


class TestCreateTaskRequest:
    """Test CreateTaskRequest model validation."""

    def test_valid_immediate_task(self):
        """Test creating a task with immediate execution."""
        request = CreateTaskRequest(
            provider_id=1,
            issue_id=1,
            user_prompt="Test prompt",
            priority=0,
        )
        assert request.issue_id == 1
        assert request.user_prompt == "Test prompt"
        assert request.priority == 0
        assert request.delay_seconds is None
        assert request.scheduled_datetime is None

    def test_task_with_delay(self):
        """Test creating a task with delay."""
        request = CreateTaskRequest(
            provider_id=1,
            issue_id=1,
            user_prompt="Test prompt",
            delay_seconds=300,
        )
        assert request.delay_seconds == 300
        assert request.scheduled_datetime is None

    def test_task_with_scheduled_datetime(self):
        """Test creating a task with scheduled datetime."""
        scheduled = datetime.now(UTC) + timedelta(days=30)
        request = CreateTaskRequest(
            provider_id=1,
            issue_id=1,
            user_prompt="Test prompt",
            scheduled_datetime=scheduled,
        )
        assert request.scheduled_datetime == scheduled
        assert request.delay_seconds is None

    def test_task_default_values(self):
        """Test default values for CreateTaskRequest."""
        request = CreateTaskRequest(
            provider_id=1,
            issue_id=1,
            user_prompt="Test prompt",
        )
        assert request.priority == 0
        assert request.user_prompt == "Test prompt"

    def test_same_delay_seconds_zero_is_rejected(self):
        """Test that delay_seconds=0 is rejected."""
        with pytest.raises(ValidationError, match="Delay seconds must be greater than 0"):
            CreateTaskRequest(
                provider_id=1,
                issue_id=1,
                user_prompt="Test prompt",
                delay_seconds=0,
            )

    def test_task_priority_p0(self):
        """Test P0 priority."""
        request = CreateTaskRequest(
            provider_id=1,
            issue_id=1,
            user_prompt="Test prompt",
            priority=0,
        )
        assert request.priority == 0

    def test_task_priority_p1(self):
        """Test P1 priority."""
        request = CreateTaskRequest(
            provider_id=1,
            issue_id=1,
            user_prompt="Test prompt",
            priority=1,
        )
        assert request.priority == 1

    def test_task_priority_p2(self):
        """Test P2 priority."""
        request = CreateTaskRequest(
            provider_id=1,
            issue_id=1,
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
    """Test Task model for new issue-based tasks."""

    def test_task_default_retry_fields(self):
        """Test is_retry defaults to False and retry_source_task_id is None."""
        task = Task(
            project_id=1,
            user_prompt="Test prompt",
        )
        assert task.is_retry is None or task.is_retry is False
        assert task.retry_source_task_id is None

    def test_task_with_issue_id(self):
        """Test task with issue_id set."""
        task = Task(
            project_id=1,
            user_prompt="Test prompt",
            issue_id=42,
        )
        assert task.issue_id == 42

    def test_task_with_all_fields(self):
        """Test task with all fields populated."""
        task = Task(
            project_id=1,
            issue_id=42,
            user_prompt="Test prompt",
            is_retry=True,
            retry_source_task_id=10,
        )
        assert task.issue_id == 42
        assert task.is_retry is True
        assert task.retry_source_task_id == 10


class TestScheduledAtCalculation:
    """Test scheduled_at calculation logic."""

    def test_no_scheduling(self):
        """Test no scheduling means immediate execution."""
        request = CreateTaskRequest(
            provider_id=1,
            issue_id=1,
            user_prompt="Test prompt",
        )
        scheduled_at = None
        if request.scheduled_datetime:
            scheduled_at = request.scheduled_datetime
        elif request.delay_seconds:
            scheduled_at = datetime.now(UTC) + timedelta(seconds=request.delay_seconds)

        assert scheduled_at is None

    def test_delay_scheduling(self):
        """Test delay scheduling calculation."""
        request = CreateTaskRequest(
            provider_id=1,
            issue_id=1,
            user_prompt="Test prompt",
            delay_seconds=300,
        )

        now = datetime.now(UTC)
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
        scheduled_time = datetime.now(UTC) + timedelta(days=30)
        request = CreateTaskRequest(
            provider_id=1,
            issue_id=1,
            user_prompt="Test prompt",
            scheduled_datetime=scheduled_time,
        )

        scheduled_at = None
        if request.scheduled_datetime:
            scheduled_at = request.scheduled_datetime
        elif request.delay_seconds:
            scheduled_at = datetime.now(UTC) + timedelta(seconds=request.delay_seconds)

        assert scheduled_at == scheduled_time

    def test_absolute_takes_precedence(self):
        """Test absolute datetime takes precedence over delay."""
        scheduled_time = datetime.now(UTC) + timedelta(days=30)
        request = CreateTaskRequest(
            provider_id=1,
            issue_id=1,
            user_prompt="Test prompt",
            delay_seconds=300,
            scheduled_datetime=scheduled_time,
        )

        # Simulating the logic from create_task endpoint
        scheduled_at = None
        if request.scheduled_datetime:
            scheduled_at = request.scheduled_datetime
        elif request.delay_seconds:
            scheduled_at = datetime.now(UTC) + timedelta(seconds=request.delay_seconds)

        # Absolute time should take precedence
        assert scheduled_at == scheduled_time

    def test_timezone_aware_scheduled_datetime_is_normalized_to_naive_utc(self):
        """Test timezone-aware datetimes are normalized before DB storage."""
        # Use a fixed future date: +30 days, 10 hours offset -> subtract 10 hours
        scheduled_time = datetime(2030, 6, 15, 22, 32, 34, tzinfo=timezone(timedelta(hours=8)))

        normalized = normalize_scheduled_datetime(scheduled_time)

        # 22:32:34 +08:00 -> 14:32:34 UTC (subtract 8 hours)
        assert normalized == datetime(2030, 6, 15, 14, 32, 34)
        assert normalized.tzinfo is None

    def test_resolve_scheduled_at_normalizes_absolute_datetime(self):
        """Test absolute scheduled datetimes are converted to naive UTC."""
        # Use a fixed future date in UTC
        scheduled_time = datetime(2030, 6, 15, 14, 32, 34, tzinfo=UTC)

        scheduled_at = resolve_scheduled_at(scheduled_time, None)

        assert scheduled_at == datetime(2030, 6, 15, 14, 32, 34)
        assert scheduled_at.tzinfo is None


class TestRescheduleTask:
    @pytest.mark.asyncio
    async def test_reschedule_task_updates_pending_scheduled_task(self):
        now = datetime.now(UTC).replace(tzinfo=None)
        task = Task(
            id=1,
            project_id=1,
            user_prompt="Test prompt",
            status=TaskStatus.PENDING,
            scheduled_at=now + timedelta(hours=1),
            created_at=now,
            updated_at=now,
        )
        _attach_v2_execution_contract(task)
        request = RescheduleTaskRequest(scheduled_datetime=now + timedelta(hours=2))
        db = AsyncMock()
        db.execute.return_value = MagicMock(scalar_one_or_none=lambda: task)
        access_scope = ProjectAccessScope(is_unrestricted=True, accessible_projects=[])
        slot_info = MagicMock(is_full=False, enforce=True)
        schedule_window = {
            "has_valid_window": True,
            "min_scheduled_at": None,
            "min_source_task_id": None,
            "max_scheduled_at": None,
            "max_source_task_id": None,
        }

        with (
            patch(
                "app.api.task_action_routes.get_project_metadata",
                new=AsyncMock(return_value={}),
            ),
            patch(
                "app.core.issue_task_order.validate_schedule_time_locked",
                new=AsyncMock(),
            ),
            patch(
                "app.core.slot_capacity.check_slot_capacity",
                new=AsyncMock(return_value=slot_info),
            ),
            patch(
                "app.api.task_responses.compute_task_queue_contexts",
                new=AsyncMock(return_value={}),
            ),
            patch(
                "app.core.issue_task_order.compute_schedule_window",
                new=AsyncMock(return_value=schedule_window),
            ),
            patch(
                "app.api.task_operations.get_effective_settings",
                return_value=SimpleNamespace(harness_execution_mode="dual_canary"),
            ),
        ):
            result = await reschedule_task(
                task_id=1,
                request=request,
                db=db,
                current_user=None,
                access_scope=access_scope,
            )

        assert task.scheduled_at is not None
        assert abs((task.scheduled_at - (now + timedelta(hours=2))).total_seconds()) < 1
        db.commit.assert_awaited_once()
        assert db.refresh.await_count == 2
        db.refresh.assert_any_await(
            task,
            attribute_names=["id", "status", "created_at", "updated_at"],
        )
        db.refresh.assert_any_await(
            task.worker_profile_snapshot,
            attribute_names=[
                "task_id",
                "worker_profile_id",
                "profile_name",
                "image",
                "runtime_mode",
                "worker_kit_version",
                "skill_selection_source",
                "created_at",
            ],
        )
        assert result["scheduled_at"] == task.scheduled_at.isoformat()

    @pytest.mark.asyncio
    async def test_reschedule_task_rejects_non_pending_task(self):
        task = Task(
            id=1,
            project_id=1,
            user_prompt="Test prompt",
            status=TaskStatus.RUNNING,
            scheduled_at=datetime.now(UTC) + timedelta(hours=1),
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        request = RescheduleTaskRequest(scheduled_datetime=datetime.now(UTC) + timedelta(hours=2))
        db = AsyncMock()
        db.execute.return_value = MagicMock(scalar_one_or_none=lambda: task)
        access_scope = ProjectAccessScope(is_unrestricted=True, accessible_projects=[])

        with pytest.raises(
            HTTPException, match="Task must be in PENDING or QUEUED status to reschedule"
        ):
            await reschedule_task(
                task_id=1,
                request=request,
                db=db,
                current_user=None,
                access_scope=access_scope,
            )

    @pytest.mark.asyncio
    async def test_reschedule_task_rejects_immediate_task(self):
        task = Task(
            id=1,
            project_id=1,
            user_prompt="Test prompt",
            status=TaskStatus.PENDING,
            scheduled_at=None,
            created_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        request = RescheduleTaskRequest(scheduled_datetime=datetime.now(UTC) + timedelta(hours=2))
        db = AsyncMock()
        db.execute.return_value = MagicMock(scalar_one_or_none=lambda: task)
        access_scope = ProjectAccessScope(is_unrestricted=True, accessible_projects=[])

        with pytest.raises(
            HTTPException, match="Only scheduled or queued tasks can update their scheduled time"
        ):
            await reschedule_task(
                task_id=1,
                request=request,
                db=db,
                current_user=None,
                access_scope=access_scope,
            )

    @pytest.mark.asyncio
    async def test_reschedule_task_rejects_other_users(self):
        now = datetime.now(UTC)
        task = Task(
            id=1,
            project_id=1,
            user_prompt="Test prompt",
            status=TaskStatus.PENDING,
            scheduled_at=now + timedelta(hours=1),
            initiator_user_id=10,
            initiator_gitlab_user_id=100,
            created_at=now,
            updated_at=now,
        )
        request = RescheduleTaskRequest(scheduled_datetime=now + timedelta(hours=2))
        db = AsyncMock()
        db.execute.return_value = MagicMock(scalar_one_or_none=lambda: task)
        access_scope = ProjectAccessScope(is_unrestricted=True, accessible_projects=[])
        current_user = User(
            id=11, gitlab_user_id=101, username="other", platform_role="platform_user"
        )

        with patch(
            "app.core.task_helpers.get_effective_settings",
            return_value=MagicMock(oidc_enabled=True),
        ):
            with pytest.raises(HTTPException, match="You may only operate on your own tasks"):
                await reschedule_task(
                    task_id=1,
                    request=request,
                    db=db,
                    current_user=current_user,
                    access_scope=access_scope,
                )


class TestTaskOperatorPermissions:
    def test_can_manage_task_allows_admin(self):
        task = Task(project_id=1, user_prompt="Test", initiator_user_id=10)
        current_user = User(
            id=99, gitlab_user_id=999, username="admin", platform_role="platform_admin"
        )

        with patch(
            "app.core.task_helpers.get_effective_settings",
            return_value=MagicMock(oidc_enabled=True),
        ):
            assert _can_manage_task(task, current_user) is True

    def test_can_manage_task_allows_owner_by_dashboard_user_id(self):
        task = Task(project_id=1, user_prompt="Test", initiator_user_id=10)
        current_user = User(
            id=10, gitlab_user_id=999, username="owner", platform_role="platform_user"
        )

        with patch(
            "app.core.task_helpers.get_effective_settings",
            return_value=MagicMock(oidc_enabled=True),
        ):
            assert _can_manage_task(task, current_user) is True

    def test_can_manage_task_allows_owner_by_gitlab_user_id(self):
        task = Task(project_id=1, user_prompt="Test", initiator_gitlab_user_id=123)
        current_user = User(
            id=10, gitlab_user_id=123, username="owner", platform_role="platform_user"
        )

        with patch(
            "app.core.task_helpers.get_effective_settings",
            return_value=MagicMock(oidc_enabled=True),
        ):
            assert _can_manage_task(task, current_user) is True

    def test_can_manage_task_rejects_other_user(self):
        task = Task(
            project_id=1, user_prompt="Test", initiator_user_id=10, initiator_gitlab_user_id=123
        )
        current_user = User(
            id=11, gitlab_user_id=456, username="other", platform_role="platform_user"
        )

        with patch(
            "app.core.task_helpers.get_effective_settings",
            return_value=MagicMock(oidc_enabled=True),
        ):
            assert _can_manage_task(task, current_user) is False


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
