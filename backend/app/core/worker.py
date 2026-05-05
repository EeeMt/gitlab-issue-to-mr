"""Worker executor for running tasks in Docker containers."""

import httpx
import logging
import re
from typing import Any, Optional

from gitlab import Gitlab
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import get_effective_settings as get_settings
from app.core.docker_client import DockerClientWrapper, get_docker_client
from app.core.gitlab_client import GitLabClient, get_gitlab_client
from app.core.mattermost_notifications import (
    MATTERMOST_EVENT_TASK_COMPLETED,
    MATTERMOST_EVENT_TASK_FAILED,
    MATTERMOST_EVENT_TASK_RETRY_SCHEDULED,
    notify_task_event,
)
from app.core.ssl_utils import get_ssl_verify
from app.core.usage_limits import upsert_task_usage_ledger
from app.core.worker_environment_variables import build_worker_environment_map, list_worker_environment_variables
from app.core.worker_event_projector import WorkerEventProjector
from app.core.worker_gitlab import (
    build_initial_mr_description,
    build_initial_mr_title,
    create_mr_if_needed,
    create_new_mr,
    find_existing_mr,
    notify_task_completed,
    notify_task_started,
    remove_mr_draft_status_for_issue,
    update_mr_description_for_issue,
)
from app.core.worker_log_parser import WorkerStdoutMarkerParser
from app.core.worker_log_stream import WorkerLogStreamer
from app.core.worker_results import finalize_archive, parse_mr_from_logs, parse_task_result, update_task_stats_from_logs_or_api
from app.core.worker_runtime import (
    build_container_env,
    build_container_volumes,
    build_legacy_container_env,
    get_container_name,
    resolve_commit_author,
    resolve_provider,
)
from app.core.worker_task_lifecycle import (
    create_execute_container,
    fail_execute_task,
    fail_resume_missing_container,
    fail_resume_task,
    monitor_container_run,
    prepare_execute_task_context,
    prepare_resume_task_context,
    send_failure_alert as lifecycle_send_failure_alert,
    send_failure_notifications as lifecycle_send_failure_notifications,
    send_success_notifications as lifecycle_send_success_notifications,
)
from app.models import Issue, Task, TaskStatus

logger = logging.getLogger(__name__)

_ANSI_ESCAPE = re.compile(
    r'\x1b\[[0-9;]*[mABCDEFGHJKLMPSTfnsu]'
    r'|\x1b\][^\x07]*\x07'
    r'|\x1b[()][A-Z0-9]'
    r'|\x1b[@-_]',
    re.DOTALL,
)


async def prepare_container_inputs(
    worker,
    db: AsyncSession,
    task: Task,
    issue: Optional[Issue],
    mr_iid: Optional[int],
):
    target_branch = issue.target_branch if issue else None
    provider = await worker._resolve_provider(db, task)
    custom_environment_rows = await list_worker_environment_variables(db)
    custom_environment = build_worker_environment_map(custom_environment_rows)
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

    text = re.sub(r'glpat-[a-zA-Z0-9\-]{10,}', '[GITLAB_TOKEN]', text)
    text = re.sub(r'sk-(?:cp|ant|api)-[a-zA-Z0-9\-]{10,}', '[ANTHROPIC_API_KEY]', text)
    text = re.sub(r'(PRIVATE-TOKEN:\s*)[^\s]+', r'\1[REDACTED]', text)
    text = text.replace('\x00', '')
    return text


def sanitize_sensitive_data(text: str) -> str:
    """Redact credentials and strip ANSI codes from text."""
    if not text:
        return text

    text = scrub_sensitive_data(text)
    text = _ANSI_ESCAPE.sub('', text)
    text = re.sub(r'[\ud800-\udfff\ufffe\uffff]', '', text)
    return text


class WorkerExecutor:
    """Worker executor that runs tasks in Docker containers."""

    def __init__(
        self,
        docker_client: Optional[DockerClientWrapper] = None,
        gitlab_client: Optional[GitLabClient] = None,
        session_factory: Optional[async_sessionmaker[AsyncSession]] = None,
    ):
        self.docker = docker_client or get_docker_client()
        self.gitlab = gitlab_client or get_gitlab_client()
        self._session_factory = session_factory
        self._event_projector = WorkerEventProjector(sanitize_sensitive_data)
        self._scrub_sensitive_data = scrub_sensitive_data
        self._sanitize_sensitive_data = sanitize_sensitive_data
        self._httpx_async_client = httpx.AsyncClient
        self._get_ssl_verify = get_ssl_verify
        self._reset_stdout_helpers()

    def _reset_stdout_helpers(self) -> None:
        self._stdout_marker_parser = WorkerStdoutMarkerParser()
        self._log_streamer = WorkerLogStreamer(
            scrub_sensitive_data=scrub_sensitive_data,
            stdout_marker_parser=self._stdout_marker_parser,
        )

    def __getattr__(self, name: str):
        projector_methods = {
            '_reset_event_archive_state': self._event_projector.reset,
            '_load_resume_runtime_state': self._event_projector.load_resume_runtime_state,
            '_ingest_event_records_from_chunk': self._event_projector.ingest_event_records_from_chunk,
            '_ingest_event_record': self._event_projector.ingest_event_record,
            '_tail_event_jsonl': self._event_projector.tail_event_jsonl,
            '_tail_console_log': self._event_projector.tail_console_log,
        }
        if name in projector_methods:
            return projector_methods[name]

        sync_wrappers = {
            '_build_initial_mr_title': lambda task: build_initial_mr_title(task),
            '_build_initial_mr_description': lambda task: build_initial_mr_description(task),
            '_remove_mr_draft_status': lambda task: None,
            '_remove_mr_draft_status_for_issue': lambda task, issue, sudo_gl=None: remove_mr_draft_status_for_issue(task, issue, self.gitlab, sudo_gl=sudo_gl),
            '_create_mr_if_needed': lambda task, issue, mr_iid, mr_web_url, sudo_gl=None: create_mr_if_needed(task, issue, mr_iid, mr_web_url, self.gitlab, sudo_gl=sudo_gl),
            '_find_existing_mr': lambda task, issue: find_existing_mr(task, issue, self.gitlab),
            '_create_new_mr': lambda task, issue, sudo_gl=None: create_new_mr(task, issue, self.gitlab, sudo_gl=sudo_gl),
            '_build_container_volumes': lambda *args, **kwargs: build_container_volumes(*args, **kwargs),
            '_get_container_name': lambda task: get_container_name(task),
            '_notify_task_started': lambda task, issue=None: notify_task_started(task, self.gitlab, issue),
        }
        if name in sync_wrappers:
            return sync_wrappers[name]

        if name == '_resolve_provider':

            async def _resolve_provider_wrapper(db: AsyncSession, task: Task):
                return await resolve_provider(db, task)

            return _resolve_provider_wrapper

        if name == '_resolve_commit_author':

            async def _resolve_commit_author_wrapper(db: AsyncSession, task: Task) -> tuple[str, str]:
                return await resolve_commit_author(db, task)

            return _resolve_commit_author_wrapper

        if name == '_parse_mr_from_logs':

            async def _parse_mr_from_logs_wrapper(task: Task, logs: str) -> None:
                await parse_mr_from_logs(task, logs, self.gitlab)

            return _parse_mr_from_logs_wrapper

        if name == '_update_task_stats_from_logs_or_api':

            async def _update_task_stats_wrapper(
                task: Task,
                logs: str,
                issue: Optional[Issue] = None,
            ) -> None:
                await update_task_stats_from_logs_or_api(task, logs, self.gitlab, issue)

            return _update_task_stats_wrapper

        if name == '_update_mr_description_for_issue':

            async def _update_mr_description_wrapper(
                task: Task,
                issue: Issue,
                db: AsyncSession,
                *,
                sudo_gl: Optional[Gitlab] = None,
            ) -> None:
                await update_mr_description_for_issue(task, issue, db, self.gitlab, sudo_gl=sudo_gl)

            return _update_mr_description_wrapper

        if name == '_notify_task_completed':

            async def _notify_task_completed_wrapper(
                task: Task,
                success: bool,
                notify_target: str = 'issue',
                issue: Optional[Issue] = None,
            ) -> None:
                await notify_task_completed(task, self.gitlab, sanitize_sensitive_data, success, notify_target, issue)

            return _notify_task_completed_wrapper

        raise AttributeError(name)

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
        mr_iid: Optional[int],
        target_branch: Optional[str],
        provider=None,
        *,
        author_name: Optional[str] = None,
        author_email: Optional[str] = None,
        custom_environment: Optional[dict[str, str]] = None,
    ) -> dict[str, str]:
        settings = get_settings()

        if provider and getattr(provider, 'id', None):
            if custom_environment:
                from app.core.worker_environment_variables import validate_worker_environment_variable_key

                for key in custom_environment:
                    validate_worker_environment_variable_key(key)
            return build_container_env(
                task,
                issue,
                mr_iid,
                target_branch,
                provider=provider,
                author_name=author_name,
                author_email=author_email,
                custom_environment=custom_environment,
            )

        return build_legacy_container_env(
            settings,
            task,
            issue,
            mr_iid,
            target_branch,
            provider=provider,
            author_name=author_name,
            author_email=author_email,
            custom_environment=custom_environment,
        )

    async def _prepare_container_inputs(
        self,
        db: AsyncSession,
        task: Task,
        issue: Optional[Issue],
        mr_iid: Optional[int],
    ):
        return await prepare_container_inputs(self, db, task, issue, mr_iid)

    async def _parse_task_result(
        self,
        task: Task,
        logs: str,
        db: AsyncSession,
        exit_code: int,
        issue: Optional[Issue] = None,
    ) -> None:
        await parse_task_result(task, logs, db, exit_code, sanitize_sensitive_data, self.gitlab, issue)


    async def _send_notifications(
        self,
        task: Task,
        success: bool,
        had_existing_mr: bool,
        logs: str,
        issue: Optional[Issue] = None,
    ) -> None:
        await lifecycle_send_success_notifications(
            self,
            task,
            had_existing_mr=had_existing_mr,
            issue=issue,
            notify_task_event_fn=notify_task_event,
            completion_event=MATTERMOST_EVENT_TASK_COMPLETED,
        )

    async def _send_failure_notifications(
        self,
        task: Task,
        success: bool,
        had_existing_mr: bool,
        issue: Optional[Issue] = None,
    ) -> None:
        await lifecycle_send_failure_notifications(
            self,
            task,
            had_existing_mr=had_existing_mr,
            issue=issue,
            notify_task_event_fn=notify_task_event,
            retry_scheduled_event=MATTERMOST_EVENT_TASK_RETRY_SCHEDULED,
            failed_event=MATTERMOST_EVENT_TASK_FAILED,
        )

    async def _try_upsert_usage_ledger(self, db: AsyncSession, task: Task) -> None:
        try:
            await upsert_task_usage_ledger(db, task)
        except Exception as ledger_error:
            logger.warning(f'[Task {task.id}] Failed to upsert usage ledger: {ledger_error}')

    async def _send_failure_alert(self, task: Task, issue: Optional[Issue] = None) -> None:
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

    async def _flush_log_chunk(
        self,
        task_id: int,
        lines: list[str],
        chunk_index: int,
        db: AsyncSession,
    ) -> None:
        await self._log_streamer.flush_log_chunk(task_id, lines, chunk_index, db)

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
        issue: Optional[Issue],
        container: Any,
        settings: Any,
        had_existing_mr: bool,
        sudo_gl: Optional[Gitlab],
        resume_prefix: str = '',
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
        issue: Optional[Issue] = None,
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
        issue: Optional[Issue] = None,
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
        settings = get_settings()
        context = await prepare_execute_task_context(self, db, task_id, settings=settings)
        if not context:
            return False
        if context['handled']:
            return context['result']

        settings = context['settings']
        task = context['task']
        issue = context['issue']
        had_existing_mr = context['had_existing_mr']
        sudo_gl = context['sudo_gl']
        container = None

        try:
            try:
                container = await create_execute_container(
                    self,
                    db,
                    settings=settings,
                    task=task,
                    issue=issue,
                    sudo_gl=sudo_gl,
                )
            except ValueError as e:
                logger.error(f'[Task {task_id}] Failed while building worker environment: {e}')
                return await self._handle_execute_task_failure(
                    db,
                    task,
                    e,
                    had_existing_mr=had_existing_mr,
                    issue=issue,
                )

            return await self._monitor_container_run(
                db=db,
                task=task,
                issue=issue,
                container=container,
                settings=settings,
                had_existing_mr=had_existing_mr,
                sudo_gl=sudo_gl,
            )
        except Exception as e:  # noqa: BLE001
            logger.exception(f'Task {task_id} failed with exception: {e}')
            return await self._handle_execute_task_failure(
                db,
                task,
                e,
                had_existing_mr=had_existing_mr,
                issue=issue,
                container=container,
            )

    async def resume_task(self, db: AsyncSession, task_id: int, container_name: str) -> bool:
        settings = get_settings()
        context = await prepare_resume_task_context(self, db, task_id, container_name, settings=settings)
        if not context:
            return False
        if context['handled']:
            return context['result']

        settings = context['settings']
        task = context['task']
        issue = context['issue']
        had_existing_mr = context['had_existing_mr']
        sudo_gl = context['sudo_gl']
        container = context['container']

        try:
            return await self._monitor_container_run(
                db=db,
                task=task,
                issue=issue,
                container=container,
                settings=settings,
                had_existing_mr=had_existing_mr,
                sudo_gl=sudo_gl,
                resume_prefix=' (resume)',
            )
        except Exception as e:  # noqa: BLE001
            return await self._handle_resume_task_failure(
                db,
                task_id,
                task,
                container,
                e,
                had_existing_mr=had_existing_mr,
                issue=issue,
            )

    async def process_pending_tasks(self, db: AsyncSession) -> int:
        result = await db.execute(select(Task).where(Task.status == TaskStatus.PENDING).order_by(Task.created_at))
        tasks = result.scalars().all()

        processed = 0
        for task in tasks:
            success = await self.execute_task(db, task.id)
            if success:
                processed += 1

        return processed
