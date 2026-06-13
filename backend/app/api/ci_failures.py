"""CI failure evidence APIs."""

from __future__ import annotations

import os
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.dependencies.project_access import (
    ProjectAccessScope,
    require_project_access,
    require_project_access_scope,
)
from app.models import CIFailureJob, CIFailureRun, CIFailureRunLog, Issue, WebhookEvent

router = APIRouter()


def _serialize_job(job: CIFailureJob) -> dict[str, Any]:
    return {
        "id": job.id,
        "gitlab_job_id": job.gitlab_job_id,
        "name": job.name,
        "stage": job.stage,
        "status": job.status,
        "failure_reason": job.failure_reason,
        "allow_failure": job.allow_failure,
        "web_url": job.web_url,
        "trace_path": job.trace_path,
        "trace_size_bytes": job.trace_size_bytes,
        "is_root_cause": job.is_root_cause,
        "is_downstream_suppressed": job.is_downstream_suppressed,
        "classification": job.classification,
        "created_at": job.created_at.isoformat() if job.created_at else None,
    }


def _serialize_run(run: CIFailureRun, jobs: list[CIFailureJob] | None = None) -> dict[str, Any]:
    return {
        "id": run.id,
        "webhook_event_id": run.webhook_event_id,
        "project_id": run.project_id,
        "issue_id": run.issue_id,
        "merge_request_iid": run.merge_request_iid,
        "source_branch": run.source_branch,
        "target_branch": run.target_branch,
        "pipeline_id": run.pipeline_id,
        "pipeline_sha": run.pipeline_sha,
        "pipeline_ref": run.pipeline_ref,
        "pipeline_status": run.pipeline_status,
        "pipeline_url": run.pipeline_url,
        "status": run.status,
        "root_cause_strategy": run.root_cause_strategy,
        "bundle_available": bool(run.bundle_path and os.path.isdir(run.bundle_path)),
        "repair_task_id": run.repair_task_id,
        "ignored_reason": run.ignored_reason,
        "error_message": run.error_message,
        "collection_attempts": run.collection_attempts,
        "created_at": run.created_at.isoformat() if run.created_at else None,
        "updated_at": run.updated_at.isoformat() if run.updated_at else None,
        "jobs": [_serialize_job(job) for job in jobs] if jobs is not None else None,
    }


def _serialize_log(log: CIFailureRunLog) -> dict[str, Any]:
    return {
        "id": log.id,
        "ci_failure_run_id": log.ci_failure_run_id,
        "issue_id": log.issue_id,
        "task_id": log.task_id,
        "step": log.step,
        "status": log.status,
        "message": log.message,
        "details": log.details,
        "created_at": log.created_at.isoformat() if log.created_at else None,
    }


def _serialize_webhook_event(event: WebhookEvent) -> dict[str, Any]:
    return {
        "id": event.id,
        "event_type": event.event_type,
        "event_action": event.event_action,
        "project_id": event.project_id,
	        "merge_request_iid": event.merge_request_iid,
	        "issue_id": event.issue_id,
	        "source_ip": event.source_ip,
	        "result": event.result,
        "result_detail": event.result_detail,
        "payload_summary": event.payload_summary,
        "created_at": event.created_at.isoformat() if event.created_at else None,
    }


async def _load_issue_with_access(
    db: AsyncSession,
    issue_id: int,
    access_scope: ProjectAccessScope,
) -> Issue:
    issue = await db.get(Issue, issue_id)
    if issue is None:
        raise HTTPException(status_code=404, detail=f"Issue {issue_id} not found")
    require_project_access(issue.project_id, access_scope)
    return issue


@router.get("/issues/{issue_id}/ci-failures")
async def list_issue_ci_failures(
    issue_id: int,
    page: int = 1,
    page_size: int = 20,
    db: AsyncSession = Depends(get_db),
    access_scope: ProjectAccessScope = Depends(require_project_access_scope),
):
    page = max(1, page)
    page_size = max(1, min(100, page_size))
    await _load_issue_with_access(db, issue_id, access_scope)

    count = await db.scalar(
        select(func.count(CIFailureRun.id)).where(CIFailureRun.issue_id == issue_id)
    ) or 0
    runs = (
        await db.execute(
            select(CIFailureRun)
            .where(CIFailureRun.issue_id == issue_id)
            .order_by(CIFailureRun.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).scalars().all()

    run_ids = [run.id for run in runs]
    jobs_by_run: dict[int, list[CIFailureJob]] = {run_id: [] for run_id in run_ids}
    if run_ids:
        jobs = (
            await db.execute(
                select(CIFailureJob)
                .where(CIFailureJob.ci_failure_run_id.in_(run_ids))
                .order_by(CIFailureJob.is_root_cause.desc(), CIFailureJob.gitlab_job_id.asc())
            )
        ).scalars().all()
        for job in jobs:
            jobs_by_run.setdefault(job.ci_failure_run_id, []).append(job)

    return {
        "items": [_serialize_run(run, jobs_by_run.get(run.id, [])) for run in runs],
        "total": count,
        "page": page,
        "page_size": page_size,
    }


@router.get("/ci-failures/{ci_failure_run_id}")
async def get_ci_failure(
    ci_failure_run_id: int,
    db: AsyncSession = Depends(get_db),
    access_scope: ProjectAccessScope = Depends(require_project_access_scope),
):
    run = await db.get(CIFailureRun, ci_failure_run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="CI failure run not found")
    if run.issue_id is not None:
        await _load_issue_with_access(db, run.issue_id, access_scope)
    jobs = (
        await db.execute(
            select(CIFailureJob)
            .where(CIFailureJob.ci_failure_run_id == run.id)
            .order_by(CIFailureJob.is_root_cause.desc(), CIFailureJob.gitlab_job_id.asc())
        )
    ).scalars().all()
    return _serialize_run(run, jobs)


@router.get("/ci-failures/{ci_failure_run_id}/logs")
async def list_ci_failure_logs(
    ci_failure_run_id: int,
    db: AsyncSession = Depends(get_db),
    access_scope: ProjectAccessScope = Depends(require_project_access_scope),
):
    run = await db.get(CIFailureRun, ci_failure_run_id)
    if run is None:
        raise HTTPException(status_code=404, detail="CI failure run not found")
    if run.issue_id is not None:
        await _load_issue_with_access(db, run.issue_id, access_scope)
    logs = (
        await db.execute(
            select(CIFailureRunLog)
            .where(CIFailureRunLog.ci_failure_run_id == ci_failure_run_id)
            .order_by(CIFailureRunLog.created_at.asc(), CIFailureRunLog.id.asc())
        )
    ).scalars().all()
    return {"items": [_serialize_log(log) for log in logs]}


@router.get("/issues/{issue_id}/webhook-events")
async def list_issue_webhook_events(
    issue_id: int,
    page: int = 1,
    page_size: int = 20,
    db: AsyncSession = Depends(get_db),
    access_scope: ProjectAccessScope = Depends(require_project_access_scope),
):
    page = max(1, page)
    page_size = max(1, min(100, page_size))
    await _load_issue_with_access(db, issue_id, access_scope)
    total = await db.scalar(
        select(func.count(WebhookEvent.id)).where(WebhookEvent.issue_id == issue_id)
    ) or 0
    events = (
        await db.execute(
            select(WebhookEvent)
            .where(WebhookEvent.issue_id == issue_id)
            .order_by(WebhookEvent.created_at.desc())
            .offset((page - 1) * page_size)
            .limit(page_size)
        )
    ).scalars().all()
    return {
        "items": [_serialize_webhook_event(event) for event in events],
        "total": total,
        "page": page,
        "page_size": page_size,
    }
