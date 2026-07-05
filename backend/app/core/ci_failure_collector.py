"""Durable GitLab CI failure collection and auto-repair task creation."""

from __future__ import annotations

import asyncio
import json
import logging
import re
import uuid
from datetime import timedelta
from pathlib import Path
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_effective_settings
from app.core.ci_failure_logs import append_ci_failure_log
from app.core.gitlab_client import get_gitlab_client
from app.core.projects import get_project_metadata
from app.core.task_creation import prepare_task_runtime_snapshot
from app.core.task_prompt import render_and_store_task_prompt
from app.core.utcnow import utcnow
from app.core.worker_profiles import (
    WorkerProfileValidationError,
    replace_task_worker_snapshot,
    resolve_provider_for_issue,
    resolve_worker_profile_for_issue,
    select_snapshot_run_instruction_template,
)
from app.core.worker_workspace import configured_workspace_root
from app.database import AsyncSessionLocal
from app.models import (
    CIFailureJob,
    CIFailureRun,
    Issue,
    Task,
    TaskStatus,
    WebhookEvent,
)
from app.runtime_config import refresh_runtime_config_if_stale

logger = logging.getLogger(__name__)

CI_AUTO_REPAIR_DISPLAY_PROMPT = "修复当前 MR 的 CI 失败"

INFRA_FAILURE_REASONS = {
    "runner_system_failure",
    "stuck_or_timeout_failure",
    "scheduler_failure",
    "api_failure",
    "missing_dependency_failure",
    "runner_unsupported",
    "data_integrity_failure",
}

INFRA_TRACE_KEYWORDS = (
    "no runners available",
    "runner system failure",
    "stuck",
    "timeout waiting for runner",
    "cannot pull image",
    "image pull back-off",
    "tls handshake timeout",
    "connection reset",
    "temporary failure in name resolution",
    "service unavailable",
    "rate limit exceeded",
    "docker daemon unavailable",
)

CODE_TRACE_KEYWORDS = (
    "assert",
    "build failed",
    "compilation failed",
    "eslint",
    "failed test",
    "npm test",
    "pytest",
    "ruff",
    "traceback",
    "type error",
)

MAX_TRACE_BYTES = 5 * 1024 * 1024


def _value(obj: Any, key: str, default: Any = None) -> Any:
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _int_value(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _sort_key(job: dict[str, Any]) -> tuple[str, str, int]:
    return (
        str(job.get("started_at") or ""),
        str(job.get("created_at") or ""),
        int(job.get("id") or 0),
    )


def select_root_cause_jobs(jobs: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Select root-cause jobs using the MVP first-failed-stage strategy."""
    failed = [
        job for job in jobs
        if str(job.get("status")) == "failed" and bool(job.get("allow_failure")) is False
    ]
    if not failed:
        return [], []
    failed.sort(key=_sort_key)
    root_stage = failed[0].get("stage")
    root = [job for job in failed if job.get("stage") == root_stage]
    suppressed = [job for job in failed if job.get("stage") != root_stage]
    return root, suppressed


def sanitize_ci_trace(text: str) -> tuple[str, int]:
    """Redact secrets from CI logs before bundle storage."""
    redactions = 0

    def replace(pattern: str, value: str) -> str:
        nonlocal redactions
        next_value, count = re.subn(pattern, "[REDACTED]", value, flags=re.IGNORECASE)
        redactions += count
        return next_value

    text = replace(r"glpat-[a-zA-Z0-9\-]{6,}", text)
    text = replace(r"sk-(?:cp|ant|api)-[a-zA-Z0-9\-]{6,}", text)
    text = replace(r"(PRIVATE-TOKEN:\s*)[^\s]+", text)
    text = text.replace("\x00", "")
    return text, redactions


def trim_trace(text: str, limit: int = MAX_TRACE_BYTES) -> str:
    encoded = text.encode("utf-8", errors="replace")
    if len(encoded) <= limit:
        return text
    half = limit // 2
    head = encoded[:half].decode("utf-8", errors="ignore")
    tail = encoded[-half:].decode("utf-8", errors="ignore")
    return f"{head}\n\n[... CI trace truncated ...]\n\n{tail}"


def classify_failure(job: dict[str, Any], trace: str | None = None) -> str:
    reason = str(job.get("failure_reason") or "")
    if reason in INFRA_FAILURE_REASONS:
        return "infra"
    if reason == "script_failure":
        return "code"

    lower_trace = (trace or "").lower()
    has_infra_keyword = any(keyword in lower_trace for keyword in INFRA_TRACE_KEYWORDS)
    has_code_keyword = any(keyword in lower_trace for keyword in CODE_TRACE_KEYWORDS)
    if has_infra_keyword and not has_code_keyword:
        return "infra"
    return "unknown"


def _safe_job_log_name(job: dict[str, Any]) -> str:
    raw_name = str(job.get("name") or "job")
    safe_name = re.sub(r"[^a-zA-Z0-9_.-]+", "-", raw_name).strip("-") or "job"
    return f"{int(job['id'])}-{safe_name}.log"


def _bundle_root(settings: Any, run_id: int) -> Path:
    root = configured_workspace_root(settings)
    if root is None:
        raise RuntimeError("worker_workspace_host_path is required for CI failure bundles")
    return Path(root) / "ci-failures" / str(run_id)


async def _ignore_run(
    db: AsyncSession,
    run: CIFailureRun,
    *,
    reason: str,
    step: str,
    message: str,
    details: dict[str, Any] | None = None,
) -> None:
    run.status = "ignored"
    run.ignored_reason = reason
    await append_ci_failure_log(
        db,
        run,
        step=step,
        status="skipped",
        message=message,
        details={"ignored_reason": reason, **(details or {})},
    )
    await db.commit()


async def _match_issue(db: AsyncSession, run: CIFailureRun, mr_details: Any | None) -> Issue | None:
    if run.merge_request_iid is not None:
        result = await db.execute(
            select(Issue).where(
                Issue.project_id == run.project_id,
                Issue.merge_request_iid == run.merge_request_iid,
            )
        )
        issue = result.scalars().first()
        if issue:
            return issue

    source_branch = run.source_branch or _value(mr_details, "source_branch")
    if source_branch:
        result = await db.execute(
            select(Issue).where(
                Issue.project_id == run.project_id,
                Issue.branch_name == source_branch,
            )
        )
        issues = result.scalars().all()
        if len(issues) == 1:
            return issues[0]

    if run.pipeline_ref:
        result = await db.execute(
            select(Issue).where(
                Issue.project_id == run.project_id,
                Issue.branch_name == run.pipeline_ref,
            )
        )
        issues = result.scalars().all()
        if len(issues) == 1:
            return issues[0]
    return None


async def _count_ci_auto_repair_attempts(db: AsyncSession, issue_id: int) -> tuple[int, dict[str, Any]]:
    reset_row = (
        await db.execute(
            select(Task.id, Task.completed_at)
            .where(
                Task.issue_id == issue_id,
                Task.trigger_source == "manual",
                Task.task_mode == "execute",
                Task.status == TaskStatus.COMPLETED,
                Task.completed_at.is_not(None),
            )
            .order_by(Task.completed_at.desc(), Task.id.desc())
            .limit(1)
        )
    ).first()

    query = select(func.count(Task.id)).where(
        Task.issue_id == issue_id,
        Task.trigger_source == "ci_auto_repair",
    )
    details: dict[str, Any] = {}
    if reset_row is not None:
        reset_task_id, reset_at = reset_row
        query = query.where(Task.created_at > reset_at)
        details = {
            "reset_after_task_id": reset_task_id,
            "reset_after_completed_at": reset_at.isoformat() if reset_at else None,
        }

    return int(await db.scalar(query) or 0), details


async def process_ci_failure_run(
    db: AsyncSession,
    run_id: int,
    *,
    gitlab_client: Any,
    settings: Any,
    collector_id: str,
) -> CIFailureRun:
    """Process one persisted CI failure run and create a repair task when all gates pass."""
    run = await db.get(CIFailureRun, run_id)
    if run is None:
        raise ValueError(f"CI failure run {run_id} not found")
    if run.repair_task_id is not None:
        return run

    run.locked_by = collector_id
    run.locked_at = utcnow()
    run.collection_attempts += 1
    await append_ci_failure_log(
        db,
        run,
        step="webhook_received",
        status="succeeded",
        details={"pipeline_id": run.pipeline_id, "pipeline_status": run.pipeline_status},
    )
    await db.flush()

    try:
        mr_details = None
        if run.merge_request_iid is not None:
            mr_details = gitlab_client.get_merge_request_details(run.project_id, run.merge_request_iid)

        issue = await _match_issue(db, run, mr_details)
        if issue is None:
            await _ignore_run(
                db,
                run,
                reason="no_match",
                step="issue_matched",
                message="No Codify issue matched the failed pipeline",
            )
            return run

        run.issue_id = issue.id
        run.source_branch = run.source_branch or issue.branch_name or _value(mr_details, "source_branch")
        run.target_branch = run.target_branch or issue.target_branch or _value(mr_details, "target_branch")
        if run.webhook_event_id:
            event = await db.get(WebhookEvent, run.webhook_event_id)
            if event is not None:
                event.issue_id = issue.id
        await append_ci_failure_log(
            db,
            run,
            step="issue_matched",
            status="succeeded",
            details={"issue_id": issue.id, "mr_iid": run.merge_request_iid},
        )

        if not issue.ci_auto_repair_enabled:
            await _ignore_run(
                db,
                run,
                reason="ci_auto_repair_disabled",
                step="auto_repair_gate_checked",
                message="Issue has CI auto-repair disabled",
                details={"enabled": False},
            )
            return run

        attempts, attempt_details = await _count_ci_auto_repair_attempts(db, issue.id)
        max_attempts = int(getattr(settings, "ci_auto_repair_max_attempts", 2))
        if attempts >= max_attempts:
            await _ignore_run(
                db,
                run,
                reason="max_attempts_exceeded",
                step="auto_repair_gate_checked",
                message="CI auto-repair attempt limit reached",
                details={"attempts": attempts, "max_attempts": max_attempts, **attempt_details},
            )
            return run
        await append_ci_failure_log(
            db,
            run,
            step="auto_repair_gate_checked",
            status="succeeded",
            details={"enabled": True, "attempts": attempts, "max_attempts": max_attempts, **attempt_details},
        )

        active_task = (
            await db.execute(
                select(Task).where(
                    Task.issue_id == issue.id,
                    Task.task_mode == "execute",
                    Task.status.in_([TaskStatus.PENDING, TaskStatus.QUEUED, TaskStatus.RUNNING]),
                )
            )
        ).scalars().first()
        if active_task is not None:
            await _ignore_run(
                db,
                run,
                reason="active_execute_task_exists",
                step="active_task_checked",
                message=f"Active execute task #{active_task.id} exists",
                details={"task_id": active_task.id},
            )
            return run
        await append_ci_failure_log(
            db,
            run,
            step="active_task_checked",
            status="succeeded",
            details={"active_execute_task": False},
        )

        mr_source_branch = _value(mr_details, "source_branch")
        matched_by_ref = not run.merge_request_iid and run.pipeline_ref and run.pipeline_ref == issue.branch_name
        if not issue.branch_name or (not matched_by_ref and not run.merge_request_iid) or (mr_source_branch and mr_source_branch != issue.branch_name):
            await _ignore_run(
                db,
                run,
                reason="mr_branch_invariant_failed",
                step="pipeline_freshness_checked",
                message="MR branch invariant failed",
                details={"issue_branch": issue.branch_name, "mr_source_branch": mr_source_branch},
            )
            return run

        latest_pipeline = _value(mr_details, "current_pipeline")
        if latest_pipeline is None and run.merge_request_iid is not None:
            latest_pipeline = gitlab_client.get_merge_request_latest_pipeline(
                run.project_id,
                run.merge_request_iid,
            )
        latest_pipeline_id = _int_value(_value(latest_pipeline, "id"))
        if latest_pipeline_id is not None and latest_pipeline_id != run.pipeline_id:
            await _ignore_run(
                db,
                run,
                reason="stale_pipeline",
                step="pipeline_freshness_checked",
                message="Failed pipeline is no longer the latest MR pipeline",
                details={
                    "pipeline_id": run.pipeline_id,
                    "latest_pipeline_id": latest_pipeline_id,
                    "pipeline_sha": run.pipeline_sha,
                    "latest_pipeline_sha": _value(latest_pipeline, "sha"),
                },
            )
            return run
        await append_ci_failure_log(
            db,
            run,
            step="pipeline_freshness_checked",
            status="succeeded",
            details={
                "latest_pipeline_matches": latest_pipeline_id == run.pipeline_id
                if latest_pipeline_id is not None
                else None,
                "pipeline_id": run.pipeline_id,
                "latest_pipeline_id": latest_pipeline_id,
                "pipeline_sha": run.pipeline_sha,
                "latest_pipeline_sha": _value(latest_pipeline, "sha"),
            },
        )

        jobs = list(gitlab_client.get_pipeline_jobs(run.project_id, run.pipeline_id))
        failed_count = len([job for job in jobs if str(job.get("status")) == "failed"])
        await append_ci_failure_log(
            db,
            run,
            step="jobs_listed",
            status="succeeded",
            details={"total": len(jobs), "failed": failed_count},
        )
        root_jobs, suppressed_jobs = select_root_cause_jobs(jobs)
        await append_ci_failure_log(
            db,
            run,
            step="root_cause_jobs_selected",
            status="succeeded",
            details={
                "strategy": "first_failed_stage",
                "root_jobs": [job.get("id") for job in root_jobs],
                "suppressed_jobs": [job.get("id") for job in suppressed_jobs],
            },
        )

        for job in suppressed_jobs:
            db.add(
                CIFailureJob(
                    ci_failure_run_id=run.id,
                    gitlab_job_id=int(job["id"]),
                    name=str(job.get("name") or job["id"]),
                    stage=job.get("stage"),
                    status=str(job.get("status") or "failed"),
                    failure_reason=job.get("failure_reason"),
                    allow_failure=bool(job.get("allow_failure")),
                    web_url=job.get("web_url"),
                    is_root_cause=False,
                    is_downstream_suppressed=True,
                    classification=classify_failure(job),
                )
            )

        root_classifications = [classify_failure(job) for job in root_jobs]
        if root_jobs and all(classification == "infra" for classification in root_classifications):
            for job, classification in zip(root_jobs, root_classifications):
                db.add(
                    CIFailureJob(
                        ci_failure_run_id=run.id,
                        gitlab_job_id=int(job["id"]),
                        name=str(job.get("name") or job["id"]),
                        stage=job.get("stage"),
                        status=str(job.get("status") or "failed"),
                        failure_reason=job.get("failure_reason"),
                        allow_failure=bool(job.get("allow_failure")),
                        web_url=job.get("web_url"),
                        is_root_cause=True,
                        classification=classification,
                    )
                )
            await _ignore_run(
                db,
                run,
                reason="infra_failure_detected",
                step="failure_classified",
                message="Root-cause CI failures look infrastructure-related",
                details={"classification": "infra"},
            )
            return run

        bundle_path = _bundle_root(settings, run.id)
        jobs_path = bundle_path / "jobs"
        jobs_path.mkdir(parents=True, exist_ok=True)
        await append_ci_failure_log(
            db,
            run,
            step="failure_classified",
            status="succeeded",
            details={"classifications": root_classifications},
        )

        root_metadata: list[dict[str, Any]] = []
        suppressed_metadata: list[dict[str, Any]] = []
        for job, classification in zip(root_jobs, root_classifications):
            trace = gitlab_client.get_job_trace(run.project_id, int(job["id"]))
            trace = trace.decode("utf-8", errors="replace") if isinstance(trace, bytes) else str(trace)
            await append_ci_failure_log(
                db,
                run,
                step="trace_downloaded",
                status="succeeded",
                details={"job_id": int(job["id"]), "bytes": len(trace.encode("utf-8"))},
            )
            sanitized, redactions = sanitize_ci_trace(trim_trace(trace))
            file_name = _safe_job_log_name(job)
            trace_rel = f"jobs/{file_name}"
            trace_abs = jobs_path / file_name
            trace_abs.write_text(sanitized, encoding="utf-8")
            stored_size = trace_abs.stat().st_size
            await append_ci_failure_log(
                db,
                run,
                step="trace_sanitized",
                status="succeeded",
                details={"job_id": int(job["id"]), "redactions": redactions, "stored_bytes": stored_size},
            )
            job_row = CIFailureJob(
                ci_failure_run_id=run.id,
                gitlab_job_id=int(job["id"]),
                name=str(job.get("name") or job["id"]),
                stage=job.get("stage"),
                status=str(job.get("status") or "failed"),
                failure_reason=job.get("failure_reason"),
                allow_failure=bool(job.get("allow_failure")),
                web_url=job.get("web_url"),
                trace_path=trace_rel,
                trace_size_bytes=stored_size,
                is_root_cause=True,
                classification=classification,
            )
            db.add(job_row)
            root_metadata.append(_job_metadata(job, classification, trace_rel))

        for job in suppressed_jobs:
            suppressed_metadata.append(_job_metadata(job, classify_failure(job), None))

        (bundle_path / "pipeline.json").write_text(
            json.dumps(
                {
                    "project_id": run.project_id,
                    "merge_request_iid": run.merge_request_iid,
                    "pipeline_id": run.pipeline_id,
                    "pipeline_sha": run.pipeline_sha,
                    "pipeline_ref": run.pipeline_ref,
                    "pipeline_url": run.pipeline_url,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        (bundle_path / "failed-jobs.json").write_text(
            json.dumps(
                {
                    "root_cause_strategy": "first_failed_stage",
                    "root_cause_jobs": root_metadata,
                    "downstream_suppressed_jobs": suppressed_metadata,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        run.bundle_path = str(bundle_path)
        run.status = "collected"
        await append_ci_failure_log(
            db,
            run,
            step="bundle_written",
            status="succeeded",
            details={"path": str(bundle_path)},
        )

        latest_task = (
            await db.execute(
                select(Task)
                .where(
                    Task.issue_id == issue.id,
                    Task.task_mode == "execute",
                    Task.status == TaskStatus.COMPLETED,
                )
                .order_by(Task.completed_at.desc().nullslast(), Task.created_at.desc())
            )
        ).scalars().first()
        priority = latest_task.priority if latest_task else 0
        try:
            worker_profile = await resolve_worker_profile_for_issue(
                db,
                issue,
                None,
                allow_system_default=False,
            )
            provider = await resolve_provider_for_issue(
                db,
                issue,
                None,
                allow_system_default=False,
            )
        except WorkerProfileValidationError as exc:
            raise RuntimeError(f"CI auto-repair cannot start: {exc}") from exc

        repair_task = Task(
            issue_id=issue.id,
            project_id=issue.project_id,
            user_prompt=CI_AUTO_REPAIR_DISPLAY_PROMPT,
            initiator_user_id=issue.initiator_user_id,
            initiator_username=issue.initiator_username,
            priority=priority,
            provider_id=provider.id,
            worker_profile_id=worker_profile.id,
            task_mode="execute",
            require_changes=True,
            trigger_source="ci_auto_repair",
            ci_failure_run_id=run.id,
        )
        db.add(repair_task)
        await db.flush()
        await prepare_task_runtime_snapshot(
            db,
            repair_task,
            issue,
            worker_profile,
            await get_project_metadata(issue.project_id),
            run_instruction_template=None,
            template_trigger_source="ci_auto_repair",
            replace_snapshot=replace_task_worker_snapshot,
            select_template=select_snapshot_run_instruction_template,
            render_prompt=render_and_store_task_prompt,
        )
        run.repair_task_id = repair_task.id
        run.status = "task_created"
        await append_ci_failure_log(
            db,
            run,
            step="repair_task_created",
            status="succeeded",
            message=f"Created CI repair task #{repair_task.id}",
            details={"task_id": repair_task.id},
            task_id=repair_task.id,
        )
        await db.commit()
        return run
    except Exception as exc:
        run.status = "failed"
        run.error_message = str(exc)[:2000]
        await append_ci_failure_log(
            db,
            run,
            step="collection_failed",
            status="failed",
            message=str(exc)[:1000],
        )
        await db.commit()
        raise


def _job_metadata(job: dict[str, Any], classification: str, trace_path: str | None) -> dict[str, Any]:
    data = {
        "id": int(job["id"]),
        "name": str(job.get("name") or job["id"]),
        "stage": job.get("stage"),
        "failure_reason": job.get("failure_reason"),
        "classification": classification,
        "web_url": job.get("web_url"),
    }
    if trace_path:
        data["trace_path"] = trace_path
    return data


async def claim_collecting_runs(
    db: AsyncSession,
    *,
    collector_id: str,
    limit: int = 5,
    stale_after_seconds: int = 300,
) -> list[int]:
    """Claim currently collectable CI failure runs for this collector instance."""
    cutoff = utcnow() - timedelta(seconds=stale_after_seconds)
    result = await db.execute(
        select(CIFailureRun)
        .where(
            CIFailureRun.status == "collecting",
            or_(CIFailureRun.locked_at.is_(None), CIFailureRun.locked_at < cutoff),
        )
        .order_by(CIFailureRun.created_at.asc())
        .limit(limit)
    )
    runs = result.scalars().all()
    claimed: list[int] = []
    for run in runs:
        run.locked_at = utcnow()
        run.locked_by = collector_id
        claimed.append(run.id)
    await db.commit()
    return claimed


async def run_ci_failure_collector_once(*, collector_id: str | None = None, limit: int = 5) -> int:
    """Claim and process a batch of CI failure runs."""
    collector_id = collector_id or f"ci-collector-{uuid.uuid4()}"
    async with AsyncSessionLocal() as db:
        await refresh_runtime_config_if_stale(db, min_check_interval=0.0)
        settings = get_effective_settings()
        run_ids = await claim_collecting_runs(db, collector_id=collector_id, limit=limit)

    processed = 0
    for run_id in run_ids:
        async with AsyncSessionLocal() as db:
            client = get_gitlab_client()
            await process_ci_failure_run(
                db,
                run_id,
                gitlab_client=client,
                settings=settings,
                collector_id=collector_id,
            )
            processed += 1
    return processed


async def start_ci_failure_collector(
    *,
    interval_seconds: int = 10,
    stop_event: asyncio.Event | None = None,
) -> None:
    """Run the CI failure collector loop until cancelled or stopped."""
    collector_id = f"ci-collector-{uuid.uuid4()}"
    while stop_event is None or not stop_event.is_set():
        try:
            await run_ci_failure_collector_once(collector_id=collector_id)
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception("CI failure collector iteration failed")
        if stop_event is not None:
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=interval_seconds)
            except TimeoutError:
                pass
        else:
            await asyncio.sleep(interval_seconds)
