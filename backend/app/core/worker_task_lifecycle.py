"""Task lifecycle helpers for WorkerExecutor."""

import asyncio
import json
import logging
import os
import time
from typing import Any

from gitlab import Gitlab
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.task_log_payloads import create_payload
from app.core.utcnow import utcnow
from app.core.worker_environment_variables import (
    build_worker_environment_map,
    list_worker_environment_variables,
)
from app.database import AsyncSessionLocal
from app.models import Issue, Task, TaskLog, TaskStatus

logger = logging.getLogger(__name__)

_CONTAINER_METADATA_PATH = "/tmp/codify-runtime/task-metadata.json"
_CONTAINER_DELIVERY_SUMMARY_PATH = "/tmp/codify-runtime/delivery-summary.md"
_CONTAINER_DELIVERY_SUMMARY_VALIDATION_PATH = "/tmp/codify-runtime/delivery-summary-validation.json"


def _build_delivery_summary_preview(text: str, limit: int = 120) -> tuple[str, bool]:
    preview = " ".join(text.split())[:limit]
    return preview, len(" ".join(text.split())) > limit


async def _save_delivery_summary_from_container(
    worker,
    container: Any,
    task: Task,
    db: AsyncSession,
) -> None:
    """Persist Codify's final delivery summary separately from raw Claude assistant text."""
    try:
        raw = worker.docker.read_file_from_container(container, _CONTAINER_DELIVERY_SUMMARY_PATH)
        if not raw:
            logger.info(
                f"[Task {task.id}] delivery-summary.md could not be read from container at "
                f"{_CONTAINER_DELIVERY_SUMMARY_PATH!r}; falling back to assistant_text logs"
            )
            return

        summary_text = raw.decode("utf-8", errors="replace") if isinstance(raw, bytes) else str(raw)
        summary = worker._sanitize_sensitive_data(summary_text).strip()
        if not summary:
            logger.info(f"[Task {task.id}] delivery-summary.md was empty after sanitization")
            return

        validation: dict[str, Any] | None = None
        validation_raw = worker.docker.read_file_from_container(
            container,
            _CONTAINER_DELIVERY_SUMMARY_VALIDATION_PATH,
        )
        if validation_raw:
            try:
                validation_text = (
                    validation_raw.decode("utf-8", errors="replace")
                    if isinstance(validation_raw, bytes)
                    else str(validation_raw)
                )
                parsed_validation = json.loads(validation_text)
                if isinstance(parsed_validation, dict):
                    validation = parsed_validation
            except Exception:
                logger.debug(f"[Task {task.id}] Failed to parse delivery summary validation JSON")

        payload = await create_payload(
            db,
            task_id=task.id,
            payload_kind="delivery_summary",
            text=summary,
        )
        preview, truncated = _build_delivery_summary_preview(summary)
        metadata = {
            "payload_id": payload.id,
            "char_count": len(summary),
            "preview": preview,
            "truncated": truncated,
        }
        if validation is not None:
            metadata["validation"] = validation

        db.add(
            TaskLog(
                task_id=task.id,
                log_level="INFO",
                message="",
                log_type="delivery_summary",
                log_metadata=json.dumps(metadata, ensure_ascii=False),
            )
        )
        logger.info(
            f"[Task {task.id}] delivery summary persisted "
            f"(chars={len(summary)}, validation_ok={validation.get('ok') if validation else 'unknown'})"
        )
    except Exception as exc:
        logger.warning(f"[Task {task.id}] Could not persist delivery summary: {exc}")


def _save_task_metadata_from_container(worker, container: Any, task: Task, issue: Any) -> None:
    """Extract task-metadata.json from the container via the Docker API and persist it locally.

    This is a belt-and-suspenders complement to the volume-mount approach:
    - When the Docker daemon is remote, volume mounts point to the *remote* host's filesystem
      while the scheduler reads from its *local* filesystem — the volume copy is unreachable.
    - When the worker image is local but the volume-mounted directory is not accessible for any
      reason (permissions, path mismatch, etc.), this extraction still works.

    container.get_archive() always uses the Docker HTTP API, so it works for both local and
    remote daemons.  The file is saved to the same path that load_task_metadata_files() expects.
    """
    try:
        from app.config import get_effective_settings
        from app.core.worker_workspace import build_issue_workspace_paths

        settings = get_effective_settings()
        paths = build_issue_workspace_paths(settings, issue, task)
        if paths is None:
            logger.debug(
                f"[Task {task.id}] Skipping metadata extraction: worker_workspace_host_path not configured"
            )
            return

        raw = worker.docker.read_file_from_container(container, _CONTAINER_METADATA_PATH)
        if not raw:
            logger.info(
                f"[Task {task.id}] task-metadata.json could not be read from container at "
                f"{_CONTAINER_METADATA_PATH!r} — file may not exist yet or container may be "
                f"in an inaccessible state; metadata will be omitted from MR description"
            )
            return

        # Validate JSON before writing
        data = json.loads(raw)
        if not isinstance(data, dict):
            logger.warning(f"[Task {task.id}] task-metadata.json in container is not a JSON object, skipping")
            return

        dest = os.path.join(paths.runtime_path, "task-metadata.json")
        os.makedirs(paths.runtime_path, exist_ok=True)
        with open(dest, "w", encoding="utf-8") as fh:
            json.dump(data, fh, ensure_ascii=False)
        logger.info(f"[Task {task.id}] task-metadata.json extracted from container → {dest}")
    except Exception as exc:
        logger.warning(f"[Task {task.id}] Could not extract task-metadata.json from container: {exc}")


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
    if not task.issue_id:
        return None
    return await db.get(Issue, task.issue_id)


async def prepare_container_inputs(
    worker,
    db: AsyncSession,
    task: Task,
    issue: Issue | None,
    mr_iid: int | None,
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


async def reset_execution_state(worker, db: AsyncSession, task_id: int) -> int:
    worker._reset_event_archive_state()
    worker._reset_stdout_helpers()
    del_result = await db.execute(delete(TaskLog).where(TaskLog.task_id == task_id))
    return del_result.rowcount or 0


async def mark_task_running_and_commit(db: AsyncSession, task: Task) -> None:
    task.status = TaskStatus.RUNNING
    task.started_at = utcnow()
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
    if task.issue_id and not issue:
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

    if not settings.worker_skip_image_pull:
        try:
            worker.docker.pull_image(settings.worker_image, force=False)
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

    if issue:
        await worker._write_previous_task_summaries_file(db, settings, issue, task)

    environment, _target_branch = await worker._prepare_container_inputs(db, task, issue, mr_iid)
    volumes = worker._build_container_volumes(settings, issue, task=task)
    container_name = worker._get_container_name(task)
    container = worker.docker.create_container(
        image=settings.worker_image,
        command="",
        environment=environment,
        volumes=volumes if volumes else None,
        network=settings.worker_network,
        name=container_name,
    )

    task.container_id = container.id
    await db.commit()
    return container


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


async def fail_missing_parent_issue(db: AsyncSession, task: Task) -> bool:
    logger.error(f"[Task {task.id}] Parent issue {task.issue_id} not found; marking task FAILED")
    task.status = TaskStatus.FAILED
    task.error_message = f"Parent issue {task.issue_id} not found"
    task.completed_at = utcnow()
    await db.commit()
    return False


async def fail_execute_task(
    worker,
    db: AsyncSession,
    task: Task,
    error: Exception,
    *,
    had_existing_mr: bool,
    issue: Issue | None = None,
    container: Any = None,
) -> bool:
    logger.error(f"[Task {task.id}] Task failed: {error}")
    had_completed_at = task.completed_at is not None
    task.status = TaskStatus.FAILED
    if task.completed_at is None:
        task.completed_at = utcnow()
    task.error_message = worker._sanitize_sensitive_data(str(error))[:1000]
    if had_completed_at:
        await worker._try_upsert_usage_ledger(db, task)
    await db.commit()

    if container:
        try:
            worker.docker.remove_container(container, force=True)
        except Exception as cleanup_error:  # noqa: BLE001
            logger.warning(f"Failed to cleanup container: {cleanup_error}")

    try:
        await worker._send_failure_notifications(
            task,
            success=False,
            had_existing_mr=had_existing_mr,
            issue=issue,
        )
    except Exception as notify_error:  # noqa: BLE001
        logger.warning(f"Failed to send failure notifications: {notify_error}")

    return False


async def fail_resume_missing_container(db: AsyncSession, task: Task, error: Exception) -> bool:
    logger.error(f"[Task {task.id}] Container disappeared during resume; marking task FAILED: {error}")
    task.status = TaskStatus.FAILED
    task.error_message = f"Container disappeared during resume: {error}"
    task.completed_at = utcnow()
    await db.commit()
    return False


async def fail_resume_task(
    worker,
    db: AsyncSession,
    task_id: int,
    task: Task,
    container: Any,
    error: Exception,
    *,
    had_existing_mr: bool,
    issue: Issue | None = None,
) -> bool:
    logger.exception(f"[Task {task_id}] Resume failed with exception: {error}")
    had_completed_at = task.completed_at is not None
    task.status = TaskStatus.FAILED
    if task.completed_at is None:
        task.completed_at = utcnow()
    task.error_message = worker._sanitize_sensitive_data(str(error))[:1000]
    if had_completed_at:
        await worker._try_upsert_usage_ledger(db, task)
    await db.commit()

    try:
        worker.docker.remove_container(container, force=True)
    except Exception as cleanup_error:  # noqa: BLE001
        logger.warning(f"[Task {task_id}] Resume: failed to cleanup container: {cleanup_error}")

    try:
        await worker._send_failure_alert(task, issue)
    except Exception as notify_error:  # noqa: BLE001
        logger.warning(f"[Task {task_id}] Resume: failed to send failure alert: {notify_error}")

    return False


async def send_failure_alert(
    worker,
    task: Task,
    issue: Issue | None = None,
    *,
    get_settings_fn,
    get_ssl_verify_fn,
    httpx_async_client_cls,
) -> None:
    settings = get_settings_fn()
    if not settings.alert_on_failure or not settings.alert_webhook_url:
        return

    error_msg = task.error_message[:500] if task.error_message else "Unknown error"
    error_msg = worker._sanitize_sensitive_data(error_msg)
    alert_data = {
        "text": "🚨 Task Failed",
        "attachments": [
            {
                "color": "danger",
                "fields": [
                    {"title": "Task ID", "value": str(task.id), "short": True},
                    {"title": "Project ID", "value": str(task.project_id), "short": True},
                    {"title": "Issue", "value": f"#{issue.id}" if issue else "N/A", "short": True},
                    {"title": "Error", "value": error_msg},
                ],
            }
        ],
    }

    try:
        async with httpx_async_client_cls(timeout=10.0, verify=get_ssl_verify_fn(settings)) as client:
            response = await client.post(settings.alert_webhook_url, json=alert_data)
        if response.status_code < 400:
            logger.info(f"Sent failure alert for task {task.id}")
        else:
            logger.warning(f"Failed to send failure alert: {response.status_code}")
    except Exception as e:
        logger.warning(f"Failed to send failure alert: {e}")


async def send_success_notifications(
    worker,
    task: Task,
    *,
    had_existing_mr: bool,
    issue: Issue | None = None,
    notify_task_event_fn=None,
    completion_event=None,
    session_factory=None,
) -> None:
    try:
        await notify_task_event_fn(task, completion_event, session_factory=session_factory)
    except Exception as e:
        logger.warning(f"Failed to send Mattermost completion notification: {e}")


async def send_failure_notifications(
    worker,
    task: Task,
    *,
    had_existing_mr: bool,
    issue: Issue | None = None,
    notify_task_event_fn=None,
    retry_scheduled_event=None,
    failed_event=None,
    session_factory=None,
) -> None:
    try:
        await worker._send_failure_alert(task, issue)
    except Exception as e:
        logger.warning(f"Failed to send failure alert: {e}")

    try:
        if task.status == TaskStatus.PENDING:
            await notify_task_event_fn(
                task,
                retry_scheduled_event,
                context={
                    "previous_scheduled_at": task.scheduled_at,
                    "scheduled_at": task.scheduled_at,
                },
                session_factory=session_factory,
            )
        else:
            await notify_task_event_fn(task, failed_event, session_factory=session_factory)
    except Exception as e:
        logger.warning(f"Failed to send Mattermost failure notification: {e}")


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

    async def _poll_artifacts(stop: asyncio.Event) -> None:
        while not stop.is_set():
            try:
                async with session_factory() as poll_db:
                    await worker._tail_event_jsonl(task_id=task.id, container=container, db=poll_db)
                    await worker._tail_console_log(task_id=task.id, container=container, db=poll_db)
            except Exception as exc:  # noqa: BLE001
                logger.debug(f"[Task {task.id}] artifact poll error{resume_prefix}: {exc}")
            await asyncio.sleep(2)

    async def _flush_artifacts_once() -> None:
        async with session_factory() as artifact_db:
            await worker._tail_event_jsonl(task_id=task.id, container=container, db=artifact_db)
            await worker._tail_console_log(task_id=task.id, container=container, db=artifact_db)
            await worker._finalize_archive(task_id=task.id, container=container, db=artifact_db)
            await worker._backfill_console_log_from_archive(task_id=task.id, db=artifact_db)
            await worker._backfill_event_jsonl_from_archive(task_id=task.id, db=artifact_db)

    stop_event = asyncio.Event()
    poll_task = asyncio.create_task(_poll_artifacts(stop_event))
    logger.info(f"[Task {task.id}] Streaming container logs (timeout={settings.task_timeout}s){resume_prefix}")
    try:
        exit_code, logs, log_chunks_saved, timed_out = await worker._stream_logs_to_db(
            container,
            task.id,
            db,
            settings.task_timeout,
        )
    finally:
        stop_event.set()
        await poll_task

    logger.info(
        f"[Task {task.id}] Log stream finished{resume_prefix}: "
        f"exit_code={exit_code}, timed_out={timed_out}, chunks={log_chunks_saved}"
    )

    try:
        await _flush_artifacts_once()
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[Task {task.id}] Post-exit artifact finalization error{resume_prefix}: {exc}")

    await db.refresh(task)
    if task.status == TaskStatus.CANCELLED:
        logger.info(f"[Task {task.id}] Task was cancelled during execution; removing container")
        try:
            worker.docker.remove_container(container, force=True)
        except Exception:
            pass
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
            logger.info(f"[Task {task.id}] Captured MR !{parsed_mr_iid} from logs → issue #{issue.id}")
            issue.merge_request_iid = parsed_mr_iid
            issue.merge_request_url = parsed_mr_url
            await db.commit()

    if exit_code == 0:
        if issue and issue.merge_request_iid:
            t_mr_draft = time.monotonic()
            logger.info(
                f"[Task {task.id}] Removing MR draft status for !{issue.merge_request_iid}"
            )
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
        logger.debug(f"[Task {task.id}] Skipping MR description update: no merge_request_iid on issue #{issue.id}")

    try:
        worker.docker.remove_container(container, force=True)
    except Exception as e:
        logger.warning(f"[Task {task.id}] Failed to remove container{resume_prefix}: {e}")

    return exit_code == 0
