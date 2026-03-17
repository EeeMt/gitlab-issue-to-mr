"""Worker executor for running tasks in Docker containers."""

import asyncio
import json as _json
import logging
import re
import threading
import time
from datetime import datetime
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings, get_effective_settings
from app.core.docker_client import DockerClientWrapper, get_docker_client
from app.core.gitlab_client import GitLabClient, get_gitlab_client
from app.core.mattermost_notifications import (
    MATTERMOST_EVENT_TASK_COMPLETED,
    MATTERMOST_EVENT_TASK_FAILED,
    MATTERMOST_EVENT_TASK_RETRY_SCHEDULED,
    notify_task_event,
)
from app.models import Task, TaskLog, TaskStatus

logger = logging.getLogger(__name__)

# Matches common ANSI/VT100 escape sequences (colors, cursor movement, etc.)
_ANSI_ESCAPE = re.compile(
    r'\x1b\[[0-9;]*[mABCDEFGHJKLMPSTfnsu]'   # CSI sequences (colors, cursor)
    r'|\x1b\][^\x07]*\x07'                     # OSC sequences (title, etc.)
    r'|\x1b[()][A-Z0-9]'                       # Character set selection
    r'|\x1b[@-_]',                             # Two-character ESC sequences
    re.DOTALL,
)

# Emitted by entrypoint.sh after Claude finishes; contains token usage JSON.
_GIMR_STATS_RE = re.compile(r'^GIMR_STATS:(.+)$', re.MULTILINE)
# Emitted by entrypoint.sh; git-computed change stats (e.g. GIMR_DIFF:+18-21).
_GIMR_DIFF_RE = re.compile(r'^GIMR_DIFF:\+(\d+)-(\d+)$', re.MULTILINE)

def scrub_sensitive_data(text: str) -> str:
    """Redact credentials (tokens, API keys) from text, preserving ANSI codes and Unicode.

    Use this for log content that will be stored in the DB and rendered in the UI.
    """
    if not text:
        return text

    # Remove GitLab personal access tokens (glpat-*)
    text = re.sub(r'glpat-[a-zA-Z0-9\-]{10,}', '[GITLAB_TOKEN]', text)

    # Remove Anthropic API keys (sk-*, sk-ant-*)
    text = re.sub(r'sk-(?:cp|ant|api)-[a-zA-Z0-9\-]{10,}', '[ANTHROPIC_API_KEY]', text)

    # Remove Authorization headers
    text = re.sub(r'(PRIVATE-TOKEN:\s*)[^\s]+', r'\1[REDACTED]', text)

    # Remove null bytes
    text = text.replace('\x00', '')

    return text


def sanitize_sensitive_data(text: str) -> str:
    """Redact credentials and strip ANSI codes from text.

    Use this for error messages and other plain-text fields.
    For log storage use scrub_sensitive_data() to preserve ANSI and emoji.
    """
    if not text:
        return text

    text = scrub_sensitive_data(text)

    # Strip ANSI escape codes (colors, cursor movement)
    text = _ANSI_ESCAPE.sub('', text)

    # Remove Unicode non-characters (surrogates, BOM variants).
    # NOTE: do NOT filter by codepoint >= 0xFFFD — that would drop emoji.
    text = re.sub(r'[\ud800-\udfff\ufffe\uffff]', '', text)

    return text


def get_settings():
    """Get effective settings with runtime overrides."""
    return get_effective_settings()


class WorkerExecutor:
    """Worker executor that runs tasks in Docker containers."""

    def __init__(
        self,
        docker_client: Optional[DockerClientWrapper] = None,
        gitlab_client: Optional[GitLabClient] = None,
    ):
        """Initialize worker executor.

        Args:
            docker_client: Docker client instance
            gitlab_client: GitLab client instance
        """
        self.docker = docker_client or get_docker_client()
        self.gitlab = gitlab_client or get_gitlab_client()

    def _build_initial_mr_title(self, task: Task) -> str:
        """Build a reasonable initial MR title before AI execution finishes."""
        if task.issue_iid:
            try:
                issue_info = self.gitlab.get_issue(task.project_id, task.issue_iid)
                issue_title = (issue_info or {}).get("title", "").strip() if issue_info else ""
                if issue_title:
                    return f"AI: {issue_title[:100]}"
            except Exception as e:
                logger.warning(f"[Task {task.id}] Failed to fetch issue title for MR title: {e}")

        prompt = re.sub(r"\s+", " ", task.user_prompt or "").strip()
        if prompt:
            short_prompt = re.split(r"[;\n。！？.!?]", prompt, maxsplit=1)[0].strip()
            if short_prompt:
                return f"AI: {short_prompt[:100]}"

        return f"AI: Task {task.id}"

    def _build_initial_mr_description(self, task: Task) -> str:
        """Build the initial MR description shown while the worker is running."""
        description = f"""## 🚀 AI 正在执行

### 需求
{task.user_prompt}

---
*AI 正在直接实施变更...*"""

        if task.issue_iid:
            description += f"\n\nCloses #{task.issue_iid}"

        return description

    def _remove_mr_draft_status(self, task: Task) -> None:
        """Remove draft status from an MR by normalizing its title."""
        project = self.gitlab.gl.projects.get(task.project_id)
        mr = project.mergerequests.get(task.merge_request_iid)

        title = getattr(mr, "title", "")
        if not isinstance(title, str):
            logger.info(f"[Task {task.id}] Skipping draft removal because MR title is unavailable")
            return

        updated_title = re.sub(r"^(?:\[Draft\]\s*|Draft:\s*|WIP:\s*)", "", title, count=1, flags=re.IGNORECASE).strip()
        if not updated_title or updated_title == title:
            logger.info(f"[Task {task.id}] MR !{task.merge_request_iid} is already non-draft")
            return

        mr.title = updated_title
        mr.save()
        logger.info(f"[Task {task.id}] Removed draft status from MR !{task.merge_request_iid}")

    async def _flush_log_chunk(
        self,
        task_id: int,
        lines: list[str],
        chunk_index: int,
        db: AsyncSession,
    ) -> None:
        """Save a batch of log lines as a TaskLog entry."""
        content = scrub_sensitive_data("".join(lines)).strip()
        if not content:
            return
        if len(content) > 8000:
            content = content[:8000]
        db.add(TaskLog(task_id=task_id, log_level="INFO", message=content))
        await db.commit()
        logger.debug(f"[Task {task_id}] Saved log chunk {chunk_index} ({len(lines)} lines)")

    async def _stream_logs_to_db(
        self,
        container: Any,
        task_id: int,
        db: AsyncSession,
        timeout: int,
    ) -> tuple[int, str, int]:
        """Stream container logs to TaskLog entries while waiting for completion.

        Saves log chunks to the DB every FLUSH_INTERVAL seconds so users can
        monitor execution progress in real-time without waiting for the container
        to finish. Returns (exit_code, full_log_string, chunks_saved).
        """
        FLUSH_INTERVAL = 10.0   # seconds between DB flushes
        MAX_BUFFER_LINES = 200  # also flush when buffer hits this many lines

        loop = asyncio.get_running_loop()
        log_queue: asyncio.Queue = asyncio.Queue()

        def _stream_thread() -> None:
            """Background thread: reads Docker log stream and enqueues chunks."""
            try:
                for chunk in container.logs(
                    stdout=True, stderr=True, follow=True, stream=True
                ):
                    loop.call_soon_threadsafe(log_queue.put_nowait, chunk)
            except Exception as exc:
                logger.debug(f"[Task {task_id}] Log stream thread error: {exc}")
            finally:
                loop.call_soon_threadsafe(log_queue.put_nowait, None)  # sentinel

        stream_thread = threading.Thread(target=_stream_thread, daemon=True)
        stream_thread.start()

        buffer: list[str] = []
        all_lines: list[str] = []
        last_flush = time.monotonic()
        chunk_index = 0
        deadline = time.monotonic() + timeout

        while True:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                logger.warning(f"[Task {task_id}] Log stream timed out after {timeout}s")
                if buffer:
                    await self._flush_log_chunk(task_id, buffer, chunk_index, db)
                    chunk_index += 1
                stream_thread.join(timeout=2)
                return -1, "".join(all_lines), chunk_index

            try:
                item = await asyncio.wait_for(log_queue.get(), timeout=min(remaining, 2.0))
            except asyncio.TimeoutError:
                # No new data; flush buffer if interval elapsed
                now = time.monotonic()
                if buffer and (now - last_flush) >= FLUSH_INTERVAL:
                    await self._flush_log_chunk(task_id, buffer, chunk_index, db)
                    chunk_index += 1
                    buffer = []
                    last_flush = now
                continue

            if item is None:
                # Sentinel: stream ended because container stopped
                break

            line = item.decode("utf-8", errors="replace")
            buffer.append(line)
            all_lines.append(line)

            now = time.monotonic()
            if len(buffer) >= MAX_BUFFER_LINES or (now - last_flush) >= FLUSH_INTERVAL:
                await self._flush_log_chunk(task_id, buffer, chunk_index, db)
                chunk_index += 1
                buffer = []
                last_flush = now

        # Flush any remaining lines
        if buffer:
            await self._flush_log_chunk(task_id, buffer, chunk_index, db)
            chunk_index += 1

        stream_thread.join(timeout=5)

        # Container stopped (stream ended); get exit code
        try:
            result = await asyncio.to_thread(container.wait, timeout=30)
            exit_code = result.get("StatusCode", 1)
        except Exception as exc:
            logger.warning(f"[Task {task_id}] container.wait() error: {exc}")
            exit_code = -1

        logger.info(
            f"[Task {task_id}] Log streaming complete: {chunk_index} chunks, exit_code={exit_code}"
        )
        return exit_code, "".join(all_lines), chunk_index

    async def execute_task(self, db: AsyncSession, task_id: int) -> bool:
        """Execute a task.

        Args:
            db: Database session
            task_id: Task ID to execute

        Returns:
            True if successful, False otherwise
        """
        # Get settings
        settings = get_settings()

        # Fetch task
        result = await db.execute(select(Task).where(Task.id == task_id))
        task = result.scalar_one_or_none()

        if not task:
            logger.error(f"[Task {task_id}] Task not found in database")
            return False

        logger.info(f"[Task {task_id}] Executing for project={task.project_id} issue_iid={task.issue_iid} priority={task.priority}")
        had_existing_mr = task.merge_request_iid is not None

        # Update task status to running
        task.status = TaskStatus.RUNNING
        task.started_at = datetime.utcnow()
        await db.commit()

        # Send "starting" notification to issue
        try:
            self._notify_task_started(task)
        except Exception as e:
            logger.warning(f"Failed to send start notification: {e}")

        container = None

        try:
            # Pull worker image (force pull for development)
            try:
                self.docker.pull_image(settings.worker_image, force=True)
            except Exception as e:
                logger.warning(f"Failed to pull image: {e}, trying to use existing")

            # Prepare environment variables
            target_branch = task.target_branch or settings.default_target_branch

            mr_title = self._build_initial_mr_title(task)

            # Create initial MR (draft) before running worker so execution can update it
            # For continuation tasks (existing merge_request_iid), use existing MR
            mr_iid = task.merge_request_iid  # Use existing MR for continuation tasks
            mr_web_url = task.merge_request_url

            if not mr_iid:
                try:
                    existing_mrs = self.gitlab.gl.projects.get(task.project_id).mergerequests.list(
                        source_branch=task.branch_name,
                        state="opened",
                    )
                    if existing_mrs:
                        mr_iid = existing_mrs[0].iid
                        mr_web_url = self.gitlab.normalize_web_url(existing_mrs[0].web_url)
                        task.merge_request_iid = mr_iid
                        task.merge_request_url = mr_web_url
                        await db.commit()
                        logger.info(f"[Task {task_id}] Reusing existing MR !{mr_iid} for branch {task.branch_name}")
                except Exception as e:
                    logger.warning(f"[Task {task_id}] Failed to look up existing MR: {e}")

            if not mr_iid:
                # No existing MR - create a new one
                try:
                    initial_mr_desc = self._build_initial_mr_description(task)

                    mr_response = self.gitlab.gl.projects.get(task.project_id).mergerequests.create({
                        "source_branch": task.branch_name,
                        "target_branch": target_branch,
                        "title": mr_title,
                        "description": initial_mr_desc,
                        "draft": True,  # Create as draft MR
                    })
                    mr_iid = mr_response.iid
                    mr_web_url = self.gitlab.normalize_web_url(mr_response.web_url)
                    task.merge_request_iid = mr_iid
                    task.merge_request_url = mr_web_url
                    await db.commit()
                    logger.info(f"[Task {task_id}] Created initial draft MR !{mr_iid}")
                except Exception as e:
                    logger.warning(f"[Task {task_id}] Failed to create initial MR: {e}, continuing without MR")

            environment = {
                "GITLAB_URL": settings.gitlab_url,
                "GITLAB_TOKEN": settings.gitlab_bot_token,
                "PROJECT_ID": str(task.project_id),
                "BRANCH_NAME": task.branch_name,
                "USER_PROMPT": task.user_prompt,
                "TARGET_BRANCH": target_branch,
                "ANTHROPIC_BASE_URL": settings.anthropic_base_url,
                "ANTHROPIC_API_KEY": settings.anthropic_api_key,
                "ANTHROPIC_MODEL": settings.anthropic_model,
                "CLAUDE_MAX_TURNS": str(settings.claude_max_turns),
                "TASK_ID": str(task.id),
            }

            # Add optional fields for webhook-triggered tasks
            if task.issue_iid:
                environment["ISSUE_IID"] = str(task.issue_iid)

            # Add BASE_BRANCH if task specifies a source branch to fork from
            if task.base_branch:
                environment["BASE_BRANCH"] = task.base_branch

            # Pass MR_IID to worker so execution can update the MR description
            if mr_iid:
                environment["MR_IID"] = str(mr_iid)

            # Generate container name with naming convention: gimr-{id}-p{pid}-[i{iid}|manual]
            issue_suffix = f"i{task.issue_iid}" if task.issue_iid else "manual"
            container_name = f"gimr-{task.id}-p{task.project_id}-{issue_suffix}"

            # Create and run container
            volumes: dict = {}
            if settings.maven_cache_host_path:
                volumes[settings.maven_cache_host_path] = {
                    "bind": "/home/gimr/.m2/repository",
                    "mode": "rw",
                }
            if settings.maven_settings_host_path:
                volumes[settings.maven_settings_host_path] = {
                    "bind": "/home/gimr/.m2/settings.xml",
                    "mode": "ro",
                }

            container = self.docker.create_container(
                image=settings.worker_image,
                command="",
                environment=environment,
                volumes=volumes if volumes else None,
                network="bridge",
                name=container_name,
            )

            # Track container ID in task
            task.container_id = container.id
            await db.commit()

            # Stream logs to DB while waiting for container to finish
            exit_code, logs, log_chunks_saved = await self._stream_logs_to_db(
                container, task.id, db, settings.task_timeout
            )

            # Extract token usage from GIMR_STATS marker line
            stats_match = _GIMR_STATS_RE.search(logs)
            if stats_match:
                try:
                    usage = _json.loads(stats_match.group(1).strip())
                    task.input_tokens = usage.get('input_tokens')
                    task.output_tokens = usage.get('output_tokens')
                    logger.info(
                        f"[Task {task_id}] Token usage: "
                        f"in={task.input_tokens} out={task.output_tokens}"
                    )
                except Exception:
                    logger.debug(f"[Task {task_id}] Failed to parse GIMR_STATS")

            # Process results
            if exit_code == 0:
                task.status = TaskStatus.COMPLETED
                task.completed_at = datetime.utcnow()
                # Parse MR URL from logs
                # Try to find web_url in any line of logs
                for line in logs.split("\n"):
                    if "/merge_requests/" in line:
                        # Extract URL from line containing merge_requests
                        match = re.search(r'http[^\s]*merge_requests/\d+', line)
                        if match:
                            task.merge_request_url = self.gitlab.normalize_web_url(match.group(0))
                            iid_match = re.search(r'/merge_requests/(\d+)', match.group(0))
                            if iid_match:
                                task.merge_request_iid = int(iid_match.group(1))
                            break

                # If URL is present but IID is still missing, derive it from the URL.
                if task.merge_request_url and not task.merge_request_iid:
                    iid_match = re.search(r'/merge_requests/(\d+)', task.merge_request_url)
                    if iid_match:
                        task.merge_request_iid = int(iid_match.group(1))

                # If not found in logs, try to get MR from GitLab API by branch name
                if not task.merge_request_iid or not task.merge_request_url:
                    try:
                        mrs = self.gitlab.gl.projects.get(task.project_id).mergerequests.list(
                            source_branch=task.branch_name,
                            state='opened'
                        )
                        if mrs:
                            task.merge_request_iid = mrs[0].iid
                            task.merge_request_url = self.gitlab.normalize_web_url(mrs[0].web_url)
                    except Exception as e:
                        logger.warning(f"Failed to get MR from API: {e}")

                logger.info(f"Task {task_id} completed successfully")

                # Get MR change stats — prefer log-parsed git diff (accurate), fall back to GitLab API.
                diff_match = _GIMR_DIFF_RE.search(logs)
                if diff_match:
                    task.additions = int(diff_match.group(1))
                    task.deletions = int(diff_match.group(2))
                    task.total_changes = task.additions + task.deletions
                    logger.info(
                        f"[Task {task_id}] Diff stats (from log): "
                        f"+{task.additions} -{task.deletions} ({task.total_changes} total)"
                    )
                elif task.merge_request_iid:
                    try:
                        logger.info(f"[Task {task_id}] Getting MR stats for MR !{task.merge_request_iid}")
                        stats = self.gitlab.get_merge_request_stats(
                            task.project_id, task.merge_request_iid
                        )
                        logger.info(f"[Task {task_id}] MR stats result: {stats}")
                        if stats:
                            task.additions = stats.get("additions", 0)
                            task.deletions = stats.get("deletions", 0)
                            task.total_changes = stats.get("total", 0)
                            logger.info(
                                f"[Task {task_id}] MR stats (from API): "
                                f"+{task.additions} -{task.deletions} ({task.total_changes} total)"
                            )
                        else:
                            logger.warning(f"[Task {task_id}] MR stats returned None")
                    except Exception as e:
                        logger.warning(f"[Task {task_id}] Failed to get MR stats: {e}")

                # Remove draft status from MR if it was created
                if task.merge_request_iid:
                    try:
                        self._remove_mr_draft_status(task)
                    except Exception as e:
                        logger.warning(f"[Task {task_id}] Failed to update MR draft status: {e}")

                # Send "completed" notification with MR URL
                try:
                    self._notify_task_completed(task, success=True, notify_target="mr" if had_existing_mr else "issue")
                except Exception as e:
                    logger.warning(f"Failed to send completion notification: {e}")
                try:
                    await notify_task_event(task, MATTERMOST_EVENT_TASK_COMPLETED)
                except Exception as e:
                    logger.warning(f"Failed to send Mattermost completion notification: {e}")
            else:
                task.status = TaskStatus.FAILED
                task.completed_at = datetime.utcnow()
                task.error_message = sanitize_sensitive_data(logs)[-1000:]
                logger.error(f"[Task {task_id}] Failed with exit code {exit_code}")

                # Check if we should retry
                settings = get_settings()
                if settings.max_retries > 0 and task.retry_count < settings.max_retries:
                    # Schedule retry
                    previous_scheduled_at = task.scheduled_at
                    task.retry_count += 1
                    task.status = TaskStatus.PENDING
                    task.scheduled_at = datetime.utcnow()
                    logger.info(f"[Task {task_id}] Scheduling retry {task.retry_count}/{settings.max_retries}")

                # Send "failed" notification
                try:
                    self._notify_task_completed(task, success=False, notify_target="mr" if had_existing_mr else "issue")
                except Exception as e:
                    logger.warning(f"Failed to send failure notification: {e}")
                try:
                    if task.status == TaskStatus.PENDING:
                        await notify_task_event(
                            task,
                            MATTERMOST_EVENT_TASK_RETRY_SCHEDULED,
                            context={
                                "previous_scheduled_at": previous_scheduled_at,
                                "scheduled_at": task.scheduled_at,
                            },
                        )
                    else:
                        await notify_task_event(task, MATTERMOST_EVENT_TASK_FAILED)
                except Exception as e:
                    logger.warning(f"Failed to send Mattermost failure notification: {e}")

            # Save a final log entry for failures, or for very fast tasks with no
            # streaming chunks (e.g., container exited immediately).
            scrubbed_logs = scrub_sensitive_data(logs)
            if exit_code != 0:
                task.error_message = sanitize_sensitive_data(logs)[-1000:]
                log_entry = TaskLog(
                    task_id=task.id,
                    log_level="ERROR",
                    message=f"[Exit code: {exit_code}]\n{scrubbed_logs[-2000:]}",
                )
                db.add(log_entry)
            elif log_chunks_saved == 0:
                # No streaming chunks were flushed (very fast / empty output)
                log_entry = TaskLog(
                    task_id=task.id,
                    log_level="INFO",
                    message=scrubbed_logs[-4000:] or "[No output]",
                )
                db.add(log_entry)

            await db.commit()

            # Cleanup container
            try:
                self.docker.remove_container(container, force=True)
            except Exception as e:
                logger.warning(f"Failed to remove container: {e}")

            return exit_code == 0

        except Exception as e:
            logger.exception(f"Task {task_id} failed with exception: {e}")
            task.status = TaskStatus.FAILED
            task.completed_at = datetime.utcnow()
            # Sanitize error message
            task.error_message = sanitize_sensitive_data(str(e))[:1000]
            await db.commit()

            # Cleanup container on exception
            if container:
                try:
                    self.docker.remove_container(container, force=True)
                    logger.info(f"Cleaned up container after exception: {container.id}")
                except Exception as cleanup_error:
                    logger.warning(f"Failed to cleanup container: {cleanup_error}")

            # Send failure notification for exceptions
            try:
                self._notify_task_completed(task, success=False, notify_target="mr" if had_existing_mr else "issue")
            except Exception as notify_error:
                logger.warning(f"Failed to send failure notification: {notify_error}")
            try:
                await notify_task_event(task, MATTERMOST_EVENT_TASK_FAILED)
            except Exception as notify_error:
                logger.warning(f"Failed to send Mattermost failure notification: {notify_error}")

            return False

    def _notify_task_started(self, task: Task) -> None:
        """Send notification when task starts execution.

        Args:
            task: Task object
        """
        # Skip notifications for manual tasks (no issue to notify)
        if task.is_manual:
            logger.info(f"Skipping start notification for manual task {task.id}")
            return

        settings = get_settings()
        task_url = f"{settings.dashboard_url}/tasks/{task.id}"
        message = f"🔄 开始处理请求... [任务 {task.id}]({task_url})"
        if task.merge_request_iid:
            self.gitlab.create_mr_note(
                task.project_id,
                task.merge_request_iid,
                message,
            )
            logger.info(f"Sent start notification to MR !{task.merge_request_iid} for task {task.id}")
        elif task.issue_iid:
            self.gitlab.create_note(
                task.project_id,
                task.issue_iid,
                message,
            )
            logger.info(f"Sent start notification for task {task.id}")

    def _notify_task_completed(self, task: Task, success: bool, notify_target: str = "issue") -> None:
        """Send notification when task completes.

        Args:
            task: Task object
            success: Whether the task succeeded
            notify_target: Target discussion, either "issue" or "mr"
        """
        # Skip notifications for manual tasks (no issue to notify)
        if task.is_manual:
            logger.info(f"Skipping completion notification for manual task {task.id}")
            return

        mr_iid = task.merge_request_iid
        settings = get_settings()
        task_url = f"{settings.dashboard_url}/tasks/{task.id}"

        if success:
            if task.merge_request_url:
                # Extract MR IID from URL if not already set
                if not mr_iid and "/merge_requests/" in task.merge_request_url:
                    try:
                        mr_iid = task.merge_request_url.split("/merge_requests/")[-1].split("/")[0].split("?")[0]
                    except (IndexError, ValueError):
                        pass

                if mr_iid:
                    message = f"✅ 代码已更新到 MR !{mr_iid} [任务 {task.id}]({task_url})"
                else:
                    message = f"✅ MR 已更新: [任务 {task.id}]({task_url})"
            else:
                message = f"✅ 任务已完成 [任务 {task.id}]({task_url})"
        else:
            error_msg = task.error_message[:200] if task.error_message else "未知错误"
            # Double sanitization for messages sent to external systems
            error_msg = sanitize_sensitive_data(error_msg)
            message = f"❌ 任务失败 [任务 {task.id}]({task_url}): {error_msg}"

        # Send notification to the original trigger discussion.
        if notify_target == "mr" and mr_iid:
            self.gitlab.create_mr_note(task.project_id, mr_iid, message)
            logger.info(f"Sent completion notification to MR !{mr_iid} for task {task.id}, success={success}")

            # Update MR description with execution progress
            if success:
                try:
                    self._update_mr_description(task, mr_iid)
                except Exception as e:
                    logger.warning(f"Failed to update MR description: {e}")
        elif task.issue_iid:
            self.gitlab.create_note(
                task.project_id,
                task.issue_iid,
                message,
            )
            logger.info(f"Sent completion notification for task {task.id}, success={success}")

        # Send webhook alert if configured
        if not success:
            self._send_failure_alert(task)

    def _update_mr_description(self, task: Task, mr_iid: int) -> None:
        """Update MR description with execution progress.

        Args:
            task: Task object
            mr_iid: MR IID to update
        """
        # Get current MR details
        mr = self.gitlab.get_merge_request(task.project_id, mr_iid)
        if not mr:
            logger.warning(f"Could not find MR !{mr_iid} to update description")
            return

        current_desc = mr.description or ""

        # Parse current description to find execution progress section
        execution_section = "\n---\n### 执行进度"

        if execution_section in current_desc:
            # Update existing section - append new progress
            progress_update = f"\n- [x] 继续修改任务完成 (任务 {task.id})"
            # Find position after "### 执行进度" and before next "---"
            idx = current_desc.find(execution_section)
            # Find next "---" after the section header
            next_section = current_desc.find("\n---", idx + len(execution_section))
            if next_section > 0:
                new_desc = current_desc[:next_section] + progress_update + current_desc[next_section:]
            else:
                new_desc = current_desc + progress_update
        else:
            # Add new section
            progress_update = f"{execution_section}\n- [x] 继续修改任务完成 (任务 {task.id})\n"
            new_desc = current_desc + progress_update

        # Update MR via API
        mr.description = new_desc
        mr.save()
        logger.info(f"Updated MR !{mr_iid} description with task #{task.id} progress")

    def _send_failure_alert(self, task: Task) -> None:
        """Send failure alert to webhook URL.

        Args:
            task: Task object
        """
        settings = get_settings()

        # Check if alerts are enabled
        if not settings.alert_on_failure or not settings.alert_webhook_url:
            return

        # Build alert message
        error_msg = task.error_message[:500] if task.error_message else "Unknown error"
        alert_data = {
            "text": f"🚨 Task Failed",
            "attachments": [{
                "color": "danger",
                "fields": [
                    {"title": "Task ID", "value": str(task.id), "short": True},
                    {"title": "Project ID", "value": str(task.project_id), "short": True},
                    {"title": "Issue", "value": f"!{task.issue_iid}", "short": True},
                    {"title": "Error", "value": error_msg},
                ]
            }]
        }

        # Send webhook request
        try:
            import httpx
            # Note: httpx is already used in the project
            # Using synchronous request for simplicity
            import requests
            response = requests.post(
                settings.alert_webhook_url,
                json=alert_data,
                timeout=10
            )
            if response.status_code < 400:
                logger.info(f"Sent failure alert for task {task.id}")
            else:
                logger.warning(f"Failed to send failure alert: {response.status_code}")
        except Exception as e:
            logger.warning(f"Failed to send failure alert: {e}")

    async def process_pending_tasks(self, db: AsyncSession) -> int:
        """Process all pending tasks.

        Args:
            db: Database session

        Returns:
            Number of tasks processed
        """
        result = await db.execute(
            select(Task).where(Task.status == TaskStatus.PENDING).order_by(Task.created_at)
        )
        tasks = result.scalars().all()

        processed = 0
        for task in tasks:
            success = await self.execute_task(db, task.id)
            if success:
                processed += 1

        return processed
