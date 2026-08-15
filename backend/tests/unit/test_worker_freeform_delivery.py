"""Unit tests for delayed freeform MR delivery (freeform Task 5).

Freeform tasks defer MR create/reuse to post-push delivery: the container is
started without an ``MR_IID``, and after a canonical finalization the MR is only
created/reused when the task completed with a persisted ``commit_sha``.
"""

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.worker_profiles import TaskWorkerRuntime
from app.core.worker_task_lifecycle import (
    create_execute_container,
    monitor_container_run,
)
from app.models import Issue, Task, TaskStatus


def _runtime():
    return TaskWorkerRuntime(
        image="custom-worker:latest",
        runtime_mode="mounted_kit",
        worker_kit_version="0.1.0",
        worker_kit_path="/opt/codify/worker-kits/0.1.0-linux-amd64",
        codegraph_enabled=True,
        volume_mounts=[],
        environment={},
        pre_script="",
        post_script="",
    )


def _bundle_and_attempt():
    bundle = SimpleNamespace(
        digest="d" * 64,
        contract_version="codify.worker.harness/v1",
        manifest={
            "archive_manifest_digest": "m" * 64,
            "adapters": {"claude": {"version": "1.0.0", "digest": "a" * 64}},
        },
        bundle_bytes=b"runtime-bundle",
    )
    attempt = SimpleNamespace(
        attempt_id="task-12-attempt-1",
        harness_key="claude",
        adapter_version="1.0.0",
    )
    return bundle, attempt


# ---------------------------------------------------------------------------
# Step 1: pre-start MR isolation in create_execute_container
# ---------------------------------------------------------------------------


def _execute_fixtures(
    *,
    task_mode="execute",
    issue_mr_iid=None,
    mr_create_return=(None, None),
    target_branch="main",
):
    task = MagicMock()
    task.id = 12
    task.project_id = 100
    task.ci_failure_run_id = None
    task.trigger_source = "manual"
    task.rendered_prompt = "Prompt"
    task.status = TaskStatus.RUNNING
    task.cancel_requested_at = None
    task.task_mode = task_mode
    task.require_changes = task_mode != "freeform"

    issue = MagicMock()
    issue.id = 1
    issue.merge_request_iid = issue_mr_iid
    issue.merge_request_url = f"http://mr/{issue_mr_iid}" if issue_mr_iid else None
    issue.target_branch = target_branch

    worker = MagicMock()
    worker.gitlab.ensure_project_label = MagicMock()
    worker._create_mr_if_needed = MagicMock(return_value=mr_create_return)
    worker._build_previous_task_summaries = AsyncMock(return_value="Previous summary")
    worker._prepare_container_inputs = AsyncMock(return_value=({"TASK_ID": "12"}, "main"))
    worker._build_container_volumes = MagicMock(
        return_value={"/cache": {"bind": "/cache", "mode": "rw"}}
    )
    worker._get_container_name = MagicMock(return_value="codify-12-issue1")
    worker.docker.pull_image = MagicMock()
    worker.docker.create_container = MagicMock(return_value=SimpleNamespace(id="container-1"))

    settings = SimpleNamespace(
        worker_image="old-worker:latest",
        worker_skip_image_pull=False,
        worker_network="bridge",
    )
    db = MagicMock()
    db.commit = AsyncMock()
    db.flush = AsyncMock()
    db.get = AsyncMock(return_value=None)
    db.refresh = AsyncMock()

    async def _mock_execute(statement, *args, **kwargs):
        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = None
        mock_result.scalars.return_value.all.return_value = []
        return mock_result

    db.execute = AsyncMock(side_effect=_mock_execute)
    bundle, attempt = _bundle_and_attempt()
    return worker, db, task, issue, settings, bundle, attempt


async def _run_create_execute_container(worker, db, task, issue, settings, bundle, attempt):
    with (
        patch(
            "app.core.worker_task_lifecycle.load_task_worker_runtime",
            new=AsyncMock(return_value=_runtime()),
        ),
        patch(
            "app.core.worker_task_lifecycle.build_issue_workspace_paths",
            return_value=SimpleNamespace(issue_root="/tmp/issue-root"),
        ),
        patch(
            "app.core.worker_task_lifecycle.load_bound_runtime_bundle",
            new=AsyncMock(return_value=bundle),
        ),
        patch(
            "app.core.worker_task_lifecycle.create_task_attempt",
            new=AsyncMock(return_value=attempt),
        ),
    ):
        return await create_execute_container(
            worker,
            db,
            settings=settings,
            task=task,
            issue=issue,
            sudo_gl=None,
        )


@pytest.mark.asyncio
async def test_execute_keeps_pre_start_mr_create_and_iid_injection():
    worker, db, task, issue, settings, bundle, attempt = _execute_fixtures(
        task_mode="execute",
        issue_mr_iid=7,
        mr_create_return=(55, "http://mr/55"),
    )

    container = await _run_create_execute_container(worker, db, task, issue, settings, bundle, attempt)

    assert container.id == "container-1"
    worker._create_mr_if_needed.assert_called_once()
    args, _ = worker._prepare_container_inputs.await_args
    assert args[3] == 55


@pytest.mark.asyncio
async def test_freeform_skips_pre_start_mr_and_passes_empty_mr_context():
    worker, db, task, issue, settings, bundle, attempt = _execute_fixtures(
        task_mode="freeform",
        issue_mr_iid=7,
    )

    container = await _run_create_execute_container(worker, db, task, issue, settings, bundle, attempt)

    assert container.id == "container-1"
    worker._create_mr_if_needed.assert_not_called()
    args, _ = worker._prepare_container_inputs.await_args
    assert args[3] is None
    # had_existing_mr remains a pre-run fact: the Issue MR fields are untouched.
    assert issue.merge_request_iid == 7


@pytest.mark.asyncio
async def test_no_target_branch_no_mr_mode_unchanged():
    worker, db, task, issue, settings, bundle, attempt = _execute_fixtures(
        task_mode="execute",
        issue_mr_iid=None,
        target_branch=None,
    )

    container = await _run_create_execute_container(worker, db, task, issue, settings, bundle, attempt)

    assert container.id == "container-1"
    worker._create_mr_if_needed.assert_not_called()
    args, _ = worker._prepare_container_inputs.await_args
    assert args[3] is None


# ---------------------------------------------------------------------------
# Step 2: finalization delivery matrix in monitor_container_run
# ---------------------------------------------------------------------------


def _monitor_fixtures(*, task_mode="execute", issue_mr_iid=None, target_branch="main"):
    task = Task(
        id=12,
        project_id=100,
        issue_id=1,
        user_prompt="Freeform task",
        status=TaskStatus.RUNNING,
        task_mode=task_mode,
        require_changes=task_mode != "freeform",
    )
    issue = Issue(
        id=1,
        title="Issue",
        project_id=100,
        branch_name="codify/issue-1",
        target_branch=target_branch,
        merge_request_iid=issue_mr_iid,
        worker_profile_id=1,
    )
    worker = MagicMock()
    worker._session_factory = MagicMock()
    worker._stream_logs_to_db = AsyncMock(return_value=(0, "logs", 1, False))
    worker._parse_task_result = AsyncMock()
    worker._scrub_sensitive_data = MagicMock(side_effect=lambda x: x)
    worker._sanitize_sensitive_data = MagicMock(side_effect=lambda x: x)
    worker._try_upsert_usage_ledger = AsyncMock()
    worker._send_notifications = AsyncMock()
    worker._send_failure_notifications = AsyncMock()
    worker._remove_mr_draft_status_for_issue = MagicMock()
    worker._update_mr_description_for_issue = AsyncMock()
    worker._create_mr_if_needed = MagicMock(return_value=(55, "http://mr/55"))
    worker.gitlab.ensure_project_label = MagicMock()
    worker.docker.remove_container = MagicMock()
    db = MagicMock()
    db.refresh = AsyncMock()
    db.commit = AsyncMock()
    db.add = MagicMock()
    container = MagicMock()
    return worker, db, task, issue, container


def _parse_cb(status: TaskStatus, commit_sha: str | None):
    async def _parse(task, logs, db, exit_code, **kwargs):
        task.status = status
        task.commit_sha = commit_sha
        if status == TaskStatus.COMPLETED:
            task.completed_at = datetime.now(UTC)

    return _parse


async def _run_monitor(
    worker,
    db,
    task,
    issue,
    container,
    *,
    had_existing_mr=False,
    resume_prefix="",
):
    with (
        patch("app.core.worker_task_lifecycle.poll_task_artifacts", new=AsyncMock()),
        patch("app.core.worker_task_lifecycle._stop_artifact_poller", new=AsyncMock()),
        patch("app.core.worker_task_lifecycle.finalize_task_raw_logs", new=AsyncMock()),
        patch("app.core.worker_task_lifecycle.flush_task_artifacts", new=AsyncMock()),
        patch(
            "app.core.worker_task_lifecycle.reconcile_task_input_session_from_runtime",
            new=AsyncMock(return_value=False),
        ),
        patch(
            "app.core.worker_task_lifecycle._save_delivery_summary_from_container",
            new=AsyncMock(),
        ),
        patch(
            "app.core.worker_task_lifecycle._save_task_metadata_from_container",
            new=MagicMock(),
        ),
    ):
        return await monitor_container_run(
            worker,
            db=db,
            task=task,
            issue=issue,
            container=container,
            settings=SimpleNamespace(task_timeout=1800),
            had_existing_mr=had_existing_mr,
            sudo_gl=None,
            resume_prefix=resume_prefix,
        )


@pytest.mark.asyncio
async def test_freeform_completed_no_commit_no_mr_no_delivery():
    worker, db, task, issue, container = _monitor_fixtures(task_mode="freeform", issue_mr_iid=None)
    worker._parse_task_result = AsyncMock(side_effect=_parse_cb(TaskStatus.COMPLETED, None))

    result = await _run_monitor(worker, db, task, issue, container)

    assert result is True
    worker._create_mr_if_needed.assert_not_called()
    assert issue.merge_request_iid is None
    worker._remove_mr_draft_status_for_issue.assert_not_called()
    worker._update_mr_description_for_issue.assert_not_called()
    worker._send_notifications.assert_not_called()


@pytest.mark.asyncio
async def test_freeform_completed_no_commit_with_existing_mr_leaves_it_untouched():
    worker, db, task, issue, container = _monitor_fixtures(task_mode="freeform", issue_mr_iid=7)
    worker._parse_task_result = AsyncMock(side_effect=_parse_cb(TaskStatus.COMPLETED, None))

    result = await _run_monitor(worker, db, task, issue, container, had_existing_mr=True)

    assert result is True
    worker._create_mr_if_needed.assert_not_called()
    assert issue.merge_request_iid == 7
    worker._remove_mr_draft_status_for_issue.assert_not_called()
    worker._update_mr_description_for_issue.assert_not_called()
    worker._send_notifications.assert_not_called()


@pytest.mark.asyncio
async def test_freeform_delivered_reuses_existing_mr_then_ready_and_description():
    worker, db, task, issue, container = _monitor_fixtures(task_mode="freeform", issue_mr_iid=7)
    worker._parse_task_result = AsyncMock(side_effect=_parse_cb(TaskStatus.COMPLETED, "abc123"))
    worker._create_mr_if_needed = MagicMock(return_value=(7, "http://mr/7"))

    result = await _run_monitor(worker, db, task, issue, container, had_existing_mr=True)

    assert result is True
    worker._create_mr_if_needed.assert_called_once()
    assert worker._create_mr_if_needed.call_args.args[2] is None
    assert issue.merge_request_iid == 7
    worker._remove_mr_draft_status_for_issue.assert_called_once()
    worker._update_mr_description_for_issue.assert_awaited_once()
    worker._send_notifications.assert_awaited_once()


@pytest.mark.asyncio
async def test_freeform_delivered_creates_new_mr_and_persists_association():
    worker, db, task, issue, container = _monitor_fixtures(task_mode="freeform", issue_mr_iid=None)
    worker._parse_task_result = AsyncMock(side_effect=_parse_cb(TaskStatus.COMPLETED, "abc123"))
    worker._create_mr_if_needed = MagicMock(return_value=(55, "http://mr/55"))

    result = await _run_monitor(worker, db, task, issue, container)

    assert result is True
    worker._create_mr_if_needed.assert_called_once()
    assert issue.merge_request_iid == 55
    worker._remove_mr_draft_status_for_issue.assert_called_once()
    worker._update_mr_description_for_issue.assert_awaited_once()
    worker._send_notifications.assert_awaited_once()


@pytest.mark.asyncio
async def test_freeform_failed_does_not_trigger_mr_delivery():
    worker, db, task, issue, container = _monitor_fixtures(task_mode="freeform", issue_mr_iid=None)
    worker._stream_logs_to_db = AsyncMock(return_value=(1, "logs", 1, False))
    worker._parse_task_result = AsyncMock(side_effect=_parse_cb(TaskStatus.FAILED, None))

    result = await _run_monitor(worker, db, task, issue, container)

    assert result is False
    worker._create_mr_if_needed.assert_not_called()
    worker._remove_mr_draft_status_for_issue.assert_not_called()
    worker._update_mr_description_for_issue.assert_not_called()
    worker._send_failure_notifications.assert_awaited_once()


@pytest.mark.asyncio
async def test_execute_completed_keeps_existing_timing_and_notification():
    worker, db, task, issue, container = _monitor_fixtures(task_mode="execute", issue_mr_iid=7)
    worker._parse_task_result = AsyncMock(side_effect=_parse_cb(TaskStatus.COMPLETED, "abc123"))

    result = await _run_monitor(worker, db, task, issue, container, had_existing_mr=True)

    assert result is True
    worker._create_mr_if_needed.assert_not_called()
    worker._remove_mr_draft_status_for_issue.assert_called_once()
    worker._update_mr_description_for_issue.assert_awaited_once()
    worker._send_notifications.assert_awaited_once()


@pytest.mark.asyncio
async def test_resume_freeform_uses_same_commit_gate():
    worker, db, task, issue, container = _monitor_fixtures(task_mode="freeform", issue_mr_iid=None)
    worker._parse_task_result = AsyncMock(side_effect=_parse_cb(TaskStatus.COMPLETED, "abc123"))
    worker._create_mr_if_needed = MagicMock(return_value=(55, "http://mr/55"))

    result = await _run_monitor(
        worker,
        db,
        task,
        issue,
        container,
        resume_prefix=" (resumed)",
    )

    assert result is True
    worker._create_mr_if_needed.assert_called_once()
    assert issue.merge_request_iid == 55


@pytest.mark.asyncio
async def test_freeform_mr_api_failure_preserves_commit_and_skips_fabrication():
    worker, db, task, issue, container = _monitor_fixtures(task_mode="freeform", issue_mr_iid=None)
    worker._parse_task_result = AsyncMock(side_effect=_parse_cb(TaskStatus.COMPLETED, "abc123"))
    worker._create_mr_if_needed = MagicMock(side_effect=RuntimeError("gitlab 500"))

    result = await _run_monitor(worker, db, task, issue, container)

    assert result is True
    assert task.commit_sha == "abc123"
    assert issue.merge_request_iid is None
    worker._create_mr_if_needed.assert_called_once()
    worker._remove_mr_draft_status_for_issue.assert_not_called()
    worker._update_mr_description_for_issue.assert_not_called()
