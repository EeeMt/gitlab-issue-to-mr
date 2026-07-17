import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.utcnow import utcnow
from app.models import (
    Base,
    Issue,
    IssueExecutionLock,
    MattermostNotificationDelivery,
    Task,
    TaskIngestCursor,
    TaskLog,
    TaskPayload,
    TaskRawLogChunk,
    TaskRunArchive,
    TaskStatus,
    TaskUsageLedger,
    WebhookEvent,
    WorkerProfile,
)


class SystemDataCleanupServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.temp_path = Path(self.tempdir.name)
        self.engine = create_async_engine(
            "sqlite+aiosqlite:///:memory:",
            poolclass=StaticPool,
            connect_args={"check_same_thread": False},
        )
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.Session = async_sessionmaker(self.engine, expire_on_commit=False)
        async with self.Session() as session:
            session.add(
                WorkerProfile(
                    id=1,
                    name="Test Worker",
                    enabled=True,
                    is_default=True,
                    image="codify-worker:test",
                    volume_mounts=[],
                    pre_script="",
                    post_script="",
                    default_execute_run_instruction_template="{{user_prompt}}",
                    default_plan_run_instruction_template="{{user_prompt}}",
                    ci_auto_repair_run_instruction_template="{{user_prompt}}",
                )
            )
            await session.commit()

    async def asyncTearDown(self):
        await self.engine.dispose()
        self.tempdir.cleanup()

    async def _seed_issue(
        self,
        session,
        *,
        issue_id: int,
        created_at: datetime,
        task_statuses: list[TaskStatus],
        archive_dir: Path | None = None,
    ) -> list[int]:
        issue = Issue(
            id=issue_id,
            title=f"Issue {issue_id}",
            project_id=100 + issue_id,
            status="open",
            worker_profile_id=1,
            created_at=created_at,
            updated_at=created_at,
        )
        session.add(issue)
        await session.flush()

        task_ids: list[int] = []
        for index, task_status in enumerate(task_statuses, start=1):
            task_id = issue_id * 100 + index
            task_ids.append(task_id)
            task = Task(
                id=task_id,
                issue_id=issue_id,
                project_id=issue.project_id,
                user_prompt=f"Task {task_id}",
                status=task_status,
                created_at=created_at,
                updated_at=created_at,
            )
            session.add(task)
            await session.flush()
            session.add(TaskLog(task_id=task_id, message="log"))
            session.add(
                TaskPayload(
                    task_id=task_id,
                    payload_kind="tool_input",
                    content=b"{}",
                    char_count=2,
                    byte_count=2,
                )
            )
            session.add(
                TaskRawLogChunk(
                    task_id=task_id,
                    sequence_no=1,
                    content=b"log",
                    char_count=3,
                    byte_count=3,
                )
            )
            session.add(TaskIngestCursor(task_id=task_id, stream_name="event_jsonl"))
            if archive_dir is not None:
                archive_path = archive_dir / f"task-{task_id}.tar.gz"
                archive_path.write_bytes(b"archive")
                session.add(
                    TaskRunArchive(
                        task_id=task_id,
                        archive_name=archive_path.name,
                        archive_path=str(archive_path),
                        archive_size_bytes=7,
                    )
                )
            session.add(
                TaskUsageLedger(
                    task_id=task_id,
                    user_id=1,
                    task_status=task_status.value,
                    completed_at=created_at,
                    timezone_day=created_at.date(),
                    timezone_week_start=created_at.date(),
                )
            )
            session.add(
                MattermostNotificationDelivery(
                    task_id=task_id,
                    profile_id=1,
                    event_type="task_completed",
                    status="sent",
                    target_summary="channel",
                )
            )

        if task_ids:
            session.add(IssueExecutionLock(issue_id=issue_id, task_id=task_ids[0]))
        session.add(
            WebhookEvent(
                event_type="merge_request",
                project_id=issue.project_id,
                issue_id=issue_id,
                result="issue_closed",
            )
        )
        return task_ids

    async def _count(self, session, model) -> int:
        return await session.scalar(select(func.count()).select_from(model))

    async def test_default_cleanup_deletes_inactive_issue_data_files_and_workspace(self):
        from app.core.system_data_cleanup import cleanup_system_data

        async with self.Session() as session:
            old = utcnow() - timedelta(days=40)
            await self._seed_issue(
                session,
                issue_id=1,
                created_at=old,
                task_statuses=[TaskStatus.COMPLETED],
                archive_dir=self.temp_path,
            )
            workspace_root = self.temp_path / "workspaces"
            await session.commit()

            with patch(
                "app.core.system_data_cleanup.remove_issue_workspace_remote",
                new=AsyncMock(return_value=True),
            ) as remove_workspace:
                result = await cleanup_system_data(
                    session,
                    older_than_days=30,
                    force=False,
                    workspace_root=str(workspace_root),
                )

            self.assertEqual(result.deleted_issues, 1)
            self.assertEqual(result.deleted_tasks, 1)
            self.assertEqual(result.skipped_active_issues, 0)
            self.assertEqual(result.deleted_archives, 1)
            self.assertEqual(result.deleted_workspaces, 1)
            remove_workspace.assert_awaited_once()
            self.assertEqual(await self._count(session, Issue), 0)
            self.assertEqual(await self._count(session, Task), 0)
            self.assertEqual(await self._count(session, TaskLog), 0)
            self.assertEqual(await self._count(session, TaskPayload), 0)
            self.assertEqual(await self._count(session, TaskRawLogChunk), 0)
            self.assertEqual(await self._count(session, TaskIngestCursor), 0)
            self.assertEqual(await self._count(session, TaskRunArchive), 0)
            self.assertEqual(await self._count(session, TaskUsageLedger), 0)
            self.assertEqual(await self._count(session, MattermostNotificationDelivery), 0)
            self.assertEqual(await self._count(session, IssueExecutionLock), 0)
            webhook = (await session.execute(select(WebhookEvent))).scalar_one()
            self.assertIsNone(webhook.issue_id)

    async def test_default_cleanup_skips_active_issues(self):
        from app.core.system_data_cleanup import cleanup_system_data

        async with self.Session() as session:
            old = utcnow() - timedelta(days=40)
            await self._seed_issue(
                session,
                issue_id=2,
                created_at=old,
                task_statuses=[TaskStatus.PENDING, TaskStatus.COMPLETED],
            )
            await session.commit()

            result = await cleanup_system_data(
                session,
                older_than_days=30,
                force=False,
                workspace_root="",
            )

            self.assertEqual(result.deleted_issues, 0)
            self.assertEqual(result.deleted_tasks, 0)
            self.assertEqual(result.skipped_active_issues, 1)
            self.assertEqual(result.skipped_active_tasks, 1)
            self.assertEqual(await self._count(session, Issue), 1)
            self.assertEqual(await self._count(session, Task), 2)

    async def test_cleanup_commits_each_issue_before_processing_the_next_one(self):
        from app.core.system_data_cleanup import cleanup_system_data

        async with self.Session() as session:
            old = utcnow() - timedelta(days=40)
            await self._seed_issue(
                session,
                issue_id=20,
                created_at=old,
                task_statuses=[TaskStatus.COMPLETED],
            )
            await self._seed_issue(
                session,
                issue_id=21,
                created_at=old,
                task_statuses=[TaskStatus.COMPLETED],
            )
            await session.commit()

            original_commit = session.commit
            with patch.object(session, "commit", new=AsyncMock(wraps=original_commit)) as commit:
                result = await cleanup_system_data(
                    session,
                    older_than_days=30,
                    force=False,
                    workspace_root="",
                )

            self.assertEqual(result.deleted_issues, 2)
            self.assertEqual(commit.await_count, 2)
            self.assertEqual(await self._count(session, Issue), 0)

    async def test_force_cleanup_includes_active_issues_and_stops_running_containers(self):
        from app.core.system_data_cleanup import cleanup_system_data

        async with self.Session() as session:
            old = utcnow() - timedelta(days=40)
            await self._seed_issue(
                session,
                issue_id=3,
                created_at=old,
                task_statuses=[TaskStatus.RUNNING],
            )
            await session.commit()
            container = MagicMock()
            docker = MagicMock()
            docker.client.containers.get.return_value = container

            with patch("app.core.system_data_cleanup.get_docker_client_async", return_value=docker):
                result = await cleanup_system_data(
                    session,
                    older_than_days=30,
                    force=True,
                    workspace_root="",
                )

            self.assertEqual(result.deleted_issues, 1)
            self.assertEqual(result.deleted_tasks, 1)
            self.assertEqual(result.skipped_active_issues, 0)
            docker.client.containers.get.assert_called_once_with("codify-301-issue3")
            container.stop.assert_called_once_with(timeout=5)
            container.remove.assert_called_once_with(force=True, v=True)

    async def test_force_cleanup_removes_retained_terminal_container_by_id(self):
        from app.core.system_data_cleanup import cleanup_system_data

        async with self.Session() as session:
            old = utcnow() - timedelta(days=40)
            task_ids = await self._seed_issue(
                session,
                issue_id=6,
                created_at=old,
                task_statuses=[TaskStatus.FAILED],
            )
            task = await session.get(Task, task_ids[0])
            task.container_id = "retained-container-id"
            task.raw_logs_finalized_at = utcnow()
            await session.commit()
            container = MagicMock()
            docker = MagicMock()
            docker.client.containers.get.return_value = container

            with patch(
                "app.core.system_data_cleanup.get_docker_client_async",
                return_value=docker,
            ):
                result = await cleanup_system_data(
                    session,
                    older_than_days=30,
                    force=True,
                    workspace_root="",
                )

            self.assertEqual(result.deleted_tasks, 1)
            docker.client.containers.get.assert_called_once_with(
                "retained-container-id"
            )
            container.stop.assert_not_called()
            container.remove.assert_called_once_with(force=True, v=True)

    async def test_non_force_cleanup_skips_retained_terminal_container(self):
        from app.core.system_data_cleanup import cleanup_system_data

        async with self.Session() as session:
            old = utcnow() - timedelta(days=40)
            task_ids = await self._seed_issue(
                session,
                issue_id=8,
                created_at=old,
                task_statuses=[TaskStatus.FAILED],
            )
            task = await session.get(Task, task_ids[0])
            task.container_id = "retained-container-id"
            await session.commit()

            result = await cleanup_system_data(
                session,
                older_than_days=30,
                force=False,
                workspace_root="",
            )

            self.assertEqual(result.deleted_issues, 0)
            self.assertEqual(result.skipped_active_issues, 1)
            self.assertEqual(result.skipped_active_tasks, 1)
            self.assertEqual(await self._count(session, Task), 1)

    async def test_force_cleanup_preserves_issue_when_container_lookup_fails(self):
        from app.core.system_data_cleanup import cleanup_system_data

        async with self.Session() as session:
            old = utcnow() - timedelta(days=40)
            await self._seed_issue(
                session,
                issue_id=4,
                created_at=old,
                task_statuses=[TaskStatus.RUNNING],
            )
            await session.commit()
            docker = MagicMock()
            docker.client.containers.get.side_effect = RuntimeError("missing docker")

            with patch("app.core.system_data_cleanup.get_docker_client_async", return_value=docker):
                result = await cleanup_system_data(
                    session,
                    older_than_days=30,
                    force=True,
                    workspace_root="",
                )

            self.assertEqual(result.deleted_issues, 0)
            self.assertEqual(result.deleted_tasks, 0)
            self.assertEqual(result.container_cleanup_errors[0]["task_id"], 401)
            self.assertIn("missing docker", result.container_cleanup_errors[0]["error"])
            self.assertEqual(await self._count(session, Issue), 1)
            self.assertEqual(await self._count(session, Task), 1)

    async def test_force_cleanup_removes_container_after_stop_failure(self):
        from app.core.system_data_cleanup import cleanup_system_data

        async with self.Session() as session:
            old = utcnow() - timedelta(days=40)
            await self._seed_issue(
                session,
                issue_id=7,
                created_at=old,
                task_statuses=[TaskStatus.RUNNING],
            )
            await session.commit()
            container = MagicMock()
            container.stop.side_effect = RuntimeError("stop timed out")
            docker = MagicMock()
            docker.client.containers.get.return_value = container

            with patch("app.core.system_data_cleanup.get_docker_client_async", return_value=docker):
                result = await cleanup_system_data(
                    session,
                    older_than_days=30,
                    force=True,
                    workspace_root="",
                )

            container.remove.assert_called_once_with(force=True, v=True)
            self.assertEqual(result.container_cleanup_errors, [])
            self.assertEqual(result.deleted_issues, 1)

    async def test_retention_filter_keeps_recent_issues(self):
        from app.core.system_data_cleanup import cleanup_system_data

        async with self.Session() as session:
            recent = utcnow() - timedelta(days=2)
            await self._seed_issue(
                session,
                issue_id=5,
                created_at=recent,
                task_statuses=[TaskStatus.COMPLETED],
            )
            await session.commit()

            result = await cleanup_system_data(
                session,
                older_than_days=30,
                force=False,
                workspace_root="",
            )

            self.assertEqual(result.deleted_issues, 0)
            self.assertEqual(await self._count(session, Issue), 1)
