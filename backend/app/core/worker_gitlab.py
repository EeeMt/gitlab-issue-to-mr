"""GitLab and notification helpers for worker execution."""

import json
import logging
import os
import re
import time

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


def remove_mr_draft_status_for_issue(task: Task, issue: Issue, gitlab_client, *, sudo_gl: Gitlab | None = None) -> None:
    gl = sudo_gl or gitlab_client.gl
    t0 = time.monotonic()
    project = gl.projects.get(task.project_id)
    t1 = time.monotonic()
    mr = project.mergerequests.get(issue.merge_request_iid)
    t2 = time.monotonic()
    logger.info(
        f"[Task {task.id}] GitLab: get project ({t1 - t0:.2f}s), "
        f"get MR !{issue.merge_request_iid} ({t2 - t1:.2f}s)"
    )

    title = getattr(mr, "title", "")
    if not isinstance(title, str):
        logger.info(f"[Task {task.id}] Skipping draft removal because MR title is unavailable")
        return

    updated_title = re.sub(r"^(?:\[Draft\]\s*|Draft:\s*|WIP:\s*)", "", title, count=1, flags=re.IGNORECASE).strip()
    mr.draft = False
    if updated_title:
        mr.title = updated_title
    mr.save()
    t3 = time.monotonic()
    logger.info(
        f"[Task {task.id}] Marked MR !{issue.merge_request_iid} ready "
        f"(save: {t3 - t2:.2f}s, total: {t3 - t0:.2f}s)"
    )


def create_mr_if_needed(
    task: Task,
    issue: Issue,
    mr_iid: int | None,
    mr_web_url: str | None,
    gitlab_client,
    *,
    sudo_gl: Gitlab | None = None,
) -> tuple[int | None, str | None]:
    if mr_iid:
        return mr_iid, mr_web_url

    existing = find_existing_mr(task, issue, gitlab_client)
    if existing:
        return existing

    return create_new_mr(task, issue, gitlab_client, sudo_gl=sudo_gl)


def find_existing_mr(task: Task, issue: Issue, gitlab_client) -> tuple[int | None, str | None] | None:
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


def create_new_mr(task: Task, issue: Issue, gitlab_client, *, sudo_gl: Gitlab | None = None) -> tuple[int | None, str | None]:
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
    sudo_gl: Gitlab | None = None,
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

        t0 = time.monotonic()
        gl = sudo_gl or gitlab_client.gl
        project = gl.projects.get(task.project_id)
        try:
            mr = project.mergerequests.get(mr_iid)
        except Exception:
            logger.warning(f"Could not find MR !{mr_iid} to update description")
            return

        overall_summary = _latest_overall_summary(all_tasks, metadata_map)
        overall_summary_source = "task_metadata" if overall_summary else "none"
        if not overall_summary:
            overall_summary = _extract_existing_overall_summary(getattr(mr, "description", "") or "")
            if overall_summary:
                overall_summary_source = "existing_mr_description"
        logger.info(
            f"[Task {task.id}] Overall MR summary source: {overall_summary_source} "
            f"(chars={len(overall_summary or '')})"
        )
        description = _build_mr_description(
            issue,
            all_tasks,
            metadata_map,
            overall_summary=overall_summary,
        )

        mr.description = description
        if issue.title:
            mr.title = issue.title
        mr.save()
        elapsed = time.monotonic() - t0
        logger.info(
            f"[Task {task.id}] Updated MR !{mr_iid} title+description with issue #{issue.id} context "
            f"({len(all_tasks)} tasks, {len(metadata_map)} with metadata) — total update: {elapsed:.2f}s"
        )

    except Exception as e:
        logger.warning(f"[Task {task.id}] Failed to update MR description: {e}")


def _resolve_issue_root(settings, issue: Issue, all_tasks: list) -> str | None:
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


async def write_previous_task_summaries_file(
    db: AsyncSession,
    settings,
    issue: Issue,
    task: Task,
) -> str | None:
    """Write previous task summaries for the worker-side overall MR summary prompt."""
    try:
        from app.core.worker_workspace import build_issue_workspace_paths

        workspace_root = getattr(settings, "worker_workspace_host_path", "") or ""
        if not isinstance(workspace_root, str) or not workspace_root.strip():
            logger.debug(
                f"[Task {task.id}] Workspace root not configured; previous summaries unavailable"
            )
            return None

        paths = build_issue_workspace_paths(settings, issue, task)
        if paths is None:
            logger.debug(
                f"[Task {task.id}] Workspace root not configured; previous summaries unavailable"
            )
            return None

        previous_tasks = (await db.execute(
            select(Task)
            .where(Task.issue_id == issue.id, Task.id < task.id)
            .order_by(Task.id)
        )).scalars().all()
        metadata_map = load_task_metadata_files(paths.issue_root, [t.id for t in previous_tasks])
        previous_task_ids = [t.id for t in previous_tasks]
        logger.info(
            f"[Task {task.id}] Preparing previous task summaries "
            f"(previous_task_ids={previous_task_ids}, metadata_task_ids={sorted(metadata_map)})"
        )
        content = _build_previous_task_summaries_content(issue, previous_tasks, metadata_map)

        os.makedirs(paths.runtime_path, exist_ok=True)
        path = os.path.join(paths.runtime_path, "previous-task-summaries.md")
        with open(path, "w", encoding="utf-8") as f:
            f.write(content)

        logger.info(
            f"[Task {task.id}] Wrote previous task summaries to {path} "
            f"({len(previous_tasks)} previous task(s), {len(metadata_map)} with metadata)"
        )
        return path
    except Exception as exc:
        logger.warning(f"[Task {task.id}] Failed to write previous task summaries: {exc}")
        return None


def _compact_summary_text(value: str, max_chars: int = 500) -> str:
    """Collapse task summary text into a compact one-line MR description snippet."""
    text = re.sub(r"\s+", " ", (value or "").strip())
    text = text.replace("</details>", "&lt;/details&gt;")
    if len(text) > max_chars:
        return text[:max_chars].rstrip() + "..."
    return text


def _build_previous_task_summaries_content(
    issue: Issue,
    previous_tasks: list,
    metadata_map: dict[int, dict],
) -> str:
    """Build the markdown file mounted into the worker for cross-task summarization."""
    lines = [
        "# Previous Task Summaries",
        "",
        f"Issue: {issue.title or '无'}",
    ]
    issue_description = _compact_summary_text(str(issue.description or ""), 1000)
    if issue_description:
        lines.extend([f"Issue description: {issue_description}", ""])
    else:
        lines.append("")

    if not previous_tasks:
        lines.append("暂无前序任务摘要。")
        lines.append("")
        return "\n".join(lines)

    for previous_task in previous_tasks:
        meta = metadata_map.get(previous_task.id, {})
        status_label = previous_task.status.value if previous_task.status else "unknown"
        prompt = _compact_summary_text(str(meta.get("prompt") or previous_task.user_prompt or ""), 300)
        commit_msg = _compact_summary_text(
            str(meta.get("commit_message") or previous_task.commit_message or ""),
            200,
        )
        summary = _compact_summary_text(
            str(meta.get("execution_summary") or commit_msg or prompt or ""),
            1500,
        )
        lines.extend([
            f"## Task #{previous_task.id}",
            f"- 状态: {status_label}",
            f"- 目标: {prompt or '无'}",
            f"- 提交说明: {commit_msg or '无'}",
            f"- 执行摘要: {summary or '无'}",
            "",
        ])

    return "\n".join(lines)


def _latest_overall_summary(all_tasks: list, metadata_map: dict[int, dict]) -> str | None:
    """Return the newest worker-generated overall summary in task metadata."""
    for task in reversed(list(all_tasks)):
        meta = metadata_map.get(task.id)
        if not meta:
            continue
        summary = str(meta.get("overall_summary") or "").strip()
        if summary:
            return summary.replace("</details>", "&lt;/details&gt;")
    return None


def _extract_existing_overall_summary(description: str) -> str | None:
    """Return the existing overall summary block from a GitLab MR description."""
    if not description:
        return None

    marker = "## 📋 总体总结"
    start = description.find(marker)
    if start == -1:
        return None

    body_start = start + len(marker)
    remaining = description[body_start:].lstrip()
    for delimiter in ("\n---\n", "\n## "):
        delimiter_index = remaining.find(delimiter)
        if delimiter_index != -1:
            remaining = remaining[:delimiter_index]
            break

    summary = remaining.strip()
    return summary or None


def _build_mr_description(
    issue: Issue,
    all_tasks: list,
    metadata_map: dict[int, dict],
    *,
    overall_summary: str | None = None,
) -> str:
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

    # Cross-task summary generated by the worker and stored in task metadata.
    if overall_summary:
        lines.append("## 📋 总体总结")
        lines.append("")
        lines.append(overall_summary)
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


async def send_failure_alert(task: Task, sanitize_sensitive_data, issue: Issue | None = None) -> None:
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


async def send_notifications(task: Task, gitlab_client, sanitize_sensitive_data, success: bool, had_existing_mr: bool, issue: Issue | None = None) -> None:
    try:
        await notify_task_event(task, MATTERMOST_EVENT_TASK_COMPLETED)
    except Exception as e:
        logger.warning(f"Failed to send Mattermost completion notification: {e}")


async def send_failure_notifications(task: Task, gitlab_client, sanitize_sensitive_data, success: bool, had_existing_mr: bool, issue: Issue | None = None) -> None:
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
