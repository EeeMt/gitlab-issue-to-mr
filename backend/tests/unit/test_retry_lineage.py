"""Unit tests for ``retry_task_record`` lineage branches (EEE-23 F4).

Covers the retry lineage decision in ``app.api.task_creation_service``: a
default ``continue`` retry inherits the tail projection when the source still
matches the queue tail, is rejected with a ``retry_lineage_conflict`` 409 when
the source belongs to an older generation, and an explicit ``fresh_retry``
confirmation advances to a new session generation at the tail.
"""

from __future__ import annotations

from datetime import datetime
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.api.task_creation_service import TaskCreationServices, retry_task_record
from app.api.task_schemas import RetryTaskRequest
from app.models import Task, TaskWorkerProfileSnapshot

SOURCE_PROJECTION = {
    "harness_key": "claude",
    "session_namespace": "claude-ns",
    "generation": 0,
    "reset_task_id": None,
    "reason": "initial",
}


def _source_task(**overrides) -> Task:
    task = Task(
        id=11,
        issue_id=10,
        project_id=3,
        user_prompt="Fix bug",
        priority=2,
        scheduled_at=None,
        is_retry=False,
        retry_source_task_id=None,
        trigger_source="manual",
        ci_failure_run_id=None,
        provider_id=1,
        task_mode="execute",
        require_changes=True,
        session_mode="continue",
        output_session_id="session-1",
        run_instruction_template=None,
        rendered_prompt="Execute Fix bug",
        rendered_prompt_at=datetime(2024, 1, 1, 11, 0, 0),
        issue_sequence=1,
        projected_harness_key=SOURCE_PROJECTION["harness_key"],
        projected_session_namespace=SOURCE_PROJECTION["session_namespace"],
        projected_lineage_generation=SOURCE_PROJECTION["generation"],
        projected_reset_task_id=SOURCE_PROJECTION["reset_task_id"],
        lineage_projection_reason=SOURCE_PROJECTION["reason"],
        input_lineage_reason="resumed",
        provider_runtime_snapshot={"provider_id": 1, "provider_name": "snapshot"},
    )
    task.worker_profile_snapshot = TaskWorkerProfileSnapshot(
        task_id=task.id,
        worker_profile_id=7,
        profile_name="Default",
        image="img",
        volume_mounts=[],
        environment_variables=[],
        pre_script="",
        post_script="",
        default_execute_run_instruction_template="Execute {{user_prompt}}",
        default_plan_run_instruction_template="Plan {{user_prompt}}",
        ci_auto_repair_run_instruction_template="Repair {{issue_title}}",
    )
    for key, value in overrides.items():
        setattr(task, key, value)
    return task


def _make_services(original_task) -> TaskCreationServices:
    return TaskCreationServices(
        require_issue_operator=MagicMock(),
        get_task_with_access_check=AsyncMock(return_value=original_task),
        validate_task_status_for_retry=MagicMock(),
        validate_scheduled_datetime_in_future=AsyncMock(),
        get_usage_quota_service=MagicMock(),
        get_project_metadata=AsyncMock(return_value={}),
        resolve_provider_for_issue=AsyncMock(),
        resolve_worker_profile_for_issue=AsyncMock(),
        prepare_task_runtime_snapshot=AsyncMock(),
        replace_task_worker_snapshot=AsyncMock(),
        clone_task_worker_snapshot=AsyncMock(return_value=MagicMock()),
        bind_runtime_bundle=AsyncMock(),
        select_snapshot_run_instruction_template=MagicMock(),
        render_and_store_task_prompt=AsyncMock(),
        notify_task_retried=AsyncMock(),
    )


def _make_db(issue) -> MagicMock:
    existing_retry = MagicMock()
    existing_retry.scalar_one_or_none.return_value = None
    issue_result = MagicMock()
    issue_result.scalar_one_or_none.return_value = issue
    mock_db = MagicMock()
    mock_db.execute = AsyncMock(side_effect=[existing_retry, issue_result])
    mock_db.refresh = AsyncMock()
    added: list = []
    mock_db.add = MagicMock(side_effect=added.append)

    async def _flush() -> None:
        # Assign transient Task ids the way the real flush would so that
        # fresh retries can self-reference as their own reset task.
        for obj in added:
            if isinstance(obj, Task) and obj.id is None:
                obj.id = 900 + added.index(obj)

    mock_db.flush = AsyncMock(side_effect=_flush)
    mock_db.commit = AsyncMock()
    return mock_db


def _patch_service_tail():
    return (
        patch("app.api.task_creation_service.ensure_issue_order_integrity_locked"),
        patch("app.api.task_creation_service.refresh_task_response_state", new=AsyncMock()),
        patch("app.api.task_creation_service.attach_task_worker_snapshot"),
        patch(
            "app.api.task_creation_service.serialize_task",
            return_value={"id": 12, "is_retry": True},
        ),
        patch(
            "app.api.task_creation_service.compute_task_queue_contexts",
            new=AsyncMock(return_value={}),
        ),
        patch("app.api.task_creation_service.apply_queue_context"),
    )


async def test_continue_retry_inherits_tail_when_source_matches():
    source = _source_task()
    issue = MagicMock()
    issue.id = 10
    issue.status = "open"
    issue.project_id = 3
    mock_db = _make_db(issue)
    services = _make_services(source)

    integrity_report = {
        "repaired_sequences": 0,
        "repaired_projections": 0,
        "blocked": False,
        "max_sequence": 1,
        "tail_projection": dict(SOURCE_PROJECTION),
    }
    patches = _patch_service_tail()
    patches[0].new = AsyncMock(return_value=integrity_report)
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
        await retry_task_record(
            task_id=11,
            request=None,
            db=mock_db,
            current_user=None,
            access_scope=None,
            services=services,
        )

    created = mock_db.add.call_args_list[0].args[0]
    assert created.session_mode == "continue"
    assert created.projected_harness_key == "claude"
    assert created.projected_session_namespace == "claude-ns"
    assert created.projected_lineage_generation == 0
    assert created.projected_reset_task_id is None
    assert created.lineage_projection_reason == "inherited"
    assert created.issue_sequence == 2
    services.notify_task_retried.assert_awaited_once()


async def test_continue_retry_rejects_stale_generation():
    source = _source_task()
    issue = MagicMock()
    issue.id = 10
    issue.status = "open"
    mock_db = _make_db(issue)
    services = _make_services(source)

    tail_projection = {
        "harness_key": "claude",
        "session_namespace": "claude-ns",
        "generation": 1,
        "reset_task_id": 15,
        "reason": "fresh",
    }
    integrity_report = {
        "repaired_sequences": 0,
        "repaired_projections": 0,
        "blocked": False,
        "max_sequence": 2,
        "tail_projection": tail_projection,
    }
    with patch(
        "app.api.task_creation_service.ensure_issue_order_integrity_locked",
        new=AsyncMock(return_value=integrity_report),
    ):
        with pytest.raises(HTTPException) as exc_info:
            await retry_task_record(
                task_id=11,
                request=None,
                db=mock_db,
                current_user=None,
                access_scope=None,
                services=services,
            )

    assert exc_info.value.status_code == 409
    detail = exc_info.value.detail
    assert detail["code"] == "retry_lineage_conflict"
    assert detail["issue_id"] == 10
    assert detail["task_id"] == 11
    assert detail["source_lineage"] == {
        "harness_key": "claude",
        "session_namespace": "claude-ns",
        "generation": 0,
        "reset_task_id": None,
    }
    assert detail["tail_lineage"] == tail_projection
    assert detail["allowed_actions"] == ["fresh_retry"]
    mock_db.add.assert_not_called()


async def test_fresh_retry_confirmation_advances_generation():
    source = _source_task()
    issue = MagicMock()
    issue.id = 10
    issue.status = "open"
    mock_db = _make_db(issue)
    services = _make_services(source)

    tail_projection = {
        "harness_key": "claude",
        "session_namespace": "claude-ns",
        "generation": 1,
        "reset_task_id": 15,
        "reason": "fresh",
    }
    integrity_report = {
        "repaired_sequences": 0,
        "repaired_projections": 0,
        "blocked": False,
        "max_sequence": 2,
        "tail_projection": tail_projection,
    }
    patches = _patch_service_tail()
    patches[0].new = AsyncMock(return_value=integrity_report)
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
        await retry_task_record(
            task_id=11,
            request=RetryTaskRequest(lineage_strategy="fresh_retry"),
            db=mock_db,
            current_user=None,
            access_scope=None,
            services=services,
        )

    created = mock_db.add.call_args_list[0].args[0]
    assert created.projected_harness_key == "claude"
    assert created.projected_session_namespace == "claude-ns"
    assert created.projected_lineage_generation == 2
    assert created.lineage_projection_reason == "fresh"
    # A fresh generation is its own reset point.
    assert created.projected_reset_task_id == created.id
    assert created.issue_sequence == 3
    # The session_mode column stays "continue"; the fresh decision lives in the
    # lineage projection + lineage_strategy, and the runtime derives input reason.
    assert created.session_mode == "continue"


async def test_fresh_retry_is_allowed_even_when_source_is_older():
    # Explicit confirmation must never be rejected by the conflict guard; it
    # must also work when the source projection is stale (older generation).
    source = _source_task(projected_lineage_generation=0)
    issue = MagicMock()
    issue.id = 10
    issue.status = "open"
    mock_db = _make_db(issue)
    services = _make_services(source)

    tail_projection = {
        "harness_key": "claude",
        "session_namespace": "claude-ns",
        "generation": 2,
        "reset_task_id": 21,
        "reason": "fresh",
    }
    integrity_report = {
        "repaired_sequences": 0,
        "repaired_projections": 0,
        "blocked": False,
        "max_sequence": 3,
        "tail_projection": tail_projection,
    }
    patches = _patch_service_tail()
    patches[0].new = AsyncMock(return_value=integrity_report)
    with patches[0], patches[1], patches[2], patches[3], patches[4], patches[5]:
        await retry_task_record(
            task_id=11,
            request=RetryTaskRequest(lineage_strategy="fresh_retry"),
            db=mock_db,
            current_user=None,
            access_scope=None,
            services=services,
        )

    created = mock_db.add.call_args_list[0].args[0]
    assert created.projected_lineage_generation == 3
    assert created.lineage_projection_reason == "fresh"
