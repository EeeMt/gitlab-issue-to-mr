"""Runtime and container setup helpers for worker execution."""

import io
import json
import logging
import os
import shutil
import tarfile
import time
from pathlib import Path, PurePosixPath
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.providers import _decrypt_provider_api_key
from app.config import (
    WORKER_ARTIFACTS_DEFAULT_MAX_ENTRIES,
    WORKER_ARTIFACTS_DEFAULT_MAX_FILE_BYTES,
    WORKER_ARTIFACTS_DEFAULT_MAX_TOTAL_BYTES,
)
from app.config import (
    get_effective_settings as get_settings,
)
from app.core.skills import (
    decode_skill_file_content,
    normalize_skill_snapshots,
    render_skill_markdown,
)
from app.core.utcnow import utcnow
from app.core.worker_environment_variables import (
    validate_worker_environment_variable_key as validate_worker_environment_key,
)
from app.core.worker_profiles import build_worker_profile_volume_map
from app.core.worker_workspace import build_issue_workspace_paths
from app.models import AIProvider, Issue, Task, User

logger = logging.getLogger(__name__)

_WORKSPACE_CONTAINER_PATH = "/workspace"
_RUNTIME_CONTAINER_PATH = "/tmp/codify-runtime"
_CLAUDE_CONTAINER_PATH = "/home/codify/.claude"
_SHARED_CONTAINER_PATH = "/opt/codify-issue-shared"
_META_CONTAINER_PATH = "/opt/codify-issue-meta"
_WORKER_PRE_SCRIPT_FILENAME = "worker-pre-script.sh"
_WORKER_POST_SCRIPT_FILENAME = "worker-post-script.sh"
_TASK_PROMPT_FILENAME = "task-prompt.md"
_ARTIFACT_POLICY_FILENAME = "artifact-policy.json"
_TASK_PROMPT_CONTAINER_PATH = f"{_RUNTIME_CONTAINER_PATH}/{_TASK_PROMPT_FILENAME}"
_TASK_SKILLS_ROOT_NAME = "skill-scope"
TASK_SKILLS_CONTAINER_PATH = f"{_RUNTIME_CONTAINER_PATH}/{_TASK_SKILLS_ROOT_NAME}"


def _artifact_policy_int(settings: Any, name: str, default: int) -> int:
    value = getattr(settings, name, default)
    return value if isinstance(value, int) and not isinstance(value, bool) else default


def _legacy_session_storage_path(issue: Issue | None) -> str | None:
    if issue is None:
        return None
    raw_path = getattr(issue, "session_storage_path", None)
    if not isinstance(raw_path, str):
        return None
    path = raw_path.strip()
    return path or None


async def resolve_provider(db: AsyncSession, task: Task) -> AIProvider:
    """Resolve the AI provider for a task."""
    if task.provider_id:
        provider = await db.get(AIProvider, task.provider_id)
        if provider:
            return provider

    result = await db.execute(select(AIProvider).where(AIProvider.is_default == True))
    provider = result.scalar_one_or_none()
    if provider:
        return provider

    settings = get_settings()
    return AIProvider(
        name="legacy",
        base_url=settings.anthropic_base_url,
        api_key=settings.anthropic_api_key,
        model=settings.anthropic_model,
        max_turns=settings.claude_max_turns,
        system_prompt=None,
    )


def capture_provider_runtime_snapshot(task: Task, provider: AIProvider) -> None:
    """Capture the non-secret model-service configuration passed to the worker."""
    provider_id = getattr(provider, "id", None)
    task.provider_runtime_snapshot = {
        "provider_id": provider_id if isinstance(provider_id, int) else None,
        "provider_name": provider.name,
        "base_url": provider.base_url,
        "configured_model": provider.model,
        "max_turns": provider.max_turns,
        "system_prompt": provider.system_prompt,
        "api_key_configured": bool(provider.api_key),
        "captured_at": utcnow().isoformat(),
    }


async def resolve_commit_author(db: AsyncSession, task: Task) -> tuple[str, str]:
    """Resolve commit author identity for worker-generated commits."""
    fallback_name = (task.initiator_username or "Codify User").strip() or "Codify User"
    fallback_email = "codify-task@codify.local"

    display_name = (getattr(task, "initiator_display_name", None) or "").strip()
    email = (getattr(task, "initiator_email", None) or "").strip()
    if display_name or email:
        return display_name or fallback_name, email or fallback_email

    if task.initiator_user_id:
        user = await db.get(User, task.initiator_user_id)
        if user:
            user_name = (getattr(user, "display_name", None) or getattr(user, "username", None) or "").strip()
            user_email = (getattr(user, "email", None) or "").strip()
            if user_name or user_email:
                return user_name or fallback_name, user_email or fallback_email

    return fallback_name, fallback_email


def build_container_env(
    task: Task,
    issue: Issue,
    mr_iid: int | None,
    target_branch: str | None,
    provider: AIProvider = None,
    *,
    author_name: str | None = None,
    author_email: str | None = None,
    custom_environment: dict[str, str] | None = None,
    settings: Any | None = None,
) -> dict[str, str]:
    """Build environment variables for the worker container."""
    return _build_container_env_with_settings(
        settings or get_settings(),
        task,
        issue,
        mr_iid,
        target_branch,
        provider=provider,
        author_name=author_name,
        author_email=author_email,
        custom_environment=custom_environment,
    )


def _build_container_env_with_settings(
    settings: Any,
    task: Task,
    issue: Issue,
    mr_iid: int | None,
    target_branch: str | None,
    provider: AIProvider = None,
    *,
    author_name: str | None = None,
    author_email: str | None = None,
    custom_environment: dict[str, str] | None = None,
) -> dict[str, str]:
    if custom_environment:
        for key in custom_environment:
            validate_worker_environment_key(key)

    api_key, base_url, model, max_turns = _resolve_provider_environment_values(
        settings,
        provider,
    )

    environment = {
        "GITLAB_URL": settings.gitlab_url,
        "GITLAB_TOKEN": settings.gitlab_bot_token,
        "PROJECT_ID": str(task.project_id),
        "BRANCH_NAME": issue.branch_name,
        "USER_PROMPT": task.user_prompt,
        "TARGET_BRANCH": target_branch or "",
        "ANTHROPIC_BASE_URL": base_url,
        "ANTHROPIC_API_KEY": api_key,
        "ANTHROPIC_MODEL": model,
        "CLAUDE_MAX_TURNS": max_turns,
        "TASK_ID": str(task.id),
        **(
            {
                "OPENAI_BASE_URL": base_url,
                "OPENAI_API_KEY": api_key,
                "OPENAI_MODEL": model,
            }
            if (getattr(provider, "wire_protocol", "") or "").startswith("openai")
            else {}
        ),
        "TASK_TIMEOUT": str(settings.task_timeout),
        "ISSUE_ID": str(issue.id),
        "ISSUE_TITLE": issue.title or "",
        "CODIFY_WORKER_PROFILE_ID": str(getattr(task, "worker_profile_id", None) or ""),
        "GIT_AUTHOR_NAME": author_name or (getattr(task, "initiator_display_name", None) or task.initiator_username or "Codify User"),
        "GIT_AUTHOR_EMAIL": author_email or (getattr(task, "initiator_email", None) or "codify-task@codify.local"),
        "CODIFY_COAUTHOR_NAME": "Codify",
        "CODIFY_COAUTHOR_EMAIL": "codify@codify.local",
        "CODIFY_TASK_PROMPT_FILE": _TASK_PROMPT_CONTAINER_PATH,
    }

    if provider and provider.system_prompt:
        environment["APPEND_SYSTEM_PROMPT"] = provider.system_prompt

    task_mode = task.task_mode if task.task_mode else "execute"
    environment["TASK_MODE"] = task_mode
    session_mode = getattr(task, "session_mode", "continue")
    if session_mode == "fresh":
        environment["START_FRESH_SESSION"] = "1"
    elif getattr(task, "input_session_id", None):
        environment["RESUME_SESSION"] = task.input_session_id

    if issue.base_branch:
        environment["BASE_BRANCH"] = issue.base_branch

    git_clone_depth = getattr(issue, "git_clone_depth", None)
    if (
        isinstance(git_clone_depth, int)
        and not isinstance(git_clone_depth, bool)
        and 1 <= git_clone_depth <= 10_000
    ):
        environment["CODIFY_GIT_CLONE_DEPTH"] = str(git_clone_depth)

    git_clone_filter = getattr(issue, "git_clone_filter", None)
    if git_clone_filter == "blob:none":
        environment["CODIFY_GIT_CLONE_FILTER"] = git_clone_filter

    if mr_iid:
        environment["MR_IID"] = str(mr_iid)

    environment["REQUIRE_CHANGES"] = "true" if getattr(task, "require_changes", True) else "false"

    if settings.custom_ca_bundle:
        environment["CUSTOM_CA_BUNDLE"] = settings.custom_ca_bundle

    if custom_environment:
        environment.update(custom_environment)

    return environment


def worker_custom_scripts_configured(settings: Any) -> bool:
    """Return whether runtime settings contain custom worker scripts."""
    return any(
        isinstance(getattr(settings, key, ""), str) and getattr(settings, key, "").strip()
        for key in ("worker_pre_script", "worker_post_script")
    )


def materialize_worker_custom_scripts(settings: Any, runtime_path: str | os.PathLike[str]) -> None:
    """Write configured worker scripts into the task runtime directory."""
    materialize_worker_custom_scripts_from_snapshot(
        runtime_path,
        pre_script=getattr(settings, "worker_pre_script", ""),
        post_script=getattr(settings, "worker_post_script", ""),
    )


def materialize_worker_custom_scripts_from_snapshot(
    runtime_path: str | os.PathLike[str],
    *,
    pre_script: str = "",
    post_script: str = "",
) -> None:
    """Write task snapshot worker scripts into the task runtime directory."""
    runtime_dir = Path(runtime_path)
    runtime_dir.mkdir(parents=True, exist_ok=True)

    script_specs = (
        (pre_script, runtime_dir / _WORKER_PRE_SCRIPT_FILENAME),
        (post_script, runtime_dir / _WORKER_POST_SCRIPT_FILENAME),
    )
    for script_content, script_path in script_specs:
        if not isinstance(script_content, str) or not script_content.strip():
            script_path.unlink(missing_ok=True)
            continue

        script_text = script_content if script_content.endswith("\n") else f"{script_content}\n"
        script_path.write_text(script_text, encoding="utf-8")
        script_path.chmod(0o700)


def materialize_task_prompt(task: Task, runtime_path: str | os.PathLike[str]) -> Path:
    """Write the persisted rendered prompt into the mounted task runtime directory."""
    rendered_prompt = getattr(task, "rendered_prompt", None)
    if not isinstance(rendered_prompt, str) or not rendered_prompt.strip():
        raise RuntimeError(f"Task {task.id} has no persisted rendered prompt")
    if not runtime_path:
        raise RuntimeError(f"Task {task.id} runtime path is unavailable")

    runtime_dir = Path(runtime_path)
    try:
        runtime_dir.mkdir(parents=True, exist_ok=True)
        prompt_path = runtime_dir / _TASK_PROMPT_FILENAME
        prompt_path.write_bytes(rendered_prompt.encode("utf-8"))
    except OSError as exc:
        raise RuntimeError(f"Could not materialize task {task.id} prompt: {exc}") from exc
    logger.info(
        "[Task %s] Materialized persisted prompt at %s (%s characters)",
        task.id,
        prompt_path,
        len(rendered_prompt),
    )
    return prompt_path


def build_task_runtime_archive(
    task: Task,
    *,
    pre_script: str = "",
    post_script: str = "",
    previous_task_summaries: str = "",
    ci_failure_bundle_path: str | os.PathLike[str] | None = None,
    artifact_policy_settings: Any | None = None,
    skills: list[dict[str, Any]] | None = None,
) -> bytes:
    """Build the immutable runtime input bundle uploaded through the Docker API."""
    rendered_prompt = getattr(task, "rendered_prompt", None)
    if not isinstance(rendered_prompt, str) or not rendered_prompt.strip():
        raise RuntimeError(f"Task {task.id} has no persisted rendered prompt")

    buffer = io.BytesIO()
    now = int(time.time())

    def add_bytes(
        archive: tarfile.TarFile,
        name: str,
        content: str | bytes,
        mode: int,
    ) -> None:
        payload = content.encode("utf-8") if isinstance(content, str) else content
        info = tarfile.TarInfo(name=f"codify-runtime/{name}")
        info.size = len(payload)
        info.mode = mode
        info.mtime = now
        archive.addfile(info, io.BytesIO(payload))

    added_directories: set[str] = set()

    def add_directory(archive: tarfile.TarFile, name: str) -> None:
        if name in added_directories:
            return
        added_directories.add(name)
        info = tarfile.TarInfo(name=f"codify-runtime/{name}")
        info.type = tarfile.DIRTYPE
        info.mode = 0o755
        info.mtime = now
        archive.addfile(info)

    with tarfile.open(fileobj=buffer, mode="w") as archive:
        runtime_dir = tarfile.TarInfo(name="codify-runtime")
        runtime_dir.type = tarfile.DIRTYPE
        runtime_dir.mode = 0o755
        runtime_dir.mtime = now
        archive.addfile(runtime_dir)
        add_bytes(archive, _TASK_PROMPT_FILENAME, rendered_prompt, 0o600)
        settings = artifact_policy_settings or get_settings()
        artifact_policy = json.dumps(
            {
                "schema_version": 1,
                "max_total_bytes": _artifact_policy_int(
                    settings,
                    "worker_artifacts_max_total_bytes",
                    WORKER_ARTIFACTS_DEFAULT_MAX_TOTAL_BYTES,
                ),
                "max_file_bytes": _artifact_policy_int(
                    settings,
                    "worker_artifacts_max_file_bytes",
                    WORKER_ARTIFACTS_DEFAULT_MAX_FILE_BYTES,
                ),
                "max_entries": _artifact_policy_int(
                    settings,
                    "worker_artifacts_max_entries",
                    WORKER_ARTIFACTS_DEFAULT_MAX_ENTRIES,
                ),
            },
            separators=(",", ":"),
            sort_keys=True,
        )
        add_bytes(archive, _ARTIFACT_POLICY_FILENAME, artifact_policy, 0o600)
        if isinstance(pre_script, str) and pre_script.strip():
            add_bytes(
                archive,
                _WORKER_PRE_SCRIPT_FILENAME,
                pre_script if pre_script.endswith("\n") else f"{pre_script}\n",
                0o700,
            )
        if isinstance(post_script, str) and post_script.strip():
            add_bytes(
                archive,
                _WORKER_POST_SCRIPT_FILENAME,
                post_script if post_script.endswith("\n") else f"{post_script}\n",
                0o700,
            )
        if previous_task_summaries:
            add_bytes(
                archive,
                "previous-task-summaries.md",
                previous_task_summaries,
                0o600,
            )

        skill_snapshots = normalize_skill_snapshots(skills or [])
        if skill_snapshots:
            add_directory(archive, _TASK_SKILLS_ROOT_NAME)
            add_directory(archive, f"{_TASK_SKILLS_ROOT_NAME}/.claude")
            add_directory(archive, f"{_TASK_SKILLS_ROOT_NAME}/.claude/skills")
            for skill in skill_snapshots:
                skill_path = f"{_TASK_SKILLS_ROOT_NAME}/.claude/skills/{skill['name']}"
                add_directory(archive, skill_path)
                add_bytes(
                    archive,
                    f"{skill_path}/SKILL.md",
                    render_skill_markdown(skill),
                    0o644,
                )
                for package_file in skill["files"]:
                    relative_path = PurePosixPath(package_file["path"])
                    parents = list(relative_path.parents)[:-1]
                    for parent in reversed(parents):
                        add_directory(archive, f"{skill_path}/{parent.as_posix()}")
                    add_bytes(
                        archive,
                        f"{skill_path}/{relative_path.as_posix()}",
                        decode_skill_file_content(package_file),
                        0o755 if package_file["executable"] else 0o644,
                    )

        if ci_failure_bundle_path:
            bundle_path = Path(ci_failure_bundle_path)
            if not bundle_path.is_dir():
                raise RuntimeError("CI failure bundle is not available for this repair task")
            for source in sorted(bundle_path.rglob("*")):
                if source.is_symlink():
                    raise RuntimeError(f"CI failure bundle contains a symlink: {source}")
                relative = source.relative_to(bundle_path)
                archive.add(
                    source,
                    arcname=str(Path("codify-runtime") / "ci-failure" / relative),
                    recursive=False,
                )

    return buffer.getvalue()


def _resolve_provider_environment_values(
    settings: Any,
    provider: AIProvider | None,
) -> tuple[str, str, str, str]:
    if provider and provider.id:
        api_key = _decrypt_provider_api_key(provider)
    elif provider:
        api_key = provider.api_key or ""
    else:
        api_key = settings.anthropic_api_key

    base_url = provider.base_url if provider else settings.anthropic_base_url
    model = provider.model if provider else settings.anthropic_model
    max_turns = str(provider.max_turns) if provider else str(settings.claude_max_turns)
    return api_key, base_url, model, max_turns


def build_container_volumes(
    settings: Any,
    issue: Issue | None = None,
    *,
    task: Task | None = None,
    custom_mounts: list[dict] | None = None,
) -> dict:
    """Build volume mounts for the worker container.

    Mount order matters: parent directories must be mounted before child directories so that
    user-specified mounts (added last) can override workspace subdirectories.
    Order: workspace mounts → user-defined worker_volume_mounts.
    """
    volumes: dict = {}

    # --- Workspace mounts (first) ---
    workspace_paths = (
        build_issue_workspace_paths(settings, issue, task)
        if issue is not None and task is not None
        else None
    )
    if workspace_paths is not None:
        logger.info(
            f"[Task {task.id}] Mounting workspace — "
            f"repo: {workspace_paths.repo_path} → {_WORKSPACE_CONTAINER_PATH}, "
            f"shared: {workspace_paths.shared_path} → {_SHARED_CONTAINER_PATH}"
        )
        volumes[workspace_paths.repo_path] = {"bind": _WORKSPACE_CONTAINER_PATH, "mode": "rw"}
        volumes[workspace_paths.claude_path] = {"bind": _CLAUDE_CONTAINER_PATH, "mode": "rw"}
        volumes[workspace_paths.shared_path] = {"bind": _SHARED_CONTAINER_PATH, "mode": "rw"}
        volumes[workspace_paths.meta_path] = {"bind": _META_CONTAINER_PATH, "mode": "rw"}
    elif session_storage_path := _legacy_session_storage_path(issue):
        os.makedirs(session_storage_path, exist_ok=True)
        volumes[session_storage_path] = {
            "bind": _CLAUDE_CONTAINER_PATH,
            "mode": "rw",
        }
    else:
        logger.info(
            f"[Task {getattr(task, 'id', '?')}] No persistent workspace configured "
            f"(worker_workspace_host_path={getattr(settings, 'worker_workspace_host_path', None)!r}); "
            f"runtime data will be lost when container exits"
        )

    # --- User-defined mounts (last) — may override subdirectories of any system mount above ---
    mounts = custom_mounts if custom_mounts is not None else settings.worker_volume_mounts_parsed
    volumes.update(build_worker_profile_volume_map(mounts))

    return volumes if volumes else {}


def materialize_ci_failure_bundle(task: Task, runtime_path: str | os.PathLike[str]) -> None:
    """Copy a prepared CI failure bundle into one task's runtime directory."""
    if (
        getattr(task, "trigger_source", "manual") != "ci_auto_repair"
        and getattr(task, "ci_failure_run_id", None) is None
    ):
        return

    run = getattr(task, "ci_failure_run", None)
    bundle_path = getattr(run, "bundle_path", None) if run is not None else None
    if not bundle_path or not os.path.isdir(bundle_path):
        raise RuntimeError("CI failure bundle is not available for this repair task")

    dest = Path(runtime_path) / "ci-failure"
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(bundle_path, dest)


def get_container_name(task: Task) -> str:
    """Generate container name with naming convention."""
    prefix = get_settings().worker_container_prefix
    return f"{prefix}-{task.id}-issue{task.issue_id}"
