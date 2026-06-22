import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.models import Base, CIFailureJob, CIFailureRun, CIFailureRunLog, Issue, Task, TaskStatus


class FakeGitLabClient:
    def __init__(self, *, mr=None, jobs=None, traces=None):
        self.mr = mr or {
            "source_branch": "codify/issue-1",
            "target_branch": "main",
            "sha": "abc123",
        }
        self.jobs = jobs or []
        self.traces = traces or {}

    def get_merge_request_details(self, project_id, mr_iid):
        return self.mr

    def get_pipeline_jobs(self, project_id, pipeline_id):
        return self.jobs

    def get_job_trace(self, project_id, job_id):
        return self.traces[job_id]


class CIFailureCollectorTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tempdir = tempfile.TemporaryDirectory()
        self.workspace_root = Path(self.tempdir.name)
        self.engine = create_async_engine(
            "sqlite+aiosqlite:///:memory:",
            poolclass=StaticPool,
            connect_args={"check_same_thread": False},
        )
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.Session = async_sessionmaker(self.engine, expire_on_commit=False)

    async def asyncTearDown(self):
        await self.engine.dispose()
        self.tempdir.cleanup()

    def _settings(self, **overrides):
        from app.core.task_prompt import BUILT_IN_CI_AUTO_REPAIR_RUN_INSTRUCTION_TEMPLATE

        values = {
            "ci_auto_repair_max_attempts": 2,
            "worker_workspace_host_path": str(self.workspace_root),
            "ci_auto_repair_run_instruction_template": (
                BUILT_IN_CI_AUTO_REPAIR_RUN_INSTRUCTION_TEMPLATE
            ),
        }
        values.update(overrides)
        return SimpleNamespace(**values)

    async def _seed_issue_and_run(self, session, *, enabled=True, sha="abc123"):
        issue = Issue(
            id=1,
            title="Repair CI",
            project_id=42,
            status="in_review",
            branch_name="codify/issue-1",
            target_branch="main",
            merge_request_iid=7,
            ci_auto_repair_enabled=enabled,
            initiator_user_id=9,
            initiator_username="alice",
        )
        session.add(issue)
        session.add(
            Task(
                id=10,
                issue_id=1,
                project_id=42,
                user_prompt="Original task",
                status=TaskStatus.COMPLETED,
                priority=1,
                provider_id=3,
                task_mode="execute",
            )
        )
        run = CIFailureRun(
            id=91,
            project_id=42,
            merge_request_iid=7,
            pipeline_id=678,
            pipeline_sha=sha,
            pipeline_ref="codify/issue-1",
            pipeline_status="failed",
            pipeline_url="https://gitlab.example.com/group/project/-/pipelines/678",
            status="collecting",
        )
        session.add(run)
        await session.commit()
        return issue, run

    def _code_failure_jobs(self):
        jobs = [
            {
                "id": 40001,
                "name": "unit-test",
                "stage": "test",
                "status": "failed",
                "failure_reason": "script_failure",
                "allow_failure": False,
                "web_url": "https://gitlab.example.com/job/40001",
            }
        ]
        return jobs, {40001: "pytest failed\n"}

    def _prior_ci_repair_task(self, task_id: int, created_at: datetime) -> Task:
        return Task(
            id=task_id,
            issue_id=1,
            project_id=42,
            user_prompt="Prior CI repair",
            status=TaskStatus.COMPLETED,
            priority=1,
            task_mode="execute",
            trigger_source="ci_auto_repair",
            created_at=created_at,
            completed_at=created_at,
        )

    async def test_collector_refreshes_runtime_config_before_reading_settings(self):
        from app.core.ci_failure_collector import run_ci_failure_collector_once

        events: list[str] = []
        refresh = AsyncMock(side_effect=lambda *_args, **_kwargs: events.append("refresh"))
        claim = AsyncMock(return_value=[])

        def get_settings():
            self.assertEqual(events, ["refresh"])
            events.append("settings")
            return self._settings()

        with (
            patch("app.core.ci_failure_collector.AsyncSessionLocal", self.Session),
            patch("app.core.ci_failure_collector.refresh_runtime_config_if_stale", refresh),
            patch("app.core.ci_failure_collector.get_effective_settings", side_effect=get_settings),
            patch("app.core.ci_failure_collector.claim_collecting_runs", claim),
        ):
            processed = await run_ci_failure_collector_once(collector_id="test")

        self.assertEqual(processed, 0)
        self.assertEqual(events, ["refresh", "settings"])
        refresh.assert_awaited_once()
        self.assertEqual(refresh.await_args.kwargs, {"min_check_interval": 0.0})

    async def test_disabled_issue_records_ignored_reason_without_task(self):
        from app.core.ci_failure_collector import process_ci_failure_run

        async with self.Session() as session:
            _, run = await self._seed_issue_and_run(session, enabled=False)

            await process_ci_failure_run(
                session,
                run.id,
                gitlab_client=FakeGitLabClient(),
                settings=self._settings(),
                collector_id="test",
            )

            refreshed = await session.get(CIFailureRun, run.id)
            self.assertEqual(refreshed.status, "ignored")
            self.assertEqual(refreshed.ignored_reason, "ci_auto_repair_disabled")
            tasks = (await session.execute(select(Task).where(Task.trigger_source == "ci_auto_repair"))).scalars().all()
            self.assertEqual(tasks, [])
            logs = (await session.execute(select(CIFailureRunLog))).scalars().all()
            self.assertTrue(any(log.step == "auto_repair_gate_checked" and log.status == "skipped" for log in logs))

    async def test_code_failure_writes_sanitized_bundle_and_creates_repair_task(self):
        from app.core.ci_failure_collector import process_ci_failure_run

        jobs = [
            {
                "id": 12345,
                "name": "build",
                "stage": "build",
                "status": "failed",
                "failure_reason": "script_failure",
                "allow_failure": False,
                "web_url": "https://gitlab.example.com/job/12345",
                "created_at": "2026-06-13T09:59:00Z",
                "started_at": "2026-06-13T10:00:00Z",
            },
            {
                "id": 12346,
                "name": "unit-test",
                "stage": "test",
                "status": "failed",
                "failure_reason": "script_failure",
                "allow_failure": False,
                "web_url": "https://gitlab.example.com/job/12346",
                "created_at": "2026-06-13T10:01:00Z",
                "started_at": "2026-06-13T10:02:00Z",
            },
        ]
        traces = {
            12345: "running build\nnpm test failed\nglpat-secret-token\n",
            12346: "downstream failure\n",
        }

        async with self.Session() as session:
            _, run = await self._seed_issue_and_run(session, enabled=True)

            with patch(
                "app.core.ci_failure_collector.get_project_metadata",
                new_callable=AsyncMock,
                return_value={"project_name": "test-project", "project_path_with_namespace": "group/test-project"},
            ):
                await process_ci_failure_run(
                    session,
                    run.id,
                    gitlab_client=FakeGitLabClient(jobs=jobs, traces=traces),
                    settings=self._settings(),
                    collector_id="test",
                )

            refreshed = await session.get(CIFailureRun, run.id)
            self.assertEqual(refreshed.status, "task_created")
            self.assertIsNotNone(refreshed.repair_task_id)
            self.assertTrue(Path(refreshed.bundle_path).exists())

            repair_task = await session.get(Task, refreshed.repair_task_id)
            self.assertEqual(repair_task.trigger_source, "ci_auto_repair")
            self.assertEqual(repair_task.ci_failure_run_id, run.id)
            self.assertEqual(repair_task.issue_id, 1)
            self.assertEqual(repair_task.provider_id, 3)
            self.assertEqual(repair_task.priority, 1)
            self.assertEqual(repair_task.task_mode, "execute")
            self.assertTrue(repair_task.require_changes)
            self.assertEqual(repair_task.user_prompt, "修复当前 MR 的 CI 失败")
            self.assertIn("/tmp/codify-runtime/ci-failure", repair_task.rendered_prompt)

            rows = (await session.execute(select(CIFailureJob).order_by(CIFailureJob.gitlab_job_id))).scalars().all()
            self.assertEqual(len(rows), 2)
            self.assertTrue(rows[0].is_root_cause)
            self.assertFalse(rows[0].is_downstream_suppressed)
            self.assertFalse(rows[1].is_root_cause)
            self.assertTrue(rows[1].is_downstream_suppressed)

            trace_path = Path(refreshed.bundle_path) / rows[0].trace_path
            trace_text = trace_path.read_text(encoding="utf-8")
            self.assertIn("[REDACTED]", trace_text)
            self.assertNotIn("glpat-secret-token", trace_text)

            steps = [(log.step, log.status) for log in (await session.execute(select(CIFailureRunLog))).scalars().all()]
            self.assertIn(("repair_task_created", "succeeded"), steps)

    async def test_max_attempts_reached_blocks_without_manual_execute_reset(self):
        from app.core.ci_failure_collector import process_ci_failure_run

        async with self.Session() as session:
            _, run = await self._seed_issue_and_run(session, enabled=True)
            session.add_all(
                [
                    self._prior_ci_repair_task(11, datetime(2026, 6, 17, 10, 0, 0)),
                    self._prior_ci_repair_task(12, datetime(2026, 6, 17, 10, 1, 0)),
                ]
            )
            await session.commit()

            await process_ci_failure_run(
                session,
                run.id,
                gitlab_client=FakeGitLabClient(),
                settings=self._settings(ci_auto_repair_max_attempts=2),
                collector_id="test",
            )

            refreshed = await session.get(CIFailureRun, run.id)
            self.assertEqual(refreshed.status, "ignored")
            self.assertEqual(refreshed.ignored_reason, "max_attempts_exceeded")

            logs = (
                await session.execute(
                    select(CIFailureRunLog).where(CIFailureRunLog.step == "auto_repair_gate_checked")
                )
            ).scalars().all()
            self.assertEqual(logs[-1].details["attempts"], 2)
            self.assertNotIn("reset_after_task_id", logs[-1].details)

    async def test_successful_manual_execute_resets_ci_auto_repair_attempt_budget(self):
        from app.core.ci_failure_collector import process_ci_failure_run

        jobs, traces = self._code_failure_jobs()
        async with self.Session() as session:
            _, run = await self._seed_issue_and_run(session, enabled=True)
            session.add_all(
                [
                    self._prior_ci_repair_task(11, datetime(2026, 6, 17, 10, 0, 0)),
                    self._prior_ci_repair_task(12, datetime(2026, 6, 17, 10, 1, 0)),
                    Task(
                        id=13,
                        issue_id=1,
                        project_id=42,
                        user_prompt="Manual verification fix",
                        status=TaskStatus.COMPLETED,
                        priority=1,
                        task_mode="execute",
                        trigger_source="manual",
                        created_at=datetime(2026, 6, 17, 10, 2, 0),
                        completed_at=datetime(2026, 6, 17, 10, 5, 0),
                    ),
                ]
            )
            await session.commit()

            with patch(
                "app.core.ci_failure_collector.get_project_metadata",
                new_callable=AsyncMock,
                return_value={"project_name": "test-project", "project_path_with_namespace": "group/test-project"},
            ):
                await process_ci_failure_run(
                    session,
                    run.id,
                    gitlab_client=FakeGitLabClient(jobs=jobs, traces=traces),
                    settings=self._settings(ci_auto_repair_max_attempts=2),
                    collector_id="test",
                )

            refreshed = await session.get(CIFailureRun, run.id)
            self.assertEqual(refreshed.status, "task_created")
            self.assertIsNotNone(refreshed.repair_task_id)

            logs = (
                await session.execute(
                    select(CIFailureRunLog).where(CIFailureRunLog.step == "auto_repair_gate_checked")
                )
            ).scalars().all()
            self.assertEqual(logs[-1].status, "succeeded")
            self.assertEqual(logs[-1].details["attempts"], 0)
            self.assertEqual(logs[-1].details["reset_after_task_id"], 13)

    async def test_successful_manual_plan_does_not_reset_ci_auto_repair_attempt_budget(self):
        from app.core.ci_failure_collector import process_ci_failure_run

        async with self.Session() as session:
            _, run = await self._seed_issue_and_run(session, enabled=True)
            session.add_all(
                [
                    self._prior_ci_repair_task(11, datetime(2026, 6, 17, 10, 0, 0)),
                    self._prior_ci_repair_task(12, datetime(2026, 6, 17, 10, 1, 0)),
                    Task(
                        id=13,
                        issue_id=1,
                        project_id=42,
                        user_prompt="Manual plan only",
                        status=TaskStatus.COMPLETED,
                        priority=1,
                        task_mode="plan",
                        trigger_source="manual",
                        created_at=datetime(2026, 6, 17, 10, 2, 0),
                        completed_at=datetime(2026, 6, 17, 10, 5, 0),
                    ),
                ]
            )
            await session.commit()

            await process_ci_failure_run(
                session,
                run.id,
                gitlab_client=FakeGitLabClient(),
                settings=self._settings(ci_auto_repair_max_attempts=2),
                collector_id="test",
            )

            refreshed = await session.get(CIFailureRun, run.id)
            self.assertEqual(refreshed.status, "ignored")
            self.assertEqual(refreshed.ignored_reason, "max_attempts_exceeded")

            logs = (
                await session.execute(
                    select(CIFailureRunLog).where(CIFailureRunLog.step == "auto_repair_gate_checked")
                )
            ).scalars().all()
            self.assertEqual(logs[-1].details["attempts"], 2)
            self.assertNotIn("reset_after_task_id", logs[-1].details)

    async def test_pipeline_ref_fallback_matches_issue_by_branch_name(self):
        from app.core.ci_failure_collector import process_ci_failure_run

        jobs = [
            {
                "id": 30001,
                "name": "build",
                "stage": "build",
                "status": "failed",
                "failure_reason": "script_failure",
                "allow_failure": False,
                "web_url": "https://gitlab.example.com/job/30001",
            },
        ]

        async with self.Session() as session:
            issue = Issue(
                id=2,
                title="Fix pipeline",
                project_id=42,
                status="in_review",
                branch_name="codify/issue-66",
                target_branch="main",
                ci_auto_repair_enabled=True,
                initiator_user_id=9,
                initiator_username="alice",
            )
            session.add(issue)
            session.add(
                Task(
                    id=20,
                    issue_id=2,
                    project_id=42,
                    user_prompt="Original task",
                    status=TaskStatus.COMPLETED,
                    priority=1,
                    provider_id=3,
                    task_mode="execute",
                )
            )
            run = CIFailureRun(
                id=92,
                project_id=42,
                merge_request_iid=None,
                source_branch=None,
                pipeline_id=700,
                pipeline_sha="def456",
                pipeline_ref="codify/issue-66",
                pipeline_status="failed",
                pipeline_url="https://gitlab.example.com/group/project/-/pipelines/700",
                status="collecting",
            )
            session.add(run)
            await session.commit()

            with patch(
                "app.core.ci_failure_collector.get_project_metadata",
                new_callable=AsyncMock,
                return_value={"project_name": "test-project", "project_path_with_namespace": "group/test-project"},
            ):
                await process_ci_failure_run(
                    session,
                    run.id,
                    gitlab_client=FakeGitLabClient(mr={}, jobs=jobs, traces={30001: "build failed\n"}),
                    settings=self._settings(),
                    collector_id="test",
                )

            refreshed = await session.get(CIFailureRun, run.id)
            self.assertEqual(refreshed.issue_id, 2)
            self.assertEqual(refreshed.status, "task_created")

    async def test_infra_failure_is_ignored_without_downloading_trace(self):
        from app.core.ci_failure_collector import process_ci_failure_run

        jobs = [
            {
                "id": 20001,
                "name": "deploy",
                "stage": "deploy",
                "status": "failed",
                "failure_reason": "runner_system_failure",
                "allow_failure": False,
            }
        ]
        fake_client = FakeGitLabClient(jobs=jobs, traces={})

        async with self.Session() as session:
            _, run = await self._seed_issue_and_run(session, enabled=True)

            await process_ci_failure_run(
                session,
                run.id,
                gitlab_client=fake_client,
                settings=self._settings(),
                collector_id="test",
            )

            refreshed = await session.get(CIFailureRun, run.id)
            self.assertEqual(refreshed.status, "ignored")
            self.assertEqual(refreshed.ignored_reason, "infra_failure_detected")
            tasks = (await session.execute(select(Task).where(Task.trigger_source == "ci_auto_repair"))).scalars().all()
            self.assertEqual(tasks, [])
