import io
import tarfile
from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from docker.errors import NotFound

from app.core.docker_client import DockerConnectionConfig
from app.core.worker import WorkerExecutor
from app.core.worker_docker_targets import (
    DockerConnectionsUnavailableError,
    KnownDockerTarget,
    TaskContainerNotFoundError,
    connection_for_task,
    docker_daemon_key,
    find_task_container,
    list_known_docker_targets,
)
from app.core.worker_task_lifecycle import (
    finalize_pre_container_cancellation,
    monitor_container_run,
)
from app.models import TaskStatus
from app.scheduler import Scheduler


def _settings():
    return SimpleNamespace(
        docker_host="unix:///var/run/docker.sock",
        docker_tls_ca=None,
        docker_tls_cert=None,
        docker_tls_key=None,
    )


def _no_active_control_attempts_result():
    result = MagicMock()
    result.scalars.return_value = []
    return result


def test_worker_executor_defers_docker_client_until_runtime_is_loaded():
    connection = DockerConnectionConfig(host="tcp://arm-worker:2376")
    runtime = SimpleNamespace(docker_connection=MagicMock(return_value=connection))
    docker = MagicMock()

    with patch("app.core.worker.get_docker_client", return_value=docker) as get_client:
        worker = WorkerExecutor(gitlab_client=MagicMock())
        get_client.assert_not_called()

        assert worker._configure_docker_for_runtime(runtime, _settings()) is docker

    get_client.assert_called_once_with(connection)


@pytest.mark.asyncio
async def test_connection_for_task_uses_snapshot_target():
    snapshot = SimpleNamespace(
        docker_host="tcp://arm-worker:2376",
        docker_tls_ca="/certs/ca.pem",
        docker_tls_cert="/certs/cert.pem",
        docker_tls_key="/certs/key.pem",
    )
    db = SimpleNamespace(get=AsyncMock(return_value=snapshot))

    connection = await connection_for_task(db, SimpleNamespace(id=12), _settings())

    assert connection == DockerConnectionConfig(
        host="tcp://arm-worker:2376",
        tls_ca="/certs/ca.pem",
        tls_cert="/certs/cert.pem",
        tls_key="/certs/key.pem",
    )


@pytest.mark.asyncio
async def test_list_known_targets_deduplicates_profiles_and_running_snapshots():
    profile_result = MagicMock()
    profile_result.all.return_value = [
        ("ARM Worker", "tcp://arm-worker:2376", None, None, None),
        ("ARM Plan Worker", "tcp://arm-worker:2376", None, None, None),
    ]
    running_snapshot = SimpleNamespace(
        profile_name="Deleted Worker",
        docker_host="tcp://legacy-worker:2376",
        docker_tls_ca=None,
        docker_tls_cert=None,
        docker_tls_key=None,
    )
    running_result = MagicMock()
    running_result.scalars.return_value = [running_snapshot]
    db = SimpleNamespace(execute=AsyncMock(side_effect=[profile_result, running_result]))

    targets = await list_known_docker_targets(db, _settings())
    targets_by_host = {target.connection.host: target for target in targets}

    assert set(targets_by_host) == {
        "unix:///var/run/docker.sock",
        "tcp://arm-worker:2376",
        "tcp://legacy-worker:2376",
    }
    assert targets_by_host["tcp://arm-worker:2376"].labels == (
        "ARM Plan Worker",
        "ARM Worker",
    )
    profile_query = db.execute.await_args_list[0].args[0]
    assert "worker_profiles.enabled = true" in str(profile_query).lower()


@pytest.mark.asyncio
async def test_list_known_targets_groups_daemon_aliases_with_rotated_tls_paths():
    profile_result = MagicMock()
    profile_result.all.return_value = [
        (
            "ARM Worker",
            "https://ARM-WORKER:2376",
            "/certs/new-ca.pem",
            "/certs/new-cert.pem",
            "/certs/new-key.pem",
        ),
    ]
    running_snapshot = SimpleNamespace(
        profile_name="ARM Worker snapshot",
        docker_host="tcp://arm-worker:2376",
        docker_tls_ca="/certs/old-ca.pem",
        docker_tls_cert="/certs/old-cert.pem",
        docker_tls_key="/certs/old-key.pem",
    )
    running_result = MagicMock()
    running_result.scalars.return_value = [running_snapshot]
    db = SimpleNamespace(execute=AsyncMock(side_effect=[profile_result, running_result]))

    targets = await list_known_docker_targets(db, _settings())
    arm_targets = [target for target in targets if target.daemon_key == "https://arm-worker:2376"]

    assert len(arm_targets) == 1
    assert arm_targets[0].connection.tls_ca == "/certs/old-ca.pem"
    assert arm_targets[0].alternate_connections[0].tls_ca == "/certs/new-ca.pem"
    assert arm_targets[0].alternate_connections[0].host == "https://ARM-WORKER:2376"


@pytest.mark.asyncio
async def test_list_known_targets_can_include_retained_terminal_snapshots():
    profile_result = MagicMock()
    profile_result.all.return_value = []
    retained_snapshot = SimpleNamespace(
        profile_name="Retained Worker",
        docker_host="tcp://retained-worker:2376",
        docker_tls_ca=None,
        docker_tls_cert=None,
        docker_tls_key=None,
    )
    snapshot_result = MagicMock()
    snapshot_result.scalars.return_value = [retained_snapshot]
    db = SimpleNamespace(execute=AsyncMock(side_effect=[profile_result, snapshot_result]))

    targets = await list_known_docker_targets(
        db,
        _settings(),
        include_retained=True,
    )

    assert "http://retained-worker:2376" in {target.daemon_key for target in targets}
    snapshot_query = db.execute.await_args_list[1].args[0]
    assert "container_id IS NOT NULL" in str(snapshot_query)


@pytest.mark.asyncio
async def test_crash_recovery_clears_finalized_missing_container_reference():
    connection = DockerConnectionConfig(host="tcp://arm-worker:2376")
    task = SimpleNamespace(
        id=9,
        issue_id=90,
        status=TaskStatus.COMPLETED,
        container_id="finished-container-9",
        raw_logs_finalized_at=datetime.now(UTC).replace(tzinfo=None),
    )
    task_result = MagicMock()
    task_result.scalars.return_value.all.return_value = [task]
    db = MagicMock()
    db.execute = AsyncMock(return_value=task_result)
    db.commit = AsyncMock()
    db_context = MagicMock()
    db_context.__aenter__ = AsyncMock(return_value=db)
    db_context.__aexit__ = AsyncMock(return_value=False)
    docker = MagicMock()
    docker.client.containers.list.return_value = []

    scheduler = Scheduler()
    with (
        patch("app.scheduler.AsyncSessionLocal", return_value=db_context),
        patch(
            "app.scheduler.cleanup_inactive_issue_execution_locks",
            new=AsyncMock(return_value=0),
        ),
        patch(
            "app.scheduler.list_known_docker_targets",
            new=AsyncMock(return_value=[KnownDockerTarget(connection, ("ARM Worker",))]),
        ),
        patch("app.scheduler.connection_for_task", new=AsyncMock(return_value=connection)),
        patch("app.scheduler._get_recovery_docker_client", return_value=docker),
        patch(
            "app.scheduler.find_task_container",
            new=AsyncMock(side_effect=TaskContainerNotFoundError("missing")),
        ) as find_container,
    ):
        await scheduler._crash_recovery()

    find_container.assert_awaited_once()
    assert task.container_id is None
    db.commit.assert_awaited()


@pytest.mark.asyncio
async def test_crash_recovery_does_not_orphan_task_when_tls_credentials_rotate():
    old_connection = DockerConnectionConfig(
        host="tcp://arm-worker:2376",
        tls_ca="/certs/old-ca.pem",
        tls_cert="/certs/old-cert.pem",
        tls_key="/certs/old-key.pem",
    )
    new_connection = DockerConnectionConfig(
        host="tcp://arm-worker:2376",
        tls_ca="/certs/new-ca.pem",
        tls_cert="/certs/new-cert.pem",
        tls_key="/certs/new-key.pem",
    )
    task = SimpleNamespace(id=21, issue_id=201, status=TaskStatus.RUNNING)
    task_result = MagicMock()
    task_result.scalars.return_value.all.return_value = [task]
    db = MagicMock()
    db.execute = AsyncMock(return_value=task_result)
    db.commit = AsyncMock()
    db_context = MagicMock()
    db_context.__aenter__ = AsyncMock(return_value=db)
    db_context.__aexit__ = AsyncMock(return_value=False)
    container = SimpleNamespace(
        name="codify-21-issue201",
        status="running",
        remove=MagicMock(),
    )
    new_docker = MagicMock()
    new_docker.client.containers.list.return_value = [container]

    def client_for_connection(connection):
        if connection == old_connection:
            raise RuntimeError("old client certificate rejected")
        assert connection == new_connection
        return new_docker

    scheduler = Scheduler()
    with (
        patch("app.scheduler.AsyncSessionLocal", return_value=db_context),
        patch("app.scheduler.cleanup_inactive_issue_execution_locks", new=AsyncMock(return_value=0)),
        patch(
            "app.scheduler.list_known_docker_targets",
            new=AsyncMock(
                return_value=[
                    KnownDockerTarget(
                        old_connection,
                        ("ARM Worker",),
                        (new_connection,),
                    )
                ]
            ),
        ),
        patch("app.scheduler.connection_for_task", new=AsyncMock(return_value=old_connection)),
        patch("app.scheduler._RECOVERY_RETRY_OFFSETS_SECONDS", (0, 0, 0)),
        patch("app.scheduler._get_recovery_docker_client", side_effect=client_for_connection),
        patch.object(
            scheduler,
            "_resume_task_background",
            new=MagicMock(return_value=object()),
        ) as resume_task,
        patch("app.scheduler.asyncio.create_task", return_value=MagicMock()),
        patch("app.scheduler.release_issue_execution_lock", new=AsyncMock()),
    ):
        await scheduler._crash_recovery()

    assert task.status == TaskStatus.RUNNING
    assert 21 in scheduler._running_tasks
    container.remove.assert_not_called()
    resume_task.assert_called_once_with(21, container.name, new_connection)


@pytest.mark.parametrize("container_status", ["running", "exited"])
@pytest.mark.asyncio
async def test_crash_recovery_does_not_orphan_alias_target_container(container_status):
    """D1: unix socket and tcp aliases of one daemon must not orphan each other's containers.

    A task snapshotted against the tcp connection is owned only by the tcp target's
    daemon key, yet both targets enumerate the same physical container. The unix
    target must not treat it as an unclaimed orphan and remove it, and the container
    must be resumed exactly once across the aliases.
    """
    unix_connection = DockerConnectionConfig(host="unix:///var/run/docker.sock")
    tcp_connection = DockerConnectionConfig(host="tcp://192.168.50.129:2375")
    task = SimpleNamespace(id=558, issue_id=96, status=TaskStatus.RUNNING)
    task_result = MagicMock()
    task_result.scalars.return_value.all.return_value = [task]
    db = MagicMock()
    db.execute = AsyncMock(return_value=task_result)
    db.commit = AsyncMock()
    db_context = MagicMock()
    db_context.__aenter__ = AsyncMock(return_value=db)
    db_context.__aexit__ = AsyncMock(return_value=False)

    container = SimpleNamespace(
        name="codify-558-issue96",
        status=container_status,
        remove=MagicMock(),
    )
    unix_docker = MagicMock()
    unix_docker.client.containers.list.return_value = [container]
    tcp_docker = MagicMock()
    tcp_docker.client.containers.list.return_value = [container]

    def client_for_connection(connection):
        if connection == unix_connection:
            return unix_docker
        assert connection == tcp_connection
        return tcp_docker

    scheduler = Scheduler()
    with (
        patch("app.scheduler.AsyncSessionLocal", return_value=db_context),
        patch("app.scheduler.cleanup_inactive_issue_execution_locks", new=AsyncMock(return_value=0)),
        patch(
            "app.scheduler.list_known_docker_targets",
            new=AsyncMock(
                return_value=[
                    KnownDockerTarget(unix_connection, ("System default",)),
                    KnownDockerTarget(tcp_connection, ("ARM Worker",)),
                ]
            ),
        ),
        patch("app.scheduler.connection_for_task", new=AsyncMock(return_value=tcp_connection)),
        patch("app.scheduler._RECOVERY_RETRY_OFFSETS_SECONDS", (0, 0, 0)),
        patch("app.scheduler._get_recovery_docker_client", side_effect=client_for_connection),
        patch.object(
            scheduler,
            "_resume_task_background",
            new=MagicMock(return_value=object()),
        ) as resume_task,
        patch("app.scheduler.asyncio.create_task", return_value=MagicMock()),
    ):
        await scheduler._crash_recovery()

    container.remove.assert_not_called()
    assert resume_task.call_count == 1
    assert task.status == TaskStatus.RUNNING
    assert 558 in scheduler._running_tasks
    assert 96 in scheduler._running_issues


@pytest.mark.asyncio
async def test_crash_recovery_keeps_alias_target_retained_container():
    """A retained (terminal, unfinalized logs) container is not orphaned by an alias target."""
    unix_connection = DockerConnectionConfig(host="unix:///var/run/docker.sock")
    tcp_connection = DockerConnectionConfig(host="tcp://192.168.50.129:2375")
    task = SimpleNamespace(
        id=559,
        issue_id=97,
        status=TaskStatus.CANCELLED,
        container_id="codify-559-issue97",
        raw_logs_finalized_at=None,
    )
    task_result = MagicMock()
    task_result.scalars.return_value.all.return_value = [task]
    db = MagicMock()
    db.execute = AsyncMock(return_value=task_result)
    db.commit = AsyncMock()
    db_context = MagicMock()
    db_context.__aenter__ = AsyncMock(return_value=db)
    db_context.__aexit__ = AsyncMock(return_value=False)

    container = SimpleNamespace(
        name="codify-559-issue97",
        status="exited",
        remove=MagicMock(),
    )
    unix_docker = MagicMock()
    unix_docker.client.containers.list.return_value = [container]
    tcp_docker = MagicMock()
    tcp_docker.client.containers.list.return_value = [container]

    def client_for_connection(connection):
        if connection == unix_connection:
            return unix_docker
        assert connection == tcp_connection
        return tcp_docker

    scheduler = Scheduler()
    with (
        patch("app.scheduler.AsyncSessionLocal", return_value=db_context),
        patch("app.scheduler.cleanup_inactive_issue_execution_locks", new=AsyncMock(return_value=0)),
        patch(
            "app.scheduler.list_known_docker_targets",
            new=AsyncMock(
                return_value=[
                    KnownDockerTarget(unix_connection, ("System default",)),
                    KnownDockerTarget(tcp_connection, ("ARM Worker",)),
                ]
            ),
        ),
        patch("app.scheduler.connection_for_task", new=AsyncMock(return_value=tcp_connection)),
        patch("app.scheduler._RECOVERY_RETRY_OFFSETS_SECONDS", (0, 0, 0)),
        patch("app.scheduler._get_recovery_docker_client", side_effect=client_for_connection),
    ):
        await scheduler._crash_recovery()

    container.remove.assert_not_called()
    assert task.status == TaskStatus.CANCELLED


@pytest.mark.asyncio
async def test_crash_recovery_stops_running_container_for_persisted_cancel_intent():
    connection = DockerConnectionConfig(host="tcp://arm-worker:2376")
    task = SimpleNamespace(
        id=24,
        issue_id=204,
        status=TaskStatus.RUNNING,
        cancel_requested_at=datetime.now(UTC).replace(tzinfo=None),
    )
    task_result = MagicMock()
    task_result.scalars.return_value.all.return_value = [task]
    db = MagicMock()
    db.execute = AsyncMock(return_value=task_result)
    db.commit = AsyncMock()
    db_context = MagicMock()
    db_context.__aenter__ = AsyncMock(return_value=db)
    db_context.__aexit__ = AsyncMock(return_value=False)
    container = MagicMock()
    container.name = "codify-24-issue204"
    container.status = "running"
    docker = MagicMock()
    docker.client.containers.list.return_value = [container]

    scheduler = Scheduler()
    with (
        patch("app.scheduler.AsyncSessionLocal", return_value=db_context),
        patch("app.scheduler.cleanup_inactive_issue_execution_locks", new=AsyncMock(return_value=0)),
        patch(
            "app.scheduler.list_known_docker_targets",
            new=AsyncMock(return_value=[KnownDockerTarget(connection, ("ARM Worker",))]),
        ),
        patch("app.scheduler.connection_for_task", new=AsyncMock(return_value=connection)),
        patch("app.scheduler._get_recovery_docker_client", return_value=docker),
        patch.object(
            scheduler,
            "_resume_task_background",
            new=MagicMock(return_value=object()),
        ) as resume_task,
        patch("app.scheduler.asyncio.create_task", return_value=MagicMock()),
    ):
        await scheduler._crash_recovery()

    container.stop.assert_called_once_with(timeout=10)
    container.kill.assert_not_called()
    resume_task.assert_called_once_with(task.id, container.name, connection)


@pytest.mark.asyncio
async def test_task_container_lookup_falls_back_to_rotated_credentials():
    old_connection = DockerConnectionConfig(
        host="tcp://arm-worker:2376",
        tls_ca="/certs/old-ca.pem",
        tls_cert="/certs/old-cert.pem",
        tls_key="/certs/old-key.pem",
    )
    new_connection = DockerConnectionConfig(
        host="https://arm-worker:2376",
        tls_ca="/certs/new-ca.pem",
        tls_cert="/certs/new-cert.pem",
        tls_key="/certs/new-key.pem",
    )
    task = SimpleNamespace(id=22)
    container = MagicMock()
    new_docker = MagicMock()
    new_docker.client.containers.get.return_value = container

    async def get_client(connection):
        if connection == old_connection:
            raise RuntimeError("old client certificate rejected")
        assert connection == new_connection
        return new_docker

    with (
        patch(
            "app.core.worker_docker_targets.connection_for_task",
            new=AsyncMock(return_value=old_connection),
        ),
        patch(
            "app.core.worker_docker_targets.list_known_docker_targets",
            new=AsyncMock(
                return_value=[
                    KnownDockerTarget(old_connection, ("ARM Worker",), (new_connection,))
                ]
            ),
        ),
    ):
        docker, resolved_container, connection = await find_task_container(
            MagicMock(),
            task,
            _settings(),
            "container-22",
            get_client=get_client,
        )

    assert docker is new_docker
    assert resolved_container is container
    assert connection == new_connection
    new_docker.client.containers.get.assert_called_once_with("container-22")


@pytest.mark.asyncio
async def test_task_container_lookup_keeps_primary_not_found_when_alternate_is_unavailable():
    primary = DockerConnectionConfig(host="tcp://arm-worker:2376")
    alternate = DockerConnectionConfig(
        host="tcp://arm-worker:2376",
        tls_ca="/certs/stale-ca.pem",
        tls_cert="/certs/stale-cert.pem",
        tls_key="/certs/stale-key.pem",
    )
    primary_docker = MagicMock()
    primary_docker.client.containers.get.side_effect = NotFound("missing")

    async def get_client(connection):
        if connection == primary:
            return primary_docker
        raise RuntimeError("stale credentials")

    with (
        patch(
            "app.core.worker_docker_targets.connection_for_task",
            new=AsyncMock(return_value=primary),
        ),
        patch(
            "app.core.worker_docker_targets.connections_for_task",
            new=AsyncMock(return_value=(primary, alternate)),
        ),
        pytest.raises(TaskContainerNotFoundError),
    ):
        await find_task_container(
            MagicMock(),
            SimpleNamespace(id=23),
            _settings(),
            "container-23",
            get_client=get_client,
        )


@pytest.mark.asyncio
async def test_crash_recovery_preserves_terminal_container_with_unfinalized_logs():
    connection = DockerConnectionConfig(host="tcp://arm-worker:2376")
    task = SimpleNamespace(
        id=23,
        issue_id=203,
        status=TaskStatus.CANCELLED,
        container_id="container-23",
        raw_logs_finalized_at=None,
    )
    task_result = MagicMock()
    task_result.scalars.return_value.all.return_value = [task]
    db = MagicMock()
    db.execute = AsyncMock(return_value=task_result)
    db.commit = AsyncMock()
    db_context = MagicMock()
    db_context.__aenter__ = AsyncMock(return_value=db)
    db_context.__aexit__ = AsyncMock(return_value=False)
    container = SimpleNamespace(
        id="container-23",
        name="codify-23-issue203",
        status="exited",
        remove=MagicMock(),
    )
    docker = MagicMock()
    docker.client.containers.list.return_value = [container]

    scheduler = Scheduler()
    with (
        patch("app.scheduler.AsyncSessionLocal", return_value=db_context),
        patch("app.scheduler.cleanup_inactive_issue_execution_locks", new=AsyncMock(return_value=0)),
        patch(
            "app.scheduler.list_known_docker_targets",
            new=AsyncMock(return_value=[KnownDockerTarget(connection, ("ARM Worker",))]),
        ),
        patch("app.scheduler.connection_for_task", new=AsyncMock(return_value=connection)),
        patch("app.scheduler._get_recovery_docker_client", return_value=docker),
    ):
        await scheduler._crash_recovery()

    container.remove.assert_not_called()
    assert task.status == TaskStatus.CANCELLED


def test_docker_daemon_key_normalizes_tls_tcp_and_https_aliases():
    tcp_tls = DockerConnectionConfig(
        host="tcp://Worker.Example:2376",
        tls_ca="/certs/ca.pem",
        tls_cert="/certs/cert.pem",
        tls_key="/certs/key.pem",
    )
    https = DockerConnectionConfig(host="https://worker.example:2376")

    assert docker_daemon_key(tcp_tls) == "https://worker.example:2376"
    assert docker_daemon_key(https) == docker_daemon_key(tcp_tls)


@pytest.mark.asyncio
async def test_crash_recovery_routes_each_task_to_its_snapshot_daemon():
    arm_connection = DockerConnectionConfig(host="tcp://arm-worker:2376")
    x86_connection = DockerConnectionConfig(host="tcp://x86-worker:2376")
    arm_task = SimpleNamespace(id=11, issue_id=101, status=TaskStatus.RUNNING)
    x86_task = SimpleNamespace(id=12, issue_id=102, status=TaskStatus.RUNNING)
    task_result = MagicMock()
    task_result.scalars.return_value.all.return_value = [arm_task, x86_task]
    db = MagicMock()
    db.execute = AsyncMock(return_value=task_result)
    db.commit = AsyncMock()
    db_context = MagicMock()
    db_context.__aenter__ = AsyncMock(return_value=db)
    db_context.__aexit__ = AsyncMock(return_value=False)

    arm_container = SimpleNamespace(
        name="codify-11-issue101",
        status="running",
        remove=MagicMock(),
    )
    arm_docker = MagicMock()
    arm_docker.client.containers.list.return_value = [arm_container]

    def client_for_connection(connection):
        if connection == arm_connection:
            return arm_docker
        raise RuntimeError("x86 daemon unavailable")

    async def task_connection(_db, task, _settings):
        return arm_connection if task.id == 11 else x86_connection

    scheduler = Scheduler()
    with (
        patch("app.scheduler.AsyncSessionLocal", return_value=db_context),
        patch("app.scheduler.cleanup_inactive_issue_execution_locks", new=AsyncMock(return_value=0)),
        patch(
            "app.scheduler.list_known_docker_targets",
            new=AsyncMock(
                return_value=[
                    KnownDockerTarget(arm_connection, ("ARM Worker",)),
                    KnownDockerTarget(x86_connection, ("x86 Worker",)),
                ]
            ),
        ),
        patch("app.scheduler.connection_for_task", new=AsyncMock(side_effect=task_connection)),
        patch("app.scheduler._RECOVERY_RETRY_OFFSETS_SECONDS", (0, 0, 0)),
        patch("app.scheduler._get_recovery_docker_client", side_effect=client_for_connection) as get_client,
        patch.object(
            scheduler,
            "_resume_task_background",
            new=MagicMock(return_value=object()),
        ),
        patch.object(
            scheduler,
            "_coordinate_unavailable_recovery",
            new=MagicMock(return_value=object()),
        ),
        patch("app.scheduler.asyncio.create_task", return_value=MagicMock()),
        patch(
            "app.scheduler.release_issue_execution_lock", new=AsyncMock()
        ) as release_lock,
    ):
        await scheduler._crash_recovery()

    assert 11 in scheduler._running_tasks
    assert 12 in scheduler._running_tasks
    assert arm_task.status == TaskStatus.RUNNING
    assert x86_task.status == TaskStatus.RUNNING
    assert 102 in scheduler._running_issues
    release_lock.assert_not_awaited()
    assert get_client.call_count == 4


@pytest.mark.asyncio
async def test_crash_recovery_uses_stable_container_id_after_prefix_change():
    connection = DockerConnectionConfig(host="tcp://arm-worker:2376")
    task = SimpleNamespace(
        id=21,
        issue_id=201,
        status=TaskStatus.RUNNING,
        container_id="stable-container-21",
    )
    task_result = MagicMock()
    task_result.scalars.return_value.all.return_value = [task]
    db = MagicMock()
    db.execute = AsyncMock(return_value=task_result)
    db.commit = AsyncMock()
    db_context = MagicMock()
    db_context.__aenter__ = AsyncMock(return_value=db)
    db_context.__aexit__ = AsyncMock(return_value=False)

    docker = MagicMock()
    docker.client.containers.list.return_value = []
    scheduler = Scheduler()
    with (
        patch("app.scheduler.AsyncSessionLocal", return_value=db_context),
        patch("app.scheduler.cleanup_inactive_issue_execution_locks", new=AsyncMock(return_value=0)),
        patch(
            "app.scheduler.list_known_docker_targets",
            new=AsyncMock(return_value=[KnownDockerTarget(connection, ("ARM Worker",))]),
        ),
        patch("app.scheduler.connection_for_task", new=AsyncMock(return_value=connection)),
        patch("app.scheduler._get_recovery_docker_client", return_value=docker),
        patch(
            "app.scheduler._inspect_recovery_container",
            return_value=("old-prefix-21-issue201", "running"),
        ) as inspect_container,
        patch.object(
            scheduler,
            "_resume_task_background",
            new=MagicMock(return_value=object()),
        ),
        patch("app.scheduler.asyncio.create_task", return_value=MagicMock()),
    ):
        await scheduler._crash_recovery()

    inspect_container.assert_called_once_with(connection, "stable-container-21")
    assert task.status == TaskStatus.RUNNING
    assert task.id in scheduler._running_tasks


@pytest.mark.asyncio
async def test_deferred_recovery_retries_then_resumes_remote_container():
    connection = DockerConnectionConfig(host="tcp://arm-worker:2376")
    task = SimpleNamespace(
        id=31,
        issue_id=301,
        status=TaskStatus.RUNNING,
        container_id="stable-container-31",
    )
    container = MagicMock(name="container")
    container.name = "old-prefix-31-issue301"
    container.status = "running"
    container.reload = MagicMock()
    db = MagicMock()
    db.get = AsyncMock(return_value=task)
    db.refresh = AsyncMock()
    db_context = MagicMock()
    db_context.__aenter__ = AsyncMock(return_value=db)
    db_context.__aexit__ = AsyncMock(return_value=False)

    scheduler = Scheduler()
    scheduler.running = True
    resume = AsyncMock()
    with (
        patch("app.scheduler.AsyncSessionLocal", return_value=db_context),
        patch(
            "app.scheduler.find_task_container",
            new=AsyncMock(
                side_effect=[
                    DockerConnectionsUnavailableError("daemon unavailable"),
                    (MagicMock(), container, connection),
                ]
            ),
        ) as find_container,
        patch("app.scheduler.asyncio.sleep", new=AsyncMock()) as sleep,
        patch.object(scheduler, "_resume_task_background", new=resume),
        patch(
            "app.scheduler.release_issue_execution_lock", new=AsyncMock()
        ) as release_lock,
    ):
        await scheduler._coordinate_unavailable_recovery(task.id)

    assert find_container.await_count == 2
    sleep.assert_awaited_once()
    resume.assert_awaited_once_with(task.id, container.name, connection)
    release_lock.assert_not_awaited()
    assert task.status == TaskStatus.RUNNING


@pytest.mark.asyncio
async def test_deferred_recovery_honors_cancel_intent_when_container_is_absent():
    cancel_requested_at = datetime.now(UTC).replace(tzinfo=None)
    task = SimpleNamespace(
        id=32,
        issue_id=302,
        status=TaskStatus.RUNNING,
        container_id="stable-container-32",
        cancel_requested_at=cancel_requested_at,
        error_message=None,
        completed_at=None,
    )
    db = MagicMock()
    db.get = AsyncMock(return_value=task)
    db.refresh = AsyncMock()
    db.commit = AsyncMock()
    db_context = MagicMock()
    db_context.__aenter__ = AsyncMock(return_value=db)
    db_context.__aexit__ = AsyncMock(return_value=False)

    scheduler = Scheduler()
    scheduler.running = True
    scheduler._running_tasks.add(task.id)
    scheduler._running_issues.add(task.issue_id)
    with (
        patch("app.scheduler.AsyncSessionLocal", return_value=db_context),
        patch(
            "app.scheduler.find_task_container",
            new=AsyncMock(side_effect=TaskContainerNotFoundError("missing")),
        ),
        patch(
            "app.scheduler.release_issue_execution_lock", new=AsyncMock()
        ) as release_lock,
        patch("app.scheduler.close_task_control_gates", new=AsyncMock()) as close_gates,
    ):
        await scheduler._coordinate_unavailable_recovery(task.id)

    assert task.status == TaskStatus.CANCELLED
    assert task.error_message == "Cancelled by user; worker container is confirmed absent"
    assert task.container_id is None
    release_lock.assert_awaited_once_with(db, issue_id=task.issue_id, owner_task_id=task.id)
    close_gates.assert_awaited_once_with(
        db,
        task_id=task.id,
        reason="scheduler recovery confirmed worker container absent",
    )
    db.commit.assert_awaited_once()
    assert task.id not in scheduler._running_tasks
    assert task.issue_id not in scheduler._running_issues


@pytest.mark.asyncio
async def test_deferred_recovery_stops_container_for_persisted_cancel_intent():
    connection = DockerConnectionConfig(host="tcp://arm-worker:2376")
    task = SimpleNamespace(
        id=33,
        issue_id=303,
        status=TaskStatus.RUNNING,
        container_id="stable-container-33",
        cancel_requested_at=datetime.now(UTC).replace(tzinfo=None),
    )
    container = MagicMock()
    container.name = "codify-33-issue303"
    container.status = "running"
    db = MagicMock()
    db.get = AsyncMock(return_value=task)
    db.refresh = AsyncMock()
    db_context = MagicMock()
    db_context.__aenter__ = AsyncMock(return_value=db)
    db_context.__aexit__ = AsyncMock(return_value=False)

    scheduler = Scheduler()
    scheduler.running = True
    resume = AsyncMock()
    with (
        patch("app.scheduler.AsyncSessionLocal", return_value=db_context),
        patch(
            "app.scheduler.find_task_container",
            new=AsyncMock(return_value=(MagicMock(), container, connection)),
        ),
        patch.object(scheduler, "_resume_task_background", new=resume),
    ):
        await scheduler._coordinate_unavailable_recovery(task.id)

    container.stop.assert_called_once_with(timeout=10)
    container.kill.assert_not_called()
    resume.assert_awaited_once_with(task.id, container.name, connection)


@pytest.mark.asyncio
async def test_deferred_recovery_keeps_cancelled_outcome_for_non_runnable_container():
    connection = DockerConnectionConfig(host="tcp://arm-worker:2376")
    task = SimpleNamespace(
        id=34,
        issue_id=304,
        status=TaskStatus.RUNNING,
        container_id="stable-container-34",
        cancel_requested_at=datetime.now(UTC).replace(tzinfo=None),
        completed_at=None,
        error_message=None,
        raw_logs_finalized_at=None,
    )
    container = MagicMock()
    container.name = "codify-34-issue304"
    container.status = "dead"
    docker = MagicMock()
    docker.read_file_from_container.return_value = b"worker stopped\n"
    db = MagicMock()
    db.get = AsyncMock(return_value=task)
    db.refresh = AsyncMock()
    db.commit = AsyncMock()
    db_context = MagicMock()
    db_context.__aenter__ = AsyncMock(return_value=db)
    db_context.__aexit__ = AsyncMock(return_value=False)

    scheduler = Scheduler()
    scheduler.running = True
    with (
        patch("app.scheduler.AsyncSessionLocal", return_value=db_context),
        patch(
            "app.scheduler.find_task_container",
            new=AsyncMock(return_value=(docker, container, connection)),
        ),
        patch(
            "app.scheduler.persist_raw_log_snapshot",
            new=AsyncMock(),
        ) as persist_snapshot,
        patch.object(scheduler, "_resume_task_background", new=AsyncMock()) as resume,
        patch("app.scheduler.release_issue_execution_lock", new=AsyncMock()) as release_lock,
        patch("app.scheduler.close_task_control_gates", new=AsyncMock()) as close_gates,
    ):
        await scheduler._coordinate_unavailable_recovery(task.id)

    container.remove.assert_called_once_with(force=True, v=True)
    assert task.status == TaskStatus.CANCELLED
    assert task.error_message == "Cancelled by user; recovered worker container was removed"
    assert task.container_id is None
    assert task.raw_logs_finalized_at is not None
    persist_snapshot.assert_awaited_once_with(
        db,
        task_id=task.id,
        content=b"worker stopped\n",
    )
    release_lock.assert_awaited_once_with(db, issue_id=task.issue_id, owner_task_id=task.id)
    close_gates.assert_awaited_once_with(
        db,
        task_id=task.id,
        reason="scheduler recovery removed non-runnable worker container",
    )
    resume.assert_not_awaited()


@pytest.mark.asyncio
async def test_worker_bootstrap_failure_keeps_persisted_cancelled_outcome():
    task = SimpleNamespace(
        id=35,
        issue_id=305,
        status=TaskStatus.RUNNING,
        cancel_requested_at=datetime.now(UTC).replace(tzinfo=None),
        completed_at=None,
        error_message=None,
    )
    task_result = MagicMock()
    task_result.scalar_one_or_none.return_value = task
    db = MagicMock()
    db.execute = AsyncMock(return_value=task_result)
    db.commit = AsyncMock()
    db_context = MagicMock()
    db_context.__aenter__ = AsyncMock(return_value=db)
    db_context.__aexit__ = AsyncMock(return_value=False)

    scheduler = Scheduler()
    with (
        patch("app.scheduler.AsyncSessionLocal", return_value=db_context),
        patch("app.scheduler.release_issue_execution_lock", new=AsyncMock()) as release_lock,
    ):
        await scheduler._mark_worker_bootstrap_failed(task.id, RuntimeError("docker down"))

    assert task.status == TaskStatus.CANCELLED
    assert task.error_message == "Cancelled by user before worker startup completed"
    release_lock.assert_awaited_once_with(db, issue_id=task.issue_id, owner_task_id=task.id)
    db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_worker_finalization_honors_persisted_cancellation_intent():
    now = datetime.now(UTC).replace(tzinfo=None)
    task = SimpleNamespace(
        id=41,
        status=TaskStatus.RUNNING,
        cancel_requested_at=now,
        completed_at=None,
        error_message=None,
        raw_logs_finalized_at=now,
    )
    container = MagicMock()
    worker = MagicMock()
    worker._session_factory = None
    worker._send_cancelled_notifications = AsyncMock()
    worker._stream_logs_to_db = AsyncMock(return_value=(137, "stopped", 1, False))
    worker._parse_task_result = AsyncMock()
    worker.docker.remove_container = MagicMock()
    db = MagicMock()
    db.execute = AsyncMock(return_value=_no_active_control_attempts_result())
    db.refresh = AsyncMock()
    db.commit = AsyncMock()
    settings = SimpleNamespace(task_timeout=1800)

    with (
        patch(
            "app.core.worker_task_lifecycle.poll_task_artifacts",
            new=MagicMock(return_value=object()),
        ),
        patch("app.core.worker_task_lifecycle.asyncio.create_task", return_value=MagicMock()),
        patch("app.core.worker_task_lifecycle._stop_artifact_poller", new=AsyncMock()),
        patch("app.core.worker_task_lifecycle.finalize_task_raw_logs", new=AsyncMock()),
        patch("app.core.worker_task_lifecycle.flush_task_artifacts", new=AsyncMock()),
    ):
        result = await monitor_container_run(
            worker,
            db=db,
            task=task,
            issue=None,
            container=container,
            settings=settings,
            had_existing_mr=False,
            sudo_gl=None,
        )

    assert result is False
    assert task.status == TaskStatus.CANCELLED
    assert task.error_message == "Cancelled by user"
    assert task.container_id is None
    assert db.commit.await_count == 2
    worker._send_cancelled_notifications.assert_awaited_once_with(task)
    worker._parse_task_result.assert_awaited()
    worker.docker.remove_container.assert_called_once_with(container, force=True)


@pytest.mark.asyncio
async def test_worker_finalization_keeps_completed_when_cancel_arrives_late():
    now = datetime.now(UTC).replace(tzinfo=None)
    task = SimpleNamespace(
        id=43,
        status=TaskStatus.RUNNING,
        cancel_requested_at=now,
        completed_at=None,
        error_message=None,
        raw_logs_finalized_at=now,
        container_id=None,
        output_session_id=None,
        _parsed_mr_iid=None,
        _parsed_mr_url=None,
        model_name=None,
        commit_sha=None,
        commit_message=None,
        input_tokens=None,
        output_tokens=None,
        _extracted_session_id=None,
    )
    container = MagicMock()
    worker = MagicMock()
    worker._session_factory = None
    worker._stream_logs_to_db = AsyncMock(return_value=(0, "", 1, False))
    worker._send_notifications = AsyncMock()
    worker._try_upsert_usage_ledger = AsyncMock()
    worker.docker.remove_container = MagicMock()

    async def _parse_success(task, logs, db, exit_code, issue=None):
        task.status = TaskStatus.COMPLETED
        task.completed_at = now

    worker._parse_task_result = AsyncMock(side_effect=_parse_success)
    db = MagicMock()
    db.execute = AsyncMock(return_value=_no_active_control_attempts_result())
    db.refresh = AsyncMock()
    db.commit = AsyncMock()
    settings = SimpleNamespace(task_timeout=1800)

    with (
        patch(
            "app.core.worker_task_lifecycle.poll_task_artifacts",
            new=MagicMock(return_value=object()),
        ),
        patch("app.core.worker_task_lifecycle.asyncio.create_task", return_value=MagicMock()),
        patch("app.core.worker_task_lifecycle._stop_artifact_poller", new=AsyncMock()),
        patch("app.core.worker_task_lifecycle.finalize_task_raw_logs", new=AsyncMock()),
        patch("app.core.worker_task_lifecycle.flush_task_artifacts", new=AsyncMock()),
        patch(
            "app.core.worker_task_lifecycle._save_delivery_summary_from_container",
            new=AsyncMock(),
        ),
    ):
        result = await monitor_container_run(
            worker,
            db=db,
            task=task,
            issue=None,
            container=container,
            settings=settings,
            had_existing_mr=False,
            sudo_gl=None,
        )

    assert result is True
    assert task.status == TaskStatus.COMPLETED
    assert task.error_message is None
    worker._send_notifications.assert_awaited_once()


@pytest.mark.asyncio
async def test_worker_finalization_gracefully_stops_container_on_timeout():
    now = datetime.now(UTC).replace(tzinfo=None)
    task = SimpleNamespace(
        id=44,
        status=TaskStatus.RUNNING,
        cancel_requested_at=None,
        completed_at=None,
        error_message=None,
        raw_logs_finalized_at=now,
        container_id=None,
        output_session_id=None,
        _parsed_mr_iid=None,
        _parsed_mr_url=None,
        model_name=None,
        commit_sha=None,
        commit_message=None,
        input_tokens=None,
        output_tokens=None,
        _extracted_session_id=None,
    )
    container = MagicMock()
    worker = MagicMock()
    worker._session_factory = None
    worker._stream_logs_to_db = AsyncMock(return_value=(-1, "", 1, True))
    worker._send_failure_notifications = AsyncMock()
    worker._try_upsert_usage_ledger = AsyncMock()
    worker._sanitize_sensitive_data = MagicMock(return_value="")
    worker._scrub_sensitive_data = MagicMock(return_value="")
    worker.docker.remove_container = MagicMock()

    async def _parse_failed(task, logs, db, exit_code, issue=None):
        task.status = TaskStatus.FAILED

    worker._parse_task_result = AsyncMock(side_effect=_parse_failed)
    db = MagicMock()
    db.execute = AsyncMock(return_value=_no_active_control_attempts_result())
    db.refresh = AsyncMock()
    db.commit = AsyncMock()
    settings = SimpleNamespace(task_timeout=1800)

    with (
        patch(
            "app.core.worker_task_lifecycle.poll_task_artifacts",
            new=MagicMock(return_value=object()),
        ),
        patch("app.core.worker_task_lifecycle.asyncio.create_task", return_value=MagicMock()),
        patch("app.core.worker_task_lifecycle._stop_artifact_poller", new=AsyncMock()),
        patch("app.core.worker_task_lifecycle.finalize_task_raw_logs", new=AsyncMock()),
        patch("app.core.worker_task_lifecycle.flush_task_artifacts", new=AsyncMock()),
        patch(
            "app.core.worker_task_lifecycle._save_delivery_summary_from_container",
            new=AsyncMock(),
        ),
    ):
        result = await monitor_container_run(
            worker,
            db=db,
            task=task,
            issue=None,
            container=container,
            settings=settings,
            had_existing_mr=False,
            sudo_gl=None,
        )

    container.stop.assert_called_once_with(timeout=15)
    marker_call = worker.docker.put_archive.call_args
    assert marker_call.args[1] == "/tmp/codify-runtime"
    with tarfile.open(fileobj=io.BytesIO(marker_call.args[2])) as archive:
        assert archive.getnames() == [".codify-timeout"]
    assert result is False
    assert task.status == TaskStatus.FAILED
    assert "Task timed out after 1800s" in task.error_message


@pytest.mark.asyncio
async def test_worker_does_not_create_container_after_cancel_intent_is_persisted():
    task = SimpleNamespace(
        id=42,
        status=TaskStatus.RUNNING,
        cancel_requested_at=datetime.now(UTC).replace(tzinfo=None),
        completed_at=None,
        error_message=None,
    )
    db = MagicMock()
    db.refresh = AsyncMock()
    db.commit = AsyncMock()

    cancelled = await finalize_pre_container_cancellation(
        db,
        task,
        phase="container creation",
    )

    assert cancelled is True
    assert task.status == TaskStatus.CANCELLED
    assert task.error_message == "Cancelled by user"
    db.commit.assert_awaited_once()
