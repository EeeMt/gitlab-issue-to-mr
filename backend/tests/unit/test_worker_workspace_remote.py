from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.core.worker_workspace_remote import (
    inspect_issue_workspace,
    remove_issue_workspace_remote,
)
from app.models import Issue, WorkerProfile


def _profile() -> WorkerProfile:
    return WorkerProfile(
        id=7,
        name="Remote Worker",
        enabled=True,
        image="codify-worker:remote",
        docker_host="tcp://worker.example:2376",
        volume_mounts=[],
        pre_script="",
        post_script="",
        default_execute_run_instruction_template="{{user_prompt}}",
        default_plan_run_instruction_template="{{user_prompt}}",
        ci_auto_repair_run_instruction_template="{{user_prompt}}",
    )


def _issue(profile: WorkerProfile) -> Issue:
    return Issue(
        id=22,
        title="Pinned issue",
        project_id=11,
        status="open",
        worker_profile_id=profile.id,
        worker_profile=profile,
    )


def _settings() -> SimpleNamespace:
    return SimpleNamespace(
        worker_workspace_host_path="/srv/codify-workspaces",
        docker_host="tcp://fallback.example:2376",
        docker_tls_ca=None,
        docker_tls_cert=None,
        docker_tls_key=None,
    )


@pytest.mark.asyncio
async def test_inspect_workspace_runs_read_only_on_issue_worker_daemon():
    profile = _profile()
    issue = _issue(profile)
    docker = MagicMock()
    docker.client.containers.run.return_value = (
        b'{"issue_exists":true,"repo_exists":true}\n'
    )
    get_client = AsyncMock(return_value=docker)
    db = MagicMock()
    db.get = AsyncMock(return_value=profile)

    status = await inspect_issue_workspace(
        db,
        _settings(),
        issue,
        get_client=get_client,
    )

    assert status.issue_root == "/srv/codify-workspaces/project-11/issue-22"
    assert status.repo_exists is True
    connection = get_client.await_args.args[0]
    assert connection.host == "tcp://worker.example:2376"
    run_kwargs = docker.client.containers.run.call_args.kwargs
    assert run_kwargs["volumes"]["/srv/codify-workspaces"]["mode"] == "ro"
    assert run_kwargs["entrypoint"] == "/bin/sh"
    assert run_kwargs["user"] == "0:0"


@pytest.mark.asyncio
async def test_inspect_workspace_uses_and_closes_a_transient_default_client(monkeypatch):
    profile = _profile()
    issue = _issue(profile)
    docker = MagicMock()
    docker.client.containers.run.return_value = (
        b'{"issue_exists":true,"repo_exists":true}\n'
    )
    create_client = AsyncMock(return_value=docker)
    db = MagicMock()
    db.get = AsyncMock(return_value=profile)
    monkeypatch.setattr(
        "app.core.worker_workspace_remote.create_docker_client_async",
        create_client,
    )

    await inspect_issue_workspace(db, _settings(), issue)

    create_client.assert_awaited_once()
    docker.close.assert_called_once()


@pytest.mark.asyncio
async def test_remove_workspace_runs_on_pinned_daemon_and_checks_owner_marker():
    profile = _profile()
    issue = _issue(profile)
    docker = MagicMock()
    docker.client.containers.run.return_value = b'{"removed":true}\n'
    db = MagicMock()
    db.get = AsyncMock(return_value=profile)

    removed = await remove_issue_workspace_remote(
        db,
        _settings(),
        issue,
        get_client=AsyncMock(return_value=docker),
    )

    assert removed is True
    run_kwargs = docker.client.containers.run.call_args.kwargs
    assert run_kwargs["volumes"]["/srv/codify-workspaces"]["mode"] == "rw"
    assert run_kwargs["user"] == "0:0"
    assert run_kwargs["environment"] == {
        "PROJECT_ID": "11",
        "ISSUE_ID": "22",
        "WORKER_PROFILE_ID": "7",
    }
    script = docker.client.containers.run.call_args.args[1][1]
    assert 'rm -rf -- "${issue_root}"' in script
    assert "owner marker" in script
    db.get.assert_awaited_once_with(WorkerProfile, profile.id)


@pytest.mark.asyncio
async def test_profile_lookup_does_not_touch_async_issue_relationship():
    profile = _profile()
    issue = Issue(
        id=22,
        title="Pinned issue",
        project_id=11,
        status="open",
        worker_profile_id=profile.id,
    )
    db = MagicMock()
    db.get = AsyncMock(return_value=profile)
    docker = MagicMock()
    docker.client.containers.run.return_value = b'{"issue_exists":false,"repo_exists":false}\n'

    await inspect_issue_workspace(
        db,
        _settings(),
        issue,
        get_client=AsyncMock(return_value=docker),
    )

    db.get.assert_awaited_once_with(WorkerProfile, profile.id)


@pytest.mark.asyncio
async def test_mounted_kit_workspace_maintenance_falls_back_when_image_has_no_shell():
    profile = _profile()
    profile.runtime_mode = "mounted_kit"
    profile.worker_kit_version = "0.2.0"
    profile.worker_kit_path = "/opt/codify/worker-kits/0.2.0-linux-amd64"
    issue = _issue(profile)
    docker = MagicMock()
    docker.client.containers.run.side_effect = [
        RuntimeError('exec: "/bin/sh": executable file not found'),
        b'{"issue_exists":true,"repo_exists":true}\n',
    ]
    db = MagicMock()
    db.get = AsyncMock(return_value=profile)

    status = await inspect_issue_workspace(
        db,
        _settings(),
        issue,
        get_client=AsyncMock(return_value=docker),
    )

    assert status.repo_exists is True
    assert docker.client.containers.run.call_count == 2
    fallback = docker.client.containers.run.call_args
    assert fallback.args[1][0] == "--maintenance-shell"
    assert fallback.kwargs["entrypoint"] == "/opt/codify-kit/launcher"
    assert fallback.kwargs["environment"]["CODIFY_KIT_VERSION"] == "0.2.0"
    assert fallback.kwargs["volumes"][profile.worker_kit_path] == {
        "bind": "/opt/codify-kit",
        "mode": "ro",
    }
    assert fallback.kwargs["volumes"][f"{profile.worker_kit_path}/nix/store"] == {
        "bind": "/nix/store",
        "mode": "ro",
    }
