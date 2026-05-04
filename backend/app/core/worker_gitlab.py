"""GitLab and notification helpers for worker execution."""

import asyncio
import logging
import re
from typing import Optional

import httpx
from gitlab import Gitlab
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_effective_settings as get_settings
from app.core.mattermost_notifications import (
    MATTERMOST_EVENT_TASK_COMPLETED,
    MATTERMOST_EVENT_TASK_FAILED,
    MATTERMOST_EVENT_TASK_RETRY_SCHEDULED,
    notify_task_event,
)
from app.core.ssl_utils import get_ssl_verify
from app.models import Issue, Task, TaskStatus

logger = logging.getLogger(__name__)


def build_initial_mr_title(task: Task) -> str:
    issue = task.issue if task.issue else None
    if issue and issue.title:
        return f"Draft: {issue.title[:120]}"

    prompt = re.sub(r"\s+", " ", task.user_prompt or "").strip()
    if prompt:
        short_prompt = re.split(r"[;\n。！？.!?]", prompt, maxsplit=1)[0].strip()
        if short_prompt:
            return f"AI: {short_prompt[:100]}"

    return f"AI: Task {task.id}"


def build_initial_mr_description(task: Task) -> str:
    return f"""## 🚀 AI 正在执行

### 需求
{task.user_prompt}

---
*AI 正在直接实施变更...*"""


def remove_mr_draft_status_for_issue(task: Task, issue: Issue, gitlab_client, *, sudo_gl: Optional[Gitlab] = None) -> None:
    gl = sudo_gl or gitlab_client.gl
    project = gl.projects.get(task.project_id)
    mr = project.mergerequests.get(issue.merge_request_iid)

    title = getattr(mr, "title", "")
    if not isinstance(title, str):
        logger.info(f"[Task {task.id}] Skipping draft removal because MR title is unavailable")
        return

    updated_title = re.sub(r"^(?:\[Draft\]\s*|Draft:\s*|WIP:\s*)", "", title, count=1, flags=re.IGNORECASE).strip()
    mr.ready()
    if updated_title:
        mr.title = updated_title
    mr.save()
    logger.info(f"[Task {task.id}] Marked MR !{issue.merge_request_iid} ready")


def create_mr_if_needed(
    task: Task,
    issue: Issue,
    mr_iid: Optional[int],
    mr_web_url: Optional[str],
    gitlab_client,
    *,
    sudo_gl: Optional[Gitlab] = None,
) -> tuple[Optional[int], Optional[str]]:
    if mr_iid:
        return mr_iid, mr_web_url

    existing = find_existing_mr(task, issue, gitlab_client)
    if existing:
        return existing

    return create_new_mr(task, issue, gitlab_client, sudo_gl=sudo_gl)


def find_existing_mr(task: Task, issue: Issue, gitlab_client) -> tuple[Optional[int], Optional[str]] | None:
    try:
        existing_mrs = gitlab_client.gl.projects.get(task.project_id).mergerequests.list(
            source_branch=issue.branch_name,
            state="opened",
        )
        if not existing_mrs:
            return None

        mr_iid = existing_mrs[0].iid
        mr_web_url = gitlab_client.normalize_web_url(existing_mrs[0].web_url)
        logger.info(f"[Task {task.id}] Reusing existing MR !{mr_iid} for branch {issue.branch_name}")
        return mr_iid, mr_web_url
    except Exception as e:
        logger.warning(f"[Task {task.id}] Failed to look up existing MR: {e}")
    return None


def create_new_mr(task: Task, issue: Issue, gitlab_client, *, sudo_gl: Optional[Gitlab] = None) -> tuple[Optional[int], Optional[str]]:
    settings = get_settings()
    target_branch = issue.target_branch or settings.default_target_branch
    mr_title = build_initial_mr_title(task)
    initial_mr_desc = build_initial_mr_description(task)

    mr_data = {
        "source_branch": issue.branch_name,
        "target_branch": target_branch,
        "title": mr_title,
        "description": initial_mr_desc,
        "draft": True,
        "labels": ["Codify"],
    }

    try:
        gl = sudo_gl or gitlab_client.gl
        mr_response = gl.projects.get(task.project_id).mergerequests.create(mr_data)
    except Exception as e:
        if sudo_gl:
            logger.warning(f"[Task {task.id}] Sudo MR creation failed: {e}, retrying with bot token")
            try:
                mr_response = gitlab_client.gl.projects.get(task.project_id).mergerequests.create(mr_data)
            except Exception as e2:
                logger.warning(f"[Task {task.id}] Bot token MR creation also failed: {e2}")
                return None, None
        else:
            logger.warning(f"[Task {task.id}] Failed to create initial MR: {e}, continuing without MR")
            return None, None

    mr_iid = mr_response.iid
    mr_web_url = gitlab_client.normalize_web_url(mr_response.web_url)
    logger.info(f"[Task {task.id}] Created initial draft MR !{mr_iid}")
    return mr_iid, mr_web_url


async def update_mr_description_for_issue(
    task: Task,
    issue: Issue,
    db: AsyncSession,
    gitlab_client,
    *,
    sudo_gl: Optional[Gitlab] = None,
) -> None:
    mr_iid = issue.merge_request_iid
    if not mr_iid:
        return

    try:
        all_tasks = (await db.execute(
            select(Task)
            .where(Task.issue_id == issue.id)
            .order_by(Task.id)
        )).scalars().all()

        status_icons = {
            TaskStatus.PENDING: "⏳",
            TaskStatus.QUEUED: "📋",
            TaskStatus.RUNNING: "🔄",
            TaskStatus.COMPLETED: "✅",
            TaskStatus.FAILED: "❌",
            TaskStatus.CANCELLED: "🚫",
        }

        lines = []
        lines.append(f"## {issue.title or 'Untitled Issue'}")
        lines.append("")
        if issue.description:
            lines.append(issue.description)
            lines.append("")

        lines.append("---")
        lines.append("")
        lines.append("### 任务执行记录")
        lines.append("")
        lines.append("| # | 状态 | 提示 |")
        lines.append("|---|------|------|")

        for t in all_tasks:
            icon = status_icons.get(t.status, "❓")
            status_label = t.status.value if t.status else "unknown"
            prompt_short = (t.user_prompt or "")[:80]
            if len(t.user_prompt or "") > 80:
                prompt_short += "..."
            prompt_short = prompt_short.replace("|", "\\|").replace("\n", " ")
            lines.append(f"| {t.id} | {icon} {status_label} | {prompt_short} |")

        lines.append("")
        description = "\n".join(lines)

        gl = sudo_gl or gitlab_client.gl
        project = gl.projects.get(task.project_id)
        try:
            mr = project.mergerequests.get(mr_iid)
        except Exception:
            logger.warning(f"Could not find MR !{mr_iid} to update description")
            return

        mr.description = description
        if issue.title:
            mr.title = issue.title
        mr.save()
        logger.info(f"[Task {task.id}] Updated MR !{mr_iid} title+description with issue #{issue.id} context ({len(all_tasks)} tasks)")

    except Exception as e:
        logger.warning(f"[Task {task.id}] Failed to update MR description: {e}")


def notify_task_started(task: Task, gitlab_client, issue: Optional[Issue] = None) -> None:
    if not issue:
        logger.info(f"Skipping start notification for task {task.id} (no issue)")
        return

    settings = get_settings()
    task_url = f"{settings.dashboard_url}/tasks/{task.id}"
    message = f"🔄 开始处理请求... [任务 {task.id}]({task_url})"
    if issue.merge_request_iid:
        gitlab_client.create_mr_note(task.project_id, issue.merge_request_iid, message)
        logger.info(f"Sent start notification to MR !{issue.merge_request_iid} for task {task.id}")


async def notify_task_completed(task: Task, gitlab_client, sanitize_sensitive_data, success: bool, notify_target: str = "issue", issue: Optional[Issue] = None) -> None:
    if not issue:
        logger.info(f"Skipping completion notification for task {task.id} (no issue)")
        return

    mr_iid = issue.merge_request_iid
    settings = get_settings()
    task_url = f"{settings.dashboard_url}/tasks/{task.id}"

    if success:
        if issue.merge_request_url:
            if mr_iid:
                message = f"✅ 代码已更新到 MR !{mr_iid} [任务 {task.id}]({task_url})"
            else:
                message = f"✅ MR 已更新: [任务 {task.id}]({task_url})"
        else:
            message = f"✅ 任务已完成 [任务 {task.id}]({task_url})"
    else:
        error_msg = task.error_message[:200] if task.error_message else "未知错误"
        error_msg = sanitize_sensitive_data(error_msg)
        message = f"❌ 任务失败 [任务 {task.id}]({task_url}): {error_msg}"

    if notify_target == "mr" and mr_iid:
        await asyncio.to_thread(gitlab_client.create_mr_note, task.project_id, mr_iid, message)
        logger.info(f"Sent completion notification to MR !{mr_iid} for task {task.id}, success={success}")


async def send_failure_alert(task: Task, sanitize_sensitive_data, issue: Optional[Issue] = None) -> None:
    settings = get_settings()
    if not settings.alert_on_failure or not settings.alert_webhook_url:
        return

    error_msg = task.error_message[:500] if task.error_message else "Unknown error"
    error_msg = sanitize_sensitive_data(error_msg)
    alert_data = {
        "text": "🚨 Task Failed",
        "attachments": [{
            "color": "danger",
            "fields": [
                {"title": "Task ID", "value": str(task.id), "short": True},
                {"title": "Project ID", "value": str(task.project_id), "short": True},
                {"title": "Issue", "value": f"#{issue.id}" if issue else "N/A", "short": True},
                {"title": "Error", "value": error_msg},
            ]
        }]
    }

    try:
        async with httpx.AsyncClient(timeout=10.0, verify=get_ssl_verify(settings)) as client:
            response = await client.post(settings.alert_webhook_url, json=alert_data)
        if response.status_code < 400:
            logger.info(f"Sent failure alert for task {task.id}")
        else:
            logger.warning(f"Failed to send failure alert: {response.status_code}")
    except Exception as e:
        logger.warning(f"Failed to send failure alert: {e}")


async def send_notifications(task: Task, gitlab_client, sanitize_sensitive_data, success: bool, had_existing_mr: bool, issue: Optional[Issue] = None) -> None:
    notify_target = "mr" if had_existing_mr else "issue"
    try:
        await notify_task_completed(task, gitlab_client, sanitize_sensitive_data, success=success, notify_target=notify_target, issue=issue)
    except Exception as e:
        logger.warning(f"Failed to send completion notification: {e}")

    try:
        await notify_task_event(task, MATTERMOST_EVENT_TASK_COMPLETED)
    except Exception as e:
        logger.warning(f"Failed to send Mattermost completion notification: {e}")


async def send_failure_notifications(task: Task, gitlab_client, sanitize_sensitive_data, success: bool, had_existing_mr: bool, issue: Optional[Issue] = None) -> None:
    notify_target = "mr" if had_existing_mr else "issue"
    try:
        await notify_task_completed(task, gitlab_client, sanitize_sensitive_data, success=success, notify_target=notify_target, issue=issue)
    except Exception as e:
        logger.warning(f"Failed to send failure notification: {e}")

    try:
        await send_failure_alert(task, sanitize_sensitive_data, issue)
    except Exception as e:
        logger.warning(f"Failed to send failure alert: {e}")

    try:
        if task.status == TaskStatus.PENDING:
            await notify_task_event(
                task,
                MATTERMOST_EVENT_TASK_RETRY_SCHEDULED,
                context={
                    "previous_scheduled_at": task.scheduled_at,
                    "scheduled_at": task.scheduled_at,
                },
            )
        else:
            await notify_task_event(task, MATTERMOST_EVENT_TASK_FAILED)
    except Exception as e:
        logger.warning(f"Failed to send Mattermost failure notification: {e}")
