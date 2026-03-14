"""GitLab Webhook endpoint."""

import logging
import re
import secrets
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.gitlab_client import get_gitlab_client
from app.core.parser import BotCommand, parse_ai_bot_command
from app.core.scheduling import resolve_scheduled_at
from app.database import get_db
from app.models import Task, TaskStatus

logger = logging.getLogger(__name__)


# Patterns that indicate user is referring to issue content
GENERIC_PROMPT_PATTERNS = [
    r"^实现这个(issue|需求)?$",
    r"^实现这个(功能)?$",
    r"^完成这个(issue|需求)?$",
    r"^完成这个功能$",
    r"^处理这个(issue|需求)?$",
    r"^做这个(issue|需求)?$",
    r"^帮我做$",
    r"^帮我实现$",
    r"^开始(实现|处理)$",
    r"^start$",
    r"^do\s*this$",
    r"^implement\s*this$",
    r"^fix\s*this$",
    r"^this\s*issue$",
    r"^这个issue$",
]


def is_generic_prompt(prompt: str) -> bool:
    """Check if the user prompt is a generic reference to the issue.

    Args:
        prompt: User's prompt from the comment

    Returns:
        True if the prompt is generic and should use issue details
    """
    if not prompt or not prompt.strip():
        return True

    prompt_lower = prompt.lower().strip()
    for pattern in GENERIC_PROMPT_PATTERNS:
        if re.match(pattern, prompt_lower, re.IGNORECASE):
            return True
    return False


def build_enhanced_prompt(prompt: str, issue_title: str, issue_description: Optional[str]) -> str:
    """Build enhanced prompt using issue details.

    Args:
        prompt: Original user prompt
        issue_title: Issue title from GitLab
        issue_description: Issue description from GitLab

    Returns:
        Enhanced prompt with issue details
    """
    parts = []

    # Add issue title
    if issue_title:
        parts.append(f"Issue: {issue_title}")

    # Add issue description if available
    if issue_description:
        parts.append(f"\n需求描述:\n{issue_description}")
    else:
        parts.append("\n需求描述: (无详细描述)")

    return "\n".join(parts)


def build_prompt_with_issue_context(prompt: str, issue_title: str, issue_description: Optional[str]) -> str:
    """Build prompt that combines explicit instruction with issue context.

    Args:
        prompt: User prompt from comment
        issue_title: Issue title
        issue_description: Issue description

    Returns:
        Combined prompt text
    """
    issue_context = build_enhanced_prompt("", issue_title, issue_description)
    trimmed_prompt = (prompt or "").strip()

    if not trimmed_prompt:
        return issue_context

    return f"{issue_context}\n\n用户补充要求: {trimmed_prompt}"
router = APIRouter()
settings = get_settings()


async def verify_gitlab_webhook(
    request: Request,
    x_gitlab_token: Optional[str] = Header(None, alias="X-Gitlab-Token"),
) -> dict:
    """Verify GitLab webhook request.

    Args:
        request: FastAPI request
        x_gitlab_token: GitLab webhook token from header

    Returns:
        Request payload

    Raises:
        HTTPException: If verification fails
    """
    # Verify webhook secret
    if settings.gitlab_webhook_secret:
        if not x_gitlab_token:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing X-Gitlab-Token header",
            )
        if not secrets.compare_digest(x_gitlab_token, settings.gitlab_webhook_secret):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid X-Gitlab-Token",
            )

    # Parse JSON body
    try:
        payload = await request.json()
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid JSON payload: {e}",
        )

    logger.info(f"Webhook received: object_kind={payload.get('object_kind')}, event_type={payload.get('event_type')}")
    # Debug: log full payload structure
    logger.info(f"Webhook payload keys: {list(payload.keys())}")
    if payload.get("object_attributes"):
        logger.info(f"Object attributes keys: {list(payload.get('object_attributes', {}).keys())}")
    return payload


@router.post("/webhook/gitlab")
async def gitlab_webhook(
    request: Request,
    db: AsyncSession = Depends(get_db),
    x_gitlab_token: Optional[str] = Header(None, alias="X-Gitlab-Token"),
) -> dict:
    """Handle GitLab webhook events.

    Listens for:
    - Note (comment) events on issues

    Args:
        request: FastAPI request
        db: Database session
        x_gitlab_token: GitLab webhook token

    Returns:
        Response dict
    """
    # Verify webhook
    payload = await verify_gitlab_webhook(request, x_gitlab_token)

    # Only handle note (comment) events
    event_type = payload.get("object_kind")
    if event_type != "note":
        logger.debug(f"Ignoring event type: {event_type}")
        return {"status": "ignored", "reason": f"event_type {event_type} not supported"}

    # Get note (comment) data - GitLab webhook uses 'note' field directly (not object_attributes)
    note_attrs = payload.get("note", {})
    note_id = note_attrs.get("id")
    note_type = note_attrs.get("noteable_type")
    comment_body = note_attrs.get("body", "")

    # Get issue and project info from root level
    issue = payload.get("issue", {})
    project = payload.get("project", {})
    # Get MR info from root level (for MR comments)
    merge_request = payload.get("merge_request", {})

    logger.info(f"Note type: {note_type}, Note ID: {note_id}, Comment: '{comment_body[:50] if comment_body else ''}'")

    # Handle issue comments
    if note_type == "Issue":
        return await _handle_issue_comment(
            db, project, issue, note_id, comment_body
        )
    # Handle MR comments
    elif note_type == "MergeRequest":
        return await _handle_mr_comment(
            db, project, merge_request, note_id, comment_body
        )
    else:
        logger.debug(f"Ignoring noteable type: {note_type}")
        return {"status": "ignored", "reason": f"noteable_type {note_type} not supported"}

    return {"status": "ignored", "reason": "empty comment body"}


async def _handle_issue_comment(
    db: AsyncSession,
    project: dict,
    issue: dict,
    note_id: int,
    comment_body: str,
) -> dict:
    """Handle comment on a GitLab Issue."""
    # Parse @ai-bot command
    command = parse_ai_bot_command(comment_body)
    if not command:
        logger.info(f"No @ai-bot command found in comment: '{comment_body[:50]}'")
        return {"status": "ignored", "reason": "no @ai-bot command found"}

    project_id = project.get("id")
    issue_id = issue.get("id")
    issue_iid = issue.get("iid")

    logger.info(f"Project: {project_id}, Issue: {issue_iid}, Note: {note_id}")

    if not all([project_id, issue_id, issue_iid, note_id]):
        logger.error(f"Missing required fields for issue comment")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing required fields in webhook payload",
        )

    # Handle cancel command
    if command.command == "cancel":
        return await _handle_cancel_command(db, project_id, issue_iid)

    # Handle status command
    if command.command == "status":
        return await _handle_status_command(db, project_id, issue_iid)

    # Handle generate command
    return await _handle_generate_command(
        db, project_id, issue_id, issue_iid, note_id, command
    )


async def _handle_cancel_command(
    db: AsyncSession,
    project_id: int,
    issue_iid: int,
) -> dict:
    """Handle @ai-bot cancel command."""
    # Find running task for this issue
    result = await db.execute(
        select(Task).where(
            Task.project_id == project_id,
            Task.issue_iid == issue_iid,
            Task.status == TaskStatus.RUNNING,
        )
    )
    task = result.scalar_one_or_none()

    if task:
        task.status = TaskStatus.CANCELLED
        task.completed_at = datetime.utcnow()
        task.error_message = "Cancelled by user"
        await db.commit()

        # TODO: Stop container if running
        logger.info(f"Cancelled task {task.id}")
        return {
            "status": "success",
            "message": f"Task {task.id} cancelled",
            "task_id": task.id,
        }

    # Check for pending tasks
    result = await db.execute(
        select(Task).where(
            Task.project_id == project_id,
            Task.issue_iid == issue_iid,
            Task.status.in_([TaskStatus.PENDING, TaskStatus.QUEUED]),
        )
    )
    pending_tasks = result.scalars().all()

    if pending_tasks:
        for task in pending_tasks:
            task.status = TaskStatus.CANCELLED
            task.completed_at = datetime.utcnow()
        await db.commit()
        return {
            "status": "success",
            "message": f"Cancelled {len(pending_tasks)} pending tasks",
        }

    return {
        "status": "ignored",
        "message": "No running or pending tasks found",
    }


async def _handle_status_command(
    db: AsyncSession,
    project_id: int,
    issue_iid: int,
) -> dict:
    """Handle @ai-bot status command."""
    # Find latest task for this issue
    result = await db.execute(
        select(Task).where(
            Task.project_id == project_id,
            Task.issue_iid == issue_iid,
        ).order_by(Task.created_at.desc()).limit(1)
    )
    task = result.scalar_one_or_none()

    if not task:
        return {
            "status": "ignored",
            "message": "No tasks found for this issue",
        }

    response = {
        "status": "success",
        "task": {
            "id": task.id,
            "status": task.status.value,
            "created_at": task.created_at.isoformat(),
            "branch": task.branch_name,
            "mr_url": task.merge_request_url,
        },
    }

    # Add error message if failed
    if task.status == TaskStatus.FAILED and task.error_message:
        response["task"]["error"] = task.error_message

    # Reply to issue with status
    try:
        gitlab = get_gitlab_client()
        status_text = f"Task Status: **{task.status.value}**"
        if task.merge_request_url:
            status_text += f"\nMR: {task.merge_request_url}"
        if task.status == TaskStatus.FAILED and task.error_message:
            status_text += f"\nError: {task.error_message[:200]}"

        gitlab.create_note(project_id, issue_iid, status_text)
    except Exception as e:
        logger.warning(f"Failed to reply to issue: {e}")

    return response


async def _handle_generate_command(
    db: AsyncSession,
    project_id: int,
    issue_id: int,
    issue_iid: int,
    note_id: int,
    command: BotCommand,
) -> dict:
    """Handle @ai-bot generate command."""
    # Check for duplicate (idempotency)
    result = await db.execute(
        select(Task).where(Task.note_id == note_id)
    )
    existing_task = result.scalar_one_or_none()

    if existing_task:
        logger.info(f"Task for note {note_id} already exists, skipping")
        return {"status": "duplicate", "message": "Task already processed"}

    user_prompt = command.args

    # Always fetch issue details first. For generic/empty prompt, use issue context directly.
    # For explicit prompt, keep user intent and append issue context.
    issue_details = None
    try:
        gitlab = get_gitlab_client()
        issue_details = gitlab.get_issue(project_id, issue_iid)
    except Exception as e:
        logger.warning(f"Failed to fetch issue details: {e}, using original prompt")

    if issue_details:
        issue_title = issue_details.get("title", "")
        issue_description = issue_details.get("description")

        if is_generic_prompt(user_prompt):
            logger.info(f"User prompt is generic/empty, using issue context for {project_id}/{issue_iid}")
            user_prompt = build_enhanced_prompt(
                user_prompt,
                issue_title,
                issue_description,
            )
        else:
            user_prompt = build_prompt_with_issue_context(
                user_prompt,
                issue_title,
                issue_description,
            )
    else:
        logger.warning("Could not fetch issue details, using original prompt")

    scheduled_at = resolve_scheduled_at(
        command.scheduled_datetime,
        command.delay_seconds,
    )

    # Determine target branch
    target_branch = command.target_branch or settings.default_target_branch

    # Create new task
    task = Task(
        project_id=project_id,
        issue_id=issue_id,
        issue_iid=issue_iid,
        note_id=note_id,
        user_prompt=user_prompt,
        branch_name=f"gimr/issue-{issue_iid}",
        priority=command.priority,
        scheduled_at=scheduled_at,
        target_branch=target_branch,
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)

    logger.info(
        f"Created task {task.id} for issue {project_id}/{issue_iid}, "
        f"note {note_id}, priority={command.priority}, delay={command.delay_seconds}"
    )

    # Note: Scheduler will pick up the task automatically

    return {
        "status": "success",
        "message": "Task created and queued for execution",
        "task_id": task.id,
        "priority": command.priority,
        "scheduled_at": scheduled_at.isoformat() if scheduled_at else None,
    }


async def _handle_mr_comment(
    db: AsyncSession,
    project: dict,
    merge_request: dict,
    note_id: int,
    comment_body: str,
) -> dict:
    """Handle comment on a GitLab Merge Request."""
    # Parse @ai-bot command
    command = parse_ai_bot_command(comment_body)
    if not command:
        logger.info(f"No @ai-bot command found in MR comment: '{comment_body[:50]}'")
        return {"status": "ignored", "reason": "no @ai-bot command found"}

    # Handle cancel/status commands on MR - redirect to issue
    if command.command == "cancel":
        # Try to find associated task via MR
        project_id = project.get("id")
        mr_iid = merge_request.get("iid")
        if project_id and mr_iid:
            result = await db.execute(
                select(Task).where(
                    Task.project_id == project_id,
                    Task.merge_request_iid == mr_iid,
                    Task.status == TaskStatus.RUNNING,
                )
            )
            task = result.scalar_one_or_none()
            if task:
                return await _handle_cancel_command(db, project_id, task.issue_iid)
        return {"status": "ignored", "reason": "no running task found for this MR"}

    if command.command == "status":
        project_id = project.get("id")
        mr_iid = merge_request.get("iid")
        if project_id and mr_iid:
            result = await db.execute(
                select(Task).where(
                    Task.project_id == project_id,
                    Task.merge_request_iid == mr_iid,
                ).order_by(Task.created_at.desc()).limit(1)
            )
            task = result.scalar_one_or_none()
            if task:
                return await _handle_status_command(db, project_id, task.issue_iid)
        return {"status": "ignored", "reason": "no task found for this MR"}

    # Handle generate command - continue on existing branch
    project_id = project.get("id")
    mr_iid = merge_request.get("iid")

    logger.info(f"Project: {project_id}, MR: {mr_iid}, Note: {note_id}")

    if not all([project_id, mr_iid, note_id]):
        logger.error(f"Missing required fields for MR comment")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Missing required fields in webhook payload",
        )

    # Check for duplicate (idempotency)
    result = await db.execute(
        select(Task).where(Task.note_id == note_id)
    )
    existing_task = result.scalar_one_or_none()

    if existing_task:
        logger.info(f"Task for note {note_id} already exists, skipping")
        return {"status": "duplicate", "message": "Task already processed"}

    # Find the associated task via merge_request_iid
    result = await db.execute(
        select(Task).where(
            Task.project_id == project_id,
            Task.merge_request_iid == mr_iid,
            Task.status.in_([TaskStatus.COMPLETED, TaskStatus.FAILED]),
        ).order_by(Task.created_at.desc()).limit(1)
    )
    parent_task = result.scalar_one_or_none()

    if not parent_task:
        # Try to find any task for this MR (might be still running)
        result = await db.execute(
            select(Task).where(
                Task.project_id == project_id,
                Task.merge_request_iid == mr_iid,
            ).order_by(Task.created_at.desc()).limit(1)
        )
        parent_task = result.scalar_one_or_none()

        if parent_task:
            return {
                "status": "ignored",
                "reason": f"Task {parent_task.id} is still {parent_task.status.value}, please wait for it to complete",
            }

        return {
            "status": "ignored",
            "reason": f"No completed task found for MR !{mr_iid}. Please create a task from the Issue first.",
        }

    # Get MR details
    gitlab = get_gitlab_client()
    mr_details = gitlab.get_mr_by_iid(project_id, mr_iid)

    if not mr_details:
        return {"status": "error", "message": "Failed to get MR details"}

    # Check if MR is open (GitLab uses "opened")
    mr_state = mr_details.get("state", "")
    if mr_state not in ["open", "opened"]:
        return {"status": "ignored", "reason": f"MR !{mr_iid} is not open (state: {mr_state})"}

    # Build prompt - use MR context
    user_prompt = command.args
    mr_title = mr_details.get("title", "")

    if is_generic_prompt(user_prompt):
        user_prompt = f"继续修改 MR !{mr_iid}: {mr_title}\n\n请继续在当前分支上进行修改。"
    else:
        user_prompt = f"MR !{mr_iid} 继续修改: {mr_title}\n\n用户补充要求: {user_prompt}"

    scheduled_at = resolve_scheduled_at(
        command.scheduled_datetime,
        command.delay_seconds,
    )

    # Create new task - continue on existing branch
    task = Task(
        project_id=project_id,
        issue_id=parent_task.issue_id,
        issue_iid=parent_task.issue_iid,
        note_id=note_id,
        user_prompt=user_prompt,
        branch_name=parent_task.branch_name,  # Continue on existing branch
        priority=command.priority,
        scheduled_at=scheduled_at,
        target_branch=parent_task.target_branch,
        merge_request_iid=mr_iid,  # Link to existing MR
    )
    db.add(task)
    await db.commit()
    await db.refresh(task)

    logger.info(
        f"Created task {task.id} for MR {project_id}/!{mr_iid}, "
        f"note {note_id}, continuing on branch {parent_task.branch_name}"
    )

    # Send notification to MR comment
    try:
        gitlab = get_gitlab_client()
        task_url = f"{settings.backend_url}/tasks/{task.id}"
        notify_msg = f"🔄 开始处理请求... [任务 {task.id}]({task_url})"
        gitlab.create_mr_note(project_id, mr_iid, notify_msg)
        logger.info(f"Sent start notification to MR !{mr_iid}")
    except Exception as e:
        logger.warning(f"Failed to send MR notification: {e}")

    return {
        "status": "success",
        "message": "Task created and queued for execution (continuing on existing branch)",
        "task_id": task.id,
        "priority": command.priority,
        "scheduled_at": scheduled_at.isoformat() if scheduled_at else None,
    }
