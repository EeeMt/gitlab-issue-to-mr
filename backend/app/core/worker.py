"""Worker executor for running tasks in Docker containers."""

import logging
import re
from typing import Any

import httpx
from gitlab import Gitlab
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import get_effective_settings as get_settings
from app.core.docker_client import DockerClientWrapper, get_docker_client
from app.core.gitlab_client import GitLabClient, get_gitlab_client
from app.core.mattermost_notifications import (
    MATTERMOST_EVENT_TASK_CANCELLED,
    MATTERMOST_EVENT_TASK_COMPLETED,
    MATTERMOST_EVENT_TASK_FAILED,
    MATTERMOST_EVENT_TASK_RETRY_SCHEDULED,
    notify_task_event,
)
from app.core.ssl_utils import get_ssl_verify
from app.core.usage_limits import upsert_task_usage_ledger
from app.core.worker_event_projector import WorkerEventProjector
from app.core.worker_gitlab import (
    build_initial_mr_description,
    build_initial_mr_title,
    build_previous_task_summaries,
    create_mr_if_needed,
    create_new_mr,
    find_existing_mr,
    remove_mr_draft_status_for_issue,
    update_mr_description_for_issue,
)
from app.core.worker_log_stream import WorkerLogStreamer
from app.core.worker_profiles import TaskWorkerRuntime
from app.core.worker_results import (
    finalize_archive,
    parse_mr_from_logs,
    parse_task_result,
    update_task_stats_from_logs_or_api,
)
from app.core.worker_runtime import (
    build_container_env,
    build_container_volumes,
    capture_provider_runtime_snapshot,
    get_container_name,
    materialize_ci_failure_bundle,
    resolve_commit_author,
    resolve_provider,
)
from app.core.worker_task_lifecycle import monitor_container_run
from app.core.worker_task_outcomes import (
    fail_execute_task,
    fail_resume_missing_container,
    fail_resume_task,
)
from app.core.worker_task_outcomes import (
    send_failure_alert as lifecycle_send_failure_alert,
)
from app.core.worker_task_outcomes import (
    send_failure_notifications as lifecycle_send_failure_notifications,
)
from app.core.worker_task_outcomes import (
    send_success_notifications as lifecycle_send_success_notifications,
)
from app.core.worker_task_runner import (
    process_pending_tasks as run_pending_tasks,
)
from app.core.worker_task_runner import (
    run_execute_task,
    run_resume_task,
)
from app.models import Issue, Task

logger = logging.getLogger(__name__)

_ANSI_ESCAPE = re.compile(
    r"\x1b\[[0-9;]*[mABCDEFGHJKLMPSTfnsu]"
    r"|\x1b\][^\x07]*\x07"
    r"|\x1b[()][A-Z0-9]"
    r"|\x1b[@-_]",
    re.DOTALL,
)


async def prepare_container_inputs(
    worker,
    db: AsyncSession,
    task: Task,
    issue: Issue | None,
    mr_iid: int | None,
    *,
    custom_environment: dict[str, str] | None = None,
):
    target_branch = issue.target_branch if issue else None
    provider = await worker._resolve_provider(db, task)
    capture_provider_runtime_snapshot(task, provider)
    author_name, author_email = await worker._resolve_commit_author(db, task)
    environment = worker._build_container_env(
        task,
        issue,
        mr_iid,
        target_branch,
        provider=provider,
        author_name=author_name,
        author_email=author_email,
        custom_environment=custom_environment,
    )
    return environment, target_branch


def scrub_sensitive_data(text: str) -> str:
    """Redact credentials (tokens, API keys) from text, preserving ANSI codes and Unicode."""
    if not text:
        return text

    # GitLab
    text = re.sub(r"glpat-[a-zA-Z0-9\-]{10,}", "[GITLAB_TOKEN]", text)
    # Anthropic (sk-ant-* / sk-cp-* / sk-api-*)
    text = re.sub(r"sk-(?:cp|ant|api)-[a-zA-Z0-9\-]{10,}", "[ANTHROPIC_API_KEY]", text)
    # OpenRouter (sk-or-v1-* keys contain hyphens and do not match the generic
    # OpenAI pattern below).
    text = re.sub(r"sk-or-v1-[a-zA-Z0-9_-]{10,}", "[OPENROUTER_API_KEY]", text)
    # OpenAI (sk-proj-* and generic sk-* with a long enough body to avoid prose)
    text = re.sub(r"sk-proj-[a-zA-Z0-9_\-]{20,}", "[OPENAI_API_KEY]", text)
    text = re.sub(r"sk-[a-zA-Z0-9]{24,}", "[OPENAI_API_KEY]", text)
    # Authorization headers / Bearer tokens
    text = re.sub(
        r"(?i)(authorization\s*:\s*bearer\s+|bearer\s+)[a-zA-Z0-9\-._~+/]+=*",
        r"\1[REDACTED]",
        text,
    )
    # Common provider token prefixes (Google, GitHub, HuggingFace, Slack)
    text = re.sub(r"AIza[0-9A-Za-z\-_]{20,}", "[GOOGLE_API_KEY]", text)
    text = re.sub(r"ghp_[A-Za-z0-9]{20,}", "[GITHUB_TOKEN]", text)
    text = re.sub(r"hf_[A-Za-z0-9]{20,}", "[HUGGINGFACE_TOKEN]", text)
    text = re.sub(r"xox[baprs]-[A-Za-z0-9\-]{10,}", "[SLACK_TOKEN]", text)
    # Config-file secret shapes (api_key / env_key / apiKey = "value")
    text = re.sub(
        r"(?i)(\b(?:api_key|env_key|apikey|api-key|apiKey|api_token)\s*[=:]\s*)[\"']?"
        r"[^\"'\s,;}{]+",
        r"\1[REDACTED]",
        text,
    )
    text = re.sub(r"(PRIVATE-TOKEN:\s*)[^\s]+", r"\1[REDACTED]", text)
    text = text.replace("\x00", "")
    return text


def sanitize_sensitive_data(text: str) -> str:
    """Redact credentials and strip ANSI codes from text."""
    if not text:
        return text

    text = scrub_sensitive_data(text)
    text = _ANSI_ESCAPE.sub("", text)
    text = re.sub(r"[\ud800-\udfff\ufffe\uffff]", "", text)
    return text


class WorkerExecutor:
    """Worker executor that runs tasks in Docker containers."""

    def __init__(
        self,
        docker_client: DockerClientWrapper | None = None,
        gitlab_client: GitLabClient | None = None,
        session_factory: async_sessionmaker[AsyncSession] | None = None,
    ):
        self._docker_client_override = docker_client is not None
        self.docker = docker_client
        self.gitlab = gitlab_client or get_gitlab_client()
        self._session_factory = session_factory
        self._event_projector = WorkerEventProjector(sanitize_sensitive_data)
        self._scrub_sensitive_data = scrub_sensitive_data
        self._sanitize_sensitive_data = sanitize_sensitive_data
        self._httpx_async_client = httpx.AsyncClient
        self._get_ssl_verify = get_ssl_verify
        self._reset_stdout_helpers()

    def _configure_docker_for_runtime(
        self,
        runtime: TaskWorkerRuntime,
        settings: Any,
    ) -> DockerClientWrapper:
        """Route this per-task executor to the daemon captured in its snapshot."""
        if not self._docker_client_override:
            self.docker = get_docker_client(runtime.docker_connection(settings))
        if self.docker is None:
            raise RuntimeError("Docker client was not configured for task runtime")
        return self.docker

    def _reset_stdout_helpers(self) -> None:
        self._log_streamer = WorkerLogStreamer()

    def _reset_event_archive_state(self) -> None:
        self._event_projector.reset()

    async def _load_resume_runtime_state(self, *, container: Any) -> None:
        await self._event_projector.load_resume_runtime_state(container=container)

    async def _ingest_event_records_from_chunk(
        self,
        *,
        task_id: int,
        chunk: str,
        cursor: Any,
        db: AsyncSession,
    ) -> None:
        await self._event_projector.ingest_event_records_from_chunk(
            task_id=task_id,
            chunk=chunk,
            cursor=cursor,
            db=db,
        )

    async def _ingest_event_record(
        self,
        *,
        task_id: int,
        record: dict,
        db: AsyncSession,
    ) -> None:
        await self._event_projector.ingest_event_record(
            task_id=task_id,
            record=record,
            db=db,
        )

    async def _tail_event_jsonl(
        self,
        *,
        task_id: int,
        container: Any,
        db: AsyncSession,
    ) -> None:
        await self._event_projector.tail_event_jsonl(
            task_id=task_id,
            container=container,
            db=db,
        )

    async def _tail_console_log(
        self,
        *,
        task_id: int,
        container: Any,
        db: AsyncSession,
    ) -> None:
        await self._event_projector.tail_console_log(
            task_id=task_id,
            container=container,
            db=db,
        )

    async def _backfill_console_log_from_archive(
        self,
        *,
        task_id: int,
        db: AsyncSession,
    ) -> None:
        await self._event_projector.backfill_console_log_from_archive(
            task_id=task_id,
            db=db,
        )

    async def _backfill_event_jsonl_from_archive(
        self,
        *,
        task_id: int,
        db: AsyncSession,
    ) -> None:
        await self._event_projector.backfill_event_jsonl_from_archive(
            task_id=task_id,
            db=db,
        )

    def _build_initial_mr_title(self, task: Task) -> str:
        return build_initial_mr_title(task)

    def _build_initial_mr_description(self, task: Task) -> str:
        return build_initial_mr_description(task)

    def _remove_mr_draft_status(self, task: Task) -> None:
        """Compatibility no-op retained for callers using the legacy hook."""

    def _remove_mr_draft_status_for_issue(
        self,
        task: Task,
        issue: Issue,
        sudo_gl: Gitlab | None = None,
    ) -> None:
        remove_mr_draft_status_for_issue(
            task,
            issue,
            self.gitlab,
            sudo_gl=sudo_gl,
        )

    def _create_mr_if_needed(
        self,
        task: Task,
        issue: Issue,
        mr_iid: int | None,
        mr_web_url: str | None,
        sudo_gl: Gitlab | None = None,
    ) -> tuple[int | None, str | None]:
        return create_mr_if_needed(
            task,
            issue,
            mr_iid,
            mr_web_url,
            self.gitlab,
            sudo_gl=sudo_gl,
        )

    def _find_existing_mr(
        self,
        task: Task,
        issue: Issue,
    ) -> tuple[int | None, str | None] | None:
        return find_existing_mr(task, issue, self.gitlab)

    def _create_new_mr(
        self,
        task: Task,
        issue: Issue,
        sudo_gl: Gitlab | None = None,
    ) -> tuple[int | None, str | None]:
        return create_new_mr(task, issue, self.gitlab, sudo_gl=sudo_gl)

    def _build_container_volumes(self, *args, **kwargs) -> dict:
        return build_container_volumes(*args, **kwargs)

    def _materialize_ci_failure_bundle(self, *args, **kwargs) -> None:
        materialize_ci_failure_bundle(*args, **kwargs)

    def _get_container_name(self, task: Task) -> str:
        return get_container_name(task)

    async def _resolve_provider(self, db: AsyncSession, task: Task):
        return await resolve_provider(db, task)

    async def _resolve_commit_author(
        self,
        db: AsyncSession,
        task: Task,
    ) -> tuple[str, str]:
        return await resolve_commit_author(db, task)

    async def _parse_mr_from_logs(self, task: Task, logs: str) -> None:
        await parse_mr_from_logs(task, logs, self.gitlab)

    async def _update_task_stats_from_logs_or_api(
        self,
        task: Task,
        logs: str,
        issue: Issue | None = None,
        structured_diff: dict[str, Any] | None = None,
    ) -> None:
        await update_task_stats_from_logs_or_api(
            task,
            logs,
            self.gitlab,
            issue,
            structured_diff,
        )

    async def _update_mr_description_for_issue(
        self,
        task: Task,
        issue: Issue,
        db: AsyncSession,
        *,
        sudo_gl: Gitlab | None = None,
    ) -> None:
        await update_mr_description_for_issue(
            task,
            issue,
            db,
            self.gitlab,
            sudo_gl=sudo_gl,
        )

    async def _build_previous_task_summaries(
        self,
        db: AsyncSession,
        issue: Issue,
        task: Task,
    ) -> str:
        return await build_previous_task_summaries(db, issue, task)

    @property
    def _run_is_resumed(self):
        return self._event_projector._run_is_resumed

    @_run_is_resumed.setter
    def _run_is_resumed(self, value):
        self._event_projector._run_is_resumed = value

    @property
    def _timeline_gate_open(self):
        return self._event_projector._timeline_gate_open

    @_timeline_gate_open.setter
    def _timeline_gate_open(self, value):
        self._event_projector._timeline_gate_open = value

    def _build_container_env(
        self,
        task: Task,
        issue: Issue,
        mr_iid: int | None,
        target_branch: str | None,
        provider=None,
        *,
        author_name: str | None = None,
        author_email: str | None = None,
        custom_environment: dict[str, str] | None = None,
    ) -> dict[str, str]:
        settings = get_settings()
        return build_container_env(
            task,
            issue,
            mr_iid,
            target_branch,
            provider=provider,
            author_name=author_name,
            author_email=author_email,
            custom_environment=custom_environment,
            settings=settings,
        )

    async def _prepare_container_inputs(
        self,
        db: AsyncSession,
        task: Task,
        issue: Issue | None,
        mr_iid: int | None,
        *,
        custom_environment: dict[str, str] | None = None,
    ):
        return await prepare_container_inputs(
            self,
            db,
            task,
            issue,
            mr_iid,
            custom_environment=custom_environment,
        )

    async def _parse_task_result(
        self,
        task: Task,
        logs: str,
        db: AsyncSession,
        exit_code: int,
        issue: Issue | None = None,
    ) -> None:
        await parse_task_result(
            task, logs, db, exit_code, sanitize_sensitive_data, self.gitlab, issue
        )

    async def _send_notifications(
        self,
        task: Task,
        success: bool,
        had_existing_mr: bool,
        logs: str,
        issue: Issue | None = None,
    ) -> None:
        await lifecycle_send_success_notifications(
            self,
            task,
            had_existing_mr=had_existing_mr,
            issue=issue,
            notify_task_event_fn=notify_task_event,
            completion_event=MATTERMOST_EVENT_TASK_COMPLETED,
            session_factory=self._session_factory,
        )

    async def _send_failure_notifications(
        self,
        task: Task,
        success: bool,
        had_existing_mr: bool,
        issue: Issue | None = None,
    ) -> None:
        await lifecycle_send_failure_notifications(
            self,
            task,
            had_existing_mr=had_existing_mr,
            issue=issue,
            notify_task_event_fn=notify_task_event,
            retry_scheduled_event=MATTERMOST_EVENT_TASK_RETRY_SCHEDULED,
            failed_event=MATTERMOST_EVENT_TASK_FAILED,
            session_factory=self._session_factory,
        )

    async def _send_cancelled_notifications(self, task: Task) -> None:
        try:
            await notify_task_event(
                task,
                MATTERMOST_EVENT_TASK_CANCELLED,
                session_factory=self._session_factory,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"Failed to send Mattermost cancellation notification: {exc}")

    async def _try_upsert_usage_ledger(self, db: AsyncSession, task: Task) -> None:
        try:
            await upsert_task_usage_ledger(db, task)
        except Exception as ledger_error:
            logger.warning(f"[Task {task.id}] Failed to upsert usage ledger: {ledger_error}")

    async def _send_failure_alert(self, task: Task, issue: Issue | None = None) -> None:
        await lifecycle_send_failure_alert(
            self,
            task,
            issue,
            get_settings_fn=get_settings,
            get_ssl_verify_fn=get_ssl_verify,
            httpx_async_client_cls=httpx.AsyncClient,
        )

    async def _finalize_archive(self, *, task_id: int, container: Any, db: AsyncSession) -> None:
        await finalize_archive(task_id=task_id, container=container, db=db)

    async def _stream_logs_to_db(
        self,
        container: Any,
        task_id: int,
        db: AsyncSession,
        timeout: int,
    ) -> tuple[int, str, int, bool]:
        return await self._log_streamer.stream_logs_to_db(container, task_id, db, timeout)

    async def _monitor_container_run(
        self,
        *,
        db: AsyncSession,
        task: Task,
        issue: Issue | None,
        container: Any,
        settings: Any,
        had_existing_mr: bool,
        sudo_gl: Gitlab | None,
        resume_prefix: str = "",
    ) -> bool:
        return await monitor_container_run(
            self,
            db=db,
            task=task,
            issue=issue,
            container=container,
            settings=settings,
            had_existing_mr=had_existing_mr,
            sudo_gl=sudo_gl,
            resume_prefix=resume_prefix,
        )

    async def _handle_execute_task_failure(
        self,
        db: AsyncSession,
        task: Task,
        error: Exception,
        *,
        had_existing_mr: bool,
        issue: Issue | None = None,
        container: Any = None,
    ) -> bool:
        return await fail_execute_task(
            self,
            db,
            task,
            error,
            had_existing_mr=had_existing_mr,
            issue=issue,
            container=container,
        )

    async def _handle_resume_task_failure(
        self,
        db: AsyncSession,
        task_id: int,
        task: Task,
        container: Any,
        error: Exception,
        *,
        had_existing_mr: bool,
        issue: Issue | None = None,
    ) -> bool:
        return await fail_resume_task(
            self,
            db,
            task_id,
            task,
            container,
            error,
            had_existing_mr=had_existing_mr,
            issue=issue,
        )

    async def _handle_resume_missing_container(
        self,
        db: AsyncSession,
        task: Task,
        error: Exception,
    ) -> bool:
        return await fail_resume_missing_container(db, task, error)

    async def execute_task(self, db: AsyncSession, task_id: int) -> bool:
        return await run_execute_task(self, db, task_id, settings=get_settings())

    async def resume_task(self, db: AsyncSession, task_id: int, container_name: str) -> bool:
        return await run_resume_task(
            self,
            db,
            task_id,
            container_name,
            settings=get_settings(),
        )

    async def process_pending_tasks(self, db: AsyncSession) -> int:
        return await run_pending_tasks(self, db)
