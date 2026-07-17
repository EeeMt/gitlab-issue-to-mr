"""Inspect and remove issue workspaces on their pinned Docker daemon."""

from __future__ import annotations

import asyncio
import contextlib
import json
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.docker_client import (
    DockerClientWrapper,
    DockerConnectionConfig,
    create_docker_client_async,
    resolve_docker_connection,
)
from app.core.worker_kit import (
    KIT_CONTAINER_USER,
    KIT_ENTRYPOINT,
    MOUNTED_KIT_MODE,
    validate_worker_kit_config,
    worker_kit_environment,
    worker_kit_mounts,
)
from app.core.worker_workspace import build_issue_workspace_paths, configured_workspace_root
from app.models import Issue, WorkerProfile

_MAINTENANCE_MOUNT = "/codify-workspaces"


@dataclass(frozen=True, slots=True)
class RemoteWorkspaceStatus:
    issue_root: str
    repo_path: str
    issue_exists: bool
    repo_exists: bool


async def _load_issue_worker_profile(
    db: AsyncSession,
    issue: Issue,
) -> WorkerProfile:
    # Never touch ``issue.worker_profile`` here. Most callers intentionally load and
    # lock only the Issue row; accessing an unloaded relationship from AsyncSession
    # would attempt implicit IO and raise MissingGreenlet.
    profile = await db.get(WorkerProfile, issue.worker_profile_id)
    if profile is None:
        raise RuntimeError(f"Worker profile {issue.worker_profile_id} is not available")
    return profile


def _profile_connection(profile: WorkerProfile, settings: Any) -> DockerConnectionConfig:
    return resolve_docker_connection(
        settings,
        docker_host=profile.docker_host,
        docker_tls_ca=profile.docker_tls_ca,
        docker_tls_cert=profile.docker_tls_cert,
        docker_tls_key=profile.docker_tls_key,
    )


async def _run_maintenance_container(
    *,
    docker: DockerClientWrapper,
    profile: WorkerProfile,
    workspace_root: str,
    environment: dict[str, str],
    script: str,
    read_only: bool,
) -> dict[str, Any]:
    workspace_volume = {
        workspace_root: {
            "bind": _MAINTENANCE_MOUNT,
            "mode": "ro" if read_only else "rw",
        }
    }

    def run(
        *,
        command: list[str],
        entrypoint: str,
        runtime_environment: dict[str, str],
        volumes: dict[str, dict[str, str]],
    ) -> bytes | str:
        return docker.client.containers.run(
            profile.image,
            command,
            entrypoint=entrypoint,
            environment=runtime_environment,
            volumes=volumes,
            # Runtime images may declare an unprivileged default USER. Docker creates
            # missing bind-mount parents as root, so workspace removal must not inherit
            # that image default or retained Issue directories can become undeletable.
            user=KIT_CONTAINER_USER,
            labels={"codify.workspace_maintenance": "true"},
            remove=True,
        )

    try:
        raw = await asyncio.to_thread(
            run,
            command=["-c", script],
            entrypoint="/bin/sh",
            runtime_environment=environment,
            volumes=workspace_volume,
        )
    except Exception as exc:
        # Mounted-kit task images are intentionally allowed to omit a shell and
        # coreutils. Retry only command-not-found failures through the kit launcher;
        # application errors such as owner-marker mismatch must remain authoritative.
        error_text = str(exc).lower()
        missing_command = getattr(exc, "exit_status", None) in {126, 127} or any(
            marker in error_text
            for marker in (
                "executable file not found",
                "/bin/sh: no such file",
                "not found in $path",
            )
        )
        runtime_mode, kit_version, kit_path = validate_worker_kit_config(
            runtime_mode=getattr(profile, "runtime_mode", None),
            worker_kit_version=getattr(profile, "worker_kit_version", None),
            worker_kit_path=getattr(profile, "worker_kit_path", None),
        )
        if not missing_command or runtime_mode != MOUNTED_KIT_MODE:
            raise
        assert kit_version is not None and kit_path is not None
        raw = await asyncio.to_thread(
            run,
            command=["--maintenance-shell", script],
            entrypoint=KIT_ENTRYPOINT,
            runtime_environment={
                **environment,
                **worker_kit_environment(kit_version),
            },
            volumes={**workspace_volume, **worker_kit_mounts(kit_path)},
        )
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", errors="replace")
    try:
        payload = json.loads(raw.strip())
    except (TypeError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"Invalid workspace maintenance response: {raw!r}") from exc
    if not isinstance(payload, dict):
        raise RuntimeError("Workspace maintenance response is not a JSON object")
    return payload


async def inspect_issue_workspace(
    db: AsyncSession,
    settings: Any,
    issue: Issue,
    *,
    get_client: Callable[[DockerConnectionConfig], Awaitable[DockerClientWrapper]] | None = None,
) -> RemoteWorkspaceStatus:
    """Inspect one issue directory through a short-lived container on its daemon."""
    root = configured_workspace_root(settings)
    paths = build_issue_workspace_paths(settings, issue, None)
    if root is None or paths is None:
        raise RuntimeError("worker_workspace_host_path is not configured")
    profile = await _load_issue_worker_profile(db, issue)
    client_factory = get_client or create_docker_client_async
    docker = await client_factory(_profile_connection(profile, settings))
    try:
        payload = await _run_maintenance_container(
            docker=docker,
            profile=profile,
            workspace_root=root,
            environment={
                "PROJECT_ID": str(issue.project_id),
                "ISSUE_ID": str(issue.id),
            },
            script=r"""
set -eu
issue_root="/codify-workspaces/project-${PROJECT_ID}/issue-${ISSUE_ID}"
issue_exists=false
repo_exists=false
[ -d "${issue_root}" ] && issue_exists=true
[ -d "${issue_root}/repo/.git" ] && repo_exists=true
printf '{"issue_exists":%s,"repo_exists":%s}\n' "${issue_exists}" "${repo_exists}"
""".strip(),
            read_only=True,
        )
    finally:
        with contextlib.suppress(Exception):
            await asyncio.to_thread(docker.close)
    return RemoteWorkspaceStatus(
        issue_root=paths.issue_root,
        repo_path=paths.repo_path,
        issue_exists=payload.get("issue_exists") is True,
        repo_exists=payload.get("repo_exists") is True,
    )


async def remove_issue_workspace_remote(
    db: AsyncSession,
    settings: Any,
    issue: Issue,
    *,
    get_client: Callable[[DockerConnectionConfig], Awaitable[DockerClientWrapper]] | None = None,
) -> bool:
    """Remove one exact issue directory from its pinned daemon-local workspace root."""
    root = configured_workspace_root(settings)
    if root is None:
        raise RuntimeError("worker_workspace_host_path is not configured")
    profile = await _load_issue_worker_profile(db, issue)
    client_factory = get_client or create_docker_client_async
    docker = await client_factory(_profile_connection(profile, settings))
    try:
        payload = await _run_maintenance_container(
            docker=docker,
            profile=profile,
            workspace_root=root,
            environment={
                "PROJECT_ID": str(issue.project_id),
                "ISSUE_ID": str(issue.id),
                "WORKER_PROFILE_ID": str(issue.worker_profile_id),
            },
            script=r"""
set -eu
issue_root="/codify-workspaces/project-${PROJECT_ID}/issue-${ISSUE_ID}"
owner_file="${issue_root}/meta/owner"
expected_owner="${PROJECT_ID}:${ISSUE_ID}:${WORKER_PROFILE_ID}"
if [ ! -e "${issue_root}" ]; then
    printf '{"removed":false}\n'
    exit 0
fi
if [ -f "${owner_file}" ] && [ "$(cat "${owner_file}")" != "${expected_owner}" ]; then
    echo "workspace owner marker does not match the pinned issue worker" >&2
    exit 42
fi
rm -rf -- "${issue_root}"
printf '{"removed":true}\n'
""".strip(),
            read_only=False,
        )
    finally:
        with contextlib.suppress(Exception):
            await asyncio.to_thread(docker.close)
    return payload.get("removed") is True
