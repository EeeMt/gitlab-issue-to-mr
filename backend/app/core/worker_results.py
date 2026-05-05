"""Result parsing and finalization helpers for worker execution."""

import asyncio
import io
import json as _json
import logging
import os as _os
import re
import tarfile as _tarfile
from typing import Any, Optional

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.task_event_archive import archive_bundle_name
from app.core.utcnow import utcnow
from app.core.usage_limits import upsert_task_usage_ledger
from app.models import Issue, Task, TaskLog, TaskRunArchive, TaskStatus

logger = logging.getLogger(__name__)
_CONTAINER_RUNTIME_DIR = "/tmp/codify-runtime"

_CODIFY_STATS_RE = re.compile(r'^CODIFY_STATS:(.+)$', re.MULTILINE)
_CODIFY_COMMIT_SHA_RE = re.compile(r'^CODIFY_COMMIT_SHA:([a-f0-9]{40})$', re.MULTILINE)
_CODIFY_DIFF_RE = re.compile(r'^CODIFY_DIFF:\+(\d+)-(\d+)$', re.MULTILINE)
_CODIFY_TOOL_CALLS_RE = re.compile(r'^CODIFY_TOOL_CALLS:(.+)$', re.MULTILINE)
_CODIFY_MR_TITLE_RE = re.compile(r'^CODIFY_MR_TITLE:(.+)$', re.MULTILINE)
_CODIFY_SESSION_ID_RE = re.compile(r'^CODIFY_SESSION_ID:(\S+)$', re.MULTILINE)
_THINK_BLOCK_RE = re.compile(r'<think\b[^>]*>.*?</think>', re.IGNORECASE | re.DOTALL)
_OPEN_THINK_RE = re.compile(r'<think\b[^>]*>', re.IGNORECASE)


async def finalize_archive(*, task_id: int, container, db: AsyncSession) -> None:
    """Package the three runtime artifacts into an archive and record its metadata."""
    archive_name = archive_bundle_name(task_id=task_id)
    try:
        stream, _stat_info = await asyncio.to_thread(
            container.get_archive,
            f"{_CONTAINER_RUNTIME_DIR}/{archive_name}",
        )
        raw_bytes = b"".join(stream)
        outer_tar_buf = io.BytesIO(raw_bytes)

        archive_store = "/opt/codify-archives"
        _os.makedirs(archive_store, exist_ok=True)
        final_path = _os.path.join(archive_store, archive_name)

        with _tarfile.open(fileobj=outer_tar_buf, mode="r|") as tf:
            member = tf.next()
            if member:
                with tf.extractfile(member) as src, open(final_path, "wb") as dst:
                    dst.write(src.read())

        size = _os.path.getsize(final_path) if _os.path.exists(final_path) else 0
        db.add(TaskRunArchive(
            task_id=task_id,
            archive_name=archive_name,
            archive_path=final_path,
            archive_size_bytes=size,
        ))
        await db.commit()
        logger.info(f"[Task {task_id}] Runtime archive saved: {final_path} ({size} bytes)")
    except Exception as exc:
        logger.warning(f"[Task {task_id}] _finalize_archive failed (non-fatal): {exc}")


async def parse_mr_from_logs(task: Task, logs: str, gitlab_client) -> None:
    """Parse MR URL and IID from container logs."""
    parsed_mr_url = None
    parsed_mr_iid = None

    for line in logs.split("\n"):
        if "/merge_requests/" in line:
            match = re.search(r'http[^\s]*merge_requests/\d+', line)
            if match:
                parsed_mr_url = gitlab_client.normalize_web_url(match.group(0))
                iid_match = re.search(r'/merge_requests/(\d+)', match.group(0))
                if iid_match:
                    parsed_mr_iid = int(iid_match.group(1))
                break

    if parsed_mr_url and not parsed_mr_iid:
        iid_match = re.search(r'/merge_requests/(\d+)', parsed_mr_url)
        if iid_match:
            parsed_mr_iid = int(iid_match.group(1))

    if parsed_mr_iid:
        task._parsed_mr_iid = parsed_mr_iid
    if parsed_mr_url:
        task._parsed_mr_url = parsed_mr_url


async def update_task_stats_from_logs_or_api(
    task: Task,
    logs: str,
    gitlab_client,
    issue: Optional[Issue] = None,
    structured_diff: Optional[dict[str, Any]] = None,
) -> None:
    """Update task with change statistics from logs or GitLab API."""
    if structured_diff:
        task.additions = int(structured_diff.get("additions") or 0)
        task.deletions = int(structured_diff.get("deletions") or 0)
        task.total_changes = int(structured_diff.get("total") or (task.additions + task.deletions))
        logger.info(
            f"[Task {task.id}] Diff stats (from structured log): "
            f"+{task.additions} -{task.deletions} ({task.total_changes} total)"
        )
        return

    diff_match = _CODIFY_DIFF_RE.search(logs)
    if diff_match:
        task.additions = int(diff_match.group(1))
        task.deletions = int(diff_match.group(2))
        task.total_changes = task.additions + task.deletions
        logger.info(
            f"[Task {task.id}] Diff stats (from log): "
            f"+{task.additions} -{task.deletions} ({task.total_changes} total)"
        )
    elif task.commit_sha:
        mr_iid = (issue.merge_request_iid if issue else None) or getattr(task, '_parsed_mr_iid', None)
        if mr_iid:
            try:
                logger.info(f"[Task {task.id}] Getting MR stats for MR !{mr_iid}")
                stats = await gitlab_client.get_merge_request_stats(task.project_id, mr_iid)
                logger.info(f"[Task {task.id}] MR stats result: {stats}")
                if stats:
                    task.additions = stats.get("additions", 0)
                    task.deletions = stats.get("deletions", 0)
                    task.total_changes = stats.get("total", 0)
                    logger.info(
                        f"[Task {task.id}] MR stats (from API): "
                        f"+{task.additions} -{task.deletions} ({task.total_changes} total)"
                    )
                else:
                    logger.warning(f"[Task {task.id}] MR stats returned None")
            except Exception as e:
                logger.warning(f"[Task {task.id}] Failed to get MR stats: {e}")


def sanitize_merge_request_title(title: str) -> str:
    """Clean model-generated MR titles before persisting/displaying them."""
    if not title:
        return ""

    cleaned = _THINK_BLOCK_RE.sub("", title)
    cleaned = re.sub(r'\s+', ' ', cleaned).strip()

    # If the title starts with an unclosed thinking block, it is not usable.
    if _OPEN_THINK_RE.match(cleaned):
        return ""

    return cleaned


async def _load_latest_log_metadata(db: AsyncSession, task_id: int, log_type: str) -> dict[str, Any]:
    """Return the newest structured log metadata for a task/log_type."""
    try:
        from sqlalchemy import select as _select
        result = await db.execute(
            _select(TaskLog).where(
                TaskLog.task_id == task_id,
                TaskLog.log_type == log_type,
            ).order_by(TaskLog.id.desc()).limit(1)
        )
        structured = result.scalar_one_or_none()
        if not structured or not structured.log_metadata:
            return {}
        parsed = _json.loads(structured.log_metadata)
        return parsed if isinstance(parsed, dict) else {}
    except Exception:
        logger.debug(f"[Task {task_id}] Failed to read {log_type} structured log")
        return {}


async def parse_task_result(
    task: Task,
    logs: str,
    db: AsyncSession,
    exit_code: int,
    sanitize_sensitive_data,
    gitlab_client,
    issue: Optional[Issue] = None,
) -> None:
    """Parse task execution logs and update task with results."""
    run_result_meta = await _load_latest_log_metadata(db, task.id, "run_result")
    system_init_meta = await _load_latest_log_metadata(db, task.id, "system_init")
    finalization_meta = await _load_latest_log_metadata(db, task.id, "worker_finalization")

    usage = run_result_meta.get("usage") if isinstance(run_result_meta.get("usage"), dict) else {}
    if usage:
        task.input_tokens = usage.get('input_tokens')
        task.output_tokens = usage.get('output_tokens')
        logger.info(f"[Task {task.id}] Token usage: in={task.input_tokens} out={task.output_tokens}")
    else:
        stats_match = _CODIFY_STATS_RE.search(logs)
        if stats_match:
            try:
                usage = _json.loads(stats_match.group(1).strip())
                task.input_tokens = usage.get('input_tokens')
                task.output_tokens = usage.get('output_tokens')
                logger.info(f"[Task {task.id}] Token usage: in={task.input_tokens} out={task.output_tokens}")
            except Exception:
                logger.debug(f"[Task {task.id}] Failed to parse CODIFY_STATS")

    model = str(system_init_meta.get('model') or '').strip()
    if model:
        task.model_name = model
        logger.info(f"[Task {task.id}] Model: {model}")

    commit_sha = str(finalization_meta.get("commit_sha") or "").strip()
    if commit_sha:
        task.commit_sha = commit_sha
        logger.info(f"[Task {task.id}] Commit SHA: {task.commit_sha}")
    else:
        commit_sha_match = _CODIFY_COMMIT_SHA_RE.search(logs)
        if commit_sha_match:
            task.commit_sha = commit_sha_match.group(1).strip()
            logger.info(f"[Task {task.id}] Commit SHA: {task.commit_sha}")

    structured_title = str(finalization_meta.get("merge_request_title") or "").strip()
    if structured_title:
        try:
            title = sanitize_merge_request_title(structured_title)
            if title:
                task.merge_request_title = sanitize_sensitive_data(title)[:512]
                logger.info(f"[Task {task.id}] MR title: {task.merge_request_title}")
        except Exception:
            logger.debug(f"[Task {task.id}] Failed to parse structured MR title")
    else:
        mr_title_match = _CODIFY_MR_TITLE_RE.search(logs)
        if mr_title_match:
            try:
                title = sanitize_merge_request_title(mr_title_match.group(1).strip())
                if title:
                    task.merge_request_title = sanitize_sensitive_data(title)[:512]
                    logger.info(f"[Task {task.id}] MR title: {task.merge_request_title}")
            except Exception:
                logger.debug(f"[Task {task.id}] Failed to parse CODIFY_MR_TITLE")

    tool_calls_match = _CODIFY_TOOL_CALLS_RE.search(logs)
    if tool_calls_match:
        try:
            tool_calls_json = tool_calls_match.group(1).strip()
            _json.loads(tool_calls_json)
            db.add(TaskLog(
                task_id=task.id,
                log_level="INFO",
                message="",
                log_type="tool_calls_json",
                log_metadata=tool_calls_json,
            ))
            await db.commit()
            logger.info(f"[Task {task.id}] Stored structured tool calls log entry")
        except Exception:
            logger.debug(f"[Task {task.id}] Failed to parse CODIFY_TOOL_CALLS")

    if exit_code == 0:
        task.status = TaskStatus.COMPLETED
        task.completed_at = utcnow()
        await parse_mr_from_logs(task, logs, gitlab_client)
        structured_diff = finalization_meta.get("diff") if isinstance(finalization_meta.get("diff"), dict) else None
        await update_task_stats_from_logs_or_api(task, logs, gitlab_client, issue, structured_diff)
    else:
        task.status = TaskStatus.FAILED
        task.completed_at = utcnow()
        task.error_message = sanitize_sensitive_data(logs)[-1000:]

    extracted_session_id = str(run_result_meta.get("session_id") or "").strip()
    if not extracted_session_id:
        session_match = _CODIFY_SESSION_ID_RE.search(logs)
        if session_match:
            extracted_session_id = session_match.group(1)
    if extracted_session_id:
        logger.info(f"[Task {task.id}] Extracted session ID: {extracted_session_id}")
        task._extracted_session_id = extracted_session_id


async def try_upsert_usage_ledger(db: AsyncSession, task: Task) -> None:
    """Best-effort quota ledger persistence for already-finished tasks."""
    try:
        await upsert_task_usage_ledger(db, task)
    except Exception as ledger_error:
        logger.warning(f"[Task {task.id}] Failed to upsert usage ledger: {ledger_error}")
