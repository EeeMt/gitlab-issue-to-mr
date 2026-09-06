"""Result parsing and finalization helpers for worker execution."""

import asyncio
import io
import json as _json
import logging
import os as _os
import re
import tarfile as _tarfile
import tempfile
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import WORKER_RUNTIME_ARCHIVE_MAX_BYTES
from app.core.change_stats import validate_change_statistics
from app.core.harness_protocol import (
    CANONICAL_RESULT_SCHEMA_V2,
    HarnessProtocolError,
    validate_result_v2,
)
from app.core.task_event_archive import archive_bundle_name
from app.core.task_failure_details import read_archived_harness_failure_detail
from app.core.usage_limits import upsert_task_usage_ledger
from app.core.utcnow import utcnow
from app.core.worker_git_delivery import normalize_git_delivery
from app.models import Issue, Task, TaskLog, TaskRunArchive, TaskStatus

logger = logging.getLogger(__name__)
_CONTAINER_RUNTIME_DIR = "/tmp/codify-runtime"
_ARCHIVE_STORE = "/opt/codify-archives"
_HARNESS_RESULT_MEMBER = "harness-result.json"

_THINK_BLOCK_RE = re.compile(r'<think\b[^>]*>.*?</think>', re.IGNORECASE | re.DOTALL)
_OPEN_THINK_RE = re.compile(r'<think\b[^>]*>', re.IGNORECASE)


class _IteratorReader(io.RawIOBase):
    """Expose Docker's chunk iterator as a bounded file-like stream."""

    def __init__(self, chunks) -> None:
        super().__init__()
        self._chunks = iter(chunks)
        self._pending = memoryview(b"")

    def readable(self) -> bool:
        return True

    def readinto(self, target) -> int:
        view = memoryview(target)
        written = 0
        while written < len(view):
            if not self._pending:
                try:
                    chunk = next(self._chunks)
                except StopIteration:
                    break
                if not chunk:
                    continue
                self._pending = memoryview(chunk)
            copied = min(len(view) - written, len(self._pending))
            view[written : written + copied] = self._pending[:copied]
            self._pending = self._pending[copied:]
            written += copied
        return written


def _stream_runtime_archive_from_container(
    container,
    *,
    container_path: str,
    archive_name: str,
    archive_store: str,
) -> tuple[str, int]:
    stream, _stat_info = container.get_archive(container_path)
    _os.makedirs(archive_store, exist_ok=True)
    final_path = _os.path.join(archive_store, archive_name)
    temp_file = tempfile.NamedTemporaryFile(
        mode="wb",
        dir=archive_store,
        prefix=f".{archive_name}.",
        suffix=".part",
        delete=False,
    )
    temp_path = temp_file.name
    try:
        with temp_file:
            with io.BufferedReader(_IteratorReader(stream)) as outer_stream:
                with _tarfile.open(fileobj=outer_stream, mode="r|") as outer_tar:
                    member = outer_tar.next()
                    if member is None or not member.isreg() or member.name != archive_name:
                        raise RuntimeError("Docker runtime archive response has an unexpected member")
                    if member.size > WORKER_RUNTIME_ARCHIVE_MAX_BYTES:
                        raise RuntimeError("Runtime archive exceeds the 640 MiB hard limit")
                    source = outer_tar.extractfile(member)
                    if source is None:
                        raise RuntimeError("Docker runtime archive member is unreadable")
                    copied = 0
                    while True:
                        chunk = source.read(1024 * 1024)
                        if not chunk:
                            break
                        copied += len(chunk)
                        if copied > WORKER_RUNTIME_ARCHIVE_MAX_BYTES:
                            raise RuntimeError("Runtime archive exceeds the 640 MiB hard limit")
                        temp_file.write(chunk)
                    if copied != member.size:
                        raise RuntimeError("Docker runtime archive member was truncated")
                    if outer_tar.next() is not None:
                        raise RuntimeError("Docker runtime archive response has extra members")
            temp_file.flush()
            _os.fsync(temp_file.fileno())
        _os.replace(temp_path, final_path)
        return final_path, copied
    except Exception:
        try:
            _os.remove(temp_path)
        except FileNotFoundError:
            pass
        raise


async def finalize_archive(*, task_id: int, container, db: AsyncSession) -> None:
    """Package the three runtime artifacts into an archive and record its metadata."""
    archive_name = archive_bundle_name(task_id=task_id)
    try:
        archive_store = "/opt/codify-archives"
        final_path, size = await asyncio.to_thread(
            _stream_runtime_archive_from_container,
            container,
            container_path=f"{_CONTAINER_RUNTIME_DIR}/{archive_name}",
            archive_name=archive_name,
            archive_store=archive_store,
        )
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
        logger.info(f"[Task {task.id}] Parsed MR IID from logs: !{parsed_mr_iid}")
    if parsed_mr_url:
        task._parsed_mr_url = parsed_mr_url
    if not parsed_mr_iid:
        logger.debug(f"[Task {task.id}] No MR IID found in container logs")


async def update_task_stats_from_logs_or_api(
    task: Task,
    logs: str,
    gitlab_client,
    issue: Issue | None = None,
    structured_diff: dict[str, Any] | None = None,
) -> None:
    """Update task with change statistics from logs or GitLab API."""
    if structured_diff:
        raw_additions = structured_diff.get("additions")
        raw_deletions = structured_diff.get("deletions")
        raw_total = structured_diff.get("total")
        if raw_additions is None and raw_deletions is None and raw_total is None:
            # Statistics could not be collected (e.g. missing blobs in a
            # partial clone): never persist fabricated zeros.
            logger.warning(
                f"[Task {task.id}] Change statistics were not collected; keeping existing stats"
            )
            return
        additions = int(raw_additions if raw_additions is not None else 0)
        deletions = int(raw_deletions if raw_deletions is not None else 0)
        total = int(raw_total if raw_total is not None else (additions + deletions))
        error = validate_change_statistics(additions, deletions, total)
        if error is not None:
            logger.warning(
                f"[Task {task.id}] Rejected change stats from structured log: {error}"
            )
            return
        task.additions = additions
        task.deletions = deletions
        task.total_changes = total
        task.change_stats_recorded_at = utcnow()
        logger.info(
            f"[Task {task.id}] Diff stats (from structured log): "
            f"+{task.additions} -{task.deletions} ({task.total_changes} total)"
        )
        return

    if task.commit_sha:
        mr_iid = (issue.merge_request_iid if issue else None) or getattr(task, '_parsed_mr_iid', None)
        if mr_iid:
            try:
                logger.info(f"[Task {task.id}] Getting MR stats for MR !{mr_iid}")
                stats = await gitlab_client.get_merge_request_stats(task.project_id, mr_iid)
                logger.info(f"[Task {task.id}] MR stats result: {stats}")
                if stats:
                    additions = int(stats.get("additions", 0))
                    deletions = int(stats.get("deletions", 0))
                    total = int(stats.get("total", 0))
                    error = validate_change_statistics(additions, deletions, total)
                    if error is not None:
                        logger.warning(
                            f"[Task {task.id}] Rejected change stats from API: {error}"
                        )
                        return
                    task.additions = additions
                    task.deletions = deletions
                    task.total_changes = total
                    task.change_stats_recorded_at = utcnow()
                    logger.info(
                        f"[Task {task.id}] MR stats (from API): "
                        f"+{task.additions} -{task.deletions} ({task.total_changes} total)"
                    )
                else:
                    logger.warning(f"[Task {task.id}] MR stats returned None")
            except Exception as e:
                logger.warning(f"[Task {task.id}] Failed to get MR stats: {e}")


def sanitize_commit_message(message: str) -> str:
    """Clean model-generated commit messages before persisting/displaying them."""
    if not message:
        return ""

    cleaned = _THINK_BLOCK_RE.sub("", message)
    cleaned = cleaned.strip()

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


def _read_archived_harness_result(task_id: int) -> dict[str, Any] | None:
    """Read the archived ``harness-result.json`` envelope, or None if absent."""
    archive_path = _os.path.join(_ARCHIVE_STORE, archive_bundle_name(task_id=task_id))
    if not _os.path.exists(archive_path):
        return None
    try:
        with _tarfile.open(archive_path, "r:gz") as archive:
            member = next(
                (item for item in archive.getmembers() if item.name == _HARNESS_RESULT_MEMBER),
                None,
            )
            if member is None:
                return None
            extracted = archive.extractfile(member)
            if extracted is None:
                return None
            parsed = _json.loads(extracted.read().decode("utf-8"))
            return parsed if isinstance(parsed, dict) else None
    except Exception as exc:  # noqa: BLE001
        logger.debug("[Task %s] V2 result archive read failed: %s", task_id, exc)
        return None


def _v2_result_validation_error(task_id: int) -> str:
    """Validate the archived V2 result envelope when present.

    Returns a ``protocol_error`` message when a ``codify.worker.result/v2``
    envelope exists but fails the frozen V2 contract, closing the "neither-nor"
    gap where a V2-shaped result could be accepted without ever being validated.
    Absent/unreadable archives are best-effort: they do not fail the task.
    """
    result = _read_archived_harness_result(task_id)
    if result is None or result.get("schema") != CANONICAL_RESULT_SCHEMA_V2:
        return ""
    try:
        validate_result_v2(result)
    except HarnessProtocolError as exc:
        return f"protocol_error: V2 result envelope rejected: {exc}"
    return ""


async def parse_task_result(
    task: Task,
    logs: str,
    db: AsyncSession,
    exit_code: int,
    sanitize_sensitive_data,
    gitlab_client,
    issue: Issue | None = None,
) -> None:
    """Apply the unique Canonical Task terminal and normalized projections."""
    run_result_meta = await _load_latest_log_metadata(db, task.id, "run_result")
    harness_result_meta = await _load_latest_log_metadata(db, task.id, "harness_result")
    usage_final_meta = await _load_latest_log_metadata(db, task.id, "usage_final")
    system_init_meta = await _load_latest_log_metadata(db, task.id, "system_init")
    finalization_meta = await _load_latest_log_metadata(db, task.id, "worker_finalization")
    v2_result_error = _v2_result_validation_error(task.id)

    usage = (
        usage_final_meta.get("usage")
        if isinstance(usage_final_meta.get("usage"), dict)
        else {}
    )
    if not usage and isinstance(run_result_meta.get("usage"), dict):
        # Read-only compatibility for task logs created before Runtime Bundles.
        usage = run_result_meta["usage"]
    if usage:
        task.input_tokens = usage.get('input_tokens')
        task.output_tokens = usage.get('output_tokens')
        logger.info(f"[Task {task.id}] Token usage: in={task.input_tokens} out={task.output_tokens}")

    model = str(system_init_meta.get('model') or '').strip()
    if model:
        task.model_name = model
        logger.info(f"[Task {task.id}] Model: {model}")

    # Validate the worker's git_delivery contract object (present only on new
    # Runtime Bundles). The normalized form is stashed on the task so the
    # container metadata merge cannot overwrite confirmed canonical facts.
    git_delivery_raw = finalization_meta.get("git_delivery")
    git_delivery = None
    git_delivery_error = ""
    if "git_delivery" in finalization_meta:
        if git_delivery_raw is None:
            git_delivery_error = "git_delivery must be an object"
        else:
            git_delivery, git_delivery_error = normalize_git_delivery(
                git_delivery_raw,
                task_id=task.id,
                sanitize_sensitive_data=sanitize_sensitive_data,
            )
            if git_delivery is not None:
                top_commit_sha = str(finalization_meta.get("commit_sha") or "").strip()
                if top_commit_sha and git_delivery.get("head_sha") != top_commit_sha:
                    git_delivery = None
                    git_delivery_error = (
                        "worker.finalization commit_sha projection does not match "
                        "git_delivery.head_sha"
                    )
        if git_delivery_error:
            logger.warning(
                f"[Task {task.id}] worker.finalization git_delivery rejected: {git_delivery_error}"
            )
    task._canonical_git_delivery = git_delivery

    commit_sha = str(finalization_meta.get("commit_sha") or "").strip()
    if commit_sha:
        task.commit_sha = commit_sha
        logger.info(f"[Task {task.id}] Commit SHA: {task.commit_sha}")

    raw_commit_message = str(finalization_meta.get("commit_message") or "").strip()
    if raw_commit_message:
        try:
            message = sanitize_commit_message(raw_commit_message)
            if message:
                task.commit_message = sanitize_sensitive_data(message)[:512]
                logger.info(f"[Task {task.id}] Commit message: {task.commit_message[:80]!r}")
        except Exception:
            logger.debug(f"[Task {task.id}] Failed to parse structured commit message")

    terminal_type = str(run_result_meta.get("type") or "")
    finalization_exit_code = finalization_meta.get("exit_code")
    if not terminal_type:
        task.status = TaskStatus.FAILED
        task.completed_at = utcnow()
        task.error_message = "protocol_error: canonical attempt is missing a Task terminal"
    elif terminal_type == "run.completed" and (
        exit_code != 0 or finalization_exit_code not in {None, 0}
    ):
        task.status = TaskStatus.FAILED
        task.completed_at = utcnow()
        task.error_message = (
            "protocol_error: run.completed conflicts with the worker process exit state"
        )
    elif terminal_type == "run.completed" and v2_result_error:
        task.status = TaskStatus.FAILED
        task.completed_at = utcnow()
        task.error_message = v2_result_error
    elif terminal_type == "run.completed" and git_delivery_error:
        # Contradictory delivery data must never decide a completed delivery:
        # fail the task through the existing protocol-error path instead.
        task.status = TaskStatus.FAILED
        task.completed_at = utcnow()
        task.error_message = (
            f"protocol_error: worker.finalization git_delivery rejected: {git_delivery_error}"
        )
    elif terminal_type == "run.completed":
        task.status = TaskStatus.COMPLETED
        task.completed_at = utcnow()
        await parse_mr_from_logs(task, logs, gitlab_client)
        if git_delivery is not None and isinstance(git_delivery.get("diff"), dict):
            contract_diff = git_delivery["diff"]
            stats = {
                key: contract_diff.get(key)
                for key in ("additions", "deletions", "total")
            }
            if (
                stats["additions"] is None
                and stats["deletions"] is None
                and stats["total"] is None
            ):
                stats = None  # uncollected: never zero-fill
            structured_diff = stats
        else:
            structured_diff = (
                finalization_meta.get("diff")
                if isinstance(finalization_meta.get("diff"), dict)
                else None
            )
        await update_task_stats_from_logs_or_api(task, logs, gitlab_client, issue, structured_diff)
    elif terminal_type == "run.failed":
        failure = run_result_meta.get("failure")
        failure_kind = str(failure.get("kind") or "") if isinstance(failure, dict) else ""
        terminal_status = str(run_result_meta.get("status") or "")
        task.status = (
            TaskStatus.CANCELLED
            if terminal_status == "cancelled" or failure_kind == "cancelled"
            else TaskStatus.FAILED
        )
        task.completed_at = utcnow()
        failure_message = ""
        if isinstance(failure, dict):
            failure_message = str(failure.get("message") or failure.get("kind") or "")
        if terminal_status == "protocol_error" or failure_kind == "protocol_error":
            failure_message = f"protocol_error: {failure_message or 'canonical attempt failed'}"
        archived_failure_detail = read_archived_harness_failure_detail(
            task.id,
            sanitize_sensitive_data,
        )
        if archived_failure_detail and failure_kind != "protocol_error" and terminal_status != "protocol_error":
            failure_message = archived_failure_detail
        task.error_message = sanitize_sensitive_data(
            failure_message or logs[-1000:] or "Harness task failed"
        )[-1000:]
    else:
        task.status = TaskStatus.FAILED
        task.completed_at = utcnow()
        task.error_message = f"protocol_error: unknown Task terminal {terminal_type!r}"

    extracted_session_id = str(
        harness_result_meta.get("session_id") or run_result_meta.get("session_id") or ""
    ).strip()
    if extracted_session_id:
        logger.info(f"[Task {task.id}] Extracted session ID: {extracted_session_id}")
        task.output_session_id = extracted_session_id
        task._extracted_session_id = extracted_session_id


async def try_upsert_usage_ledger(db: AsyncSession, task: Task) -> None:
    """Best-effort quota ledger persistence for already-finished tasks."""
    try:
        await upsert_task_usage_ledger(db, task)
    except Exception as ledger_error:
        logger.warning(f"[Task {task.id}] Failed to upsert usage ledger: {ledger_error}")
