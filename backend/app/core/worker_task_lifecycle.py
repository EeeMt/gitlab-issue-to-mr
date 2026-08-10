"""Task lifecycle helpers for WorkerExecutor."""

import asyncio
import json
import logging
import time
from datetime import datetime
from typing import Any

from docker.errors import NotFound
from gitlab import Gitlab
from sqlalchemy import delete, select
from sqlalchemy import inspect as sa_inspect
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.ci_failure_logs import append_ci_failure_log
from app.core.harness_attempts import create_task_attempt
from app.core.harness_sessions import (
    record_task_output_session,
    session_namespace_for,
)
from app.core.issue_task_lineage import (
    projection_for_task,
    record_projected_output_session,
    resolve_projected_resume_session,
)
from app.core.utcnow import utcnow
from app.core.worker_docker_targets import TaskContainerLookupError
from app.core.worker_profiles import load_task_worker_runtime
from app.core.worker_runtime import (
    TASK_SKILLS_CONTAINER_PATH,
    build_task_runtime_archive,
    capture_provider_runtime_snapshot,
    worker_custom_scripts_configured,
)
from app.core.worker_runtime_bundle import load_bound_runtime_bundle
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
_CONTAINER_RUNTIME_JSON = "/tmp/codify-runtime/runtime.json"


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


async def reconcile_task_input_session_from_runtime(
    worker,
    container: Any,
    task: Task,
) -> bool:
    """Replace the planned input session with the one actually used by the CLI wrapper."""
    try:
        raw_runtime = await asyncio.to_thread(
            worker.docker.read_file_from_container,
            container,
            _CONTAINER_RUNTIME_JSON,
        )
        if not isinstance(raw_runtime, (bytes, bytearray)):
            return False
        runtime = json.loads(bytes(raw_runtime).decode("utf-8"))
        if not isinstance(runtime, dict) or "resume_session" not in runtime:
            return False
        raw_resume_session = runtime["resume_session"]
        if not isinstance(raw_resume_session, str):
            return False
        actual_input_session_id = raw_resume_session.strip() or None
    except Exception as exc:  # noqa: BLE001
        logger.debug(
            "[Task %s] Could not reconcile runtime input session: %s",
            task.id,
            exc,
        )
        return False

    if getattr(task, "input_session_id", None) == actual_input_session_id:
        return False
    task.input_session_id = actual_input_session_id
    logger.info(
        "[Task %s] Reconciled input session from worker runtime (%s)",
        task.id,
        "resumed" if actual_input_session_id else "fresh",
    )
    return True


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
        raise RuntimeError("worker_workspace_host_path is required for issue workspaces")

    previous_task_summaries = (
        await worker._build_previous_task_summaries(db, issue, task) if issue else ""
    )

    runtime_bundle = await load_bound_runtime_bundle(db, task)
    # The harness is a per-Task choice frozen into the snapshot at creation;
    # never default to claude when the snapshot is loaded.
    harness_key = "claude"
    try:
        inspection = sa_inspect(task)
        if "worker_profile_snapshot" not in inspection.unloaded:
            harness_key = (
                getattr(task.worker_profile_snapshot, "harness_key", None) or "claude"
            )
    except Exception:  # noqa: BLE001
        harness_key = "claude"
    adapter_meta = (runtime_bundle.manifest.get("adapters") or {}).get(harness_key) or {}
    attempt = await create_task_attempt(
        db,
        task=task,
        harness_key=harness_key,
        adapter_version=str(adapter_meta.get("version") or "1.0.0"),
    )

    if worker_custom_scripts_configured(settings):
        logger.debug(
            "[Task %s] Ignoring legacy global worker scripts; using task worker snapshot",
            task_id,
        )
    is_ci_failure_task = (
        getattr(task, "trigger_source", None) == "ci_auto_repair"
        or getattr(task, "ci_failure_run_id", None) is not None
    )
    ci_failure_bundle_path = None
    if issue and is_ci_failure_task:
        run = await db.get(CIFailureRun, task.ci_failure_run_id) if task.ci_failure_run_id else None
        if run is None:
            raise RuntimeError("CI failure run is not available for this repair task")
        task.ci_failure_run = run
        ci_failure_bundle_path = run.bundle_path
        await append_ci_failure_log(
            db,
            run,
            step="bundle_materialized_for_worker",
            status="succeeded",
            message=f"Materialized CI failure bundle for task #{task.id}",
            task_id=task.id,
        )
        await db.flush()

    runtime_archive = build_task_runtime_archive(
        task,
        pre_script=worker_runtime.pre_script,
        post_script=worker_runtime.post_script,
        previous_task_summaries=previous_task_summaries,
        ci_failure_bundle_path=ci_failure_bundle_path,
        artifact_policy_settings=settings,
        skills=worker_runtime.skills,
    )

    session_mode = getattr(task, "session_mode", "continue")
    # Resolve the resume session through the Task's frozen projected lineage
    # (spec §5.5 / §6.8). A continue only resumes the exact
    # (issue, generation, harness, namespace) lineage row, or starts with no
    # resume ID (fresh_no_match); it never falls back to Issue.claude_session_id,
    # which may point at an older generation. A task without a complete
    # projection fails closed before a container is created.
    projection = projection_for_task(task)
    if projection is None:
        raise ValueError(
            f"Task {task.id} has no complete projected lineage; refusing to "
            "start without a fail-closed resume decision"
        )
    harness_key = projection["harness_key"]
    resume_session, input_lineage_reason = await resolve_projected_resume_session(
        db,
        task=task,
        harness_key=projection["harness_key"],
        session_namespace=projection["session_namespace"],
        generation=projection["generation"],
        reset_task_id=projection["reset_task_id"],
        session_mode=session_mode,
    )
    task.input_session_id = (
        resume_session if session_mode == "continue" and issue is not None else None
    )
    task.input_lineage_reason = input_lineage_reason
    # Mirror the resolved session to the legacy Claude pointer so the runtime
    # env builder and old readers keep working during the 068 compat window;
    # this is a compatibility write, not a resume-decision source.
    if issue is not None and harness_key == "claude" and resume_session:
        issue.claude_session_id = resume_session
    task.output_session_id = None
    # Record the exact session decision at execution time. Scheduled tasks must not snapshot
    # this at creation because earlier queued tasks may advance the Issue session first. The
    # existing container-id commit below persists these fields in the same transaction.

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
    environment.update(
        {
            "CODIFY_HARNESS_KEY": attempt.harness_key,
            "CODIFY_ADAPTER_VERSION": attempt.adapter_version,
            "CODIFY_ATTEMPT_ID": attempt.attempt_id,
            "CODIFY_RUNTIME_BUNDLE_DIGEST": runtime_bundle.digest,
            "CODIFY_RUNTIME_MANIFEST_DIGEST": str(
                runtime_bundle.manifest.get("archive_manifest_digest") or ""
            ),
            "CODIFY_RUNTIME_CONTRACT_VERSION": runtime_bundle.contract_version,
        }
    )
    if worker_runtime.skills:
        environment["CODIFY_TASK_SKILLS_DIR"] = TASK_SKILLS_CONTAINER_PATH
    sandbox_mode = None
    cli_binary_digest = None
    try:
        inspection = sa_inspect(task)
        if "worker_profile_snapshot" not in inspection.unloaded:
            frozen_snapshot = task.worker_profile_snapshot
            frozen_config = getattr(frozen_snapshot, "harness_config_snapshot", None)
            if isinstance(frozen_config, dict):
                sandbox_mode = frozen_config.get("sandbox_mode")
            cli_binary_digest = getattr(frozen_snapshot, "cli_binary_digest", None)
    except Exception:  # noqa: BLE001 - sandbox policy is advisory for old snapshots
        sandbox_mode = None
        cli_binary_digest = None
    if sandbox_mode:
        environment["CODIFY_HARNESS_SANDBOX_MODE"] = str(sandbox_mode)
    if resume_session and harness_key == "codex":
        environment["CODIFY_RESUME_SESSION"] = resume_session
    if cli_binary_digest:
        environment["CODIFY_CLI_BINARY_DIGEST"] = str(cli_binary_digest)
    # Persist the exact provider/session choices before the Docker side effect. If the
    # scheduler crashes after container creation, recovery can still report the runtime
    # configuration that was used to build the container environment.
    await db.commit()
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
    container = _create_stopped_container(
        worker,
        task,
        container_name,
        image=worker_runtime.image,
        command="",
        environment=environment,
        volumes=volumes if volumes else None,
        network=settings.worker_network,
        entrypoint=container_overrides["entrypoint"],
        user=container_overrides["user"],
        labels={
            "codify.task_id": str(task.id),
            "codify.worker_runtime_mode": worker_runtime.runtime_mode,
            "codify.worker_kit_version": worker_runtime.worker_kit_version or "",
            "codify.attempt_id": attempt.attempt_id,
            "codify.runtime_bundle_digest": runtime_bundle.digest,
        },
    )

    await _persist_created_container_reference(worker, db, task, container)
    if await finalize_pre_container_cancellation(db, task, phase="container start"):
        await _remove_created_container(worker, db, task, container)
        return None
    try:
        worker.docker.put_archive(container, "/tmp", runtime_bundle.bundle_bytes)
        worker.docker.put_archive(container, "/tmp", runtime_archive)
    except Exception:
        await _remove_created_container(worker, db, task, container)
        raise
    await _start_created_container(worker, db, task, container)
    return container


def _create_stopped_container(
    worker,
    task: Task,
    container_name: str,
    **create_kwargs: Any,
):
    """Create a stopped container and recover a timed-out successful response safely."""
    try:
        return worker.docker.create_container(
            **create_kwargs,
            name=container_name,
            start=False,
        )
    except Exception as create_error:
        try:
            container = worker.docker.client.containers.get(container_name)
        except NotFound:
            raise create_error
        except Exception as lookup_error:
            # The create request may have committed server-side. Leave the task
            # RUNNING so deferred recovery can resolve the stable task name later.
            raise TaskContainerLookupError(
                f"Container {container_name} creation outcome is unknown"
            ) from lookup_error

        labels = getattr(container, "labels", None)
        task_label = labels.get("codify.task_id") if isinstance(labels, dict) else None
        if getattr(container, "status", None) != "created" or task_label != str(task.id):
            raise create_error
        logger.warning(
            "[Task %s] Docker create returned an error, but stopped container %s "
            "exists with the expected owner label; continuing runtime upload",
            task.id,
            getattr(container, "id", container_name),
        )
        return container


async def _persist_created_container_reference(
    worker,
    db: AsyncSession,
    task: Task,
    container: Any,
) -> None:
    """Persist a new container ID or remove the otherwise unreachable container."""
    task_id = task.id
    task.container_id = container.id
    try:
        await db.commit()
    except Exception:
        try:
            await db.rollback()
        except Exception as rollback_error:  # noqa: BLE001
            logger.warning(
                "[Task %s] Failed to roll back container reference transaction: %s",
                task_id,
                rollback_error,
            )

        try:
            worker.docker.remove_container(container, force=True)
        except Exception as cleanup_error:  # noqa: BLE001
            raise TaskContainerLookupError(
                f"Could not clean up task {task_id} container after its reference "
                "failed to persist"
            ) from cleanup_error

        try:
            await db.refresh(task)
        except Exception as refresh_error:  # noqa: BLE001
            logger.warning(
                "[Task %s] Failed to refresh task after container cleanup: %s",
                task_id,
                refresh_error,
            )
        task.container_id = None
        raise


async def _remove_created_container(worker, db: AsyncSession, task: Task, container: Any) -> bool:
    """Remove an unstarted container and durably record that it has no raw logs."""
    task.raw_logs_finalized_at = getattr(task, "raw_logs_finalized_at", None) or utcnow()
    try:
        worker.docker.remove_container(container, force=True)
    except Exception:
        logger.warning(
            "[Task %s] Failed to remove unstarted container %s",
            task.id,
            getattr(container, "id", "unknown"),
            exc_info=True,
        )
        # Keep the reference so startup reconciliation can remove the container later,
        # but do not leave it looking like a container whose logs still need collection.
        await db.commit()
        return False

    task.container_id = None
    await db.commit()
    return True


async def _start_created_container(
    worker,
    db: AsyncSession,
    task: Task,
    container: Any,
) -> None:
    """Start a created container without guessing after an ambiguous Docker response."""
    try:
        worker.docker.start_container(container)
        return
    except Exception as start_error:
        try:
            container.reload()
        except NotFound:
            # The daemon conclusively says there is no container to monitor or collect
            # logs from. Clear the durable owner before reporting the start failure.
            task.container_id = None
            task.raw_logs_finalized_at = getattr(task, "raw_logs_finalized_at", None) or utcnow()
            await db.commit()
            raise start_error
        except Exception as lookup_error:
            # A timed-out start request may have succeeded server-side. Leave the task
            # RUNNING and retain its issue lock/reference until recovery can inspect it.
            raise TaskContainerLookupError(
                f"Container {getattr(container, 'id', 'unknown')} start outcome is unknown"
            ) from lookup_error

        status = getattr(container, "status", None)
        if status in ("running", "exited"):
            logger.warning(
                "[Task %s] Docker start returned an error, but container %s is %s; "
                "continuing with normal monitoring",
                task.id,
                getattr(container, "id", "unknown"),
                status,
            )
            return

        logger.warning(
            "[Task %s] Docker start failed and container %s is not runnable (status=%s)",
            task.id,
            getattr(container, "id", "unknown"),
            status,
        )
        if status == "created":
            await _remove_created_container(worker, db, task, container)
            raise start_error
        if status in {"dead", "removing"}:
            # It may have emitted launcher/bootstrap diagnostics before becoming
            # non-runnable. Keep the durable reference for terminal reconciliation.
            raise start_error
        raise TaskContainerLookupError(
            f"Container {getattr(container, 'id', 'unknown')} is not safely quiescent "
            f"after start failure (status={status})"
        ) from start_error


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
    if getattr(task, "container_id", None) is None:
        task.raw_logs_finalized_at = getattr(task, "raw_logs_finalized_at", None) or utcnow()
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
    except NotFound as e:
        return {
            "handled": True,
            "result": await fail_resume_missing_container(db, task, e),
        }
    except Exception as e:  # noqa: BLE001
        raise TaskContainerLookupError(
            f"Could not confirm resume container {container_name}: {e}"
        ) from e

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

    if timed_out:
        # The log stream hit task_timeout while the harness was still running.
        # Stop the container gracefully (TERM -> EXIT trap -> harness finalizer
        # flushes its canonical events) with a bounded grace, then force-kill
        # only if it does not exit in time. This leaves the workspace in a
        # consistent state instead of force-removing a mid-write container.
        try:
            await asyncio.to_thread(container.stop, timeout=15)
            logger.info(
                f"[Task {task.id}] Gracefully stopped container after log timeout{resume_prefix}"
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                f"[Task {task.id}] Graceful stop after log timeout failed: {exc}"
            )
            try:
                await asyncio.to_thread(container.kill)
            except Exception as kill_exc:  # noqa: BLE001
                logger.warning(
                    f"[Task {task.id}] Force kill after log timeout failed: {kill_exc}"
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
    input_session_reconciled = await reconcile_task_input_session_from_runtime(
        worker,
        container,
        task,
    )
    raw_logs_finalized = raw_logs_finalized or task.raw_logs_finalized_at is not None
    cancellation_requested = isinstance(
        getattr(task, "cancel_requested_at", None),
        datetime,
    )
    if issue:
        await db.refresh(issue)

    # The canonical terminal is authoritative. Parse it first so a persisted
    # cancellation intent never downgrades a run that actually completed (the
    # cancel request can land after the container already exited with success).
    await worker._parse_task_result(task, logs, db, exit_code, issue=issue)
    if exit_code == 0:
        await _save_delivery_summary_from_container(worker, container, task, db)

    if (
        task.status == TaskStatus.CANCELLED or cancellation_requested
    ) and task.status != TaskStatus.COMPLETED and not timed_out:
        if task.status != TaskStatus.CANCELLED:
            task.status = TaskStatus.CANCELLED
            task.completed_at = task.completed_at or utcnow()
            task.error_message = "Cancelled by user"
            await db.commit()
            logger.info(
                "[Task %s] Applied persisted cancellation intent during worker finalization",
                task.id,
            )
        elif input_session_reconciled:
            await db.commit()
        if issue:
            issue.workspace_last_used_at = utcnow()
            issue.workspace_delete_attempted_at = None
            issue.workspace_deleted_at = None
            issue.workspace_delete_error = None
        if raw_logs_finalized:
            logger.info(f"[Task {task.id}] Task was cancelled during execution; removing container")
            try:
                worker.docker.remove_container(container, force=True)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "[Task %s] Failed to remove cancelled container%s: %s",
                    task.id,
                    resume_prefix,
                    exc,
                )
            else:
                task.container_id = None
        else:
            logger.error(
                f"[Task {task.id}] Retaining cancelled task container because raw logs "
                "were not finalized"
            )
        await db.commit()
        return False

    if cancellation_requested:
        logger.info(
            "[Task %s] Cancellation intent arrived after the run had already completed; "
            "keeping COMPLETED",
            task.id,
        )

    output_session_id = getattr(task, "output_session_id", None)
    if issue and isinstance(output_session_id, str) and output_session_id:
        # The session returned by the task is the only safe pointer for subsequent work. This
        # also covers fresh runs and the CLI wrapper's resume-not-found fallback.
        # Record it into the Task's projected lineage row first (spec §6.8); rows without a
        # projection (legacy 068 rows) are only mirrored to the IssueHarnessSession compat
        # table. Bookkeeping must never break completion.
        if projection_for_task(task) is not None:
            try:
                await record_projected_output_session(
                    db,
                    task=task,
                    session_id=output_session_id,
                )
            except Exception as exc:  # noqa: BLE001 - never break completion on lineage bookkeeping
                logger.warning(
                    "[Task %s] Failed to record projected output session: %s",
                    task.id,
                    exc,
                )
        # Resolve the frozen harness key first so a codex task's session is never
        # recorded under the claude lineage (which would break codex resume).
        harness_key = "claude"
        endpoint_fingerprint = None
        try:
            inspection = sa_inspect(task)
            if "worker_profile_snapshot" in inspection.unloaded:
                await db.refresh(task, attribute_names=["worker_profile_snapshot"])
            snapshot = task.worker_profile_snapshot
            harness_key = getattr(snapshot, "harness_key", None) or "claude"
            if isinstance(getattr(snapshot, "model_endpoint_snapshot", None), dict):
                endpoint_fingerprint = snapshot.model_endpoint_snapshot.get("fingerprint")
        except Exception:  # noqa: BLE001 - session bookkeeping must never break completion
            harness_key = "claude"
        await record_task_output_session(
            db,
            issue=issue,
            harness_key=harness_key,
            session_namespace=session_namespace_for(harness_key, endpoint_fingerprint),
            session_id=output_session_id,
        )
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
        # Timeout is the authoritative outcome: the graceful stop we issued above
        # may have let the harness emit a `cancelled` terminal, but a wall-clock
        # timeout is a FAILED task, never a user cancellation.
        task.status = TaskStatus.FAILED
        task.completed_at = task.completed_at or utcnow()
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
        sanitized_failure_logs = worker._sanitize_sensitive_data(logs)
        if len(sanitized_failure_logs) > 16_000:
            sanitized_failure_logs = (
                sanitized_failure_logs[:8_000]
                + "\n...[failure output truncated]...\n"
                + sanitized_failure_logs[-8_000:]
            )
        task.error_message = sanitized_failure_logs
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

    if issue:
        issue.workspace_last_used_at = utcnow()
        issue.workspace_delete_attempted_at = None
        issue.workspace_deleted_at = None
        issue.workspace_delete_error = None
    await worker._try_upsert_usage_ledger(db, task)
    await db.commit()

    # Pull task-metadata.json from the container filesystem via the Docker API before
    # removing the container. This keeps result metadata in the database even when the
    # Docker daemon and its workspace live on another host.
    if issue:
        _save_task_metadata_from_container(worker, container, task, issue)
        await db.commit()

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
            task.container_id = None
            await db.commit()
    else:
        logger.error(
            f"[Task {task.id}] Retaining task container because raw logs were not finalized"
        )

    return exit_code == 0
