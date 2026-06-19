"""Runtime and container setup helpers for worker execution."""

import logging
import os
import shutil
from pathlib import Path
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.providers import _decrypt_provider_api_key
from app.config import get_effective_settings as get_settings
from app.core.worker_environment_variables import (
    validate_worker_environment_variable_key as validate_worker_environment_key,
)
from app.core.worker_workspace import build_issue_workspace_paths
from app.models import AIProvider, Issue, Task, User

logger = logging.getLogger(__name__)

_MAVEN_CACHE_CONTAINER_PATH = "/home/codify/.m2/repository"
_MAVEN_SETTINGS_CONTAINER_PATH = "/home/codify/.m2/settings.xml"
_WORKSPACE_CONTAINER_PATH = "/workspace"
_RUNTIME_CONTAINER_PATH = "/tmp/codify-runtime"
_CLAUDE_CONTAINER_PATH = "/home/codify/.claude"
_SHARED_CONTAINER_PATH = "/opt/codify-issue-shared"
_WORKER_PRE_SCRIPT_FILENAME = "worker-pre-script.sh"
_WORKER_POST_SCRIPT_FILENAME = "worker-post-script.sh"
_TASK_PROMPT_FILENAME = "task-prompt.md"
_TASK_PROMPT_CONTAINER_PATH = f"{_RUNTIME_CONTAINER_PATH}/{_TASK_PROMPT_FILENAME}"


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
        "TASK_TIMEOUT": str(settings.task_timeout),
        "ISSUE_ID": str(issue.id),
        "ISSUE_TITLE": issue.title or "",
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
    if issue.claude_session_id:
        environment["RESUME_SESSION"] = issue.claude_session_id

    if issue.base_branch:
        environment["BASE_BRANCH"] = issue.base_branch

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
    runtime_dir = Path(runtime_path)
    runtime_dir.mkdir(parents=True, exist_ok=True)

    script_specs = (
        ("worker_pre_script", runtime_dir / _WORKER_PRE_SCRIPT_FILENAME),
        ("worker_post_script", runtime_dir / _WORKER_POST_SCRIPT_FILENAME),
    )
    for setting_key, script_path in script_specs:
        script_content = getattr(settings, setting_key, "")
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
) -> dict:
    """Build volume mounts for the worker container.

    Mount order matters: parent directories must be mounted before child directories so that
    user-specified mounts (added last) can override any subdirectory of a system mount.
    Order: system fixed mounts → workspace mounts → user-defined worker_volume_mounts.
    """
    volumes: dict = {}

    # --- System fixed mounts (first) ---
    if settings.maven_cache_host_path:
        volumes[settings.maven_cache_host_path] = {
            "bind": _MAVEN_CACHE_CONTAINER_PATH,
            "mode": "rw",
        }
    if settings.maven_settings_host_path:
        volumes[settings.maven_settings_host_path] = {
            "bind": _MAVEN_SETTINGS_CONTAINER_PATH,
            "mode": "ro",
        }

    # --- Workspace mounts (second) ---
    workspace_paths = (
        build_issue_workspace_paths(settings, issue, task)
        if issue is not None and task is not None
        else None
    )
    if workspace_paths is not None:
        logger.info(
            f"[Task {task.id}] Mounting workspace — "
            f"repo: {workspace_paths.repo_path} → {_WORKSPACE_CONTAINER_PATH}, "
            f"runtime: {workspace_paths.runtime_path} → {_RUNTIME_CONTAINER_PATH}"
        )
        for path in (
            workspace_paths.repo_path,
            workspace_paths.claude_path,
            workspace_paths.runtime_path,
            workspace_paths.shared_path,
        ):
            try:
                os.makedirs(path, exist_ok=True)
            except OSError as exc:
                logger.warning(f"[Task {task.id}] Could not create workspace dir {path}: {exc}")
        volumes[workspace_paths.repo_path] = {"bind": _WORKSPACE_CONTAINER_PATH, "mode": "rw"}
        volumes[workspace_paths.claude_path] = {"bind": _CLAUDE_CONTAINER_PATH, "mode": "rw"}
        volumes[workspace_paths.runtime_path] = {"bind": _RUNTIME_CONTAINER_PATH, "mode": "rw"}
        volumes[workspace_paths.shared_path] = {"bind": _SHARED_CONTAINER_PATH, "mode": "rw"}
    elif issue and issue.session_storage_path:
        os.makedirs(issue.session_storage_path, exist_ok=True)
        volumes[issue.session_storage_path] = {
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
    for mount in settings.worker_volume_mounts_parsed:
        host_path = mount.get("host_path")
        container_path = mount.get("container_path")
        mode = mount.get("mode", "ro")
        if host_path and container_path:
            volumes[host_path] = {"bind": container_path, "mode": mode}

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
