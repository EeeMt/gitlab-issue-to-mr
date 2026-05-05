"""Runtime and container setup helpers for worker execution."""

import os
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.providers import _decrypt_provider_api_key
from app.config import get_effective_settings as get_settings
from app.core.worker_environment_variables import validate_worker_environment_variable_key as validate_worker_environment_key
from app.core.worker_workspace import build_issue_workspace_paths
from app.models import AIProvider, Issue, Task, User

_MAVEN_CACHE_CONTAINER_PATH = "/home/codify/.m2/repository"
_MAVEN_SETTINGS_CONTAINER_PATH = "/home/codify/.m2/settings.xml"
_WORKSPACE_CONTAINER_PATH = "/workspace"
_RUNTIME_CONTAINER_PATH = "/tmp/codify-runtime"


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
    mr_iid: Optional[int],
    target_branch: Optional[str],
    provider: AIProvider = None,
    *,
    author_name: Optional[str] = None,
    author_email: Optional[str] = None,
    custom_environment: Optional[dict[str, str]] = None,
) -> dict[str, str]:
    """Build environment variables for the worker container."""
    settings = get_settings()

    if provider and provider.id:
        api_key = _decrypt_provider_api_key(provider)
    elif provider:
        api_key = provider.api_key or ""
    else:
        api_key = settings.anthropic_api_key

    base_url = provider.base_url if provider else settings.anthropic_base_url
    model = provider.model if provider else settings.anthropic_model
    max_turns = str(provider.max_turns) if provider else str(settings.claude_max_turns)

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
    }

    if provider and provider.system_prompt:
        environment["APPEND_SYSTEM_PROMPT"] = provider.system_prompt

    if issue.claude_session_id:
        environment["RESUME_SESSION"] = issue.claude_session_id

    if issue.base_branch:
        environment["BASE_BRANCH"] = issue.base_branch

    if mr_iid:
        environment["MR_IID"] = str(mr_iid)

    if settings.custom_ca_bundle:
        environment["CUSTOM_CA_BUNDLE"] = settings.custom_ca_bundle

    if custom_environment:
        for key, value in custom_environment.items():
            validate_worker_environment_key(key)
            environment[key] = value

    return environment


def build_legacy_container_env(
    settings: Any,
    task: Task,
    issue: Issue,
    mr_iid: Optional[int],
    target_branch: Optional[str],
    provider: AIProvider = None,
    *,
    author_name: Optional[str] = None,
    author_email: Optional[str] = None,
    custom_environment: Optional[dict[str, str]] = None,
) -> dict[str, str]:
    """Build the legacy worker environment while preserving validation order."""
    api_key = provider.api_key if provider else settings.anthropic_api_key
    base_url = provider.base_url if provider else settings.anthropic_base_url
    model = provider.model if provider else settings.anthropic_model
    max_turns = str(provider.max_turns) if provider else str(settings.claude_max_turns)

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
    }

    if provider and getattr(provider, "system_prompt", None):
        environment["APPEND_SYSTEM_PROMPT"] = provider.system_prompt
    if issue.claude_session_id:
        environment["RESUME_SESSION"] = issue.claude_session_id
    if issue.base_branch:
        environment["BASE_BRANCH"] = issue.base_branch
    if mr_iid:
        environment["MR_IID"] = str(mr_iid)
    if settings.custom_ca_bundle:
        environment["CUSTOM_CA_BUNDLE"] = settings.custom_ca_bundle
    if custom_environment:
        for key, value in custom_environment.items():
            validate_worker_environment_key(key)
            environment[key] = value

    return environment


def build_container_volumes(
    settings: Any,
    issue: Optional[Issue] = None,
    *,
    task: Optional[Task] = None,
) -> dict:
    """Build volume mounts for the worker container."""
    volumes: dict = {}

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

    for mount in settings.worker_volume_mounts_parsed:
        host_path = mount.get("host_path")
        container_path = mount.get("container_path")
        mode = mount.get("mode", "ro")
        if host_path and container_path:
            volumes[host_path] = {"bind": container_path, "mode": mode}

    workspace_paths = (
        build_issue_workspace_paths(settings, issue, task)
        if issue is not None and task is not None
        else None
    )
    if workspace_paths is not None:
        try:
            os.makedirs(workspace_paths.repo_path, exist_ok=True)
            os.makedirs(workspace_paths.runtime_path, exist_ok=True)
        except OSError:
            pass
        volumes[workspace_paths.repo_path] = {"bind": _WORKSPACE_CONTAINER_PATH, "mode": "rw"}
        volumes[workspace_paths.runtime_path] = {"bind": _RUNTIME_CONTAINER_PATH, "mode": "rw"}

    if issue and issue.session_storage_path:
        os.makedirs(issue.session_storage_path, exist_ok=True)
        volumes[issue.session_storage_path] = {
            "bind": "/home/codify/.claude",
            "mode": "rw",
        }

    return volumes if volumes else {}


def get_container_name(task: Task) -> str:
    """Generate container name with naming convention."""
    prefix = get_settings().worker_container_prefix
    return f"{prefix}-{task.id}-issue{task.issue_id}"
