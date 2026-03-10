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

        container = None

        try:
            # Pull worker image
            try:
                self.docker.pull_image(settings.worker_image)
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

                # Parse MR URL from logs (simplified)
                # In production, you'd want more robust parsing
                for line in logs.split("\n"):
                    if "MR created:" in line:
                        mr_url = line.split("MR created:")[-1].strip()
                        task.merge_request_url = mr_url

                logger.info(f"Task {task_id} completed successfully")
            else:
                task.status = TaskStatus.FAILED
                task.completed_at = datetime.utcnow()
                task.error_message = logs[-500:]  # Store last 500 chars
                logger.error(f"Task {task_id} failed with exit code {exit_code}")

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
            return False

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

