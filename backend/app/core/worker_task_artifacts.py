"""Live and final artifact handling for worker task runs."""

import asyncio
import json
import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.task_log_payloads import create_payload, persist_raw_log_snapshot
from app.core.utcnow import utcnow
from app.models import Task, TaskLog

logger = logging.getLogger(__name__)

_CONTAINER_METADATA_PATH = "/tmp/codify-runtime/task-metadata.json"
_CONTAINER_DELIVERY_SUMMARY_PATH = "/tmp/codify-runtime/delivery-summary.md"
_CONTAINER_DELIVERY_SUMMARY_VALIDATION_PATH = "/tmp/codify-runtime/delivery-summary-validation.json"
_CONTAINER_CONSOLE_LOG_PATH = "/tmp/codify-runtime/console.log"
_ARTIFACT_POLLER_STOP_TIMEOUT_SECONDS = 3.0


async def _stop_artifact_poller(
    *,
    task_id: int,
    stop_event: asyncio.Event,
    poll_task: asyncio.Task,
    resume_prefix: str = "",
    timeout: float = _ARTIFACT_POLLER_STOP_TIMEOUT_SECONDS,
) -> None:
    """Stop the live artifact poller without letting it block finalization."""
    stop_event.set()
    done, _pending = await asyncio.wait({poll_task}, timeout=timeout)
    if poll_task in done:
        try:
            await poll_task
        except asyncio.CancelledError:
            pass
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                f"[Task {task_id}] Artifact poller stopped with error{resume_prefix}: {exc}"
            )
        return

    logger.warning(
        f"[Task {task_id}] Artifact poller did not stop within {timeout:.0f}s; "
        f"cancelling{resume_prefix}"
    )
    poll_task.cancel()
    try:
        await poll_task
    except asyncio.CancelledError:
        pass
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            f"[Task {task_id}] Artifact poller cancel finished with error{resume_prefix}: {exc}"
        )


def _build_delivery_summary_preview(text: str, limit: int = 120) -> tuple[str, bool]:
    normalized = " ".join(text.split())
    return normalized[:limit], len(normalized) > limit


async def save_delivery_summary_from_container(
    worker,
    container: Any,
    task: Task,
    db: AsyncSession,
) -> None:
    """Persist Codify's final delivery summary separately from assistant text."""
    try:
        raw = worker.docker.read_file_from_container(
            container,
            _CONTAINER_DELIVERY_SUMMARY_PATH,
        )
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
    except Exception as exc:  # noqa: BLE001
        logger.warning(f"[Task {task.id}] Could not persist delivery summary: {exc}")


def save_task_metadata_from_container(
    worker,
    container: Any,
    task: Task,
    issue: Any,
) -> None:
    """Extract task-metadata.json via the Docker API and persist it on the Task row."""
    try:
        raw = worker.docker.read_file_from_container(container, _CONTAINER_METADATA_PATH)
        if not raw:
            logger.info(
                f"[Task {task.id}] task-metadata.json could not be read from container at "
                f"{_CONTAINER_METADATA_PATH!r} — file may not exist yet or container may be "
                "in an inaccessible state; metadata will be omitted from MR description"
            )
            return

        data = json.loads(raw)
        if not isinstance(data, dict):
            logger.warning(
                f"[Task {task.id}] task-metadata.json in container is not a JSON object, skipping"
            )
            return

        # The canonical finalization is authoritative for git_delivery. The
        # container file is a stale-able copy (written before the canonical
        # finalizer ran); it may enrich summaries but must never overwrite
        # confirmed canonical delivery facts with an older snapshot.
        canonical = getattr(task, "_canonical_git_delivery", None)
        artifact_git_delivery = data.get("git_delivery")
        if canonical is not None:
            data["git_delivery"] = canonical
        elif isinstance(artifact_git_delivery, dict):
            from app.core.worker_git_delivery import normalize_git_delivery

            sanitizer = getattr(worker, "_sanitize_sensitive_data", None)
            normalized, error = normalize_git_delivery(
                artifact_git_delivery,
                task_id=task.id,
                sanitize_sensitive_data=sanitizer if callable(sanitizer) else (lambda value: value),
            )
            if error:
                logger.warning(
                    f"[Task {task.id}] Discarding invalid task-metadata git_delivery: {error}"
                )
                data.pop("git_delivery", None)
            else:
                data["git_delivery"] = normalized
        task.worker_metadata = data
        logger.info(f"[Task {task.id}] task-metadata.json persisted on task row")
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            f"[Task {task.id}] Could not extract task-metadata.json from container: {exc}"
        )


async def poll_task_artifacts(
    worker,
    *,
    task: Task,
    container: Any,
    session_factory,
    stop: asyncio.Event,
    resume_prefix: str,
) -> None:
    """Continuously persist live task artifacts without holding the main session."""
    while not stop.is_set():
        try:
            async with session_factory() as poll_db:
                await worker._tail_event_jsonl(
                    task_id=task.id,
                    container=container,
                    db=poll_db,
                )
                await worker._tail_console_log(
                    task_id=task.id,
                    container=container,
                    db=poll_db,
                )
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"[Task {task.id}] artifact poll error{resume_prefix}: {exc}")
        await asyncio.sleep(2)


async def finalize_task_raw_logs(
    worker,
    *,
    task: Task,
    container: Any,
    session_factory,
) -> None:
    """Persist the authoritative raw console log and mark it finalized."""
    async with session_factory() as artifact_db:
        raw_console_log = await asyncio.to_thread(
            worker.docker.read_file_from_container,
            container,
            _CONTAINER_CONSOLE_LOG_PATH,
        )
        if not isinstance(raw_console_log, bytes):
            # The launcher or image entrypoint can fail before bootstrap creates
            # console.log. Docker's captured stdout/stderr is then the only durable
            # source and must be persisted so the failed container can still be reaped.
            raw_console_log = await asyncio.to_thread(
                worker.docker.get_container_logs,
                container,
            )
        if not isinstance(raw_console_log, bytes):
            raise RuntimeError(
                f"Could not read {_CONTAINER_CONSOLE_LOG_PATH} or Docker logs "
                "from task container"
            )
        await persist_raw_log_snapshot(
            artifact_db,
            task_id=task.id,
            content=raw_console_log,
        )
        artifact_task = await artifact_db.get(Task, task.id)
        if artifact_task is None:
            raise RuntimeError(f"Task {task.id} disappeared during raw-log finalization")
        artifact_task.raw_logs_finalized_at = utcnow()
        await artifact_db.commit()


async def flush_task_artifacts(
    worker,
    *,
    task: Task,
    container: Any,
    session_factory,
) -> None:
    """Flush event, archive, and archive-derived log artifacts once."""
    async with session_factory() as artifact_db:
        try:
            await worker._tail_event_jsonl(
                task_id=task.id,
                container=container,
                db=artifact_db,
            )
        except Exception as exc:  # noqa: BLE001
            # Docker rejects exec calls after a container has stopped. The
            # stopped container can still serve get_archive, so preserve that
            # authoritative fallback and replay event.jsonl from it below.
            logger.warning(
                "[Task %s] Could not tail final canonical events; "
                "continuing with runtime archive: %s",
                task.id,
                exc,
            )
        await worker._finalize_archive(
            task_id=task.id,
            container=container,
            db=artifact_db,
        )
        await worker._backfill_console_log_from_archive(
            task_id=task.id,
            db=artifact_db,
        )
        await worker._backfill_event_jsonl_from_archive(
            task_id=task.id,
            db=artifact_db,
        )
