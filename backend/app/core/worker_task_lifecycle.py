"""Task lifecycle helpers for WorkerExecutor."""

import asyncio
import logging
import time
from datetime import datetime
from typing import Any

from gitlab import Gitlab
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ci_failure_logs import append_ci_failure_log
from app.core.utcnow import utcnow
from app.core.worker_profiles import load_task_worker_runtime
from app.core.worker_runtime import (
    materialize_task_prompt,
    materialize_worker_custom_scripts_from_snapshot,
    worker_custom_scripts_configured,
)
from app.core.worker_task_artifacts import (
    _stop_artifact_poller,
    finalize_task_raw_logs,
    flush_task_artifacts,
    poll_task_artifacts,
)
from app.core.worker_task_artifacts import (
    save_delivery_summary_from_container as _save_delivery_summary_from_container,
)
from app.core.worker_task_artifacts import (
    save_task_metadata_from_container as _save_task_metadata_from_container,
)
from app.core.worker_task_outcomes import (
    fail_missing_parent_issue,
    fail_resume_missing_container,
)
from app.core.worker_workspace import build_issue_workspace_paths
from app.database import AsyncSessionLocal
from app.models import CIFailureRun, Issue, Task, TaskLog, TaskStatus

logger = logging.getLogger(__name__)


async def load_task_or_fail(db: AsyncSession, task_id: int) -> Task | None:
    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        logger.error(f"[Task {task_id}] Task not found in database")
        return None
    return task


async def load_resume_task_or_fail(db: AsyncSession, task_id: int) -> Task | None:
    result = await db.execute(select(Task).where(Task.id == task_id))
    task = result.scalar_one_or_none()
    if not task:
        logger.error(f"[Task {task_id}] Resume: task not found in database")
        return None
    return task


async def load_issue_for_task(db: AsyncSession, task: Task) -> Issue | None:
    return await db.get(Issue, task.issue_id)


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


async def reset_execution_state(worker, db: AsyncSession, task_id: int) -> int:
    worker._reset_event_archive_state()
    worker._reset_stdout_helpers()
    del_result = await db.execute(delete(TaskLog).where(TaskLog.task_id == task_id))
    return del_result.rowcount or 0


async def mark_task_running_and_commit(db: AsyncSession, task: Task) -> None:
    task.status = TaskStatus.RUNNING
    task.started_at = utcnow()
    task.raw_logs_finalized_at = None
    await db.commit()


def resolve_had_existing_mr(issue: Issue | None) -> bool:
    return (issue.merge_request_iid is not None) if issue else False


def resolve_sudo_gitlab(
    task: Task,
    gitlab_client,
    task_id: int,
    *,
    resume: bool = False,
) -> Gitlab | None:
    if not task.initiator_gitlab_user_id or not gitlab_client.settings.gitlab_admin_token:
        return None
    try:
        return gitlab_client.create_sudo_gl(task.initiator_gitlab_user_id)
    except ValueError as e:
        if not resume:
            logger.warning(f"[Task {task_id}] Cannot use sudo: {e}, falling back to bot token")
        return None


async def persist_issue_mr_if_changed(
    db: AsyncSession,
    issue: Issue | None,
    mr_iid: int | None,
    mr_web_url: str | None,
) -> None:
    if issue and mr_iid and mr_iid != issue.merge_request_iid:
        logger.info(f"[Issue {issue.id}] Storing MR IID !{mr_iid} → DB")
        issue.merge_request_iid = mr_iid
        issue.merge_request_url = mr_web_url
        await db.commit()


async def prepare_execute_task_context(
    worker,
    db: AsyncSession,
    task_id: int,
    *,
    settings: Any,
):
    task = await load_task_or_fail(db, task_id)
    if not task:
        return None

    issue = await load_issue_for_task(db, task)
    if not issue:
        return {
            "handled": True,
            "result": await fail_missing_parent_issue(db, task),
        }

    had_existing_mr = resolve_had_existing_mr(issue)
    sudo_gl = resolve_sudo_gitlab(task, worker.gitlab, task_id)

    cleared_logs = await reset_execution_state(worker, db, task_id)
    if cleared_logs:
        logger.info(f"[Task {task_id}] Cleared {cleared_logs} log entries from previous execution")

    await mark_task_running_and_commit(db, task)

    return {
        "handled": False,
        "settings": settings,
        "task": task,
        "issue": issue,
        "had_existing_mr": had_existing_mr,
        "sudo_gl": sudo_gl,
    }


async def create_execute_container(
    worker,
    db: AsyncSession,
    *,
    settings: Any,
    task: Task,
    issue: Issue | None,
    sudo_gl: Gitlab | None,
):
    task_id = task.id
    if await finalize_pre_container_cancellation(db, task, phase="runtime setup"):
        return None
    worker_runtime = await load_task_worker_runtime(db, task)
    worker._configure_docker_for_runtime(worker_runtime, settings)

    if not settings.worker_skip_image_pull:
        try:
            worker.docker.pull_image(worker_runtime.image, force=False)
        except Exception as e:
            logger.warning(f"Failed to pull image: {e}, using existing local image if available")

    mr_iid = issue.merge_request_iid if issue else None
    mr_web_url = issue.merge_request_url if issue else None

    if issue and issue.target_branch:
        try:
            worker.gitlab.ensure_project_label(task.project_id, "Codify", "#6699cc")
        except Exception as e:
            logger.warning(f"[Task {task_id}] Failed to ensure Codify label: {e}")

        mr_iid, mr_web_url = worker._create_mr_if_needed(
            task,
            issue,
            mr_iid,
            mr_web_url,
            sudo_gl=sudo_gl,
        )

    await persist_issue_mr_if_changed(db, issue, mr_iid, mr_web_url)

    workspace_paths = build_issue_workspace_paths(settings, issue, task) if issue else None

    if workspace_paths is None:
        raise RuntimeError("worker_workspace_host_path is required for persisted task prompts")
    materialize_task_prompt(task, workspace_paths.runtime_path)

    if issue:
        await worker._write_previous_task_summaries_file(db, settings, issue, task)

    if worker_custom_scripts_configured(settings):
        logger.debug(
            "[Task %s] Ignoring legacy global worker scripts; using task worker snapshot",
            task_id,
        )
    materialize_worker_custom_scripts_from_snapshot(
        workspace_paths.runtime_path,
        pre_script=worker_runtime.pre_script,
        post_script=worker_runtime.post_script,
    )

    is_ci_failure_task = (
        getattr(task, "trigger_source", None) == "ci_auto_repair"
        or getattr(task, "ci_failure_run_id", None) is not None
    )
    if issue and is_ci_failure_task:
        if workspace_paths is None:
            raise RuntimeError("worker_workspace_host_path is required for CI auto-repair tasks")
        run = await db.get(CIFailureRun, task.ci_failure_run_id) if task.ci_failure_run_id else None
        if run is None:
            raise RuntimeError("CI failure run is not available for this repair task")
        task.ci_failure_run = run
        worker._materialize_ci_failure_bundle(task, workspace_paths.runtime_path)
        await append_ci_failure_log(
            db,
            run,
            step="bundle_materialized_for_worker",
            status="succeeded",
            message=f"Materialized CI failure bundle for task #{task.id}",
            task_id=task.id,
        )
        await db.flush()

    environment, _target_branch = await worker._prepare_container_inputs(
        db,
        task,
        issue,
        mr_iid,
        custom_environment=worker_runtime.environment,
    )
    environment["CODIFY_CODEGRAPH_ENABLED"] = (
        "true" if worker_runtime.codegraph_enabled else "false"
    )
    container_overrides = worker_runtime.container_overrides()
    environment.update(container_overrides["environment"])
    volumes = worker._build_container_volumes(
        settings,
        issue,
        task=task,
        custom_mounts=worker_runtime.volume_mounts,
    )
    volumes.update(container_overrides["volumes"])
    if await finalize_pre_container_cancellation(db, task, phase="container creation"):
        return None
    container_name = worker._get_container_name(task)
    container = worker.docker.create_container(
        image=worker_runtime.image,
        command="",
        environment=environment,
        volumes=volumes if volumes else None,
        network=settings.worker_network,
        name=container_name,
        entrypoint=container_overrides["entrypoint"],
        user=container_overrides["user"],
        labels={
            "codify.task_id": str(task.id),
            "codify.worker_runtime_mode": worker_runtime.runtime_mode,
            "codify.worker_kit_version": worker_runtime.worker_kit_version or "",
        },
    )

    task.container_id = container.id
    await db.commit()
    return container


async def finalize_pre_container_cancellation(
    db: AsyncSession,
    task: Task,
    *,
    phase: str,
) -> bool:
    """Converge a durable cancel request before a worker container is created."""
    await db.refresh(task)
    cancellation_requested = isinstance(
        getattr(task, "cancel_requested_at", None),
        datetime,
    )
    if task.status != TaskStatus.CANCELLED and not cancellation_requested:
        return False

    task.status = TaskStatus.CANCELLED
    task.completed_at = task.completed_at or utcnow()
    task.error_message = "Cancelled by user"
    await db.commit()
    logger.info(
        "[Task %s] Applied cancellation before %s; no worker container was created",
        task.id,
        phase,
    )
    return True


async def prepare_resume_task_context(
    worker,
    db: AsyncSession,
    task_id: int,
    container_name: str,
    *,
    settings: Any,
):
    task = await load_resume_task_or_fail(db, task_id)
    if not task:
        return None

    issue = await load_issue_for_task(db, task)
    worker_runtime = await load_task_worker_runtime(db, task)
    worker._configure_docker_for_runtime(worker_runtime, settings)
    worker._reset_event_archive_state()
    worker._reset_stdout_helpers()
    had_existing_mr = resolve_had_existing_mr(issue)
    sudo_gl = resolve_sudo_gitlab(task, worker.gitlab, task_id, resume=True)

    try:
        container = worker.docker.client.containers.get(container_name)
    except Exception as e:
        return {
            "handled": True,
            "result": await fail_resume_missing_container(db, task, e),
        }

    return {
        "handled": False,
        "settings": settings,
        "task": task,
        "issue": issue,
        "had_existing_mr": had_existing_mr,
        "sudo_gl": sudo_gl,
        "container": container,
    }


async def monitor_container_run(
    worker,
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
    session_factory = getattr(worker, "_session_factory", None) or AsyncSessionLocal

    stop_event = asyncio.Event()
    poll_task = asyncio.create_task(
        poll_task_artifacts(
            worker,
            task=task,
            container=container,
            session_factory=session_factory,
            stop=stop_event,
            resume_prefix=resume_prefix,
        )
    )
    logger.info(
        f"[Task {task.id}] Streaming container logs (timeout={settings.task_timeout}s){resume_prefix}"
    )
    try:
        exit_code, logs, log_chunks_saved, timed_out = await worker._stream_logs_to_db(
            container,
            task.id,
            db,
            settings.task_timeout,
        )
    finally:
        await _stop_artifact_poller(
            task_id=task.id,
            stop_event=stop_event,
            poll_task=poll_task,
            resume_prefix=resume_prefix,
        )

    logger.info(
        f"[Task {task.id}] Log stream finished{resume_prefix}: "
        f"exit_code={exit_code}, timed_out={timed_out}, chunks={log_chunks_saved}"
    )

    raw_logs_finalized = False
    for attempt in range(1, 4):
        try:
            await finalize_task_raw_logs(
                worker,
                task=task,
                container=container,
                session_factory=session_factory,
            )
            raw_logs_finalized = True
            break
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                f"[Task {task.id}] Post-exit raw-log finalization attempt "
                f"{attempt}/3 failed{resume_prefix}: {exc}"
            )
            if attempt < 3:
                await asyncio.sleep(1)

    try:
        await flush_task_artifacts(
            worker,
            task=task,
            container=container,
            session_factory=session_factory,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            f"[Task {task.id}] Post-exit artifact finalization error{resume_prefix}: {exc}"
        )

    await db.refresh(task)
    raw_logs_finalized = raw_logs_finalized or task.raw_logs_finalized_at is not None
    cancellation_requested = isinstance(
        getattr(task, "cancel_requested_at", None),
        datetime,
    )
    if task.status == TaskStatus.CANCELLED or cancellation_requested:
        if task.status != TaskStatus.CANCELLED:
            task.status = TaskStatus.CANCELLED
            task.completed_at = task.completed_at or utcnow()
            task.error_message = "Cancelled by user"
            await db.commit()
            logger.info(
                "[Task %s] Applied persisted cancellation intent during worker finalization",
                task.id,
            )
        if raw_logs_finalized:
            logger.info(f"[Task {task.id}] Task was cancelled during execution; removing container")
            try:
                worker.docker.remove_container(container, force=True)
            except Exception:
                pass
        else:
            logger.error(
                f"[Task {task.id}] Retaining cancelled task container because raw logs "
                "were not finalized"
            )
        return False

    if issue:
        await db.refresh(issue)

    await worker._parse_task_result(task, logs, db, exit_code, issue=issue)
    if exit_code == 0:
        await _save_delivery_summary_from_container(worker, container, task, db)

    if issue and hasattr(task, "_extracted_session_id") and task._extracted_session_id:
        if not issue.claude_session_id:
            issue.claude_session_id = task._extracted_session_id
        await db.commit()

    if issue:
        parsed_mr_iid = getattr(task, "_parsed_mr_iid", None)
        parsed_mr_url = getattr(task, "_parsed_mr_url", None)
        if parsed_mr_iid and not issue.merge_request_iid:
            logger.info(
                f"[Task {task.id}] Captured MR !{parsed_mr_iid} from logs → issue #{issue.id}"
            )
            issue.merge_request_iid = parsed_mr_iid
            issue.merge_request_url = parsed_mr_url
            await db.commit()

    if exit_code == 0:
        if issue and issue.merge_request_iid:
            t_mr_draft = time.monotonic()
            logger.info(f"[Task {task.id}] Removing MR draft status for !{issue.merge_request_iid}")
            try:
                worker._remove_mr_draft_status_for_issue(task, issue, sudo_gl=sudo_gl)
                logger.info(
                    f"[Task {task.id}] MR draft status removed in {time.monotonic() - t_mr_draft:.1f}s"
                )
            except Exception as e:
                logger.warning(
                    f"[Task {task.id}] Failed to update MR draft status after "
                    f"{time.monotonic() - t_mr_draft:.1f}s{resume_prefix}: {e}"
                )
        await worker._send_notifications(
            task,
            success=True,
            had_existing_mr=had_existing_mr,
            logs=logs,
            issue=issue,
        )
    else:
        await worker._send_failure_notifications(
            task,
            success=False,
            had_existing_mr=had_existing_mr,
            issue=issue,
        )

    scrubbed_logs = worker._scrub_sensitive_data(logs)
    if timed_out:
        task.error_message = (
            f"Task timed out after {settings.task_timeout}s\n"
            + worker._sanitize_sensitive_data(logs)[-800:]
        )
        if log_chunks_saved == 0:
            db.add(
                TaskLog(
                    task_id=task.id,
                    log_level="ERROR",
                    message=f"[Timed out after {settings.task_timeout}s]\n{scrubbed_logs[-2000:]}",
                )
            )
    elif exit_code != 0:
        task.error_message = worker._sanitize_sensitive_data(logs)[-1000:]
        if log_chunks_saved == 0:
            db.add(
                TaskLog(
                    task_id=task.id,
                    log_level="ERROR",
                    message=f"[Exit code: {exit_code}]\n{scrubbed_logs[-2000:]}",
                )
            )
    elif log_chunks_saved == 0:
        db.add(
            TaskLog(
                task_id=task.id,
                log_level="INFO",
                message=scrubbed_logs[-4000:] or "[No output]",
            )
        )

    await worker._try_upsert_usage_ledger(db, task)
    await db.commit()

    # Pull task-metadata.json from the container filesystem via the Docker API before
    # removing the container.  This ensures the file is available on the scheduler's local
    # filesystem even when the Docker daemon is running on a remote host (where volume mounts
    # point to the *remote* host's paths, not the scheduler's paths).
    if issue:
        _save_task_metadata_from_container(worker, container, task, issue)

    if issue and issue.merge_request_iid:
        await worker._update_mr_description_for_issue(task, issue, db, sudo_gl=sudo_gl)
    elif issue:
        logger.debug(
            f"[Task {task.id}] Skipping MR description update: no merge_request_iid on issue #{issue.id}"
        )

    if raw_logs_finalized:
        try:
            worker.docker.remove_container(container, force=True)
        except Exception as e:
            logger.warning(f"[Task {task.id}] Failed to remove container{resume_prefix}: {e}")
    else:
        logger.error(
            f"[Task {task.id}] Retaining task container because raw logs were not finalized"
        )

    return exit_code == 0
