"""Resolve task and profile Docker daemon targets."""

from __future__ import annotations

import asyncio
import inspect
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any

from docker.errors import NotFound
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.docker_client import (
    DockerConnectionConfig,
    canonicalize_docker_host,
    get_docker_client_async,
    resolve_docker_connection,
)
from app.models import Task, TaskStatus, TaskWorkerProfileSnapshot, WorkerProfile


class DockerConnectionsUnavailableError(RuntimeError):
    """Raised when no credential variant can establish a Docker client."""


class TaskContainerLookupError(LookupError):
    """Raised when Docker is reachable but the task container cannot be resolved."""


class TaskContainerNotFoundError(TaskContainerLookupError):
    """Raised when every reachable credential variant confirms the container is absent."""


@dataclass(frozen=True)
class KnownDockerTarget:
    connection: DockerConnectionConfig
    labels: tuple[str, ...]
    alternate_connections: tuple[DockerConnectionConfig, ...] = ()

    @property
    def daemon_key(self) -> str:
        """Identity of the physical daemon, independent of credential file paths."""
        return docker_daemon_key(self.connection)

    @property
    def connections(self) -> tuple[DockerConnectionConfig, ...]:
        return (self.connection, *self.alternate_connections)


def docker_daemon_key(connection: DockerConnectionConfig) -> str:
    """Return the stable daemon identity used for discovery and ownership checks."""
    return canonicalize_docker_host(
        connection.host,
        tls_enabled=connection.tls_ca is not None,
    )


def connection_from_snapshot(
    snapshot: TaskWorkerProfileSnapshot,
    settings: Any,
) -> DockerConnectionConfig:
    return resolve_docker_connection(
        settings,
        docker_host=getattr(snapshot, "docker_host", None),
        docker_tls_ca=getattr(snapshot, "docker_tls_ca", None),
        docker_tls_cert=getattr(snapshot, "docker_tls_cert", None),
        docker_tls_key=getattr(snapshot, "docker_tls_key", None),
    )


async def connection_for_task(
    db: AsyncSession,
    task: Task,
    settings: Any,
) -> DockerConnectionConfig:
    """Resolve a task target, retaining global fallback for pre-snapshot legacy tasks."""
    snapshot_result = db.get(TaskWorkerProfileSnapshot, task.id)
    if not inspect.isawaitable(snapshot_result):
        return resolve_docker_connection(settings)
    snapshot = await snapshot_result
    if snapshot is None:
        return resolve_docker_connection(settings)
    return connection_from_snapshot(snapshot, settings)


async def connections_for_task(
    db: AsyncSession,
    task: Task,
    settings: Any,
    *,
    known_targets: list[KnownDockerTarget] | None = None,
    primary: DockerConnectionConfig | None = None,
) -> tuple[DockerConnectionConfig, ...]:
    """Return snapshot-first credential variants for the task's physical daemon."""
    primary = primary or await connection_for_task(db, task, settings)
    daemon_key = docker_daemon_key(primary)
    targets = known_targets
    if targets is None:
        targets = await list_known_docker_targets(db, settings, include_retained=True)

    candidates = [primary]
    profile_id = getattr(task, "worker_profile_id", None)
    if isinstance(profile_id, int):
        profile_result = db.get(WorkerProfile, profile_id)
        if inspect.isawaitable(profile_result):
            profile = await profile_result
            if profile is not None:
                current_profile_connection = resolve_docker_connection(
                    settings,
                    docker_host=getattr(profile, "docker_host", None),
                    docker_tls_ca=getattr(profile, "docker_tls_ca", None),
                    docker_tls_cert=getattr(profile, "docker_tls_cert", None),
                    docker_tls_key=getattr(profile, "docker_tls_key", None),
                )
                if (
                    docker_daemon_key(current_profile_connection) == daemon_key
                    and current_profile_connection not in candidates
                ):
                    candidates.append(current_profile_connection)
    for target in targets:
        if target.daemon_key != daemon_key:
            continue
        for connection in target.connections:
            if connection not in candidates:
                candidates.append(connection)
    return tuple(candidates)


async def find_task_container(
    db: AsyncSession,
    task: Task,
    settings: Any,
    container_reference: str,
    *,
    known_targets: list[KnownDockerTarget] | None = None,
    get_client: Callable[[DockerConnectionConfig], Awaitable[Any]] = get_docker_client_async,
):
    """Resolve a task container, falling back across credentials for the same daemon."""
    primary = await connection_for_task(db, task, settings)
    try:
        return await find_container_with_connections(
            (primary,),
            container_reference,
            get_client=get_client,
        )
    except (DockerConnectionsUnavailableError, TaskContainerLookupError) as primary_error:
        connections = await connections_for_task(
            db,
            task,
            settings,
            known_targets=known_targets,
            primary=primary,
        )
        alternates = tuple(connection for connection in connections if connection != primary)
        if not alternates:
            raise primary_error
        try:
            return await find_container_with_connections(
                alternates,
                container_reference,
                get_client=get_client,
            )
        except DockerConnectionsUnavailableError:
            # A reachable credential already confirmed absence on this physical daemon.
            # Broken fallback credentials must not turn that result into indefinite
            # cancellation/recovery deferral.
            if isinstance(primary_error, TaskContainerNotFoundError):
                raise primary_error
            raise


async def find_container_with_connections(
    connections: tuple[DockerConnectionConfig, ...],
    container_reference: str,
    *,
    get_client: Callable[[DockerConnectionConfig], Awaitable[Any]] = get_docker_client_async,
):
    """Find a container through an already resolved sequence of credential variants."""
    last_client_error: Exception | None = None
    last_lookup_error: Exception | None = None
    last_not_found_error: Exception | None = None
    for connection in connections:
        try:
            docker = await get_client(connection)
        except Exception as exc:  # noqa: BLE001
            last_client_error = exc
            continue
        try:
            container = await asyncio.to_thread(
                docker.client.containers.get,
                container_reference,
            )
            return docker, container, connection
        except NotFound as exc:
            last_not_found_error = exc
        except Exception as exc:  # noqa: BLE001
            last_lookup_error = exc
    if last_lookup_error is not None:
        raise TaskContainerLookupError(str(last_lookup_error)) from last_lookup_error
    if last_not_found_error is not None:
        raise TaskContainerNotFoundError(str(last_not_found_error)) from last_not_found_error
    if last_client_error is not None:
        raise DockerConnectionsUnavailableError(str(last_client_error)) from last_client_error
    raise DockerConnectionsUnavailableError("No Docker connection is available for the task")


async def list_known_docker_targets(
    db: AsyncSession,
    settings: Any,
    *,
    include_retained: bool = False,
) -> list[KnownDockerTarget]:
    """List one target per daemon with all known connection credential variants."""
    labels_by_daemon: dict[str, set[str]] = {}
    connections_by_daemon: dict[str, list[DockerConnectionConfig]] = {}

    def add_connection(
        connection: DockerConnectionConfig,
        label: str,
        *,
        preferred: bool = False,
    ) -> None:
        daemon_key = docker_daemon_key(connection)
        labels_by_daemon.setdefault(daemon_key, set()).add(label)
        connections = connections_by_daemon.setdefault(daemon_key, [])
        if connection in connections:
            if preferred and connections[0] != connection:
                connections.remove(connection)
                connections.insert(0, connection)
            return
        if preferred:
            connections.insert(0, connection)
        else:
            connections.append(connection)

    add_connection(resolve_docker_connection(settings), "System default")
    profile_rows = (
        await db.execute(
            select(
                WorkerProfile.name,
                WorkerProfile.docker_host,
                WorkerProfile.docker_tls_ca,
                WorkerProfile.docker_tls_cert,
                WorkerProfile.docker_tls_key,
            ).where(WorkerProfile.enabled == True)
        )
    ).all()
    for name, host, tls_ca, tls_cert, tls_key in profile_rows:
        connection = resolve_docker_connection(
            settings,
            docker_host=host,
            docker_tls_ca=tls_ca,
            docker_tls_cert=tls_cert,
            docker_tls_key=tls_key,
        )
        add_connection(connection, name)

    snapshot_filter = Task.status == TaskStatus.RUNNING
    if include_retained:
        snapshot_filter = or_(
            snapshot_filter,
            and_(
                Task.container_id.is_not(None),
                Task.raw_logs_finalized_at.is_(None),
            ),
        )
    running_rows = (
        await db.execute(
            select(TaskWorkerProfileSnapshot).join(
                Task,
                Task.id == TaskWorkerProfileSnapshot.task_id,
            ).where(snapshot_filter)
        )
    ).scalars()
    for snapshot in running_rows:
        connection = connection_from_snapshot(snapshot, settings)
        add_connection(connection, snapshot.profile_name, preferred=True)

    targets: list[KnownDockerTarget] = []
    for daemon_key, connections in connections_by_daemon.items():
        targets.append(
            KnownDockerTarget(
                connection=connections[0],
                alternate_connections=tuple(connections[1:]),
                labels=tuple(sorted(labels_by_daemon[daemon_key])),
            )
        )
    return targets
