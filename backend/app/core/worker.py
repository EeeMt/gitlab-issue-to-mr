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
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_effective_settings as get_settings
from app.core.docker_client import DockerClientWrapper, get_docker_client
from app.core.worker_environment_variables import RESERVED_WORKER_ENVIRONMENT_KEYS
from gitlab import Gitlab
from app.core.gitlab_client import GitLabClient, get_gitlab_client
from app.core.ssl_utils import get_ssl_verify
from app.core.utcnow import utcnow
from app.core.mattermost_notifications import (
    MATTERMOST_EVENT_TASK_COMPLETED,
    MATTERMOST_EVENT_TASK_FAILED,
    MATTERMOST_EVENT_TASK_RETRY_SCHEDULED,
    notify_task_event,
)
from app.models import Task, TaskLog, TaskStatus, Issue, IssueStatus, AIProvider, User
from app.api.providers import _decrypt_provider_api_key

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
# Emitted by entrypoint.sh after Claude finishes; contains the session ID for resumption.
_CODIFY_SESSION_ID_RE = re.compile(r'^CODIFY_SESSION_ID:(\S+)$', re.MULTILINE)

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
        """Build a reasonable initial MR title — uses issue title when available."""
        issue = task.issue if task.issue else None
        if issue and issue.title:
            return f"Draft: {issue.title[:120]}"

        prompt = re.sub(r"\s+", " ", task.user_prompt or "").strip()
        if prompt:
            short_prompt = re.split(r"[;\n。！？.!?]", prompt, maxsplit=1)[0].strip()
            if short_prompt:
                return f"AI: {short_prompt[:100]}"

        return f"AI: Task {task.id}"

    def _build_initial_mr_description(self, task: Task) -> str:
        """Build the initial MR description shown while the worker is running."""
        return f"""## 🚀 AI 正在执行

### 需求
{task.user_prompt}

---
*AI 正在直接实施变更...*"""

    def _remove_mr_draft_status(self, task: Task) -> None:
        """Remove draft status from an MR by normalizing its title (legacy)."""
        pass

    def _remove_mr_draft_status_for_issue(
        self, task: Task, issue: Issue, *, sudo_gl: Optional["Gitlab"] = None
    ) -> None:
        """Mark an MR ready and normalize legacy draft prefixes in the title."""
        gl = sudo_gl or self.gitlab.gl
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

            text = item.decode("utf-8", errors="replace")

            # Docker may batch multiple lines into a single chunk.
            # Split into individual lines so CODIFY markers are detected
            # even when they appear in the middle of a multi-line chunk.
            lines = text.splitlines(keepends=True)

            for line in lines:
                stripped = line.rstrip('\n\r')
                if not stripped:
                    buffer.append(line)
                    all_lines.append(line)
                    continue

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
                            json_str = th_match.group(1).strip()
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
                            json_str = at_match.group(1).strip()
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

                elif stripped.startswith('CODIFY_SYSTEM_INIT:'):
                    si_match = _CODIFY_SYSTEM_INIT_RE.match(stripped)
                    if si_match:
                        try:
                            json_str = si_match.group(1).strip()
                            _json.loads(json_str)  # validate
                            db.add(TaskLog(
                                task_id=task_id,
                                log_level="INFO",
                                message="",
                                log_type="system_init",
                                log_metadata=json_str,
                            ))
                            await db.commit()
                            logger.debug(f"[Task {task_id}] Stored real-time system_init entry")
                        except Exception as exc:
                            logger.debug(f"[Task {task_id}] Failed to parse CODIFY_SYSTEM_INIT: {exc}")

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
        issue: Issue,
        mr_iid: Optional[int],
        mr_web_url: Optional[str],
        *,
        sudo_gl: Optional["Gitlab"] = None,
    ) -> tuple[Optional[int], Optional[str]]:
        """Create or reuse MR for the task's issue."""
        if mr_iid:
            return mr_iid, mr_web_url

        existing = self._find_existing_mr(task, issue)
        if existing:
            return existing

        return self._create_new_mr(task, issue, sudo_gl=sudo_gl)

    def _find_existing_mr(
        self,
        task: Task,
        issue: Issue,
    ) -> tuple[Optional[int], Optional[str]] | None:
        """Find existing open MR for the issue's branch."""
        try:
            existing_mrs = self.gitlab.gl.projects.get(task.project_id).mergerequests.list(
                source_branch=issue.branch_name,
                state="opened",
            )
            if not existing_mrs:
                return None

            mr_iid = existing_mrs[0].iid
            mr_web_url = self.gitlab.normalize_web_url(existing_mrs[0].web_url)
            logger.info(f"[Task {task.id}] Reusing existing MR !{mr_iid} for branch {issue.branch_name}")
            return mr_iid, mr_web_url
        except Exception as e:
            logger.warning(f"[Task {task.id}] Failed to look up existing MR: {e}")
        return None

    def _create_new_mr(
        self,
        task: Task,
        issue: Issue,
        *,
        sudo_gl: Optional["Gitlab"] = None,
    ) -> tuple[Optional[int], Optional[str]]:
        """Create a new draft MR for the task's issue."""
        settings = get_settings()
        target_branch = issue.target_branch or settings.default_target_branch
        mr_title = self._build_initial_mr_title(task)
        initial_mr_desc = self._build_initial_mr_description(task)

        mr_data = {
            "source_branch": issue.branch_name,
            "target_branch": target_branch,
            "title": mr_title,
            "description": initial_mr_desc,
            "draft": True,
            "labels": ["Codify"],
        }

        try:
            gl = sudo_gl or self.gitlab.gl
            mr_response = gl.projects.get(task.project_id).mergerequests.create(mr_data)
        except Exception as e:
            if sudo_gl:
                logger.warning(
                    f"[Task {task.id}] Sudo MR creation failed: {e}, retrying with bot token"
                )
                try:
                    mr_response = self.gitlab.gl.projects.get(task.project_id).mergerequests.create(mr_data)
                except Exception as e2:
                    logger.warning(f"[Task {task.id}] Bot token MR creation also failed: {e2}")
                    return None, None
            else:
                logger.warning(f"[Task {task.id}] Failed to create initial MR: {e}, continuing without MR")
                return None, None

        mr_iid = mr_response.iid
        mr_web_url = self.gitlab.normalize_web_url(mr_response.web_url)
        logger.info(f"[Task {task.id}] Created initial draft MR !{mr_iid}")
        return mr_iid, mr_web_url

    async def _resolve_provider(self, db: AsyncSession, task: "Task") -> "AIProvider":
        """Resolve the AI provider for a task.

        Resolution chain: task.provider_id → default provider → legacy settings.
        """
        # 1. Task has explicit provider
        if task.provider_id:
            provider = await db.get(AIProvider, task.provider_id)
            if provider:
                return provider

        # 2. System default provider
        result = await db.execute(
            select(AIProvider).where(AIProvider.is_default == True)
        )
        provider = result.scalar_one_or_none()
        if provider:
            return provider

        # 3. Legacy fallback: build from settings
        settings = get_settings()
        return AIProvider(
            name="legacy",
            base_url=settings.anthropic_base_url,
            api_key=settings.anthropic_api_key,
            model=settings.anthropic_model,
            max_turns=settings.claude_max_turns,
            system_prompt=None,
        )

    async def _resolve_commit_author(self, db: AsyncSession, task: "Task") -> tuple[str, str]:
        """Resolve commit author identity for worker-generated commits."""
        fallback_name = (task.initiator_username or "Codify User").strip() or "Codify User"
        fallback_email = "codify-task@codify.local"

        display_name = (getattr(task, "initiator_display_name", None) or "").strip()
        email = (getattr(task, "initiator_email", None) or "").strip()
        if display_name or email:
            return display_name or fallback_name, email or fallback_email

        if task.initiator_user_id:
            user = await db.get(User, task.initiator_user_id)
            if user:
                user_name = (getattr(user, "display_name", None) or getattr(user, "username", None) or "").strip()
                user_email = (getattr(user, "email", None) or "").strip()
                if user_name or user_email:
                    return user_name or fallback_name, user_email or fallback_email

        return fallback_name, fallback_email

    def _build_container_env(
        self,
        task: "Task",
        issue: "Issue",
        mr_iid: Optional[int],
        target_branch: Optional[str],
        provider: "AIProvider" = None,
        *,
        author_name: Optional[str] = None,
        author_email: Optional[str] = None,
    ) -> dict[str, str]:
        """Build environment variables for the worker container."""
        settings = get_settings()

        # Use provider values for AI config, fall back to settings
        if provider and provider.id:
            api_key = _decrypt_provider_api_key(provider)
        elif provider:
            api_key = provider.api_key or ""
        else:
            api_key = settings.anthropic_api_key

        base_url = provider.base_url if provider else settings.anthropic_base_url
        model = provider.model if provider else settings.anthropic_model
        max_turns = str(provider.max_turns) if provider else str(settings.claude_max_turns)

        environment = {
            "GITLAB_URL": settings.gitlab_url,
            "GITLAB_TOKEN": settings.gitlab_bot_token,
            "PROJECT_ID": str(task.project_id),
            "BRANCH_NAME": issue.branch_name,
            "USER_PROMPT": task.user_prompt,
            "TARGET_BRANCH": target_branch or "",
            "ANTHROPIC_BASE_URL": base_url,
            "ANTHROPIC_API_KEY": api_key,
            "ANTHROPIC_MODEL": model,
            "CLAUDE_MAX_TURNS": max_turns,
            "TASK_ID": str(task.id),
            "TASK_TIMEOUT": str(settings.task_timeout),
            "ISSUE_ID": str(issue.id),
            "ISSUE_TITLE": issue.title or "",
            "GIT_AUTHOR_NAME": author_name or (getattr(task, "initiator_display_name", None) or task.initiator_username or "Codify User"),
            "GIT_AUTHOR_EMAIL": author_email or (getattr(task, "initiator_email", None) or "codify-task@codify.local"),
            "CODIFY_COAUTHOR_NAME": "Codify",
            "CODIFY_COAUTHOR_EMAIL": "codify@codify.local",
        }

        # System prompt for Claude CLI
        if provider and provider.system_prompt:
            environment["APPEND_SYSTEM_PROMPT"] = provider.system_prompt

        # Pass session ID for resume
        if issue.claude_session_id:
            environment["RESUME_SESSION"] = issue.claude_session_id

        # Add BASE_BRANCH if issue specifies a source branch to fork from
        if issue.base_branch:
            environment["BASE_BRANCH"] = issue.base_branch

        if mr_iid:
            environment["MR_IID"] = str(mr_iid)

        if settings.custom_ca_bundle:
            environment["CUSTOM_CA_BUNDLE"] = settings.custom_ca_bundle

        unexpected_keys = set(environment) - RESERVED_WORKER_ENVIRONMENT_KEYS
        if unexpected_keys:
            raise RuntimeError(
                "Worker container environment emitted keys not covered by reserved worker "
                f"environment keys: {sorted(unexpected_keys)}"
            )

        return environment

    def _build_container_volumes(self, settings: Any, issue: Optional[Issue] = None) -> dict:
        """Build volume mounts for the worker container."""
        import os
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

        # Mount session storage for Claude session persistence
        if issue and issue.session_storage_path:
            os.makedirs(issue.session_storage_path, exist_ok=True)
            volumes[issue.session_storage_path] = {
                "bind": "/home/codify/.claude",
                "mode": "rw",
            }

        return volumes if volumes else {}

    async def _parse_task_result(
        self,
        task: Task,
        logs: str,
        db: AsyncSession,
        exit_code: int,
        issue: Optional[Issue] = None,
    ) -> None:
        """Parse task execution logs and update task with results."""
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
            await self._update_task_stats_from_logs_or_api(task, logs, issue)
        else:
            task.status = TaskStatus.FAILED
            task.completed_at = utcnow()
            task.error_message = sanitize_sensitive_data(logs)[-1000:]

        # Extract session ID from container output
        session_match = _CODIFY_SESSION_ID_RE.search(logs)
        if session_match:
            extracted_session_id = session_match.group(1)
            logger.info(f"[Task {task.id}] Extracted session ID: {extracted_session_id}")
            task._extracted_session_id = extracted_session_id

    async def _parse_mr_from_logs(self, task: Task, logs: str) -> None:
        """Parse MR URL and IID from container logs.

        Stores parsed values as temporary attributes on the task object
        (_parsed_mr_iid, _parsed_mr_url) for the caller to persist to the Issue.
        """
        parsed_mr_url = None
        parsed_mr_iid = None

        # Try to find web_url in any line of logs
        for line in logs.split("\n"):
            if "/merge_requests/" in line:
                match = re.search(r'http[^\s]*merge_requests/\d+', line)
                if match:
                    parsed_mr_url = self.gitlab.normalize_web_url(match.group(0))
                    iid_match = re.search(r'/merge_requests/(\d+)', match.group(0))
                    if iid_match:
                        parsed_mr_iid = int(iid_match.group(1))
                    break

        # If URL is present but IID is still missing, derive it from the URL.
        if parsed_mr_url and not parsed_mr_iid:
            iid_match = re.search(r'/merge_requests/(\d+)', parsed_mr_url)
            if iid_match:
                parsed_mr_iid = int(iid_match.group(1))

        if parsed_mr_iid:
            task._parsed_mr_iid = parsed_mr_iid
        if parsed_mr_url:
            task._parsed_mr_url = parsed_mr_url

    async def _update_task_stats_from_logs_or_api(self, task: Task, logs: str, issue: Optional[Issue] = None) -> None:
        """Update task with change statistics from logs or GitLab API."""
        diff_match = _CODIFY_DIFF_RE.search(logs)
        if diff_match:
            task.additions = int(diff_match.group(1))
            task.deletions = int(diff_match.group(2))
            task.total_changes = task.additions + task.deletions
            logger.info(
                f"[Task {task.id}] Diff stats (from log): "
                f"+{task.additions} -{task.deletions} ({task.total_changes} total)"
            )
        else:
            mr_iid = (issue.merge_request_iid if issue else None) or getattr(task, '_parsed_mr_iid', None)
            if mr_iid:
                try:
                    logger.info(f"[Task {task.id}] Getting MR stats for MR !{mr_iid}")
                    stats = await self.gitlab.get_merge_request_stats(
                        task.project_id, mr_iid
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

    async def _update_mr_description_for_issue(
        self,
        task: Task,
        issue: Issue,
        db: AsyncSession,
        *,
        sudo_gl: Optional["Gitlab"] = None,
    ) -> None:
        """Rebuild MR description from issue context + all tasks.

        Replaces the entire MR description with a comprehensive view:
        - Issue title and description
        - Table of all tasks with status and prompt summary
        - Issue reference (Closes #N)
        """
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

            gl = sudo_gl or self.gitlab.gl
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
                f"[Task {task.id}] Updated MR !{mr_iid} title+description "
                f"with issue #{issue.id} context ({len(all_tasks)} tasks)"
            )

        except Exception as e:
            logger.warning(f"[Task {task.id}] Failed to update MR description: {e}")

    async def _send_notifications(
        self,
        task: Task,
        success: bool,
        had_existing_mr: bool,
        logs: str,
        issue: Optional[Issue] = None,
    ) -> None:
        """Send notifications for task completion."""
        notify_target = "mr" if had_existing_mr else "issue"
        try:
            await self._notify_task_completed(task, success=success, notify_target=notify_target, issue=issue)
        except Exception as e:
            logger.warning(f"Failed to send completion notification: {e}")

        try:
            await notify_task_event(task, MATTERMOST_EVENT_TASK_COMPLETED)
        except Exception as e:
            logger.warning(f"Failed to send Mattermost completion notification: {e}")

    async def _send_failure_notifications(
        self,
        task: Task,
        success: bool,
        had_existing_mr: bool,
        issue: Optional[Issue] = None,
    ) -> None:
        """Send notifications for task failure."""
        notify_target = "mr" if had_existing_mr else "issue"
        try:
            await self._notify_task_completed(task, success=success, notify_target=notify_target, issue=issue)
        except Exception as e:
            logger.warning(f"Failed to send failure notification: {e}")

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
        """Generate container name with naming convention."""
        prefix = get_settings().worker_container_prefix
        return f"{prefix}-{task.id}-issue{task.issue_id}"

    async def execute_task(self, db: AsyncSession, task_id: int) -> bool:
        """Execute a task."""
        settings = get_settings()

        result = await db.execute(select(Task).where(Task.id == task_id))
        task = result.scalar_one_or_none()
        if not task:
            logger.error(f"[Task {task_id}] Task not found in database")
            return False

        # Load parent issue
        issue = None
        if task.issue_id:
            issue = await db.get(Issue, task.issue_id)
            if not issue:
                logger.error(f"[Task {task_id}] Issue {task.issue_id} not found")
                task.status = TaskStatus.FAILED
                task.error_message = f"Parent issue {task.issue_id} not found"
                task.completed_at = utcnow()
                await db.commit()
                return False

        logger.info(f"[Task {task_id}] Executing for project={task.project_id} issue_id={task.issue_id} priority={task.priority}")
        had_existing_mr = (issue.merge_request_iid is not None) if issue else False

        # Create sudo GL for MR operations if initiator has a GitLab user ID
        sudo_gl: Optional[Gitlab] = None
        if task.initiator_gitlab_user_id and self.gitlab.settings.gitlab_admin_token:
            try:
                sudo_gl = self.gitlab.create_sudo_gl(task.initiator_gitlab_user_id)
                logger.info(
                    f"[Task {task_id}] Using sudo impersonation for GitLab user {task.initiator_gitlab_user_id}"
                )
            except ValueError as e:
                logger.warning(f"[Task {task_id}] Cannot use sudo: {e}, falling back to bot token")

        # Clear logs from any previous execution so the event stream starts fresh
        del_result = await db.execute(
            delete(TaskLog).where(TaskLog.task_id == task_id)
        )
        if del_result.rowcount:
            logger.info(
                f"[Task {task_id}] Cleared {del_result.rowcount} log entries"
                " from previous execution"
            )

        # Update task status to running
        task.status = TaskStatus.RUNNING
        task.started_at = utcnow()
        await db.commit()

        # Send "starting" notification
        try:
            self._notify_task_started(task, issue)
        except Exception as e:
            logger.warning(f"Failed to send start notification: {e}")

        container = None

        try:
            # Pull worker image (skipped when worker_skip_image_pull is set)
            if not settings.worker_skip_image_pull:
                try:
                    self.docker.pull_image(settings.worker_image, force=True)
                except Exception as e:
                    logger.warning(f"Failed to pull image: {e}, trying to use existing")

            mr_iid = issue.merge_request_iid if issue else None
            mr_web_url = issue.merge_request_url if issue else None

            # Create or reuse MR (skip when target_branch is None — no-MR mode)
            if issue and issue.target_branch:
                # Ensure "Codify" label exists in the project
                try:
                    self.gitlab.ensure_project_label(task.project_id, "Codify", "#6699cc")
                except Exception as e:
                    logger.warning(f"[Task {task_id}] Failed to ensure Codify label: {e}")

                mr_iid, mr_web_url = self._create_mr_if_needed(
                    task, issue, mr_iid, mr_web_url, sudo_gl=sudo_gl
                )

            # Save MR info to Issue if new MR was created
            if issue and mr_iid and mr_iid != issue.merge_request_iid:
                issue.merge_request_iid = mr_iid
                issue.merge_request_url = mr_web_url
                await db.commit()

            target_branch = issue.target_branch if issue else None

            # Resolve AI provider
            provider = await self._resolve_provider(db, task)
            
            # Build environment and volumes
            author_name, author_email = await self._resolve_commit_author(db, task)
            environment = self._build_container_env(
                task,
                issue,
                mr_iid,
                target_branch,
                provider=provider,
                author_name=author_name,
                author_email=author_email,
            )
            volumes = self._build_container_volumes(settings, issue)

            container_name = self._get_container_name(task)

            container = self.docker.create_container(
                image=settings.worker_image,
                command="",
                environment=environment,
                volumes=volumes if volumes else None,
                network=settings.worker_network,
                name=container_name,
            )

            task.container_id = container.id
            await db.commit()

            # Stream logs
            exit_code, logs, log_chunks_saved = await self._stream_logs_to_db(
                container, task.id, db, settings.task_timeout
            )

            # Check if task was cancelled externally while container was running
            await db.refresh(task)
            if task.status == TaskStatus.CANCELLED:
                logger.info(f"[Task {task_id}] Was cancelled during execution, preserving cancelled status")
                try:
                    self.docker.remove_container(container, force=True)
                except Exception:
                    pass
                return False

            # Parse results
            await self._parse_task_result(task, logs, db, exit_code, issue=issue)

            # Save session ID to Issue if extracted
            if issue and hasattr(task, '_extracted_session_id') and task._extracted_session_id:
                if not issue.claude_session_id:
                    issue.claude_session_id = task._extracted_session_id
                    logger.info(f"[Task {task_id}] Saved session ID to issue {issue.id}")
                await db.commit()

            # Save parsed MR info from logs to Issue
            if issue:
                parsed_mr_iid = getattr(task, '_parsed_mr_iid', None)
                parsed_mr_url = getattr(task, '_parsed_mr_url', None)
                if parsed_mr_iid and not issue.merge_request_iid:
                    issue.merge_request_iid = parsed_mr_iid
                    issue.merge_request_url = parsed_mr_url
                    await db.commit()

            if exit_code == 0:
                logger.info(f"Task {task_id} completed successfully")
                if issue and issue.merge_request_iid:
                    try:
                        self._remove_mr_draft_status_for_issue(task, issue, sudo_gl=sudo_gl)
                    except Exception as e:
                        logger.warning(f"[Task {task_id}] Failed to update MR draft status: {e}")
                await self._send_notifications(task, success=True, had_existing_mr=had_existing_mr, logs=logs, issue=issue)
            else:
                logger.error(f"[Task {task_id}] Failed with exit code {exit_code}")
                await self._send_failure_notifications(task, success=False, had_existing_mr=had_existing_mr, issue=issue)

            # Save a final log entry for failures, or for very fast tasks with no
            # streaming chunks (e.g., container exited immediately).
            scrubbed_logs = scrub_sensitive_data(logs)
            if exit_code != 0:
                task.error_message = sanitize_sensitive_data(logs)[-1000:]
                if log_chunks_saved == 0:
                    # No streaming chunks saved — store full log as error entry
                    log_entry = TaskLog(
                        task_id=task.id,
                        log_level="ERROR",
                        message=f"[Exit code: {exit_code}]\n{scrubbed_logs[-2000:]}",
                    )
                    db.add(log_entry)
                # When streaming chunks exist, error_message is sufficient — no duplicate log
            elif log_chunks_saved == 0:
                log_entry = TaskLog(
                    task_id=task.id,
                    log_level="INFO",
                    message=scrubbed_logs[-4000:] or "[No output]",
                )
                db.add(log_entry)

            await db.commit()

            # Update MR description with comprehensive issue context + all tasks
            if issue and issue.merge_request_iid:
                await self._update_mr_description_for_issue(task, issue, db, sudo_gl=sudo_gl)
            try:
                self.docker.remove_container(container, force=True)
            except Exception as e:
                logger.warning(f"Failed to remove container: {e}")

            return exit_code == 0

        except Exception as e:
            logger.exception(f"Task {task_id} failed with exception: {e}")
            task.status = TaskStatus.FAILED
            task.completed_at = utcnow()
            task.error_message = sanitize_sensitive_data(str(e))[:1000]
            await db.commit()

            if container:
                try:
                    self.docker.remove_container(container, force=True)
                except Exception as cleanup_error:
                    logger.warning(f"Failed to cleanup container: {cleanup_error}")

            try:
                await self._notify_task_completed(task, success=False, notify_target="mr" if had_existing_mr else "issue", issue=issue)
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
        """
        settings = get_settings()

        result = await db.execute(select(Task).where(Task.id == task_id))
        task = result.scalar_one_or_none()

        if not task:
            logger.error(f"[Task {task_id}] Resume: task not found in database")
            return False

        # Load parent issue
        issue = None
        if task.issue_id:
            issue = await db.get(Issue, task.issue_id)

        logger.info(
            f"[Task {task_id}] Resuming monitoring for container {container_name} "
            f"(project={task.project_id} issue_id={task.issue_id})"
        )
        had_existing_mr = (issue.merge_request_iid is not None) if issue else False

        # Create sudo GL for MR operations if initiator has a GitLab user ID
        sudo_gl: Optional[Gitlab] = None
        if task.initiator_gitlab_user_id and self.gitlab.settings.gitlab_admin_token:
            try:
                sudo_gl = self.gitlab.create_sudo_gl(task.initiator_gitlab_user_id)
            except ValueError:
                pass  # Fall back to bot token silently

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

            # Check if task was cancelled externally while container was running
            await db.refresh(task)
            if task.status == TaskStatus.CANCELLED:
                logger.info(f"[Task {task_id}] Resume: was cancelled during execution, preserving cancelled status")
                try:
                    self.docker.remove_container(container, force=True)
                except Exception:
                    pass
                return False

            # Parse results and update task
            await self._parse_task_result(task, logs, db, exit_code, issue=issue)

            # Save session ID to Issue if extracted
            if issue and hasattr(task, '_extracted_session_id') and task._extracted_session_id:
                if not issue.claude_session_id:
                    issue.claude_session_id = task._extracted_session_id
                    logger.info(f"[Task {task_id}] Resume: saved session ID to issue {issue.id}")
                await db.commit()

            # Save parsed MR info from logs to Issue
            if issue:
                parsed_mr_iid = getattr(task, '_parsed_mr_iid', None)
                parsed_mr_url = getattr(task, '_parsed_mr_url', None)
                if parsed_mr_iid and not issue.merge_request_iid:
                    issue.merge_request_iid = parsed_mr_iid
                    issue.merge_request_url = parsed_mr_url
                    await db.commit()

            if exit_code == 0:
                logger.info(f"[Task {task_id}] Resume: completed successfully")
                if issue and issue.merge_request_iid:
                    try:
                        self._remove_mr_draft_status_for_issue(task, issue, sudo_gl=sudo_gl)
                    except Exception as e:
                        logger.warning(f"[Task {task_id}] Resume: failed to update MR draft status: {e}")
                await self._send_notifications(task, success=True, had_existing_mr=had_existing_mr, logs=logs, issue=issue)
            else:
                logger.error(f"[Task {task_id}] Resume: failed with exit code {exit_code}")
                await self._send_failure_notifications(task, success=False, had_existing_mr=had_existing_mr, issue=issue)

            scrubbed_logs = scrub_sensitive_data(logs)
            if exit_code != 0:
                task.error_message = sanitize_sensitive_data(logs)[-1000:]
                if log_chunks_saved == 0:
                    db.add(TaskLog(task_id=task.id, log_level="ERROR",
                                   message=f"[Exit code: {exit_code}]\n{scrubbed_logs[-2000:]}"))
            elif log_chunks_saved == 0:
                db.add(TaskLog(task_id=task.id, log_level="INFO",
                               message=scrubbed_logs[-4000:] or "[No output]"))

            await db.commit()

            # Update MR description with comprehensive issue context + all tasks
            if issue and issue.merge_request_iid:
                await self._update_mr_description_for_issue(task, issue, db, sudo_gl=sudo_gl)

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
                await self._notify_task_completed(task, success=False, notify_target="mr" if had_existing_mr else "issue", issue=issue)
            except Exception as notify_error:
                logger.warning(f"[Task {task_id}] Resume: failed to send failure notification: {notify_error}")
            try:
                await notify_task_event(task, MATTERMOST_EVENT_TASK_FAILED)
            except Exception as notify_error:
                logger.warning(f"[Task {task_id}] Resume: failed to send Mattermost notification: {notify_error}")

            return False

    def _notify_task_started(self, task: Task, issue: Optional[Issue] = None) -> None:
        """Send notification when task starts execution."""
        if not issue:
            logger.info(f"Skipping start notification for task {task.id} (no issue)")
            return

        settings = get_settings()
        task_url = f"{settings.dashboard_url}/tasks/{task.id}"
        message = f"🔄 开始处理请求... [任务 {task.id}]({task_url})"
        if issue.merge_request_iid:
            self.gitlab.create_mr_note(
                task.project_id,
                issue.merge_request_iid,
                message,
            )
            logger.info(f"Sent start notification to MR !{issue.merge_request_iid} for task {task.id}")

    async def _notify_task_completed(self, task: Task, success: bool, notify_target: str = "issue", issue: Optional[Issue] = None) -> None:
        """Send notification when task completes."""
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
            await asyncio.to_thread(self.gitlab.create_mr_note, task.project_id, mr_iid, message)
            logger.info(f"Sent completion notification to MR !{mr_iid} for task {task.id}, success={success}")

        if not success:
            await self._send_failure_alert(task, issue)

    async def _send_failure_alert(self, task: Task, issue: Optional[Issue] = None) -> None:
        """Send failure alert to webhook URL."""
        settings = get_settings()

        if not settings.alert_on_failure or not settings.alert_webhook_url:
            return

        error_msg = task.error_message[:500] if task.error_message else "Unknown error"
        alert_data = {
            "text": f"🚨 Task Failed",
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
