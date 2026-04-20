"""GitLab webhook receiver and event log query API."""

from __future__ import annotations

import hmac
import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_effective_settings
from app.database import get_db
from app.models import Issue, IssueStatus, WebhookEvent
from app.project_webhook_config import get_project_webhook_secret
from app.runtime_config import load_runtime_config_from_db

logger = logging.getLogger(__name__)

# Router for the unauthenticated webhook receiver
webhook_router = APIRouter()

# Router for the authenticated event query endpoint
events_router = APIRouter()


class WebhookResponse(BaseModel):
    result: str
    detail: Optional[str] = None
    results: Optional[list[dict[str, Any]]] = None


class WebhookEventOut(BaseModel):
    id: int
    event_type: str
    event_action: Optional[str]
    project_id: int
    merge_request_iid: Optional[int]
    issue_id: Optional[int]
    source_ip: Optional[str]
    result: str
    result_detail: Optional[str]
    payload_summary: Optional[dict[str, Any]]
    created_at: str


class WebhookEventsResponse(BaseModel):
    items: list[WebhookEventOut]
    total: int
    page: int
    page_size: int


def _extract_payload_summary(payload: dict[str, Any]) -> dict[str, Any]:
    """Extract key fields from the webhook payload for storage."""
    summary: dict[str, Any] = {"object_kind": payload.get("object_kind")}
    project = payload.get("project")
    if isinstance(project, dict):
        summary["project_id"] = project.get("id")
        summary["project_path"] = project.get("path_with_namespace")
    attrs = payload.get("object_attributes")
    if isinstance(attrs, dict):
        summary["action"] = attrs.get("action")
        summary["iid"] = attrs.get("iid")
        summary["title"] = attrs.get("title")
        summary["state"] = attrs.get("state")
        summary["source_branch"] = attrs.get("source_branch")
        summary["target_branch"] = attrs.get("target_branch")
    return summary


async def _log_event(
    db: AsyncSession,
    *,
    event_type: str,
    event_action: Optional[str],
    project_id: int,
    merge_request_iid: Optional[int],
    issue_id: Optional[int],
    source_ip: Optional[str],
    result: str,
    result_detail: Optional[str] = None,
    payload_summary: Optional[dict[str, Any]] = None,
) -> None:
    """Persist a webhook event record."""
    event = WebhookEvent(
        event_type=event_type,
        event_action=event_action,
        project_id=project_id,
        merge_request_iid=merge_request_iid,
        issue_id=issue_id,
        source_ip=source_ip,
        result=result,
        result_detail=result_detail,
        payload_summary=payload_summary,
    )
    db.add(event)
    await db.flush()


@webhook_router.post("/webhook/gitlab", response_model=WebhookResponse)
async def receive_gitlab_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
):
    """Receive and process GitLab webhook events."""
    # Parse body
    try:
        payload: dict[str, Any] = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON body")

    # Extract project ID
    project_data = payload.get("project")
    if not isinstance(project_data, dict) or "id" not in project_data:
        raise HTTPException(status_code=400, detail="Missing project.id in payload")
    project_id = int(project_data["id"])

    source_ip = request.client.host if request.client else None
    event_type = str(payload.get("object_kind", "unknown"))
    attrs = payload.get("object_attributes") or {}
    event_action = attrs.get("action") if isinstance(attrs, dict) else None
    mr_iid = attrs.get("iid") if isinstance(attrs, dict) else None
    summary = _extract_payload_summary(payload)

    # --- Token verification ---
    token = request.headers.get("X-Gitlab-Token", "")
    await load_runtime_config_from_db(db)
    settings = get_effective_settings()

    expected_secret = await get_project_webhook_secret(db, project_id)
    if not expected_secret:
        expected_secret = (
            settings.gitlab_webhook_secret.strip() if settings.gitlab_webhook_secret else ""
        )

    if not expected_secret or not hmac.compare_digest(token, expected_secret):
        await _log_event(
            db,
            event_type=event_type,
            event_action=event_action,
            project_id=project_id,
            merge_request_iid=mr_iid,
            issue_id=None,
            source_ip=source_ip,
            result="auth_failed",
            result_detail="Token mismatch or no secret configured",
            payload_summary=summary,
        )
        await db.commit()
        raise HTTPException(status_code=401, detail="Invalid webhook token")

    # --- Event routing ---
    if event_type != "merge_request":
        await _log_event(
            db,
            event_type=event_type,
            event_action=event_action,
            project_id=project_id,
            merge_request_iid=mr_iid,
            issue_id=None,
            source_ip=source_ip,
            result="unsupported_event",
            result_detail=f"Event type '{event_type}' is not handled",
            payload_summary=summary,
        )
        await db.commit()
        return WebhookResponse(
            result="unsupported_event", detail=f"Event type '{event_type}' not handled"
        )

    if event_action != "merge":
        await _log_event(
            db,
            event_type=event_type,
            event_action=event_action,
            project_id=project_id,
            merge_request_iid=mr_iid,
            issue_id=None,
            source_ip=source_ip,
            result="ignored_action",
            result_detail=f"MR action '{event_action}' is not 'merge'",
            payload_summary=summary,
        )
        await db.commit()
        return WebhookResponse(result="ignored_action", detail=f"Action '{event_action}' ignored")

    # --- MR merged: find and close matching issues ---
    if mr_iid is None:
        await _log_event(
            db,
            event_type=event_type,
            event_action=event_action,
            project_id=project_id,
            merge_request_iid=None,
            issue_id=None,
            source_ip=source_ip,
            result="no_match",
            result_detail="MR IID missing from payload",
            payload_summary=summary,
        )
        await db.commit()
        return WebhookResponse(result="no_match", detail="MR IID missing")

    result = await db.execute(
        select(Issue).where(
            Issue.project_id == project_id,
            Issue.merge_request_iid == int(mr_iid),
        )
    )
    issues = result.scalars().all()

    if not issues:
        await _log_event(
            db,
            event_type=event_type,
            event_action=event_action,
            project_id=project_id,
            merge_request_iid=int(mr_iid),
            issue_id=None,
            source_ip=source_ip,
            result="no_match",
            result_detail=f"No Codify issue for project {project_id} MR !{mr_iid}",
            payload_summary=summary,
        )
        await db.commit()
        return WebhookResponse(result="no_match", detail=f"No issue for MR !{mr_iid}")

    results: list[dict[str, Any]] = []
    for issue in issues:
        if issue.status == IssueStatus.CLOSED.value:
            await _log_event(
                db,
                event_type=event_type,
                event_action=event_action,
                project_id=project_id,
                merge_request_iid=int(mr_iid),
                issue_id=issue.id,
                source_ip=source_ip,
                result="ignored_already_closed",
                payload_summary=summary,
            )
            results.append({"issue_id": issue.id, "result": "ignored_already_closed"})
        else:
            prev_status = issue.status
            issue.status = IssueStatus.CLOSED.value
            await _log_event(
                db,
                event_type=event_type,
                event_action=event_action,
                project_id=project_id,
                merge_request_iid=int(mr_iid),
                issue_id=issue.id,
                source_ip=source_ip,
                result="issue_closed",
                result_detail=f"Closed issue #{issue.id} (was '{prev_status}')",
                payload_summary=summary,
            )
            results.append({"issue_id": issue.id, "result": "issue_closed"})

    await db.commit()

    overall = (
        "issue_closed"
        if any(r["result"] == "issue_closed" for r in results)
        else "ignored_already_closed"
    )
    return WebhookResponse(result=overall, results=results)


@events_router.get("/webhook/events", response_model=WebhookEventsResponse)
async def list_webhook_events(
    page: int = 1,
    page_size: int = 20,
    event_type: Optional[str] = None,
    result: Optional[str] = None,
    project_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
):
    """Query paginated webhook event log."""
    if page < 1:
        page = 1
    if page_size < 1:
        page_size = 1
    elif page_size > 100:
        page_size = 100

    query = select(WebhookEvent)
    count_query = select(func.count(WebhookEvent.id))

    if event_type:
        query = query.where(WebhookEvent.event_type == event_type)
        count_query = count_query.where(WebhookEvent.event_type == event_type)
    if result:
        query = query.where(WebhookEvent.result == result)
        count_query = count_query.where(WebhookEvent.result == result)
    if project_id is not None:
        query = query.where(WebhookEvent.project_id == project_id)
        count_query = count_query.where(WebhookEvent.project_id == project_id)

    total_result = await db.execute(count_query)
    total = total_result.scalar() or 0

    query = query.order_by(WebhookEvent.created_at.desc())
    query = query.offset((page - 1) * page_size).limit(page_size)
    rows = await db.execute(query)
    events = rows.scalars().all()

    items = [
        WebhookEventOut(
            id=e.id,
            event_type=e.event_type,
            event_action=e.event_action,
            project_id=e.project_id,
            merge_request_iid=e.merge_request_iid,
            issue_id=e.issue_id,
            source_ip=e.source_ip,
            result=e.result,
            result_detail=e.result_detail,
            payload_summary=e.payload_summary,
            created_at=e.created_at.isoformat() if e.created_at else "",
        )
        for e in events
    ]

    return WebhookEventsResponse(items=items, total=total, page=page, page_size=page_size)
