import hashlib
import io
import tarfile
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.harness_protocol import CANONICAL_EVENT_SCHEMA, HARNESS_CONTRACT_VERSION
from app.core.utcnow import utcnow
from app.core.worker_docker_targets import TaskContainerLookupError
from app.core.worker_profiles import TaskWorkerRuntime
from app.core.worker_runtime import build_container_volumes
from app.core.worker_runtime_bundle import (
    _v2_bundle_digest,
    v2_launcher_manifest_bytes,
)
from app.core.worker_task_artifacts import finalize_task_raw_logs
from app.core.worker_task_lifecycle import (
    _create_stopped_container,
    _persist_created_container_reference,
    _remove_created_container,
    _start_created_container,
    _verify_v2_kit_before_start,
    create_execute_container,
    prepare_container_inputs,
)
from app.core.worker_task_outcomes import fail_execute_task
from app.core.worker_task_runner import run_execute_task
from app.models import TaskStatus

_V2_WORKER_IMAGE_IDENTITY = {
    "schema": "codify.worker-image-identity/v1",
    "daemon_key": "profile-runtime-tests",
    "image_reference": f"registry.example.com/custom-worker@sha256:{'1' * 64}",
    "image_id": f"sha256:{'2' * 64}",
    "runtime_platform": "linux/amd64",
}
_V2_WORKER_KIT_IDENTITY = {
    "schema": "codify.worker.kit-identity/v1",
    "kit_version": "0.4.0",
    "platform": "linux/amd64",
    "manifest_sha256": "4" * 64,
}
_V2_KIT_HARNESS_INVENTORY = {
    "pi": {"availability": "absent", "reason_code": "not_selected"},
    "opencode": {"availability": "absent", "reason_code": "not_selected"},
    "claude": {
        "availability": "present",
        "path": "/opt/codify-kit/harness/claude/bin/claude",
        "version": "1.0.0",
        "sha256": "f" * 64,
        "size": 1024,
    },
    "codex": {"availability": "absent", "reason_code": "not_selected"},
}
_V2_HARNESS_EVIDENCE = {
    "schema": "codify.worker-harness-verification/v1",
    "harness_key": "claude",
    "contract_version": "codify.worker.harness/v2",
    "adapter": {"version": "1.0.0"},
    "verification_input_digest": "d" * 64,
    "image_identity": _V2_WORKER_IMAGE_IDENTITY,
    "generation": 1,
    "verified_at": "2026-08-24T00:00:00+00:00",
}


def _make_v2_runtime_bundle():
    """Build persisted V2 bytes so lifecycle tests use the real verifier."""
    entrypoint = b"#!/bin/sh\nexit 0\n"
    files = [
        {
            "path": "entrypoint.sh",
            "size": len(entrypoint),
            "sha256": hashlib.sha256(entrypoint).hexdigest(),
        }
    ]
    digest = _v2_bundle_digest(
        files, _V2_WORKER_IMAGE_IDENTITY, _V2_HARNESS_EVIDENCE, _V2_WORKER_KIT_IDENTITY
    )
    manifest = {
        "schema": "codify.worker.runtime-manifest/v2",
        "contract_version": "codify.worker.harness/v2",
        "event_schema": "codify.worker.event/v2",
        "orchestration_version": "1.0.0",
        "bundle_digest": digest,
        "runtime_platform": "linux/amd64",
        "worker_image_identity": _V2_WORKER_IMAGE_IDENTITY,
        "worker_kit_identity": _V2_WORKER_KIT_IDENTITY,
        "harness_verification_evidence": _V2_HARNESS_EVIDENCE,
        "files": files,
        "adapters": {
            "claude": {
                "adapter": {"version": "1.0.0", "digest": digest},
                "capabilities": {"steering": False},
            }
        },
    }
    launcher_manifest = v2_launcher_manifest_bytes(SimpleNamespace(manifest=manifest))
    archive_buffer = io.BytesIO()
    with tarfile.open(fileobj=archive_buffer, mode="w", format=tarfile.PAX_FORMAT) as archive:
        for name, payload, mode in (
            ("codify-runtime/orchestration/manifest.json", launcher_manifest, 0o644),
            ("codify-runtime/orchestration/entrypoint.sh", entrypoint, 0o755),
        ):
            member = tarfile.TarInfo(name=name)
            member.size = len(payload)
            member.mode = mode
            member.mtime = 0
            archive.addfile(member, io.BytesIO(payload))
    archive_bytes = archive_buffer.getvalue()
    return SimpleNamespace(
        id=81,
        digest=digest,
        contract_version="codify.worker.harness/v2",
        orchestration_version="1.0.0",
        manifest={
            **manifest,
            "archive_sha256": hashlib.sha256(archive_bytes).hexdigest(),
        },
        bundle_bytes=archive_bytes,
        size_bytes=len(archive_bytes),
    )


_V2_RUNTIME_BUNDLE = _make_v2_runtime_bundle()


def _bind_v2_runtime(task, db):
    """Bind a Task/DB mock to one verified immutable V2 execution identity."""
    task.runtime_bundle_id = _V2_RUNTIME_BUNDLE.id
    task.worker_profile_snapshot = SimpleNamespace(
        harness_key="claude",
        harness_config_snapshot={
            "requested_runtime_contract_version": "codify.worker.harness/v2",
            "v2_worker_image_identity": _V2_WORKER_IMAGE_IDENTITY,
            "v2_harness_verification_evidence": _V2_HARNESS_EVIDENCE,
            "worker_kit_identity": _V2_WORKER_KIT_IDENTITY,
        },
        runtime_contract_version="codify.worker.harness/v2",
        runtime_bundle_digest=_V2_RUNTIME_BUNDLE.digest,
        runtime_locator_fingerprint="profile-runtime-v2-fingerprint",
    )

    async def execute(statement, *args, **kwargs):
        result = MagicMock()
        statement_text = str(statement)
        if "FROM worker_runtime_bundles" in statement_text:
            result.scalar_one_or_none.return_value = _V2_RUNTIME_BUNDLE
            result.scalars.return_value.all.return_value = [_V2_RUNTIME_BUNDLE]
        else:
            result.scalar_one_or_none.return_value = None
            result.scalars.return_value.all.return_value = []
        return result

    db.execute = AsyncMock(side_effect=execute)

    def _readiness_row(model, pk, **kwargs):
        if getattr(model, "__name__", None) == "WorkerRuntimeReadiness":
            return SimpleNamespace(
                status="ready",
                docker_daemon_key=None,
                runtime_mode="mounted_kit",
                worker_kit_version="0.4.0",
                worker_kit_path="/opt/codify/worker-kits/0.4.0-linux-amd64",
                failure_code=None,
                failure_message=None,
                checked_at=None,
                ready_until=utcnow() + timedelta(seconds=900),
                check_generation=0,
                check_started_at=None,
                updated_at=None,
                harness_inventory=_V2_KIT_HARNESS_INVENTORY,
                kit_identity=_V2_WORKER_KIT_IDENTITY,
            )
        return None

    db.get = AsyncMock(side_effect=_readiness_row)
    return SimpleNamespace(
        attempt_id="task-12-attempt-1",
        harness_key="claude",
        adapter_version="1.0.0",
        event_schema="codify.worker.event/v2",
        control_state="disabled",
        control_supported=False,
    )


def _ready_kit_probe_outcome(*, kit_identity=None, harness_inventory=None):
    from app.core.worker_runtime_readiness import (
        READINESS_READY,
        RuntimeProbeOutcome,
        RuntimeReadiness,
    )

    return RuntimeProbeOutcome(
        readiness=RuntimeReadiness(
            status=READINESS_READY,
            worker_kit_version="0.4.0",
            worker_kit_path="/opt/codify/worker-kits/0.4.0-linux-amd64",
            harness_inventory=harness_inventory or _V2_KIT_HARNESS_INVENTORY,
            kit_identity=kit_identity or _V2_WORKER_KIT_IDENTITY,
        ),
        committed=True,
    )


def _ready_kit_check(*, kit_identity=None, harness_inventory=None):
    from app.core.worker_runtime_readiness import READINESS_READY, RuntimeCheckResult

    return RuntimeCheckResult(
        status=READINESS_READY,
        harness_inventory=harness_inventory or _V2_KIT_HARNESS_INVENTORY,
        kit_identity=kit_identity or _V2_WORKER_KIT_IDENTITY,
    )


@pytest.fixture(autouse=True)
def _stub_v2_image_inspection():
    """Keep daemon inspection external while exercising bundle verification."""
    with patch(
        "app.core.worker_task_lifecycle.inspect_v2_worker_image_identity",
        return_value=_V2_WORKER_IMAGE_IDENTITY,
    ):
        yield


@pytest.fixture(autouse=True)
def _stub_v2_kit_probe():
    with patch(
        "app.core.worker_task_lifecycle.run_deterministic_kit_probe",
        new=AsyncMock(return_value=_ready_kit_probe_outcome()),
    ) as probe:
        yield probe


@pytest.fixture(autouse=True)
def _stub_v2_final_kit_probe():
    with patch(
        "app.core.worker_task_lifecycle.inspect_mounted_kit_container",
        return_value=_ready_kit_check(),
    ) as probe:
        yield probe


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
    task.worker_profile_snapshot = SimpleNamespace(
        runtime_contract_version="codify.worker.harness/v1",
        runtime_bundle_digest="d" * 64,
        harness_key="claude",
    )

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
        docker_host="unix:///var/run/docker.sock",
        worker_runtime_readiness_ttl_seconds=900,
        harness_execution_mode="dual_canary",
    )
    db = MagicMock()
    db.commit = AsyncMock()
    db.flush = AsyncMock()
    db.get = AsyncMock(return_value=None)
    db.refresh = AsyncMock()

    attempt = _bind_v2_runtime(task, db)

    with (
        patch(
            "app.core.worker_task_lifecycle.load_task_worker_runtime",
            new=AsyncMock(return_value=runtime),
        ),
        patch(
            "app.core.worker_task_lifecycle.build_issue_workspace_paths",
            return_value=SimpleNamespace(issue_root=str(tmp_path)),
        ),
        patch(
            "app.core.worker_task_lifecycle.create_task_attempt",
            new=AsyncMock(return_value=attempt),
        ),
        patch(
            "app.core.worker_task_lifecycle.inspect_mounted_kit_container",
            return_value=_ready_kit_check(),
        ) as final_kit_probe,
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
    worker.docker.pull_image.assert_called_once_with(
        _V2_WORKER_IMAGE_IDENTITY["image_reference"], force=False
    )
    worker._prepare_container_inputs.assert_awaited_once()
    assert worker._prepare_container_inputs.call_args.kwargs["custom_environment"] == {
        "CUSTOM_ENV": "value"
    }
    assert worker.docker.create_container.call_args.kwargs["environment"][
        "CODIFY_CODEGRAPH_ENABLED"
    ] == "true"
    assert (
        worker.docker.create_container.call_args.kwargs["environment"]["CODIFY_HARNESS_CLI_BIN"]
        == _V2_KIT_HARNESS_INVENTORY["claude"]["path"]
    )
    assert worker.docker.create_container.call_args.kwargs["environment"]["CODIFY_KIT_VERSION"] == "0.1.0"
    assert (
        worker.docker.create_container.call_args.kwargs["environment"][
            "CODIFY_KIT_MANIFEST_SHA256"
        ]
        == _V2_WORKER_KIT_IDENTITY["manifest_sha256"]
    )
    worker._build_container_volumes.assert_called_once_with(
        settings, issue, task=task, custom_mounts=runtime.volume_mounts
    )
    worker.docker.create_container.assert_called_once()
    assert worker.docker.create_container.call_args.kwargs["start"] is False
    assert worker.docker.put_archive.call_count == 2
    worker.docker.start_container.assert_called_once_with(container)
    final_kit_probe.assert_called_once()
    assert db.commit.await_count == 2
    assert (
        worker.docker.create_container.call_args.kwargs["image"]
        == _V2_WORKER_IMAGE_IDENTITY["image_reference"]
    )
    assert worker.docker.create_container.call_args.kwargs["entrypoint"] == "/opt/codify-kit/launcher"
    assert worker.docker.create_container.call_args.kwargs["user"] == "0:0"
    assert worker.docker.create_container.call_args.kwargs["volumes"][
        "/opt/codify/worker-kits/0.1.0-linux-amd64"
    ] == {"bind": "/opt/codify-kit", "mode": "ro"}
    assert worker.docker.create_container.call_args.kwargs["volumes"][
        "/opt/codify/worker-kits/0.1.0-linux-amd64/nix/store"
    ] == {"bind": "/nix/store", "mode": "ro"}


@pytest.mark.asyncio
async def test_v2_final_kit_check_removes_container_on_identity_change():
    worker = MagicMock()
    db = MagicMock()
    db.commit = AsyncMock()
    task = SimpleNamespace(id=12, container_id="container-1", raw_logs_finalized_at=None)
    container = SimpleNamespace(id="container-1")
    changed_identity = {**_V2_WORKER_KIT_IDENTITY, "manifest_sha256": "5" * 64}

    with patch(
        "app.core.worker_task_lifecycle.inspect_mounted_kit_container",
        return_value=_ready_kit_check(kit_identity=changed_identity),
    ):
        with pytest.raises(RuntimeError, match="before container start"):
            await _verify_v2_kit_before_start(
                worker,
                db,
                task,
                container,
                worker_kit_version="0.4.0",
                worker_kit_path="/opt/codify/worker-kits/0.4.0-linux-amd64",
                snapshot_kit_identity=_V2_WORKER_KIT_IDENTITY,
            )

    worker.docker.remove_container.assert_called_once_with(container, force=True)
    db.commit.assert_awaited_once()
    assert task.container_id is None


@pytest.mark.asyncio
async def test_create_execute_container_v1_dual_canary_uses_legacy_cli_path(tmp_path):
    """V1 must cross the shared CLI path without reading an unbound V2 local."""
    bundle = SimpleNamespace(
        contract_version=HARNESS_CONTRACT_VERSION,
        digest="d" * 64,
        manifest={
            "event_schema": CANONICAL_EVENT_SCHEMA,
            "archive_manifest_digest": "e" * 64,
            "adapters": {"claude": {"version": "1.0.0"}},
        },
        bundle_bytes=b"legacy-runtime-bundle",
    )
    task = SimpleNamespace(
        id=12,
        project_id=100,
        issue_id=1,
        ci_failure_run_id=None,
        trigger_source="manual",
        rendered_prompt="Prompt",
        status=TaskStatus.RUNNING,
        cancel_requested_at=None,
        task_mode="execute",
        session_mode="continue",
        worker_profile_snapshot=SimpleNamespace(
            runtime_contract_version=HARNESS_CONTRACT_VERSION,
            runtime_bundle_digest=bundle.digest,
            harness_key="claude",
        ),
    )
    issue = SimpleNamespace(
        id=1,
        merge_request_iid=None,
        merge_request_url=None,
        target_branch=None,
    )
    worker = MagicMock()
    worker._build_previous_task_summaries = AsyncMock(return_value="")
    worker._prepare_container_inputs = AsyncMock(return_value=({"TASK_ID": "12"}, "main"))
    worker._build_container_volumes = MagicMock(return_value={})
    worker._get_container_name = MagicMock(return_value="codify-12-issue1")
    worker.docker.pull_image = MagicMock()
    worker.docker.create_container = MagicMock(return_value=SimpleNamespace(id="container-1"))

    runtime = TaskWorkerRuntime(
        image="legacy-worker:latest",
        runtime_mode="baked_image",
        codegraph_enabled=False,
        volume_mounts=[],
        environment={},
        pre_script="",
        post_script="",
    )
    settings = SimpleNamespace(
        worker_skip_image_pull=False,
        worker_network="bridge",
        harness_execution_mode="dual_canary",
        worker_runtime_readiness_ttl_seconds=900,
    )
    db = MagicMock()
    db.commit = AsyncMock()
    db.flush = AsyncMock()
    db.refresh = AsyncMock()
    attempt = SimpleNamespace(
        attempt_id="task-12-attempt-1",
        harness_key="claude",
        adapter_version="1.0.0",
        event_schema=CANONICAL_EVENT_SCHEMA,
        control_state="disabled",
    )

    with (
        patch(
            "app.core.worker_task_lifecycle.load_task_worker_runtime",
            new=AsyncMock(return_value=runtime),
        ),
        patch(
            "app.core.worker_task_lifecycle.build_issue_workspace_paths",
            return_value=SimpleNamespace(issue_root=str(tmp_path)),
        ),
        patch(
            "app.core.worker_task_lifecycle.load_bound_runtime_bundle",
            new=AsyncMock(return_value=bundle),
        ),
        patch(
            "app.core.worker_task_lifecycle.create_task_attempt",
            new=AsyncMock(return_value=attempt),
        ),
        patch(
            "app.core.worker_task_lifecycle.build_task_runtime_archive",
            return_value=b"task-runtime-archive",
        ),
        patch(
            "app.core.worker_task_lifecycle.projection_for_task",
            return_value={
                "harness_key": "claude",
                "session_namespace": "issue:1:claude",
                "generation": 0,
                "reset_task_id": None,
            },
        ),
        patch(
            "app.core.worker_task_lifecycle.resolve_projected_resume_session",
            new=AsyncMock(return_value=(None, "fresh_no_match")),
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
    worker.docker.pull_image.assert_called_once_with("legacy-worker:latest", force=False)
    environment = worker.docker.create_container.call_args.kwargs["environment"]
    assert environment["CODIFY_RUNTIME_CONTRACT_VERSION"] == HARNESS_CONTRACT_VERSION
    assert environment["CODIFY_HARNESS_CLI_BIN"] == ""
    assert worker.docker.create_container.call_args.kwargs["image"] == "legacy-worker:latest"


@pytest.mark.asyncio
async def test_v2_execution_rejects_daemon_image_identity_mismatch_before_container(tmp_path):
    identity = {
        "schema": "codify.worker-image-identity/v1",
        "daemon_key": "tcp://worker.example:2376",
        "image_reference": "registry.example/worker@sha256:" + "a" * 64,
        "image_id": "sha256:" + "b" * 64,
        "runtime_platform": "linux/amd64",
    }
    task = SimpleNamespace(
        id=12,
        project_id=100,
        ci_failure_run_id=None,
        trigger_source="manual",
        rendered_prompt="Prompt",
        status=TaskStatus.RUNNING,
        cancel_requested_at=None,
        worker_profile_snapshot=SimpleNamespace(
            harness_config_snapshot={"v2_worker_image_identity": identity}, harness_key="pi"
        ),
    )
    issue = SimpleNamespace(id=1, merge_request_iid=None, merge_request_url=None, target_branch="main")
    runtime = TaskWorkerRuntime(
        image="worker:mutable-tag",
        codegraph_enabled=False,
        volume_mounts=[],
        environment={},
        pre_script="",
        post_script="",
        docker_host="tcp://worker.example:2376",
    )
    worker = MagicMock()
    worker._build_previous_task_summaries = AsyncMock(return_value="")
    worker._create_mr_if_needed = MagicMock(return_value=(None, None))
    db = MagicMock()
    db.commit = AsyncMock()
    bundle = SimpleNamespace(
        contract_version="codify.worker.harness/v2",
        manifest={"worker_image_identity": identity},
    )
    observed = {**identity, "image_id": "sha256:" + "d" * 64}
    settings = SimpleNamespace(worker_skip_image_pull=True, worker_network="bridge")

    with (
        patch("app.core.worker_task_lifecycle.finalize_pre_container_cancellation", new=AsyncMock(return_value=False)),
        patch("app.core.worker_task_lifecycle.load_task_worker_runtime", new=AsyncMock(return_value=runtime)),
        patch("app.core.worker_task_lifecycle.build_issue_workspace_paths", return_value=SimpleNamespace(issue_root=str(tmp_path))),
        patch("app.core.worker_task_lifecycle.load_bound_runtime_bundle", new=AsyncMock(return_value=bundle)),
        patch("app.core.worker_task_lifecycle.inspect_v2_worker_image_identity", return_value=observed),
    ):
        with pytest.raises(RuntimeError, match="identity changed"):
            await create_execute_container(
                worker, db, settings=settings, task=task, issue=issue, sudo_gl=None
            )

    worker.docker.create_container.assert_not_called()


@pytest.mark.asyncio
async def test_v2_execution_rejects_bundle_evidence_mismatch_before_container(tmp_path):
    task = SimpleNamespace(
        id=12, project_id=100, ci_failure_run_id=None, trigger_source="manual", rendered_prompt="Prompt",
        status=TaskStatus.RUNNING, cancel_requested_at=None,
        worker_profile_snapshot=SimpleNamespace(
            harness_config_snapshot={
                "v2_worker_image_identity": _V2_WORKER_IMAGE_IDENTITY,
                "v2_harness_verification_evidence": _V2_HARNESS_EVIDENCE,
            }, harness_key="claude",
        ),
    )
    issue = SimpleNamespace(id=1, merge_request_iid=None, merge_request_url=None, target_branch="main")
    runtime = TaskWorkerRuntime(image="worker:mutable-tag", codegraph_enabled=False, volume_mounts=[], environment={}, pre_script="", post_script="")
    worker, db = MagicMock(), MagicMock()
    worker._create_mr_if_needed.return_value = (None, None)
    worker._build_previous_task_summaries = AsyncMock(return_value="")
    bundle = SimpleNamespace(
        contract_version="codify.worker.harness/v2",
        manifest={
            "worker_image_identity": _V2_WORKER_IMAGE_IDENTITY,
            "harness_verification_evidence": {**_V2_HARNESS_EVIDENCE, "generation": 2},
        },
    )
    settings = SimpleNamespace(worker_skip_image_pull=True, worker_network="bridge")
    with (
        patch("app.core.worker_task_lifecycle.finalize_pre_container_cancellation", new=AsyncMock(return_value=False)),
        patch("app.core.worker_task_lifecycle.load_task_worker_runtime", new=AsyncMock(return_value=runtime)),
        patch("app.core.worker_task_lifecycle.build_issue_workspace_paths", return_value=SimpleNamespace(issue_root=str(tmp_path))),
        patch("app.core.worker_task_lifecycle.load_bound_runtime_bundle", new=AsyncMock(return_value=bundle)),
    ):
        with pytest.raises(RuntimeError, match="Harness verification evidence does not match"):
            await create_execute_container(worker, db, settings=settings, task=task, issue=issue, sudo_gl=None)
    worker.docker.create_container.assert_not_called()


@pytest.mark.asyncio
async def test_create_execute_container_freeform_defers_mr_and_omits_mr_iid(tmp_path):
    """Freeform containers start without a pre-start MR and without MR_IID env,
    even when the Issue already carries a merge request."""
    task = MagicMock()
    task.id = 12
    task.project_id = 100
    task.ci_failure_run_id = None
    task.trigger_source = "manual"
    task.rendered_prompt = "Prompt"
    task.status = TaskStatus.RUNNING
    task.cancel_requested_at = None
    task.task_mode = "freeform"
    task.require_changes = False

    issue = MagicMock()
    issue.id = 1
    issue.merge_request_iid = 7
    issue.merge_request_url = "http://mr/7"
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
        volume_mounts=[],
        environment={},
        pre_script="",
        post_script="",
    )
    settings = SimpleNamespace(
        worker_image="old-worker:latest",
        worker_skip_image_pull=False,
        worker_network="bridge",
        docker_host="unix:///var/run/docker.sock",
        worker_runtime_readiness_ttl_seconds=900,
        harness_execution_mode="dual_canary",
    )
    db = MagicMock()
    db.commit = AsyncMock()
    db.flush = AsyncMock()
    db.get = AsyncMock(return_value=None)
    db.refresh = AsyncMock()

    attempt = _bind_v2_runtime(task, db)

    with (
        patch(
            "app.core.worker_task_lifecycle.load_task_worker_runtime",
            new=AsyncMock(return_value=runtime),
        ),
        patch(
            "app.core.worker_task_lifecycle.build_issue_workspace_paths",
            return_value=SimpleNamespace(issue_root=str(tmp_path)),
        ),
        patch(
            "app.core.worker_task_lifecycle.create_task_attempt",
            new=AsyncMock(return_value=attempt),
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
    worker._create_mr_if_needed.assert_not_called()
    args, _ = worker._prepare_container_inputs.await_args
    assert args[3] is None
    # The Issue MR association is a pre-run fact for freeform; leave it untouched.
    assert issue.merge_request_iid == 7
    assert "MR_IID" not in worker.docker.create_container.call_args.kwargs["environment"]


def _kit_runtime_and_settings():
    runtime = TaskWorkerRuntime(
        image="custom-worker:latest",
        runtime_mode="mounted_kit",
        worker_kit_version="0.1.0",
        worker_kit_path="/opt/codify/worker-kits/0.1.0-linux-amd64",
        docker_host="tcp://worker:2376",
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
        worker_runtime_readiness_ttl_seconds=900,
        harness_execution_mode="dual_canary",
    )
    return runtime, settings


def _kit_failure_execute_fixtures(runtime, settings, tmp_path):
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
    worker.docker.put_archive = MagicMock()
    worker.docker.start_container = MagicMock()

    db = MagicMock()
    db.commit = AsyncMock()
    db.flush = AsyncMock()
    db.get = AsyncMock(return_value=None)
    db.refresh = AsyncMock()

    attempt = _bind_v2_runtime(task, db)
    return worker, db, task, issue, attempt


@pytest.mark.asyncio
async def test_create_execute_container_missing_bind_source_raises_structured_kit_error(
    tmp_path,
):
    """F2 §13.4: a create-time bind-source-missing error re-probes the Kit and,
    when the Kit is gone, fails with a structured unavailable error."""
    from app.core.worker_runtime_readiness import WorkerRuntimeUnavailableError

    runtime, settings = _kit_runtime_and_settings()
    worker, db, task, issue, attempt = _kit_failure_execute_fixtures(
        runtime, settings, tmp_path
    )
    worker.docker.create_container.side_effect = RuntimeError(
        "Error response from daemon: create command failed: "
        "bind source path does not exist: /opt/codify/worker-kits/0.1.0-linux-amd64"
    )
    recheck = AsyncMock(
        return_value=WorkerRuntimeUnavailableError(
            failure_code="worker_kit_not_found",
            failure_message="Worker Kit directory does not exist on the Docker host",
        )
    )

    with (
        patch(
            "app.core.worker_task_lifecycle.load_task_worker_runtime",
            new=AsyncMock(return_value=runtime),
        ),
        patch(
            "app.core.worker_task_lifecycle.build_issue_workspace_paths",
            return_value=SimpleNamespace(issue_root=str(tmp_path)),
        ),
        patch(
            "app.core.worker_task_lifecycle.create_task_attempt",
            new=AsyncMock(return_value=attempt),
        ),
        patch(
            "app.core.worker_task_lifecycle.recheck_runtime_on_container_error",
            new=recheck,
        ),
    ):
        with pytest.raises(WorkerRuntimeUnavailableError) as exc_info:
            await create_execute_container(
                worker,
                db,
                settings=settings,
                task=task,
                issue=issue,
                sudo_gl=None,
            )

    assert exc_info.value.failure_code == "worker_kit_not_found"
    recheck.assert_awaited_once()
    assert recheck.await_args.kwargs["worker_kit_path"] == (
        "/opt/codify/worker-kits/0.1.0-linux-amd64"
    )


@pytest.mark.asyncio
async def test_create_execute_container_kit_error_recheck_ready_keeps_original_error(
    tmp_path,
):
    """F2 §13.4: when the re-probe keeps ready, the original create error is kept
    as a Profile/image runtime error instead of a structured Kit error."""
    runtime, settings = _kit_runtime_and_settings()
    worker, db, task, issue, attempt = _kit_failure_execute_fixtures(
        runtime, settings, tmp_path
    )
    original_error = RuntimeError(
        "Error response from daemon: create command failed: "
        "bind source path does not exist: /opt/codify/worker-kits/0.1.0-linux-amd64"
    )
    worker.docker.create_container.side_effect = original_error
    recheck = AsyncMock(return_value=original_error)

    with (
        patch(
            "app.core.worker_task_lifecycle.load_task_worker_runtime",
            new=AsyncMock(return_value=runtime),
        ),
        patch(
            "app.core.worker_task_lifecycle.build_issue_workspace_paths",
            return_value=SimpleNamespace(issue_root=str(tmp_path)),
        ),
        patch(
            "app.core.worker_task_lifecycle.create_task_attempt",
            new=AsyncMock(return_value=attempt),
        ),
        patch(
            "app.core.worker_task_lifecycle.recheck_runtime_on_container_error",
            new=recheck,
        ),
    ):
        with pytest.raises(RuntimeError, match="bind source path does not exist"):
            await create_execute_container(
                worker,
                db,
                settings=settings,
                task=task,
                issue=issue,
                sudo_gl=None,
            )

    recheck.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_execute_container_non_kit_error_does_not_recheck(tmp_path):
    """F2: an unrelated create error (image/network) must not trigger the Kit
    re-probe and must propagate unchanged."""
    runtime, settings = _kit_runtime_and_settings()
    worker, db, task, issue, attempt = _kit_failure_execute_fixtures(
        runtime, settings, tmp_path
    )
    worker.docker.create_container.side_effect = RuntimeError(
        "Error response from daemon: image 'custom-worker:latest' not found"
    )
    recheck = AsyncMock()

    with (
        patch(
            "app.core.worker_task_lifecycle.load_task_worker_runtime",
            new=AsyncMock(return_value=runtime),
        ),
        patch(
            "app.core.worker_task_lifecycle.build_issue_workspace_paths",
            return_value=SimpleNamespace(issue_root=str(tmp_path)),
        ),
        patch(
            "app.core.worker_task_lifecycle.create_task_attempt",
            new=AsyncMock(return_value=attempt),
        ),
        patch(
            "app.core.worker_task_lifecycle.recheck_runtime_on_container_error",
            new=recheck,
        ),
    ):
        with pytest.raises(RuntimeError, match="image 'custom-worker:latest' not found"):
            await create_execute_container(
                worker,
                db,
                settings=settings,
                task=task,
                issue=issue,
                sudo_gl=None,
            )

    recheck.assert_not_called()


@pytest.mark.asyncio
async def test_v2_execution_rejects_kit_identity_change_between_verification_and_execution(
    tmp_path,
):
    """A mounted Kit replacement between verification and execution fails
    closed instead of silently running against different Kit bytes."""
    runtime, settings = _kit_runtime_and_settings()
    worker, db, task, issue, attempt = _kit_failure_execute_fixtures(
        runtime, settings, tmp_path
    )
    # The cached readiness row still reports the frozen build, but the live
    # execution probe observes a replacement before container creation.
    changed_kit = {**_V2_WORKER_KIT_IDENTITY, "manifest_sha256": "9" * 64}
    db.get = AsyncMock(
        return_value=SimpleNamespace(
            status="ready",
            docker_daemon_key=None,
            runtime_mode="mounted_kit",
            worker_kit_version="0.4.0",
            worker_kit_path="/opt/codify/worker-kits/0.4.0-linux-amd64",
            failure_code=None,
            failure_message=None,
            checked_at=None,
            ready_until=utcnow() + timedelta(seconds=900),
            check_generation=0,
            check_started_at=None,
            updated_at=None,
            harness_inventory=_V2_KIT_HARNESS_INVENTORY,
            kit_identity=_V2_WORKER_KIT_IDENTITY,
        )
    )

    with (
        patch(
            "app.core.worker_task_lifecycle.load_task_worker_runtime",
            new=AsyncMock(return_value=runtime),
        ),
        patch(
            "app.core.worker_task_lifecycle.build_issue_workspace_paths",
            return_value=SimpleNamespace(issue_root=str(tmp_path)),
        ),
        patch(
            "app.core.worker_task_lifecycle.create_task_attempt",
            new=AsyncMock(return_value=attempt),
        ),
        patch(
            "app.core.worker_task_lifecycle.run_deterministic_kit_probe",
            new=AsyncMock(return_value=_ready_kit_probe_outcome(kit_identity=changed_kit)),
        ),
    ):
        with pytest.raises(RuntimeError, match="Worker Kit identity changed"):
            await create_execute_container(
                worker,
                db,
                settings=settings,
                task=task,
                issue=issue,
                sudo_gl=None,
            )

    worker.docker.create_container.assert_not_called()


@pytest.mark.asyncio
async def test_v2_execution_rejects_absent_harness_with_harness_cli_unavailable(tmp_path):
    """A Task selecting a Harness absent from the frozen Kit inventory fails
    with the stable harness_cli_unavailable rejection (§11.3)."""
    from app.core.worker_runtime_readiness import HarnessCliUnavailableError

    runtime, settings = _kit_runtime_and_settings()
    worker, db, task, issue, attempt = _kit_failure_execute_fixtures(
        runtime, settings, tmp_path
    )
    inventory = {
        key: {"availability": "absent", "reason_code": "not_selected"}
        for key in ("pi", "opencode", "claude", "codex")
    }
    db.get = AsyncMock(
        return_value=SimpleNamespace(
            status="ready",
            docker_daemon_key=None,
            runtime_mode="mounted_kit",
            worker_kit_version="0.4.0",
            worker_kit_path="/opt/codify/worker-kits/0.4.0-linux-amd64",
            failure_code=None,
            failure_message=None,
            checked_at=None,
            ready_until=utcnow() + timedelta(seconds=900),
            check_generation=0,
            check_started_at=None,
            updated_at=None,
            harness_inventory=inventory,
            kit_identity=_V2_WORKER_KIT_IDENTITY,
        )
    )

    with (
        patch(
            "app.core.worker_task_lifecycle.load_task_worker_runtime",
            new=AsyncMock(return_value=runtime),
        ),
        patch(
            "app.core.worker_task_lifecycle.build_issue_workspace_paths",
            return_value=SimpleNamespace(issue_root=str(tmp_path)),
        ),
        patch(
            "app.core.worker_task_lifecycle.create_task_attempt",
            new=AsyncMock(return_value=attempt),
        ),
        patch(
            "app.core.worker_task_lifecycle.run_deterministic_kit_probe",
            new=AsyncMock(return_value=_ready_kit_probe_outcome(harness_inventory=inventory)),
        ),
    ):
        with pytest.raises(HarnessCliUnavailableError) as exc_info:
            await create_execute_container(
                worker,
                db,
                settings=settings,
                task=task,
                issue=issue,
                sudo_gl=None,
            )

    assert exc_info.value.harness_key == "claude"
    assert exc_info.value.reason_code == "not_selected"
    assert exc_info.value.kit_version == "0.4.0"
    worker.docker.create_container.assert_not_called()


@pytest.mark.asyncio
async def test_prepare_container_inputs_uses_only_snapshot_custom_environment():
    worker = MagicMock()
    worker._resolve_provider = AsyncMock(
        return_value=SimpleNamespace(
            id=1,
            name="Test provider",
            base_url="https://ai.example.com",
            model="claude-sonnet-4-6",
            max_turns=32,
            system_prompt=None,
            **{"api_key": "fixture-value"},
        )
    )
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
    assert task.provider_runtime_snapshot["provider_name"] == "Test provider"
    assert task.provider_runtime_snapshot["configured_model"] == "claude-sonnet-4-6"
    assert task.provider_runtime_snapshot["model_protocol"] == "anthropic_messages"
    assert task.provider_runtime_snapshot["api_key_configured"] is True
    assert "api_key" not in task.provider_runtime_snapshot
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
async def test_failure_handler_renders_worker_runtime_unavailable_as_structured_error():
    import json as json_module

    from app.core.worker_runtime_readiness import WorkerRuntimeUnavailableError

    task = SimpleNamespace(
        id=12,
        status=TaskStatus.RUNNING,
        completed_at=None,
        container_id=None,
        raw_logs_finalized_at=None,
    )
    worker = MagicMock()
    worker._sanitize_sensitive_data.side_effect = lambda value: value
    worker._send_failure_notifications = AsyncMock()
    db = MagicMock()
    db.commit = AsyncMock()

    error = WorkerRuntimeUnavailableError(
        failure_code="worker_kit_not_found",
        failure_message="Worker Kit directory does not exist on the Docker host",
    )
    result = await fail_execute_task(
        worker,
        db,
        task,
        error,
        had_existing_mr=False,
        container=None,
    )

    assert result is False
    assert task.status == TaskStatus.FAILED
    payload = json_module.loads(task.error_message)
    assert payload["code"] == "worker_runtime_unavailable"
    assert payload["failure_code"] == "worker_kit_not_found"
    assert "does not exist" in payload["failure_message"]
    # The structured path never runs sanitize on a raw Docker string.
    worker._sanitize_sensitive_data.assert_not_called()


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


@pytest.mark.asyncio
async def test_execute_runner_stops_started_container_for_persisted_cancellation():
    task = SimpleNamespace(
        id=12,
        status=TaskStatus.RUNNING,
        cancel_requested_at=datetime.now(UTC).replace(tzinfo=None),
    )
    issue = SimpleNamespace(id=1)
    container = MagicMock(status="running", id="container-12")
    worker = MagicMock()
    worker._monitor_container_run = AsyncMock(return_value=False)
    worker._handle_execute_task_failure = AsyncMock()
    db = MagicMock()
    db.refresh = AsyncMock()
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
            new=AsyncMock(return_value=container),
        ),
    ):
        result = await run_execute_task(worker, db, 12, settings=SimpleNamespace())

    assert result is False
    container.reload.assert_called_once_with()
    container.stop.assert_called_once_with(timeout=10)
    worker._monitor_container_run.assert_awaited_once()
    worker._handle_execute_task_failure.assert_not_awaited()
