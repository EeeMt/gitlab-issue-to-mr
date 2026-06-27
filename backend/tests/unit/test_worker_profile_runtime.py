from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.worker_runtime import build_container_volumes
from app.core.worker_task_lifecycle import create_execute_container, prepare_container_inputs


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


@pytest.mark.asyncio
async def test_create_execute_container_uses_snapshot_runtime(tmp_path):
    task = MagicMock()
    task.id = 12
    task.project_id = 100
    task.ci_failure_run_id = None
    task.trigger_source = "manual"
    task.rendered_prompt = "Prompt"

    issue = MagicMock()
    issue.id = 1
    issue.merge_request_iid = None
    issue.merge_request_url = None
    issue.target_branch = "main"

    worker = MagicMock()
    worker.gitlab.ensure_project_label = MagicMock()
    worker._create_mr_if_needed = MagicMock(return_value=(None, None))
    worker._write_previous_task_summaries_file = AsyncMock()
    worker._prepare_container_inputs = AsyncMock(return_value=({"TASK_ID": "12"}, "main"))
    worker._build_container_volumes = MagicMock(
        return_value={"/cache": {"bind": "/cache", "mode": "rw"}}
    )
    worker._get_container_name = MagicMock(return_value="codify-12-issue1")
    worker.docker.pull_image = MagicMock()
    worker.docker.create_container = MagicMock(return_value=SimpleNamespace(id="container-1"))

    runtime = SimpleNamespace(
        image="custom-worker:latest",
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

    with (
        patch(
            "app.core.worker_task_lifecycle.load_task_worker_runtime",
            new=AsyncMock(return_value=runtime),
        ),
        patch(
            "app.core.worker_task_lifecycle.build_issue_workspace_paths",
            return_value=SimpleNamespace(runtime_path=str(tmp_path)),
        ),
        patch("app.core.worker_task_lifecycle.materialize_task_prompt"),
        patch("app.core.worker_task_lifecycle.materialize_worker_custom_scripts_from_snapshot"),
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
    worker._build_container_volumes.assert_called_once_with(
        settings,
        issue,
        task=task,
        custom_mounts=runtime.volume_mounts,
    )
    worker.docker.create_container.assert_called_once()
    assert worker.docker.create_container.call_args.kwargs["image"] == "custom-worker:latest"


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
