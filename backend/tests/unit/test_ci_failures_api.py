import unittest
from datetime import datetime, timedelta

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.api.ci_failures import list_issue_ci_failures
from app.dependencies.project_access import ProjectAccessScope
from app.models import Base, CIFailureRun, CIFailureRunLog, Issue, WorkerProfile


class ListIssueCIFailuresTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
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

    async def test_list_includes_logs_for_all_runs_in_one_response(self):
        now = datetime(2026, 6, 19, 8, 0, 0)
        async with self.Session() as session:
            session.add(
                WorkerProfile(
                    id=1,
                    name="CI Worker",
                    enabled=True,
                    image="codify-worker:test",
                    volume_mounts=[],
                    pre_script="",
                    post_script="",
                    default_execute_run_instruction_template="{{user_prompt}}",
                    default_plan_run_instruction_template="{{user_prompt}}",
                    ci_auto_repair_run_instruction_template="{{user_prompt}}",
                )
            )
            session.add(
                Issue(
                    id=66,
                    title="Repair CI",
                    project_id=42,
                    status="in_review",
                    worker_profile_id=1,
                )
            )
            session.add_all(
                [
                    CIFailureRun(
                        id=12,
                        project_id=42,
                        issue_id=66,
                        pipeline_id=1200,
                        pipeline_sha="a" * 40,
                        pipeline_status="failed",
                        created_at=now,
                    ),
                    CIFailureRun(
                        id=11,
                        project_id=42,
                        issue_id=66,
                        pipeline_id=1100,
                        pipeline_sha="b" * 40,
                        pipeline_status="failed",
                        created_at=now - timedelta(minutes=1),
                    ),
                ]
            )
            session.add_all(
                [
                    CIFailureRunLog(
                        id=2,
                        ci_failure_run_id=12,
                        issue_id=66,
                        step="second",
                        status="success",
                        created_at=now + timedelta(seconds=2),
                    ),
                    CIFailureRunLog(
                        id=1,
                        ci_failure_run_id=12,
                        issue_id=66,
                        step="first",
                        status="success",
                        created_at=now + timedelta(seconds=1),
                    ),
                    CIFailureRunLog(
                        id=3,
                        ci_failure_run_id=11,
                        issue_id=66,
                        step="only",
                        status="success",
                        created_at=now,
                    ),
                ]
            )
            await session.commit()

            response = await list_issue_ci_failures(
                issue_id=66,
                page=1,
                page_size=5,
                db=session,
                access_scope=ProjectAccessScope(is_unrestricted=True, accessible_projects=[]),
            )

        self.assertEqual([item["id"] for item in response["items"]], [12, 11])
        self.assertEqual(
            [log["step"] for log in response["items"][0]["logs"]],
            ["first", "second"],
        )
        self.assertEqual(
            [log["step"] for log in response["items"][1]["logs"]],
            ["only"],
        )
