from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.worker_docker_targets import TaskContainerLookupError
from app.core.worker_profiles import TaskWorkerRuntime
from app.core.worker_runtime import build_container_volumes
from app.core.worker_task_artifacts import finalize_task_raw_logs
from app.core.worker_task_lifecycle import (
    _create_stopped_container,
    _persist_created_container_reference,
    _remove_created_container,
    _start_created_container,
    create_execute_container,
    prepare_container_inputs,
)
from app.core.worker_task_outcomes import fail_execute_task
from app.core.worker_task_runner import run_execute_task
from app.models import TaskStatus


def test_build_container_volumes_uses_snapshot_mounts_last(tmp_path):
    settings = SimpleNamespace(worker_workspace_host_path="", worker_volume_mounts_parsed=[])
    issue = SimpleNamespace(id=1, session_storage_path="")
    task = SimpleNamespace(id=2)

    volumes = build_container_volumes(
        settings,
        issue,
        task=task,
        custom_mounts=[
            {
                "host_path": str(tmp_path / "cache"),
                "container_path": "/cache",
                "mode": "rw",
            },
        ],
    )

    assert volumes[str(tmp_path / "cache")] == {"bind": "/cache", "mode": "rw"}


def test_create_stopped_container_recovers_timed_out_success_by_name_and_label():
    worker = MagicMock()
    worker.docker.create_container.side_effect = RuntimeError("response timed out")
    recovered = SimpleNamespace(
        id="container-1",
        status="created",
        labels={"codify.task_id": "12"},
    )
    worker.docker.client.containers.get.return_value = recovered
    task = SimpleNamespace(id=12)

    container = _create_stopped_container(
        worker,
        task,
        "codify-12-issue1",
        image="worker:latest",
        command="",
    )

    assert container is recovered
    worker.docker.client.containers.get.assert_called_once_with("codify-12-issue1")


def test_create_stopped_container_defers_when_create_outcome_is_unknown():
    worker = MagicMock()
    worker.docker.create_container.side_effect = RuntimeError("response timed out")
    worker.docker.client.containers.get.side_effect = RuntimeError("daemon offline")
    task = SimpleNamespace(id=12)

    with pytest.raises(TaskContainerLookupError, match="creation outcome is unknown"):
        _create_stopped_container(
            worker,
            task,
            "codify-12-issue1",
            image="worker:latest",
            command="",
        )


@pytest.mark.asyncio
async def test_container_reference_commit_failure_removes_created_container():
    worker = MagicMock()
    container = SimpleNamespace(id="container-1")
    task = SimpleNamespace(id=12, container_id=None)
    db = MagicMock()
    db.commit = AsyncMock(side_effect=RuntimeError("database unavailable"))
    db.rollback = AsyncMock()
    db.refresh = AsyncMock()

    with pytest.raises(RuntimeError, match="database unavailable"):
        await _persist_created_container_reference(worker, db, task, container)

    db.rollback.assert_awaited_once()
    db.refresh.assert_awaited_once_with(task)
    worker.docker.remove_container.assert_called_once_with(container, force=True)
    assert task.container_id is None


@pytest.mark.asyncio
async def test_container_reference_cleanup_failure_defers_scheduler_recovery():
    worker = MagicMock()
    worker.docker.remove_container.side_effect = RuntimeError("daemon unavailable")
    container = SimpleNamespace(id="container-1")
    task = SimpleNamespace(id=12, container_id=None)
    db = MagicMock()
    db.commit = AsyncMock(side_effect=RuntimeError("database unavailable"))
    db.rollback = AsyncMock()

    with pytest.raises(TaskContainerLookupError, match="Could not clean up task 12 container"):
        await _persist_created_container_reference(worker, db, task, container)

    db.rollback.assert_awaited_once()
    worker.docker.remove_container.assert_called_once_with(container, force=True)


@pytest.mark.asyncio
async def test_create_execute_container_uses_snapshot_runtime(tmp_path):
    task = MagicMock()
    task.id = 12
    task.project_id = 100
    task.ci_failure_run_id = None
    task.trigger_source = "manual"
    task.rendered_prompt = "Prompt"
    task.status = TaskStatus.RUNNING
    task.cancel_requested_at = None

    issue = MagicMock()
    issue.id = 1
    issue.merge_request_iid = None
    issue.merge_request_url = None
    issue.target_branch = "main"

    worker = MagicMock()
    worker.gitlab.ensure_project_label = MagicMock()
    worker._create_mr_if_needed = MagicMock(return_value=(None, None))
    worker._build_previous_task_summaries = AsyncMock(return_value="Previous summary")
    worker._prepare_container_inputs = AsyncMock(return_value=({"TASK_ID": "12"}, "main"))
    worker._build_container_volumes = MagicMock(
        return_value={"/cache": {"bind": "/cache", "mode": "rw"}}
    )
    worker._get_container_name = MagicMock(return_value="codify-12-issue1")
    worker.docker.pull_image = MagicMock()
    worker.docker.create_container = MagicMock(return_value=SimpleNamespace(id="container-1"))

    runtime = TaskWorkerRuntime(
        image="custom-worker:latest",
        runtime_mode="mounted_kit",
        worker_kit_version="0.1.0",
        worker_kit_path="/opt/codify/worker-kits/0.1.0-linux-amd64",
        codegraph_enabled=True,
        volume_mounts=[{"host_path": "/cache", "container_path": "/cache", "mode": "rw"}],
        environment={"CUSTOM_ENV": "value"},
        pre_script="echo pre",
        post_script="echo post",
    )
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

    with (
        patch(
            "app.core.worker_task_lifecycle.load_task_worker_runtime",
            new=AsyncMock(return_value=runtime),
        ),
        patch(
            "app.core.worker_task_lifecycle.build_issue_workspace_paths",
            return_value=SimpleNamespace(issue_root=str(tmp_path)),
        ),
    ):
        container = await create_execute_container(
            worker,
            db,
            settings=settings,
            task=task,
            issue=issue,
            sudo_gl=None,
        )

    assert container.id == "container-1"
    worker.docker.pull_image.assert_called_once_with("custom-worker:latest", force=False)
    worker._prepare_container_inputs.assert_awaited_once()
    assert worker._prepare_container_inputs.call_args.kwargs["custom_environment"] == {
        "CUSTOM_ENV": "value"
    }
    assert worker.docker.create_container.call_args.kwargs["environment"][
        "CODIFY_CODEGRAPH_ENABLED"
    ] == "true"
    assert worker.docker.create_container.call_args.kwargs["environment"][
        "CODIFY_KIT_VERSION"
    ] == "0.1.0"
    worker._build_container_volumes.assert_called_once_with(
        settings,
        issue,
        task=task,
        custom_mounts=runtime.volume_mounts,
    )
    worker.docker.create_container.assert_called_once()
    assert worker.docker.create_container.call_args.kwargs["start"] is False
    worker.docker.put_archive.assert_called_once()
    worker.docker.start_container.assert_called_once_with(container)
    assert worker.docker.create_container.call_args.kwargs["image"] == "custom-worker:latest"
    assert worker.docker.create_container.call_args.kwargs["entrypoint"] == (
        "/opt/codify-kit/launcher"
    )
    assert worker.docker.create_container.call_args.kwargs["user"] == "0:0"
    assert worker.docker.create_container.call_args.kwargs["volumes"][
        "/opt/codify/worker-kits/0.1.0-linux-amd64"
    ] == {"bind": "/opt/codify-kit", "mode": "ro"}
    assert worker.docker.create_container.call_args.kwargs["volumes"][
        "/opt/codify/worker-kits/0.1.0-linux-amd64/nix/store"
    ] == {"bind": "/nix/store", "mode": "ro"}


@pytest.mark.asyncio
async def test_prepare_container_inputs_uses_only_snapshot_custom_environment():
    worker = MagicMock()
    worker._resolve_provider = AsyncMock(return_value=SimpleNamespace(id=1, system_prompt=None))
    worker._resolve_commit_author = AsyncMock(return_value=("Author", "author@example.com"))
    worker._build_container_env = MagicMock(return_value={"TASK_ID": "12"})
    task = SimpleNamespace(id=12, project_id=100)
    issue = SimpleNamespace(id=1, target_branch="main")
    db = MagicMock()

    legacy_env_loader = AsyncMock(
        return_value=[
            SimpleNamespace(key="GLOBAL_ENV", value="global", is_secret=False),
        ]
    )
    legacy_env_builder = MagicMock(return_value={"GLOBAL_ENV": "global"})
    with (
        patch(
            "app.core.worker_task_lifecycle.list_worker_environment_variables",
            new=legacy_env_loader,
            create=True,
        ),
        patch(
            "app.core.worker_task_lifecycle.build_worker_environment_map",
            new=legacy_env_builder,
            create=True,
        ),
    ):
        await prepare_container_inputs(
            worker,
            db,
            task,
            issue,
            mr_iid=None,
            custom_environment={"SNAPSHOT_ENV": "snapshot"},
        )

    assert worker._build_container_env.call_args.kwargs["custom_environment"] == {
        "SNAPSHOT_ENV": "snapshot"
    }
    legacy_env_loader.assert_not_awaited()
    legacy_env_builder.assert_not_called()


@pytest.mark.asyncio
async def test_remove_created_container_clears_durable_reference_after_removal():
    task = SimpleNamespace(
        id=12,
        container_id="container-1",
        raw_logs_finalized_at=None,
    )
    container = SimpleNamespace(id="container-1")
    worker = MagicMock()
    db = MagicMock()
    db.commit = AsyncMock()

    removed = await _remove_created_container(worker, db, task, container)

    assert removed is True
    assert task.container_id is None
    assert task.raw_logs_finalized_at is not None
    worker.docker.remove_container.assert_called_once_with(container, force=True)
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_remove_created_container_retains_reference_when_removal_fails():
    task = SimpleNamespace(
        id=12,
        container_id="container-1",
        raw_logs_finalized_at=None,
    )
    container = SimpleNamespace(id="container-1")
    worker = MagicMock()
    worker.docker.remove_container.side_effect = RuntimeError("daemon offline")
    db = MagicMock()
    db.commit = AsyncMock()

    removed = await _remove_created_container(worker, db, task, container)

    assert removed is False
    assert task.container_id == "container-1"
    assert task.raw_logs_finalized_at is not None
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["running", "exited"])
async def test_start_created_container_continues_when_start_succeeded_despite_error(status):
    task = SimpleNamespace(
        id=12,
        container_id="container-1",
        raw_logs_finalized_at=None,
    )
    container = MagicMock(id="container-1", status=status)
    container.status = status
    worker = MagicMock()
    worker.docker.start_container.side_effect = RuntimeError("response timed out")
    db = MagicMock()
    db.commit = AsyncMock()

    await _start_created_container(worker, db, task, container)

    container.reload.assert_called_once_with()
    worker.docker.remove_container.assert_not_called()
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_start_created_container_defers_when_start_outcome_is_unknown():
    task = SimpleNamespace(
        id=12,
        container_id="container-1",
        raw_logs_finalized_at=None,
    )
    container = MagicMock(id="container-1")
    container.reload.side_effect = RuntimeError("daemon offline")
    worker = MagicMock()
    worker.docker.start_container.side_effect = RuntimeError("response timed out")
    db = MagicMock()
    db.commit = AsyncMock()

    with pytest.raises(TaskContainerLookupError, match="start outcome is unknown"):
        await _start_created_container(worker, db, task, container)

    assert task.container_id == "container-1"
    assert task.raw_logs_finalized_at is None
    worker.docker.remove_container.assert_not_called()
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_start_created_container_retains_dead_container_for_log_reconciliation():
    task = SimpleNamespace(
        id=12,
        container_id="container-1",
        raw_logs_finalized_at=None,
    )
    container = MagicMock(id="container-1")
    container.status = "dead"
    worker = MagicMock()
    worker.docker.start_container.side_effect = RuntimeError("start failed")
    db = MagicMock()
    db.commit = AsyncMock()

    with pytest.raises(RuntimeError, match="start failed"):
        await _start_created_container(worker, db, task, container)

    assert task.container_id == "container-1"
    assert task.raw_logs_finalized_at is None
    worker.docker.remove_container.assert_not_called()
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_failure_handler_stops_container_and_retains_it_until_logs_are_finalized():
    task = SimpleNamespace(
        id=12,
        status=TaskStatus.RUNNING,
        completed_at=None,
        container_id="container-1",
        raw_logs_finalized_at=None,
    )
    container = MagicMock(id="container-1")
    container.status = "running"

    def reload_container():
        if container.stop.called:
            container.status = "exited"

    container.reload.side_effect = reload_container
    worker = MagicMock()
    worker._sanitize_sensitive_data.side_effect = lambda value: value
    worker._send_failure_notifications = AsyncMock()
    db = MagicMock()
    db.commit = AsyncMock()

    result = await fail_execute_task(
        worker,
        db,
        task,
        RuntimeError("stream failed"),
        had_existing_mr=False,
        container=container,
    )

    assert result is False
    assert task.status == TaskStatus.FAILED
    assert task.container_id == "container-1"
    container.stop.assert_called_once_with(timeout=10)
    worker.docker.remove_container.assert_not_called()


@pytest.mark.asyncio
async def test_failure_handler_defers_when_container_cannot_be_stopped():
    task = SimpleNamespace(
        id=12,
        status=TaskStatus.RUNNING,
        completed_at=None,
        container_id="container-1",
        raw_logs_finalized_at=None,
    )
    container = MagicMock(id="container-1")
    container.status = "running"
    container.stop.side_effect = RuntimeError("daemon unavailable")
    container.kill.side_effect = RuntimeError("daemon unavailable")
    worker = MagicMock()
    worker._sanitize_sensitive_data.side_effect = lambda value: value
    db = MagicMock()
    db.commit = AsyncMock()

    with pytest.raises(TaskContainerLookupError, match="Could not stop"):
        await fail_execute_task(
            worker,
            db,
            task,
            RuntimeError("stream failed"),
            had_existing_mr=False,
            container=container,
        )

    assert task.status == TaskStatus.RUNNING
    assert task.container_id == "container-1"
    db.commit.assert_not_awaited()


@pytest.mark.asyncio
async def test_finalize_raw_logs_falls_back_to_docker_logs_before_bootstrap_console_exists():
    task = SimpleNamespace(id=12)
    artifact_task = SimpleNamespace(id=12, raw_logs_finalized_at=None)
    artifact_db = MagicMock()
    artifact_db.get = AsyncMock(return_value=artifact_task)
    artifact_db.commit = AsyncMock()
    session = MagicMock()
    session.__aenter__ = AsyncMock(return_value=artifact_db)
    session.__aexit__ = AsyncMock(return_value=False)
    session_factory = MagicMock(return_value=session)
    worker = MagicMock()
    worker.docker.read_file_from_container.return_value = None
    worker.docker.get_container_logs.return_value = b"launcher failed\n"
    container = MagicMock()

    with patch(
        "app.core.worker_task_artifacts.persist_raw_log_snapshot",
        new=AsyncMock(),
    ) as persist_snapshot:
        await finalize_task_raw_logs(
            worker,
            task=task,
            container=container,
            session_factory=session_factory,
        )

    persist_snapshot.assert_awaited_once_with(
        artifact_db,
        task_id=12,
        content=b"launcher failed\n",
    )
    worker.docker.get_container_logs.assert_called_once_with(container)
    assert artifact_task.raw_logs_finalized_at is not None
    artifact_db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_execute_runner_propagates_unknown_container_outcome_for_scheduler_recovery():
    task = SimpleNamespace(id=12)
    issue = SimpleNamespace(id=1)
    worker = MagicMock()
    worker._handle_execute_task_failure = AsyncMock()
    db = MagicMock()
    context = {
        "handled": False,
        "settings": SimpleNamespace(),
        "task": task,
        "issue": issue,
        "had_existing_mr": False,
        "sudo_gl": None,
    }

    with (
        patch(
            "app.core.worker_task_runner.prepare_execute_task_context",
            new=AsyncMock(return_value=context),
        ),
        patch(
            "app.core.worker_task_runner.create_execute_container",
            new=AsyncMock(side_effect=TaskContainerLookupError("create outcome unknown")),
        ),
    ):
        with pytest.raises(TaskContainerLookupError, match="create outcome unknown"):
            await run_execute_task(worker, db, 12, settings=SimpleNamespace())

    worker._handle_execute_task_failure.assert_not_awaited()
