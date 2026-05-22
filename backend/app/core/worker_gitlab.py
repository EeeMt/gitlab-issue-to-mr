"""GitLab and notification helpers for worker execution."""

import json
import logging
import os
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
    mr.draft = False
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

        # Load per-task metadata files from the persistent workspace (if available).
        settings = get_settings()
        issue_root = _resolve_issue_root(settings, issue, all_tasks)
        metadata_map = load_task_metadata_files(issue_root, [t.id for t in all_tasks]) if issue_root else {}

        if issue_root:
            logger.info(
                f"[Task {task.id}] Metadata load: {len(metadata_map)}/{len(all_tasks)} task(s) "
                f"have metadata (workspace: {issue_root})"
            )
        else:
            logger.info(
                f"[Task {task.id}] Workspace root not resolved — "
                f"worker_workspace_host_path={getattr(settings, 'worker_workspace_host_path', None)!r}; "
                f"MR description will omit per-task metadata"
            )

        description = _build_mr_description(issue, all_tasks, metadata_map)

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
        logger.info(
            f"[Task {task.id}] Updated MR !{mr_iid} title+description with issue #{issue.id} context "
            f"({len(all_tasks)} tasks, {len(metadata_map)} with metadata)"
        )

    except Exception as e:
        logger.warning(f"[Task {task.id}] Failed to update MR description: {e}")


def _resolve_issue_root(settings, issue: Issue, all_tasks: list) -> Optional[str]:
    """Return the issue workspace root path, or None if workspace is not configured."""
    try:
        from app.core.worker_workspace import build_issue_workspace_paths
        if not all_tasks:
            return None
        paths = build_issue_workspace_paths(settings, issue, all_tasks[0])
        if paths is None:
            logger.debug(f"[Issue {issue.id}] worker_workspace_host_path not configured; metadata unavailable")
            return None
        logger.info(f"[Issue {issue.id}] Resolved workspace root: {paths.issue_root}")
        return paths.issue_root
    except Exception:
        logger.warning("Could not resolve issue workspace root", exc_info=True)
        return None


def load_task_metadata_files(issue_root: str, task_ids: list[int]) -> dict[int, dict]:
    """Read task-metadata.json for each task from the persistent workspace runtime directory.

    Returns a mapping of task_id -> metadata dict. Tasks without a metadata file are omitted.
    """
    result: dict[int, dict] = {}
    for task_id in task_ids:
        path = os.path.join(issue_root, "runtime", f"task-{task_id}", "task-metadata.json")
        try:
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                result[task_id] = data
                logger.info(f"[Task {task_id}] Loaded metadata from {path}")
            else:
                logger.warning(f"[Task {task_id}] task-metadata.json at {path} is not a JSON object, skipping")
        except FileNotFoundError:
            logger.info(f"[Task {task_id}] task-metadata.json not found at {path}")
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning(f"[Task {task_id}] Failed to read task-metadata.json at {path}: {exc}")
    return result


def build_aggregated_file_summary(metadata_map: dict[int, dict]) -> dict:
    """Aggregate file changes across all tasks.

    Returns:
        {
            "new": {filepath: [task_id, ...]},
            "modified": {filepath: [task_id, ...]},
            "deleted": {filepath: [task_id, ...]},
            "total_additions": int,
            "total_deletions": int,
        }

    Priority when the same file appears in multiple change types:
    deleted > new > modified (last operation wins). When a higher-priority type
    supersedes a lower one, task IDs from the superseded entry are not carried forward.
    """
    # file -> (change_type, [task_ids])
    # priority: deleted=3, new=2, modified=1
    _PRIORITY = {"deleted": 3, "new": 2, "modified": 1}
    file_state: dict[str, tuple[str, list[int]]] = {}

    total_additions = 0
    total_deletions = 0

    for task_id in sorted(metadata_map.keys()):
        meta = metadata_map[task_id]
        total_additions += int(meta.get("additions") or 0)
        total_deletions += int(meta.get("deletions") or 0)

        for change_type in ("new", "modified", "deleted"):
            raw = meta.get(f"{change_type}_files") or []
            files: list[str] = [f.strip() for f in (raw if isinstance(raw, list) else []) if f.strip()]
            for filepath in files:
                current_type, current_ids = file_state.get(filepath, (change_type, []))
                # Keep the higher-priority type; merge task ids
                if _PRIORITY.get(change_type, 0) >= _PRIORITY.get(current_type, 0):
                    new_ids = current_ids if current_type == change_type else []
                    if task_id not in new_ids:
                        new_ids = new_ids + [task_id]
                    file_state[filepath] = (change_type, new_ids)
                else:
                    if task_id not in current_ids:
                        file_state[filepath] = (current_type, current_ids + [task_id])

    aggregated: dict[str, dict] = {"new": {}, "modified": {}, "deleted": {}}
    for filepath, (change_type, task_ids) in file_state.items():
        aggregated[change_type][filepath] = task_ids

    return {
        "new": aggregated["new"],
        "modified": aggregated["modified"],
        "deleted": aggregated["deleted"],
        "total_additions": total_additions,
        "total_deletions": total_deletions,
    }


def _format_file_list(file_map: dict[str, list[int]], max_inline: int = 8) -> str:
    """Format a file->task_ids map into a compact inline string."""
    parts = []
    for filepath, task_ids in sorted(file_map.items()):
        task_refs = ", ".join(f"#{tid}" for tid in task_ids)
        safe_path = filepath.replace("`", r"\`")
        parts.append(f"`{safe_path}`（Task {task_refs}）")
    if len(parts) <= max_inline:
        return "、".join(parts)
    shown = "、".join(parts[:max_inline])
    return f"{shown} 等 {len(parts)} 个文件"


def _build_mr_description(issue: Issue, all_tasks: list, metadata_map: dict[int, dict]) -> str:
    """Build the full MR description string."""
    settings = get_settings()

    status_icons = {
        TaskStatus.PENDING: "⏳",
        TaskStatus.QUEUED: "📋",
        TaskStatus.RUNNING: "🔄",
        TaskStatus.COMPLETED: "✅",
        TaskStatus.FAILED: "❌",
        TaskStatus.CANCELLED: "🚫",
    }

    lines: list[str] = []

    # Issue description (MR title is already set to issue.title, so no need to repeat it here)
    if issue.description:
        lines.append(issue.description)
        lines.append("")

    # Link to Codify issue details page
    dashboard_url = (settings.dashboard_url or "").rstrip("/")
    if dashboard_url:
        lines.append(f"🔗 [在 Codify 中查看 Issue]({dashboard_url}/issues/{issue.id})")
        lines.append("")

    lines.append("---")
    lines.append("")

    # Aggregated summary section (only when metadata is available)
    if metadata_map:
        agg = build_aggregated_file_summary(metadata_map)
        total_add = agg["total_additions"]
        total_del = agg["total_deletions"]
        n_tasks = len(all_tasks)
        lines.append(f"## 📋 整体变更（{n_tasks} 个任务，+{total_add} -{total_del}）")
        lines.append("")

        if agg["new"]:
            lines.append(f"**新增文件** ({len(agg['new'])})：{_format_file_list(agg['new'])}")
            lines.append("")
        if agg["modified"]:
            lines.append(f"**修改文件** ({len(agg['modified'])})：{_format_file_list(agg['modified'])}")
            lines.append("")
        if agg["deleted"]:
            lines.append(f"**删除文件** ({len(agg['deleted'])})：{_format_file_list(agg['deleted'])}")
            lines.append("")

        lines.append("---")
        lines.append("")

    # Execution record table
    lines.append("## 🔖 执行记录")
    lines.append("")
    lines.append("| # | 状态 | 提交说明 | 变更 |")
    lines.append("|---|------|----------|------|")

    for t in all_tasks:
        icon = status_icons.get(t.status, "❓")
        status_label = t.status.value if t.status else "unknown"
        # Prefer commit_message from metadata, fall back to DB field
        meta = metadata_map.get(t.id, {})
        commit_msg = (meta.get("commit_message") or t.commit_message or "—").split("\n")[0].strip()
        if len(commit_msg) > 72:
            commit_msg = commit_msg[:72] + "..."
        commit_msg = commit_msg.replace("|", "\\|")
        add = int(meta.get("additions") or t.additions or 0)
        del_ = int(meta.get("deletions") or t.deletions or 0)
        change_str = f"+{add} -{del_}" if (add or del_) else "—"
        lines.append(f"| {t.id} | {icon} {status_label} | {commit_msg} | {change_str} |")

    lines.append("")

    # Per-task details blocks
    for t in all_tasks:
        meta = metadata_map.get(t.id)
        if not meta:
            continue
        icon = status_icons.get(t.status, "❓")
        commit_msg_first = (meta.get("commit_message") or "").split("\n")[0].strip()
        if len(commit_msg_first) > 72:
            commit_msg_first = commit_msg_first[:72] + "..."
        add = int(meta.get("additions") or 0)
        del_ = int(meta.get("deletions") or 0)
        change_str = f"+{add} -{del_}" if (add or del_) else ""
        summary_title = f"{icon} Task #{t.id}"
        if commit_msg_first:
            summary_title += f" — {commit_msg_first}"
        if change_str:
            summary_title += f" ({change_str})"

        lines.append(f"<details><summary>{summary_title}</summary>")
        lines.append("")
        prompt = (meta.get("prompt") or t.user_prompt or "").strip()
        if len(prompt) > 2000:
            prompt = prompt[:2000] + "..."
        if prompt:
            lines.append(f"**目标**：{prompt}")
            lines.append("")
        execution_summary = (meta.get("execution_summary") or "").strip()
        # Escape closing tags that could break the <details> block rendering
        execution_summary = execution_summary.replace("</details>", "&lt;/details&gt;")
        if execution_summary:
            lines.append(execution_summary)
            lines.append("")
        commit_sha = (meta.get("commit_sha") or t.commit_sha or "").strip()
        if commit_sha:
            lines.append(f"Commit: `{commit_sha[:12]}`")
            lines.append("")
        lines.append("</details>")
        lines.append("")

    return "\n".join(lines)


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
