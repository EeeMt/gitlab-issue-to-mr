"""Runtime and container setup helpers for worker execution."""

import io
import json
import logging
import os
import shutil
import tarfile
import time
from pathlib import Path, PurePosixPath
from types import SimpleNamespace
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
from app.core.model_credentials import CredentialError, resolve_task_credential
from app.core.model_endpoints import (
    ModelEndpoint,
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
    """Resolve the AI provider from the task's frozen endpoint when available.

    A Task's Worker Profile Snapshot is the execution boundary for model
    configuration.  Looking up the editable ``AIProvider`` row here would let
    a later protocol/model/base-url edit change a queued or retrying Task after
    its Bundle had already been selected.  The endpoint fields therefore come
    from the immutable snapshot; only the independently managed credential is
    resolved at execution time.
    """
    snapshot = _loaded_worker_profile_snapshot(task)
    endpoint_snapshot = getattr(snapshot, "model_endpoint_snapshot", None)
    if endpoint_snapshot is not None:
        if not isinstance(endpoint_snapshot, dict):
            raise RuntimeError(f"Task {task.id} has an invalid model endpoint snapshot")
        endpoint = _model_endpoint_from_snapshot(endpoint_snapshot, task)
        return await _resolve_frozen_provider(
            db,
            task,
            snapshot,
            endpoint,
            credential_ref_is_frozen="credential_ref" in endpoint_snapshot,
        )
    # Snapshots written before the endpoint contract was introduced do not
    # carry model_endpoint_snapshot.  Keep their legacy lookup path for
    # compatibility; all current snapshots take the frozen path above.
    return await _resolve_live_provider(db, task)


def _loaded_worker_profile_snapshot(task: Task) -> Any | None:
    """Return a task snapshot only when the relationship is already loaded."""
    task_state = getattr(task, "__dict__", None)
    if not isinstance(task_state, dict):
        return None
    return task_state.get("worker_profile_snapshot")


def _model_endpoint_from_snapshot(
    raw_snapshot: dict[str, Any],
    task: Task,
) -> ModelEndpoint:
    """Validate and materialize the secret-free endpoint snapshot."""
    protocol = raw_snapshot.get("model_protocol")
    if protocol is None:
        protocol = raw_snapshot.get("wire_protocol")
    if not isinstance(protocol, str) or not protocol.strip():
        raise RuntimeError(f"Task {task.id} has an invalid frozen model protocol")
    protocol = protocol.strip().replace("-", "_")

    def required_string(name: str) -> str:
        value = raw_snapshot.get(name)
        if not isinstance(value, str) or not value.strip():
            raise RuntimeError(
                f"Task {task.id} has an invalid frozen model endpoint field: {name}"
            )
        return value.strip()

    endpoint_id = raw_snapshot.get("id")
    if endpoint_id is not None and (
        not isinstance(endpoint_id, int) or isinstance(endpoint_id, bool)
    ):
        raise RuntimeError(f"Task {task.id} has an invalid frozen provider id")

    name = raw_snapshot.get("name", "task snapshot")
    if not isinstance(name, str) or not name.strip():
        raise RuntimeError(f"Task {task.id} has an invalid frozen provider name")
    provider_kind = raw_snapshot.get("provider_kind")
    if provider_kind is None:
        provider_kind = (
            "openai_compatible" if protocol.startswith("openai_") else "anthropic_compatible"
        )
    if not isinstance(provider_kind, str) or not provider_kind.strip():
        raise RuntimeError(f"Task {task.id} has an invalid frozen provider kind")

    compat_profile = raw_snapshot.get("compat_profile")
    if compat_profile is not None and not isinstance(compat_profile, str):
        raise RuntimeError(f"Task {task.id} has an invalid frozen compatibility profile")
    provider_driver = raw_snapshot.get("provider_driver")
    if provider_driver is not None and not isinstance(provider_driver, str):
        raise RuntimeError(f"Task {task.id} has an invalid frozen provider driver")
    provider_options = raw_snapshot.get("provider_options", {})
    if not isinstance(provider_options, dict):
        raise RuntimeError(f"Task {task.id} has invalid frozen provider options")
    credential_ref = raw_snapshot.get("credential_ref")
    if credential_ref is not None and not isinstance(credential_ref, str):
        raise RuntimeError(f"Task {task.id} has an invalid frozen credential reference")
    credential_ref = credential_ref.strip() if isinstance(credential_ref, str) else None
    credential_ref = credential_ref or None

    max_turns = raw_snapshot.get("max_turns")
    if "max_turns" in raw_snapshot and (
        not isinstance(max_turns, int)
        or isinstance(max_turns, bool)
        or not 1 <= max_turns <= 1000
    ):
        raise RuntimeError(f"Task {task.id} has an invalid frozen max_turns")
    system_prompt = raw_snapshot.get("system_prompt")
    if system_prompt is not None and (
        not isinstance(system_prompt, str) or len(system_prompt) > 10000
    ):
        raise RuntimeError(f"Task {task.id} has an invalid frozen system_prompt")

    endpoint = ModelEndpoint(
        id=endpoint_id,
        name=name.strip(),
        base_url=required_string("base_url"),
        model=required_string("model"),
        provider_kind=provider_kind.strip(),
        model_protocol=protocol,
        compat_profile=compat_profile.strip() if isinstance(compat_profile, str) else None,
        provider_driver=provider_driver.strip() if isinstance(provider_driver, str) else None,
        provider_options=dict(provider_options),
        credential_ref=credential_ref,
        max_turns=max_turns,
        system_prompt=system_prompt,
    )
    fingerprint = raw_snapshot.get("fingerprint")
    if fingerprint is not None and (
        not isinstance(fingerprint, str) or fingerprint != endpoint.fingerprint
    ):
        raise RuntimeError(f"Task {task.id} has a tampered frozen model endpoint fingerprint")
    return endpoint


async def _resolve_live_provider(db: AsyncSession, task: Task) -> AIProvider:
    """Keep the legacy lookup path for tasks without an endpoint snapshot."""
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


async def _resolve_frozen_provider(
    db: AsyncSession,
    task: Task,
    snapshot: Any,
    endpoint: ModelEndpoint,
    *,
    credential_ref_is_frozen: bool,
) -> Any:
    """Build a transient provider from frozen endpoint data and live credential."""
    source_provider = None
    source_provider_id = endpoint.id
    if source_provider_id is None:
        candidate_id = getattr(task, "provider_id", None)
        if isinstance(candidate_id, int) and not isinstance(candidate_id, bool):
            source_provider_id = candidate_id
    if source_provider_id is not None:
        source_provider = await db.get(AIProvider, source_provider_id)

    snapshot_credential_ref = _optional_credential_ref(
        getattr(snapshot, "credential_ref", None), task
    )
    if (
        snapshot_credential_ref is not None
        and endpoint.credential_ref is not None
        and snapshot_credential_ref != endpoint.credential_ref
    ):
        raise RuntimeError(f"Task {task.id} has conflicting frozen credential references")
    credential_ref = snapshot_credential_ref or endpoint.credential_ref
    api_key = ""
    if credential_ref is not None:
        api_key = await _resolve_frozen_credential(db, task, credential_ref)
    elif not credential_ref_is_frozen and source_provider is not None:
        # Providers created before the independent credential migration may
        # still have only the legacy key.  Keep that compatibility path only
        # for old endpoint snapshots that did not record a credential_ref key.
        # A current snapshot explicitly recording null means "no credential";
        # a credential added to the mutable Provider later must not be adopted.
        legacy_ref = _optional_credential_ref(
            getattr(source_provider, "credential_ref", None), task
        )
        if legacy_ref is not None:
            api_key = await _resolve_frozen_credential(db, task, legacy_ref)
            credential_ref = legacy_ref
        else:
            api_key = _decrypt_provider_api_key(source_provider)

    settings = get_settings()
    if endpoint.max_turns is not None:
        max_turns = endpoint.max_turns
        system_prompt = endpoint.system_prompt
    else:
        # Snapshots created before max_turns/system_prompt joined the endpoint
        # contract have no frozen policy fields. Preserve their legacy lookup
        # semantics while all newly created endpoint snapshots use the branch
        # above.
        max_turns = getattr(source_provider, "max_turns", None)
        if not isinstance(max_turns, int) or isinstance(max_turns, bool):
            max_turns = getattr(settings, "claude_max_turns", 20)
        system_prompt = getattr(source_provider, "system_prompt", None)
        if system_prompt is not None and not isinstance(system_prompt, str):
            system_prompt = None

    # This object is intentionally transient: it carries the frozen endpoint
    # and resolved secret into environment construction without ever being
    # attached to the SQLAlchemy session.
    return SimpleNamespace(
        id=endpoint.id,
        name=endpoint.name,
        base_url=endpoint.base_url,
        api_key=api_key,
        model=endpoint.model,
        max_turns=max_turns,
        system_prompt=system_prompt,
        provider_kind=endpoint.provider_kind,
        model_protocol=endpoint.model_protocol,
        compat_profile=endpoint.compat_profile,
        provider_driver=endpoint.provider_driver,
        provider_options=dict(endpoint.provider_options),
        credential_ref=credential_ref,
        endpoint_fingerprint=endpoint.fingerprint,
        _codify_api_key_resolved=True,
    )


def _optional_credential_ref(value: Any, task: Task) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str):
        raise RuntimeError(f"Task {task.id} has an invalid credential reference")
    return value.strip() or None


async def _resolve_frozen_credential(
    db: AsyncSession,
    task: Task,
    credential_ref: str,
) -> str:
    try:
        resolved = await resolve_task_credential(db, credential_ref, allow_retired=True)
    except CredentialError as exc:
        raise RuntimeError(
            f"Task {task.id} credential resolution failed; execution is blocked"
        ) from exc
    secret = resolved.get("secret") if isinstance(resolved, dict) else None
    if not isinstance(secret, str):
        raise RuntimeError(f"Task {task.id} resolved credential is invalid")
    return secret


def capture_provider_runtime_snapshot(task: Task, provider: AIProvider) -> None:
    """Capture the non-secret model-service configuration passed to the worker."""
    provider_id = getattr(provider, "id", None)
    model_protocol = getattr(provider, "model_protocol", None)
    if not isinstance(model_protocol, str) or not model_protocol.strip():
        model_protocol = "anthropic_messages"
    task.provider_runtime_snapshot = {
        "provider_id": provider_id if isinstance(provider_id, int) else None,
        "provider_name": provider.name,
        "base_url": provider.base_url,
        "configured_model": provider.model,
        "model_protocol": model_protocol.strip().replace("-", "_"),
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

    model_protocol = getattr(provider, "model_protocol", None) or "anthropic_messages"
    supported_protocols = {
        "anthropic_messages",
        "openai_responses",
        "openai_chat_completions",
    }
    if model_protocol not in supported_protocols:
        raise RuntimeError(f"Unsupported model protocol for worker environment: {model_protocol!r}")

    environment = {
        "GITLAB_URL": settings.gitlab_url,
        "GITLAB_TOKEN": settings.gitlab_bot_token,
        "PROJECT_ID": str(task.project_id),
        "BRANCH_NAME": issue.branch_name,
        "USER_PROMPT": task.user_prompt,
        "TARGET_BRANCH": target_branch or "",
        # Adapters select their provider mapping from this frozen Snapshot
        # value. They must not infer a protocol from whichever credential env
        # happens to be present in a long-lived Worker image.
        "CODIFY_MODEL_PROTOCOL": model_protocol,
        "CLAUDE_MAX_TURNS": max_turns,
        "TASK_ID": str(task.id),
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
    endpoint_fingerprint = getattr(provider, "endpoint_fingerprint", None)
    if isinstance(endpoint_fingerprint, str) and endpoint_fingerprint:
        environment["CODIFY_MODEL_ENDPOINT_FINGERPRINT"] = endpoint_fingerprint

    if model_protocol == "anthropic_messages":
        environment.update(
            {
                "ANTHROPIC_BASE_URL": base_url,
                "ANTHROPIC_API_KEY": api_key,
                "ANTHROPIC_MODEL": model,
                # Claude sub-agents otherwise select public defaults. These
                # variables intentionally exist only on the Anthropic path.
                "ANTHROPIC_DEFAULT_HAIKU_MODEL": model,
                "ANTHROPIC_DEFAULT_SONNET_MODEL": model,
                "ANTHROPIC_DEFAULT_OPUS_MODEL": model,
                "ANTHROPIC_SMALL_FAST_MODEL": model,
                "CLAUDE_CODE_SUBAGENT_MODEL": model,
            }
        )
    else:
        environment.update(
            {
                "OPENAI_BASE_URL": base_url,
                "OPENAI_API_KEY": api_key,
                "OPENAI_MODEL": model,
            }
        )

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
    if provider and getattr(provider, "_codify_api_key_resolved", False):
        api_key = provider.api_key or ""
    elif provider and provider.id:
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
