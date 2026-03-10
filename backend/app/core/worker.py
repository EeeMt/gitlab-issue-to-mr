"""Worker executor for running tasks in Docker containers."""

import logging
from datetime import datetime
from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings, get_effective_settings
from app.core.docker_client import DockerClientWrapper, get_docker_client
from app.core.gitlab_client import GitLabClient, get_gitlab_client
from app.models import Task, TaskLog, TaskStatus

logger = logging.getLogger(__name__)


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
            logger.error(f"Task {task_id} not found")
            return False

        logger.info(f"Executing task {task_id} for issue {task.issue_iid}")

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

            environment = {
                "GITLAB_URL": settings.gitlab_url,
                "GITLAB_TOKEN": settings.gitlab_bot_token,
                "PROJECT_ID": str(task.project_id),
                "ISSUE_IID": str(task.issue_iid),
                "BRANCH_NAME": task.branch_name,
                "USER_PROMPT": task.user_prompt,
                "TARGET_BRANCH": target_branch,
                "ANTHROPIC_BASE_URL": settings.anthropic_base_url,
                "ANTHROPIC_API_KEY": settings.anthropic_api_key,
                "ANTHROPIC_MODEL": settings.anthropic_model,
            }

            # Generate container name with naming convention: gimr-{id}-p{pid}-i{iid}
            container_name = f"gimr-{task.id}-p{task.project_id}-i{task.issue_iid}"

            # Create and run container
            container = self.docker.create_container(
                image=settings.worker_image,
                command="",
                environment=environment,
                network="bridge",
                name=container_name,
            )

            # Track container ID in task
            task.container_id = container.id
            await db.commit()

            # Wait for completion
            exit_code, logs = self.docker.wait_for_container(
                container, timeout=settings.task_timeout
            )

            # Process results
            if exit_code == 0:
                task.status = TaskStatus.COMPLETED
                task.completed_at = datetime.utcnow()

                # Parse MR URL from logs
                # Try to find web_url in any line of logs
                for line in logs.split("\n"):
                    if "/merge_requests/" in line:
                        # Extract URL from line containing merge_requests
                        import re
                        match = re.search(r'http[^\s]*merge_requests/\d+', line)
                        if match:
                            task.merge_request_url = match.group(0)
                            break

                # If not found in logs, try to get MR from GitLab API by branch name
                if not task.merge_request_url:
                    try:
                        mrs = self.gitlab.gl.projects.get(task.project_id).mergerequests.list(
                            source_branch=task.branch_name,
                            state='opened'
                        )
                        if mrs:
                            task.merge_request_url = mrs[0].web_url
                    except Exception as e:
                        logger.warning(f"Failed to get MR from API: {e}")

                logger.info(f"Task {task_id} completed successfully")

                # Send "completed" notification with MR URL
                try:
                    self._notify_task_completed(task, success=True)
                except Exception as e:
                    logger.warning(f"Failed to send completion notification: {e}")
            else:
                task.status = TaskStatus.FAILED
                task.completed_at = datetime.utcnow()
                task.error_message = logs[-500:]  # Store last 500 chars
                logger.error(f"Task {task_id} failed with exit code {exit_code}")

                # Send "failed" notification
                try:
                    self._notify_task_completed(task, success=False)
                except Exception as e:
                    logger.warning(f"Failed to send failure notification: {e}")

            # Add log entry
            log_entry = TaskLog(
                task_id=task.id,
                log_level="ERROR" if exit_code != 0 else "INFO",
                message=logs[-2000:],  # Store last 2000 chars
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
            logger.exception(f"Task {task_id} failed with exception")
            task.status = TaskStatus.FAILED
            task.completed_at = datetime.utcnow()
            task.error_message = str(e)[:500]
            await db.commit()

            # Send failure notification for exceptions
            try:
                self._notify_task_completed(task, success=False)
            except Exception as notify_error:
                logger.warning(f"Failed to send failure notification: {notify_error}")

            return False

    def _notify_task_started(self, task: Task) -> None:
        """Send notification when task starts execution.

        Args:
            task: Task object
        """
        message = "🔄 开始处理请求..."
        self.gitlab.create_note(
            task.project_id,
            task.issue_iid,
            message,
        )
        logger.info(f"Sent start notification for task {task.id}")

    def _notify_task_completed(self, task: Task, success: bool) -> None:
        """Send notification when task completes.

        Args:
            task: Task object
            success: Whether the task succeeded
        """
        if success and task.merge_request_url:
            # Extract MR IID from URL (e.g., /merge_requests/14 -> !14)
            mr_iid = None
            if "/merge_requests/" in task.merge_request_url:
                try:
                    mr_iid = task.merge_request_url.split("/merge_requests/")[-1].split("/")[0].split("?")[0]
                except (IndexError, ValueError):
                    pass

            if mr_iid:
                message = f"✅ MR 已创建: !{mr_iid}"
            else:
                message = f"✅ MR 已创建: {task.merge_request_url}"
        elif success:
            message = "✅ 任务已完成"
        else:
            error_msg = task.error_message[:200] if task.error_message else "未知错误"
            message = f"❌ 任务失败: {error_msg}"

        self.gitlab.create_note(
            task.project_id,
            task.issue_iid,
            message,
        )
        logger.info(f"Sent completion notification for task {task.id}, success={success}")

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

