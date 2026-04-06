"""Worker executor for running tasks in Docker containers."""

import asyncio
import json as _json
import logging
import re
import threading
import time
from datetime import datetime
from typing import Any, Optional

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_effective_settings as get_settings
from app.core.docker_client import DockerClientWrapper, get_docker_client
from app.core.gitlab_client import GitLabClient, get_gitlab_client
from app.core.ssl_utils import get_ssl_verify
from app.core.utcnow import utcnow
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
_CODIFY_STATS_RE = re.compile(r'^CODIFY_STATS:(.+)$', re.MULTILINE)
_CODIFY_COMMIT_SHA_RE = re.compile(r'^CODIFY_COMMIT_SHA:([a-f0-9]{40})$', re.MULTILINE)
# Emitted by entrypoint.sh; git-computed change stats (e.g. CODIFY_DIFF:+18-21).
_CODIFY_DIFF_RE = re.compile(r'^CODIFY_DIFF:\+(\d+)-(\d+)$', re.MULTILINE)
# Emitted by entrypoint.sh after Claude finishes; JSON array of all tool call objects.
_CODIFY_TOOL_CALLS_RE = re.compile(r'^CODIFY_TOOL_CALLS:(.+)$', re.MULTILINE)
# Emitted by ci-claude.sh in real-time after EACH tool completes; single tool call object.
_CODIFY_TOOL_CALL_RE = re.compile(r'^CODIFY_TOOL_CALL:(.+)$')
# Emitted by ci-claude.sh on system init; contains model name and cwd as JSON.
_CODIFY_SYSTEM_INIT_RE = re.compile(r'^CODIFY_SYSTEM_INIT:(.+)$', re.MULTILINE)
# Emitted by entrypoint.sh after AI-generated MR title is determined; plain string.
_CODIFY_MR_TITLE_RE = re.compile(r'^CODIFY_MR_TITLE:(.+)$', re.MULTILINE)
# Emitted by ci-claude.sh in real-time when a thinking block completes; JSON with text.
_CODIFY_THINKING_RE = re.compile(r'^CODIFY_THINKING:(.+)$')
# Emitted by ci-claude.sh in real-time when a text (assistant response) block completes.
_CODIFY_ASSISTANT_TEXT_RE = re.compile(r'^CODIFY_ASSISTANT_TEXT:(.+)$')
# Emitted by ci-claude.sh when a tool_use block completes (name + input); id for correlation.
_CODIFY_TOOL_USE_START_RE = re.compile(r'^CODIFY_TOOL_USE_START:(.+)$')
# Emitted by ci-claude.sh when a tool_result arrives in a user message; correlates via id.
_CODIFY_TOOL_RESULT_RE = re.compile(r'^CODIFY_TOOL_RESULT:(.+)$')

# Volume mount constants
_MAVEN_CACHE_CONTAINER_PATH = "/home/codify/.m2/repository"
_MAVEN_SETTINGS_CONTAINER_PATH = "/home/codify/.m2/settings.xml"


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
        # Maps tool_use id → TaskLog.id for correlating tool results with their calls
        pending_tool_uses: dict[str, int] = {}

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

            stripped = line.rstrip('\n\r')

            # CODIFY_TOOL_USE_START: tool_use block completed → create a tool_call log entry
            # immediately so the frontend sees it in real-time (output populated later).
            if stripped.startswith('CODIFY_TOOL_USE_START:'):
                match = _CODIFY_TOOL_USE_START_RE.match(stripped)
                if match:
                    try:
                        data = _json.loads(match.group(1))
                        tool_use_id = data.get('id', '')
                        log_entry = TaskLog(
                            task_id=task_id,
                            log_level="INFO",
                            message="",
                            log_type="tool_call",
                            log_metadata=_json.dumps({
                                "name": data.get("name", ""),
                                "input": data.get("input", {}),
                                "output": None,
                                "error": False,
                            }),
                        )
                        db.add(log_entry)
                        await db.flush()   # get auto-assigned ID
                        if tool_use_id and log_entry.id:
                            pending_tool_uses[tool_use_id] = log_entry.id
                        await db.commit()
                        logger.debug(f"[Task {task_id}] Tool use start: {data.get('name')} (id={tool_use_id})")
                    except Exception as exc:
                        logger.debug(f"[Task {task_id}] Failed to parse CODIFY_TOOL_USE_START: {exc}")

            # CODIFY_TOOL_RESULT: tool result arrived → update the matching log entry with output.
            elif stripped.startswith('CODIFY_TOOL_RESULT:'):
                match = _CODIFY_TOOL_RESULT_RE.match(stripped)
                if match:
                    try:
                        data = _json.loads(match.group(1))
                        tool_use_id = data.get('id', '')
                        log_id = pending_tool_uses.pop(tool_use_id, None)
                        if log_id:
                            log_entry = await db.get(TaskLog, log_id)
                            if log_entry and log_entry.log_metadata:
                                existing = _json.loads(log_entry.log_metadata)
                                existing['output'] = data.get('output', '')
                                existing['error'] = data.get('error', False)
                                log_entry.log_metadata = _json.dumps(existing)
                                await db.commit()
                                logger.debug(f"[Task {task_id}] Tool result stored (id={tool_use_id})")
                    except Exception as exc:
                        logger.debug(f"[Task {task_id}] Failed to parse CODIFY_TOOL_RESULT: {exc}")

            elif stripped.startswith('CODIFY_THINKING:'):
                th_match = _CODIFY_THINKING_RE.match(stripped)
                if th_match:
                    try:
                        json_str = th_match.group(1)
                        _json.loads(json_str)  # validate before storing
                        db.add(TaskLog(
                            task_id=task_id,
                            log_level="INFO",
                            message="",
                            log_type="thinking",
                            log_metadata=json_str,
                        ))
                        await db.commit()
                        logger.debug(f"[Task {task_id}] Stored real-time thinking entry")
                    except Exception as exc:
                        logger.debug(f"[Task {task_id}] Failed to parse CODIFY_THINKING: {exc}")

            elif stripped.startswith('CODIFY_ASSISTANT_TEXT:'):
                at_match = _CODIFY_ASSISTANT_TEXT_RE.match(stripped)
                if at_match:
                    try:
                        json_str = at_match.group(1)
                        _json.loads(json_str)  # validate before storing
                        db.add(TaskLog(
                            task_id=task_id,
                            log_level="INFO",
                            message="",
                            log_type="assistant_text",
                            log_metadata=json_str,
                        ))
                        await db.commit()
                        logger.debug(f"[Task {task_id}] Stored real-time assistant_text entry")
                    except Exception as exc:
                        logger.debug(f"[Task {task_id}] Failed to parse CODIFY_ASSISTANT_TEXT: {exc}")

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

    def _create_mr_if_needed(
        self,
        task: Task,
        mr_iid: Optional[int],
        mr_web_url: Optional[str],
    ) -> tuple[Optional[int], Optional[str]]:
        """Create MR if needed or reuse existing one.

        Args:
            task: Task object
            mr_iid: Existing MR IID (if any)
            mr_web_url: Existing MR web URL (if any)

        Returns:
            Tuple of (mr_iid, mr_web_url) - may be unchanged or newly created
        """
        # Use existing MR for continuation tasks
        if mr_iid:
            return mr_iid, mr_web_url

        # Try to find existing open MR from this branch
        existing = self._find_existing_mr(task)
        if existing:
            return existing

        # No existing MR - create a new one
        return self._create_new_mr(task)

    def _find_existing_mr(
        self,
        task: Task,
    ) -> tuple[Optional[int], Optional[str]] | None:
        """Find existing open MR for the task's branch.

        Args:
            task: Task object

        Returns:
            Tuple of (mr_iid, mr_web_url) if found, None otherwise
        """
        try:
            existing_mrs = self.gitlab.gl.projects.get(task.project_id).mergerequests.list(
                source_branch=task.branch_name,
                state="opened",
            )
            if not existing_mrs:
                return None

            mr_iid = existing_mrs[0].iid
            mr_web_url = self.gitlab.normalize_web_url(existing_mrs[0].web_url)
            logger.info(f"[Task {task.id}] Reusing existing MR !{mr_iid} for branch {task.branch_name}")
            return mr_iid, mr_web_url
        except Exception as e:
            logger.warning(f"[Task {task.id}] Failed to look up existing MR: {e}")
        return None

    def _create_new_mr(
        self,
        task: Task,
    ) -> tuple[Optional[int], Optional[str]]:
        """Create a new draft MR for the task.

        Args:
            task: Task object

        Returns:
            Tuple of (mr_iid, mr_web_url) if successful, (None, None) otherwise
        """
        settings = get_settings()
        target_branch = task.target_branch or settings.default_target_branch
        mr_title = self._build_initial_mr_title(task)
        initial_mr_desc = self._build_initial_mr_description(task)

        try:
            mr_response = self.gitlab.gl.projects.get(task.project_id).mergerequests.create({
                "source_branch": task.branch_name,
                "target_branch": target_branch,
                "title": mr_title,
                "description": initial_mr_desc,
                "draft": True,  # Create as draft MR
            })
        except Exception as e:
            logger.warning(f"[Task {task.id}] Failed to create initial MR: {e}, continuing without MR")
            return None, None

        mr_iid = mr_response.iid
        mr_web_url = self.gitlab.normalize_web_url(mr_response.web_url)
        logger.info(f"[Task {task.id}] Created initial draft MR !{mr_iid}")
        return mr_iid, mr_web_url

    def _build_container_env(
        self,
        task: Task,
        mr_iid: Optional[int],
        target_branch: Optional[str],
    ) -> dict[str, str]:
        """Build environment variables for the worker container.

        Args:
            task: Task object
            mr_iid: MR IID (if available)
            target_branch: Target branch for the MR; None = no-MR mode (direct push only)

        Returns:
            Dict of environment variables for the container
        """
        settings = get_settings()

        # In no-MR mode target_branch is None; pass empty string so entrypoint
        # knows to skip MR creation and push the branch without opening an MR.
        environment = {
            "GITLAB_URL": settings.gitlab_url,
            "GITLAB_TOKEN": settings.gitlab_bot_token,
            "PROJECT_ID": str(task.project_id),
            "BRANCH_NAME": task.branch_name,
            "USER_PROMPT": task.user_prompt,
            "TARGET_BRANCH": target_branch or "",
            "ANTHROPIC_BASE_URL": settings.anthropic_base_url,
            "ANTHROPIC_API_KEY": settings.anthropic_api_key,
            "ANTHROPIC_MODEL": settings.anthropic_model,
            "CLAUDE_MAX_TURNS": str(settings.claude_max_turns),
            "TASK_ID": str(task.id),
            "TASK_TIMEOUT": str(settings.task_timeout),
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

        # Pass custom CA bundle to worker container for HTTPS verification
        if settings.custom_ca_bundle:
            environment["CUSTOM_CA_BUNDLE"] = settings.custom_ca_bundle

        return environment

    def _build_container_volumes(self, settings: Any) -> dict:
        """Build volume mounts for the worker container.

        Args:
            settings: Application settings object

        Returns:
            Dict of volume mounts (host_path -> container_path mapping)
        """
        volumes: dict = {}

        if settings.maven_cache_host_path:
            volumes[settings.maven_cache_host_path] = {
                "bind": _MAVEN_CACHE_CONTAINER_PATH,
                "mode": "rw",
            }
        if settings.maven_settings_host_path:
            volumes[settings.maven_settings_host_path] = {
                "bind": _MAVEN_SETTINGS_CONTAINER_PATH,
                "mode": "ro",
            }

        # Apply generic volume mounts from configuration
        for mount in settings.worker_volume_mounts_parsed:
            host_path = mount.get("host_path")
            container_path = mount.get("container_path")
            mode = mount.get("mode", "ro")
            if host_path and container_path:
                volumes[host_path] = {"bind": container_path, "mode": mode}

        return volumes if volumes else {}

    async def _parse_task_result(
        self,
        task: Task,
        logs: str,
        db: AsyncSession,
        exit_code: int,
    ) -> None:
        """Parse task execution logs and update task with results.

        Args:
            task: Task object to update
            logs: Full container logs
            db: Database session
            exit_code: Container exit code
        """
        # Extract token usage from CODIFY_STATS marker line
        stats_match = _CODIFY_STATS_RE.search(logs)
        if stats_match:
            try:
                usage = _json.loads(stats_match.group(1).strip())
                task.input_tokens = usage.get('input_tokens')
                task.output_tokens = usage.get('output_tokens')
                logger.info(
                    f"[Task {task.id}] Token usage: "
                    f"in={task.input_tokens} out={task.output_tokens}"
                )
            except Exception:
                logger.debug(f"[Task {task.id}] Failed to parse CODIFY_STATS")

        # Extract model name from CODIFY_SYSTEM_INIT marker line
        system_init_match = _CODIFY_SYSTEM_INIT_RE.search(logs)
        if system_init_match:
            try:
                init_data = _json.loads(system_init_match.group(1).strip())
                model = init_data.get('model', '').strip()
                if model:
                    task.model_name = model
                    logger.info(f"[Task {task.id}] Model: {model}")
            except Exception:
                logger.debug(f"[Task {task.id}] Failed to parse CODIFY_SYSTEM_INIT")

        # Extract commit SHA from CODIFY_COMMIT_SHA marker line
        commit_sha_match = _CODIFY_COMMIT_SHA_RE.search(logs)
        if commit_sha_match:
            task.commit_sha = commit_sha_match.group(1).strip()
            logger.info(f"[Task {task.id}] Commit SHA: {task.commit_sha}")

        # Extract AI-generated MR title from CODIFY_MR_TITLE marker line
        mr_title_match = _CODIFY_MR_TITLE_RE.search(logs)
        if mr_title_match:
            try:
                title = mr_title_match.group(1).strip()
                if title:
                    task.merge_request_title = sanitize_sensitive_data(title)[:512]
                    logger.info(f"[Task {task.id}] MR title: {task.merge_request_title}")
            except Exception:
                logger.debug(f"[Task {task.id}] Failed to parse CODIFY_MR_TITLE")

        # Extract and store structured tool calls from CODIFY_TOOL_CALLS marker line.
        # Stored as a separate TaskLog entry (log_type='tool_calls_json') so the frontend
        # can render a timeline view without parsing the raw terminal output.
        tool_calls_match = _CODIFY_TOOL_CALLS_RE.search(logs)
        if tool_calls_match:
            try:
                tool_calls_json = tool_calls_match.group(1).strip()
                _json.loads(tool_calls_json)  # validate JSON before storing
                db.add(TaskLog(
                    task_id=task.id,
                    log_level="INFO",
                    message="",
                    log_type="tool_calls_json",
                    log_metadata=tool_calls_json,
                ))
                await db.commit()
                logger.info(f"[Task {task.id}] Stored structured tool calls log entry")
            except Exception:
                logger.debug(f"[Task {task.id}] Failed to parse CODIFY_TOOL_CALLS")

        if exit_code == 0:
            task.status = TaskStatus.COMPLETED
            task.completed_at = utcnow()
            await self._parse_mr_from_logs(task, logs)
            await self._update_task_stats_from_logs_or_api(task, logs)
        else:
            task.status = TaskStatus.FAILED
            task.completed_at = utcnow()
            task.error_message = sanitize_sensitive_data(logs)[-1000:]

    async def _parse_mr_from_logs(self, task: Task, logs: str) -> None:
        """Parse MR URL and IID from container logs.

        Args:
            task: Task object to update
            logs: Container logs
        """
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

    async def _update_task_stats_from_logs_or_api(self, task: Task, logs: str) -> None:
        """Update task with change statistics from logs or GitLab API.

        Args:
            task: Task object to update
            logs: Container logs
        """
        # Get MR change stats — prefer log-parsed git diff (accurate), fall back to GitLab API.
        diff_match = _CODIFY_DIFF_RE.search(logs)
        if diff_match:
            task.additions = int(diff_match.group(1))
            task.deletions = int(diff_match.group(2))
            task.total_changes = task.additions + task.deletions
            logger.info(
                f"[Task {task.id}] Diff stats (from log): "
                f"+{task.additions} -{task.deletions} ({task.total_changes} total)"
            )
        elif task.merge_request_iid:
            try:
                logger.info(f"[Task {task.id}] Getting MR stats for MR !{task.merge_request_iid}")
                stats = await self.gitlab.get_merge_request_stats(
                    task.project_id, task.merge_request_iid
                )
                logger.info(f"[Task {task.id}] MR stats result: {stats}")
                if stats:
                    task.additions = stats.get("additions", 0)
                    task.deletions = stats.get("deletions", 0)
                    task.total_changes = stats.get("total", 0)
                    logger.info(
                        f"[Task {task.id}] MR stats (from API): "
                        f"+{task.additions} -{task.deletions} ({task.total_changes} total)"
                    )
                else:
                    logger.warning(f"[Task {task.id}] MR stats returned None")
            except Exception as e:
                logger.warning(f"[Task {task.id}] Failed to get MR stats: {e}")

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

    async def _send_notifications(
        self,
        task: Task,
        success: bool,
        had_existing_mr: bool,
        logs: str,
    ) -> None:
        """Send notifications for task completion.

        Args:
            task: Task object
            success: Whether the task succeeded
            had_existing_mr: Whether task started with an existing MR
            logs: Container logs
        """
        # Send completion notification to MR or issue
        notify_target = "mr" if had_existing_mr else "issue"
        try:
            await self._notify_task_completed(task, success=success, notify_target=notify_target)
        except Exception as e:
            logger.warning(f"Failed to send completion notification: {e}")

        # Send Mattermost notification
        try:
            await notify_task_event(task, MATTERMOST_EVENT_TASK_COMPLETED)
        except Exception as e:
            logger.warning(f"Failed to send Mattermost completion notification: {e}")

    async def _send_failure_notifications(
        self,
        task: Task,
        success: bool,
        had_existing_mr: bool,
    ) -> None:
        """Send notifications for task failure.

        Args:
            task: Task object
            success: Whether the task succeeded (False)
            had_existing_mr: Whether task started with an existing MR
        """
        # Send failure notification
        notify_target = "mr" if had_existing_mr else "issue"
        try:
            await self._notify_task_completed(task, success=success, notify_target=notify_target)
        except Exception as e:
            logger.warning(f"Failed to send failure notification: {e}")

        # Send Mattermost notification
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

    def _get_container_name(self, task: Task) -> str:
        """Generate container name with naming convention.

        Args:
            task: Task object

        Returns:
            Container name string
        """
        issue_suffix = f"i{task.issue_iid}" if task.issue_iid else "manual"
        return f"codify-{task.id}-p{task.project_id}-{issue_suffix}"

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
        task.started_at = utcnow()
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
            mr_iid = task.merge_request_iid
            mr_web_url = task.merge_request_url

            # Create or reuse MR (skip when target_branch is None — no-MR mode)
            if task.target_branch:
                mr_iid, mr_web_url = self._create_mr_if_needed(task, mr_iid, mr_web_url)

            # Update task with MR info if new MR was created
            if mr_iid and mr_iid != task.merge_request_iid:
                task.merge_request_iid = mr_iid
                task.merge_request_url = mr_web_url
                await db.commit()

            target_branch = task.target_branch  # None = no-MR mode; entrypoint sees TARGET_BRANCH=""

            # Build environment and volumes
            environment = self._build_container_env(task, mr_iid, target_branch)
            volumes = self._build_container_volumes(settings)

            # Generate container name
            container_name = self._get_container_name(task)

            # Create and run container
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

            # Parse results and update task
            await self._parse_task_result(task, logs, db, exit_code)

            if exit_code == 0:
                logger.info(f"Task {task_id} completed successfully")

                # Remove draft status from MR if it was created
                if task.merge_request_iid:
                    try:
                        self._remove_mr_draft_status(task)
                    except Exception as e:
                        logger.warning(f"[Task {task_id}] Failed to update MR draft status: {e}")

                # Send success notifications
                await self._send_notifications(task, success=True, had_existing_mr=had_existing_mr, logs=logs)
            else:
                logger.error(f"[Task {task_id}] Failed with exit code {exit_code}")

                # Check if we should retry
                if settings.max_retries > 0 and task.retry_count < settings.max_retries:
                    # Schedule retry
                    previous_scheduled_at = task.scheduled_at
                    task.retry_count += 1
                    task.status = TaskStatus.PENDING
                    task.scheduled_at = utcnow()
                    logger.info(f"[Task {task_id}] Scheduling retry {task.retry_count}/{settings.max_retries}")

                # Send failure notifications
                await self._send_failure_notifications(task, success=False, had_existing_mr=had_existing_mr)

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
            task.completed_at = utcnow()
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
                await self._notify_task_completed(task, success=False, notify_target="mr" if had_existing_mr else "issue")
            except Exception as notify_error:
                logger.warning(f"Failed to send failure notification: {notify_error}")
            try:
                await notify_task_event(task, MATTERMOST_EVENT_TASK_FAILED)
            except Exception as notify_error:
                logger.warning(f"Failed to send Mattermost failure notification: {notify_error}")

            return False

    async def resume_task(self, db: AsyncSession, task_id: int, container_name: str) -> bool:
        """Resume monitoring a task whose container survived a scheduler restart.

        Unlike execute_task(), this does NOT create a new container. Instead it
        attaches to the existing running container, streams remaining logs,
        and performs the same post-processing (parse results, update status,
        notifications, cleanup).

        Args:
            db: Database session
            task_id: Task ID to resume
            container_name: Name of the running Docker container

        Returns:
            True if the task completed successfully, False otherwise
        """
        settings = get_settings()

        # Fetch task
        result = await db.execute(select(Task).where(Task.id == task_id))
        task = result.scalar_one_or_none()

        if not task:
            logger.error(f"[Task {task_id}] Resume: task not found in database")
            return False

        logger.info(
            f"[Task {task_id}] Resuming monitoring for container {container_name} "
            f"(project={task.project_id} issue_iid={task.issue_iid})"
        )
        had_existing_mr = task.merge_request_iid is not None

        # Find the running container
        try:
            container = self.docker.client.containers.get(container_name)
        except Exception as e:
            logger.error(f"[Task {task_id}] Resume: container {container_name} not found: {e}")
            task.status = TaskStatus.FAILED
            task.error_message = f"Container disappeared during resume: {e}"
            task.completed_at = utcnow()
            await db.commit()
            return False

        try:
            # Stream remaining logs (follow=True will wait for container to finish)
            exit_code, logs, log_chunks_saved = await self._stream_logs_to_db(
                container, task.id, db, settings.task_timeout
            )

            # Parse results and update task
            await self._parse_task_result(task, logs, db, exit_code)

            if exit_code == 0:
                logger.info(f"[Task {task_id}] Resume: completed successfully")
                if task.merge_request_iid:
                    try:
                        self._remove_mr_draft_status(task)
                    except Exception as e:
                        logger.warning(f"[Task {task_id}] Resume: failed to update MR draft status: {e}")
                await self._send_notifications(task, success=True, had_existing_mr=had_existing_mr, logs=logs)
            else:
                logger.error(f"[Task {task_id}] Resume: failed with exit code {exit_code}")
                if settings.max_retries > 0 and task.retry_count < settings.max_retries:
                    task.retry_count += 1
                    task.status = TaskStatus.PENDING
                    task.scheduled_at = utcnow()
                    logger.info(f"[Task {task_id}] Resume: scheduling retry {task.retry_count}/{settings.max_retries}")
                await self._send_failure_notifications(task, success=False, had_existing_mr=had_existing_mr)

            scrubbed_logs = scrub_sensitive_data(logs)
            if exit_code != 0:
                task.error_message = sanitize_sensitive_data(logs)[-1000:]
                db.add(TaskLog(task_id=task.id, log_level="ERROR",
                               message=f"[Exit code: {exit_code}]\n{scrubbed_logs[-2000:]}"))
            elif log_chunks_saved == 0:
                db.add(TaskLog(task_id=task.id, log_level="INFO",
                               message=scrubbed_logs[-4000:] or "[No output]"))

            await db.commit()

            try:
                self.docker.remove_container(container, force=True)
            except Exception as e:
                logger.warning(f"[Task {task_id}] Resume: failed to remove container: {e}")

            return exit_code == 0

        except Exception as e:
            logger.exception(f"[Task {task_id}] Resume failed with exception: {e}")
            task.status = TaskStatus.FAILED
            task.completed_at = utcnow()
            task.error_message = sanitize_sensitive_data(str(e))[:1000]
            await db.commit()

            try:
                self.docker.remove_container(container, force=True)
            except Exception as cleanup_error:
                logger.warning(f"[Task {task_id}] Resume: failed to cleanup container: {cleanup_error}")

            try:
                await self._notify_task_completed(task, success=False, notify_target="mr" if had_existing_mr else "issue")
            except Exception as notify_error:
                logger.warning(f"[Task {task_id}] Resume: failed to send failure notification: {notify_error}")
            try:
                await notify_task_event(task, MATTERMOST_EVENT_TASK_FAILED)
            except Exception as notify_error:
                logger.warning(f"[Task {task_id}] Resume: failed to send Mattermost notification: {notify_error}")

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

    async def _notify_task_completed(self, task: Task, success: bool, notify_target: str = "issue") -> None:
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
            await asyncio.to_thread(self.gitlab.create_mr_note, task.project_id, mr_iid, message)
            logger.info(f"Sent completion notification to MR !{mr_iid} for task {task.id}, success={success}")

            # Update MR description with execution progress
            if success:
                try:
                    self._update_mr_description(task, mr_iid)
                except Exception as e:
                    logger.warning(f"Failed to update MR description: {e}")
        elif task.issue_iid:
            await asyncio.to_thread(self.gitlab.create_note, task.project_id, task.issue_iid, message)
            logger.info(f"Sent completion notification for task {task.id}, success={success}")

        # Send webhook alert if configured
        if not success:
            await self._send_failure_alert(task)

    async def _send_failure_alert(self, task: Task) -> None:
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
            async with httpx.AsyncClient(timeout=10.0, verify=get_ssl_verify(settings)) as client:
                response = await client.post(
                    settings.alert_webhook_url,
                    json=alert_data,
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
