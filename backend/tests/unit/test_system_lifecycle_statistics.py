"""System lifecycle statistics: archive service, query builders, API and §6.4 stats writers.

Covers the system lifecycle statistics design §15.1 acceptance checklist on an
in-memory SQLite schema (row-lock + same-transaction deletion semantics run
against real PostgreSQL in test_system_lifecycle_statistics_pg.py).
"""

import asyncio
import unittest
from datetime import datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient
from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.change_stats import validate_change_statistics
from app.core.utcnow import utcnow
from app.models import (
    AIProvider,
    Base,
    DeletedIssueStatistics,
    DeletedTaskStatistics,
    Issue,
    SystemStatisticsMetadata,
    Task,
    TaskStatus,
    TaskWorkerProfileSnapshot,
    WorkerProfile,
)

# ---------------------------------------------------------------------------
# Shared SQLite scaffolding
# ---------------------------------------------------------------------------


def _make_engine():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    return engine


async def _create_schema(engine):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


def _snapshot(task_id: int, *, harness_key: str = "claude") -> TaskWorkerProfileSnapshot:
    return TaskWorkerProfileSnapshot(
        task_id=task_id,
        worker_profile_id=1,
        profile_name="Default Worker",
        image="codify-worker:test",
        volume_mounts=[],
        environment_variables=[],
        pre_script="",
        post_script="",
        default_execute_run_instruction_template="{{user_prompt}}",
        default_plan_run_instruction_template="{{user_prompt}}",
        ci_auto_repair_run_instruction_template="{{issue_title}}",
        harness_key=harness_key,
        harness_adapter_version="1.2",
        cli_version="2.0",
    )


async def _seed_base(session) -> None:
    session.add(
        WorkerProfile(
            id=1,
            name="Default Worker",
            enabled=True,
            is_default=True,
            image="codify-worker:test",
            volume_mounts=[],
            pre_script="",
            post_script="",
            default_execute_run_instruction_template="{{user_prompt}}",
            default_plan_run_instruction_template="{{user_prompt}}",
            ci_auto_repair_run_instruction_template="{{issue_title}}",
        )
    )
    session.add(
        AIProvider(
            id=10,
            name="SnapProvider",
            model="snap-model",
            base_url="https://provider.example.test",
            is_default=True,
            is_disabled=False,
        )
    )
    session.add(SystemStatisticsMetadata(id=1, capture_started_at=None))
    await session.flush()


def _seed_issue(
    session,
    issue_id: int,
    *,
    project_id: int = 1,
    status: str = "open",
    created_at: datetime,
    merge_request_iid: int | None = None,
) -> None:
    session.add(
        Issue(
            id=issue_id,
            title=f"Issue {issue_id}",
            project_id=project_id,
            status=status,
            worker_profile_id=1,
            created_at=created_at,
            updated_at=created_at,
            merge_request_iid=merge_request_iid,
        )
    )


def _seed_task(
    session,
    task_id: int,
    issue_id: int,
    *,
    status: TaskStatus = TaskStatus.COMPLETED,
    created_at: datetime,
    started_at: datetime | None = None,
    completed_at: datetime | None = None,
    provider_id: int | None = 10,
    change_stats_recorded_at: datetime | None = None,
    additions: int = 0,
    deletions: int = 0,
    total_changes: int = 0,
    input_tokens: int | None = None,
    output_tokens: int | None = None,
    task_mode: str = "execute",
    harness_key: str = "claude",
    snapshot: bool = True,
    provider_runtime_snapshot: dict | None = None,
) -> None:
    if provider_runtime_snapshot is None:
        provider_runtime_snapshot = {
            "provider_id": provider_id,
            "provider_name": "Snap",
            "configured_model": "snap-model",
        }
    session.add(
        Task(
            id=task_id,
            issue_id=issue_id,
            project_id=1,
            user_prompt=f"Task {task_id}",
            status=status,
            provider_id=provider_id,
            provider_runtime_snapshot=provider_runtime_snapshot,
            task_mode=task_mode,
            created_at=created_at,
            updated_at=created_at,
            started_at=started_at,
            completed_at=completed_at,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            additions=additions,
            deletions=deletions,
            total_changes=total_changes,
            change_stats_recorded_at=change_stats_recorded_at,
        )
    )
    if snapshot:
        session.add(_snapshot(task_id, harness_key=harness_key))


# ---------------------------------------------------------------------------
# §6.4 change-statistics validation
# ---------------------------------------------------------------------------


class ChangeStatsValidationTests(unittest.TestCase):
    def test_accepts_real_zeros(self):
        self.assertIsNone(validate_change_statistics(0, 0, 0))

    def test_accepts_positive_triple(self):
        self.assertIsNone(validate_change_statistics(5, 2, 7))

    def test_rejects_negative(self):
        self.assertIsNotNone(validate_change_statistics(-1, 0, -1))

    def test_rejects_mismatched_total(self):
        self.assertIsNotNone(validate_change_statistics(5, 2, 9))

    def test_rejects_non_integer(self):
        self.assertIsNotNone(validate_change_statistics("5.5", 2, 7))

    def test_accepts_integer_strings(self):
        self.assertIsNone(validate_change_statistics("5", "2", "7"))


# ---------------------------------------------------------------------------
# §7 deletion archive service
# ---------------------------------------------------------------------------


class ArchiveServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = _make_engine()
        await _create_schema(self.engine)
        self.Session = async_sessionmaker(self.engine, expire_on_commit=False)

    async def asyncTearDown(self):
        await self.engine.dispose()

    async def test_archives_issue_and_tasks_with_normalized_values(self):
        from app.core.system_statistics_deletion import archive_issue_statistics_before_delete

        now = utcnow()
        async with self.Session() as db:
            await _seed_base(db)
            _seed_issue(
                db, 1, created_at=now - timedelta(days=5), merge_request_iid=42
            )
            _seed_task(
                db,
                1,
                1,
                status=TaskStatus.COMPLETED,
                created_at=now - timedelta(days=5),
                started_at=now - timedelta(hours=2),
                completed_at=now,
                change_stats_recorded_at=now,
                additions=5,
                deletions=2,
                total_changes=7,
                input_tokens=100,
                output_tokens=50,
            )
            _seed_task(
                db,
                2,
                1,
                status=TaskStatus.FAILED,
                created_at=now - timedelta(days=5),
                provider_id=None,
                harness_key="codex",
                change_stats_recorded_at=None,
                snapshot=True,
            )
            await db.commit()

            archived = await archive_issue_statistics_before_delete(
                db, issue_id=1, deletion_reason="manual", deleted_by_user_id=7, now=now
            )
            self.assertEqual(archived, 2)

            rows = list(
                (
                    await db.execute(
                        select(DeletedTaskStatistics).order_by(
                            DeletedTaskStatistics.source_task_id
                        )
                    )
                )
                .scalars()
                .all()
            )
            self.assertEqual(len(rows), 2)

            completed = rows[0]
            self.assertEqual(completed.source_issue_id, 1)
            self.assertEqual(completed.project_id, 1)
            self.assertEqual(completed.initiator_user_id, None)
            self.assertEqual(completed.provider_id, 10)
            self.assertEqual(completed.provider_name_snapshot, "Snap")
            self.assertEqual(completed.provider_model_snapshot, "snap-model")
            self.assertEqual(completed.harness_key, "claude")
            self.assertEqual(completed.adapter_version, "1.2")
            self.assertEqual(completed.cli_version, "2.0")
            self.assertEqual(completed.last_status, "completed")
            self.assertFalse(completed.deleted_before_terminal)
            self.assertEqual(completed.terminal_at, now)
            self.assertTrue(completed.change_data_available)
            self.assertEqual(completed.additions, 5)
            self.assertEqual(completed.deletions, 2)
            self.assertEqual(completed.total_changes, 7)
            self.assertEqual(completed.deleted_by_user_id, 7)
            self.assertEqual(completed.deletion_reason, "manual")

            failed = rows[1]
            self.assertEqual(failed.last_status, "failed")
            self.assertEqual(failed.terminal_at, None)
            self.assertFalse(failed.change_data_available)
            self.assertIsNone(failed.additions)
            self.assertIsNone(failed.total_changes)

            issue_row = (
                await db.execute(select(DeletedIssueStatistics))
            ).scalar_one()
            self.assertTrue(issue_row.had_merge_request)
            self.assertEqual(issue_row.deletion_reason, "manual")
            self.assertEqual(issue_row.deleted_by_user_id, 7)
            self.assertFalse(issue_row.forced_with_active_tasks)

    async def test_rearchive_is_idempotent_upsert(self):
        from app.core.system_statistics_deletion import archive_issue_statistics_before_delete

        now = utcnow()
        async with self.Session() as db:
            await _seed_base(db)
            _seed_issue(db, 1, created_at=now - timedelta(days=5))
            _seed_task(
                db,
                1,
                1,
                status=TaskStatus.COMPLETED,
                created_at=now - timedelta(days=5),
                change_stats_recorded_at=now,
                additions=1,
                deletions=1,
                total_changes=2,
            )
            await db.commit()

            await archive_issue_statistics_before_delete(
                db, issue_id=1, deletion_reason="manual", deleted_by_user_id=1, now=now
            )
            db.expire_all()
            await archive_issue_statistics_before_delete(
                db, issue_id=1, deletion_reason="cleanup", deleted_by_user_id=None, now=now
            )
            await db.commit()

            task_rows = list(
                (await db.execute(select(DeletedTaskStatistics))).scalars().all()
            )
            self.assertEqual(len(task_rows), 1)
            self.assertEqual(task_rows[0].deletion_reason, "cleanup")
            issue_row = (
                await db.execute(select(DeletedIssueStatistics))
            ).scalar_one()
            self.assertEqual(issue_row.deletion_reason, "cleanup")

    async def test_missing_issue_raises(self):
        from app.core.system_statistics_deletion import archive_issue_statistics_before_delete

        async with self.Session() as db:
            with self.assertRaises(ValueError):
                await archive_issue_statistics_before_delete(db, issue_id=999)

    async def test_archive_failure_rolls_back_business_delete(self):
        from app.core.system_statistics_deletion import archive_issue_statistics_before_delete

        now = utcnow()
        async with self.Session() as db:
            await _seed_base(db)
            _seed_issue(db, 1, created_at=now - timedelta(days=5))
            _seed_task(
                db,
                1,
                1,
                status=TaskStatus.COMPLETED,
                created_at=now - timedelta(days=5),
            )
            await db.commit()

            with patch(
                "app.core.system_statistics_deletion._task_upsert_statement",
                side_effect=RuntimeError("archive boom"),
            ):
                with self.assertRaises(RuntimeError):
                    await archive_issue_statistics_before_delete(
                        db, issue_id=1, deletion_reason="manual", now=now
                    )
            await db.rollback()

            # Nothing persisted: business rows + no archive rows.
            self.assertEqual(await db.scalar(select(func.count()).select_from(Issue)), 1)
            self.assertEqual(await db.scalar(select(func.count()).select_from(Task)), 1)
            self.assertEqual(
                await db.scalar(select(func.count()).select_from(DeletedTaskStatistics)), 0
            )


# ---------------------------------------------------------------------------
# §7 cleanup path archives in the same transaction as the delete
# ---------------------------------------------------------------------------


class CleanupArchivesLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = _make_engine()
        await _create_schema(self.engine)
        self.Session = async_sessionmaker(self.engine, expire_on_commit=False)

    async def asyncTearDown(self):
        await self.engine.dispose()

    async def test_cleanup_archives_before_delete(self):
        from app.core.system_data_cleanup import cleanup_system_data

        now = utcnow()
        async with self.Session() as db:
            await _seed_base(db)
            _seed_issue(
                db, 1, created_at=now - timedelta(days=40), merge_request_iid=7
            )
            _seed_task(
                db,
                1,
                1,
                status=TaskStatus.COMPLETED,
                created_at=now - timedelta(days=40),
                change_stats_recorded_at=now,
                additions=3,
                deletions=1,
                total_changes=4,
            )
            await db.commit()

            result = await cleanup_system_data(
                db,
                older_than_days=30,
                force=False,
                workspace_root="",
            )

            self.assertEqual(result.deleted_issues, 1)
            self.assertEqual(result.deleted_tasks, 1)
            # Business rows gone.
            self.assertEqual(await db.scalar(select(func.count()).select_from(Issue)), 0)
            self.assertEqual(await db.scalar(select(func.count()).select_from(Task)), 0)
            # Lifecycle archive rows written in the same transaction.
            self.assertEqual(
                await db.scalar(select(func.count()).select_from(DeletedTaskStatistics)),
                1,
            )
            self.assertEqual(
                await db.scalar(select(func.count()).select_from(DeletedIssueStatistics)),
                1,
            )
            archived = (
                await db.execute(select(DeletedTaskStatistics))
            ).scalar_one()
            self.assertEqual(archived.deletion_reason, "cleanup")
            self.assertTrue(archived.change_data_available)
            self.assertEqual(archived.total_changes, 4)
            issue_archive = (
                await db.execute(select(DeletedIssueStatistics))
            ).scalar_one()
            self.assertEqual(issue_archive.deletion_reason, "cleanup")
            self.assertTrue(issue_archive.had_merge_request)


# ---------------------------------------------------------------------------
# §8–9 query builders
# ---------------------------------------------------------------------------


class QueryBuilderTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = _make_engine()
        await _create_schema(self.engine)
        self.Session = async_sessionmaker(self.engine, expire_on_commit=False)
        self.dialect = "sqlite"
        self.now = utcnow()

        async with self.Session() as db:
            await _seed_base(db)
            _seed_issue(
                db, 1, created_at=self.now - timedelta(days=5), merge_request_iid=42
            )
            _seed_task(
                db,
                1,
                1,
                status=TaskStatus.COMPLETED,
                created_at=self.now - timedelta(days=5),
                started_at=self.now - timedelta(hours=2),
                completed_at=self.now,
                change_stats_recorded_at=self.now,
                additions=5,
                deletions=2,
                total_changes=7,
                input_tokens=100,
                output_tokens=50,
            )
            _seed_issue(db, 2, status="closed", created_at=self.now - timedelta(days=3))
            _seed_task(
                db,
                2,
                2,
                status=TaskStatus.QUEUED,
                created_at=self.now - timedelta(minutes=10),
                provider_id=None,
                harness_key="codex",
                input_tokens=None,
                output_tokens=None,
                provider_runtime_snapshot=None,
            )
            # Archive issue 1 + task 1, then delete the business rows so the
            # UNION CTE exercises both the retained and the deleted branch.
            from app.core.system_statistics_deletion import (
                archive_issue_statistics_before_delete,
            )

            await archive_issue_statistics_before_delete(
                db, issue_id=1, deletion_reason="cleanup", now=self.now
            )
            await db.execute(delete(Task).where(Task.id == 1))
            await db.execute(delete(Issue).where(Issue.id == 1))
            await db.commit()

    async def asyncTearDown(self):
        await self.engine.dispose()

    def _ctes(self, data_state="all"):
        from app.api import system_statistics_queries as q

        all_tasks = q.build_all_task_statistics_cte(
            dialect=self.dialect,
            project_id=None,
            provider_id=None,
            harness_key=None,
            data_state=data_state,
        )
        all_issues = q.build_all_issue_statistics_cte(
            project_id=None, data_state=data_state
        )
        return q, all_tasks, all_issues

    async def test_lifetime_aggregates(self):
        q, all_tasks, all_issues = self._ctes()
        async with self.Session() as db:
            lt = (await db.execute(q.build_lifetime_task_query(self.dialect, all_tasks))).one()
            li = (await db.execute(q.build_lifetime_issue_query(all_issues))).one()
        self.assertEqual(lt.task_count, 2)
        self.assertEqual(lt.completed, 1)
        self.assertEqual(lt.known_input_tokens, 100)
        self.assertEqual(lt.known_output_tokens, 50)
        self.assertEqual(lt.known_total_changes, 7)
        self.assertEqual(lt.token_eligible_samples, 1)
        self.assertEqual(lt.code_eligible_samples, 1)
        self.assertEqual(lt.change_available_samples, 1)
        self.assertEqual(li.issue_count, 2)
        self.assertEqual(li.issues_with_mr, 1)  # archived issue 1 had an MR

    async def test_data_state_deleted_only(self):
        q, all_tasks, _ = self._ctes(data_state="deleted")
        async with self.Session() as db:
            lt = (await db.execute(q.build_lifetime_task_query(self.dialect, all_tasks))).one()
        # Only the archived (deleted) task is visible.
        self.assertEqual(lt.task_count, 1)
        self.assertEqual(lt.deleted_task_count, 1)

    async def test_data_state_retained_only(self):
        q, all_tasks, _ = self._ctes(data_state="retained")
        async with self.Session() as db:
            lt = (await db.execute(q.build_lifetime_task_query(self.dialect, all_tasks))).one()
        self.assertEqual(lt.task_count, 1)
        self.assertEqual(lt.deleted_task_count, 0)

    async def test_current_state(self):
        from app.api import system_statistics_queries as q

        async with self.Session() as db:
            cs = (
                await db.execute(
                    q.build_current_state_task_query(
                        dialect=self.dialect,
                        project_id=None,
                        provider_id=None,
                        harness_key=None,
                        now=self.now,
                    )
                )
            ).one()
            ai = (await db.execute(q.build_current_state_issue_query(project_id=None))).one()
        self.assertEqual(cs.pending, 0)
        self.assertEqual(cs.queued, 1)
        self.assertEqual(cs.running, 0)
        self.assertEqual(cs.long_running, 0)
        # Only retained issues count toward "active"; issue 2 is closed.
        self.assertEqual(ai.active_issues, 0)

    async def test_project_filter(self):
        from app.api import system_statistics_queries as q

        async with self.Session() as db:
            cs = (
                await db.execute(
                    q.build_current_state_task_query(
                        dialect=self.dialect,
                        project_id=999,
                        provider_id=None,
                        harness_key=None,
                        now=self.now,
                    )
                )
            ).one()
        self.assertEqual(cs.queued, 0)

    async def test_trends(self):
        q, all_tasks, all_issues = self._ctes()
        async with self.Session() as db:
            created = list(
                (await db.execute(q.build_task_created_trend(all_tasks, self.dialect, "day", None))).all()
            )
            finished = list(
                (await db.execute(q.build_task_finished_trend(all_tasks, self.dialect, "day", None))).all()
            )
            earliest = (
                await db.execute(q.build_earliest_lifecycle_query(all_tasks, all_issues))
            ).scalar_one_or_none()
        self.assertEqual(len(created), 2)
        self.assertEqual(len(finished), 1)
        self.assertEqual(finished[0].completed, 1)
        bucket = q.pick_bucket_for_all(earliest, self.now)
        self.assertIn(bucket, {"day", "week", "month"})

    async def test_breakdowns(self):
        q, all_tasks, _ = self._ctes()
        async with self.Session() as db:
            projects = list((await db.execute(q.build_project_breakdown(self.dialect, all_tasks))).all())
            providers = list((await db.execute(q.build_provider_breakdown(self.dialect, all_tasks))).all())
            harnesses = list((await db.execute(q.build_harness_breakdown(self.dialect, all_tasks))).all())
        self.assertEqual(projects[0].task_count, 2)
        # Queued task has provider_id None -> snapshot normalization yields NULL;
        # the completed task normalizes to provider 10 ("Snap").
        provider_rows = {r.key: r for r in providers}
        self.assertEqual(provider_rows[10].task_count, 1)
        self.assertEqual(provider_rows[10].label, "Snap")
        harness_map = {r.key: r.task_count for r in harnesses}
        self.assertEqual(harness_map["claude"], 1)
        self.assertEqual(harness_map["codex"], 1)


# ---------------------------------------------------------------------------
# §10 admin API endpoints
# ---------------------------------------------------------------------------


class LifecycleStatsAPITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = _make_engine()
        asyncio.run(_create_schema(cls.engine))
        cls.Session = async_sessionmaker(cls.engine, expire_on_commit=False)
        now = utcnow()

        async def seed():
            async with cls.Session() as db:
                await _seed_base(db)
                _seed_issue(db, 1, created_at=now - timedelta(days=5), merge_request_iid=42)
                _seed_task(
                    db,
                    1,
                    1,
                    status=TaskStatus.COMPLETED,
                    created_at=now - timedelta(days=5),
                    started_at=now - timedelta(hours=2),
                    completed_at=now,
                    change_stats_recorded_at=now,
                    additions=5,
                    deletions=2,
                    total_changes=7,
                    input_tokens=100,
                    output_tokens=50,
                )
                _seed_task(
                    db,
                    2,
                    1,
                    status=TaskStatus.QUEUED,
                    created_at=now - timedelta(minutes=10),
                    provider_id=None,
                    harness_key="codex",
                    input_tokens=None,
                    output_tokens=None,
                    provider_runtime_snapshot=None,
                )
                await db.commit()

        asyncio.run(seed())

    @classmethod
    def tearDownClass(cls):
        asyncio.run(cls.engine.dispose())

    def _client(self, *, user):
        from app.database import get_db
        from app.dependencies.auth import AuthContext, get_optional_auth_context
        from app.main import app

        async def override_db():
            session = self.Session()
            try:
                yield session
            finally:
                await session.close()

        if user is None:
            async def override_auth():
                return None
        else:
            async def override_auth():
                return AuthContext(
                    user=user,
                    session=MagicMock(),
                    gitlab_access_token=None,
                    gitlab_refresh_token=None,
                )

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[get_optional_auth_context] = override_auth
        return TestClient(app, raise_server_exceptions=False), app

    def tearDown(self):
        from app.main import app

        app.dependency_overrides.clear()

    @staticmethod
    def _user(role: str):
        user = MagicMock()
        user.platform_role = role
        return user

    def test_overview_shape_for_admin(self):
        client, _ = self._client(user=self._user("platform_admin"))
        r = client.get("/api/admin/system-statistics/overview")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data["reporting_timezone"], "Asia/Shanghai")
        self.assertEqual(data["lifetime"]["task_count"], 2)
        self.assertEqual(data["lifetime"]["completed"], 1)
        self.assertEqual(data["lifetime"]["known_total_tokens"], 150)
        self.assertEqual(data["lifetime"]["known_total_changes"], 7)
        self.assertEqual(data["current_state"]["queued"], 1)
        self.assertEqual(data["current_state"]["active_issues"], 1)
        self.assertEqual(data["deletion"]["deleted_task_count"], 0)
        self.assertFalse(data["coverage"]["capture_enabled"])
        self.assertIsNone(data["coverage"]["capture_started_at"])

    def test_trends_for_admin(self):
        client, _ = self._client(user=self._user("platform_admin"))
        r = client.get("/api/admin/system-statistics/trends?range=90d")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data["bucket"], "day")
        bases = [s["time_basis"] for s in data["series"]]
        self.assertEqual(
            bases, ["created_at", "terminal_at", "source_deleted_at", "issue_created_at"]
        )

    def test_breakdowns_for_admin(self):
        client, _ = self._client(user=self._user("platform_admin"))
        r = client.get("/api/admin/system-statistics/breakdowns")
        self.assertEqual(r.status_code, 200)
        data = r.json()
        self.assertEqual(data["projects"][0]["label"], "Project 1")
        self.assertEqual(data["projects"][0]["task_count"], 2)
        provider_map = {p["provider_id"]: p for p in data["providers"]}
        self.assertEqual(provider_map[10]["label"], "Snap")
        self.assertEqual(provider_map[10]["known_total_changes"], 7)

    def test_rejects_non_admin(self):
        client, _ = self._client(user=self._user("platform_user"))
        r = client.get("/api/admin/system-statistics/overview")
        self.assertEqual(r.status_code, 403)

    def test_rejects_unauthenticated(self):
        client, _ = self._client(user=None)
        r = client.get("/api/admin/system-statistics/overview")
        self.assertEqual(r.status_code, 401)

    def test_rejects_invalid_data_state(self):
        client, _ = self._client(user=self._user("platform_admin"))
        r = client.get("/api/admin/system-statistics/overview?data_state=bogus")
        self.assertEqual(r.status_code, 422)


# ---------------------------------------------------------------------------
# §6.4 worker stats writer + task stats routes
# ---------------------------------------------------------------------------


class WorkerStatsWriterTests(unittest.TestCase):
    def _task(self):
        task = MagicMock()
        task.id = 1
        task.project_id = 1
        task.commit_sha = None
        task.additions = 0
        task.deletions = 0
        task.total_changes = 0
        task.change_stats_recorded_at = None
        task.status = TaskStatus.COMPLETED
        return task

    def _run(self, task, *, structured_diff=None, stats=None):
        from app.core import worker_results

        gitlab = MagicMock()
        gitlab.get_merge_request_stats = AsyncMock(return_value=stats)
        logs = ""
        return asyncio.run(
            worker_results.update_task_stats_from_logs_or_api(
                task, logs, gitlab, issue=None, structured_diff=structured_diff
            )
        )

    def test_structured_diff_valid_sets_recorded_at(self):
        task = self._task()
        self._run(task, structured_diff={"additions": 5, "deletions": 2, "total": 7})
        self.assertEqual(task.additions, 5)
        self.assertEqual(task.total_changes, 7)
        self.assertIsNotNone(task.change_stats_recorded_at)

    def test_structured_diff_invalid_keeps_null(self):
        task = self._task()
        self._run(task, structured_diff={"additions": 5, "deletions": 2, "total": 99})
        self.assertEqual(task.additions, 0)
        self.assertIsNone(task.change_stats_recorded_at)

    def test_api_stats_valid_sets_recorded_at(self):
        task = self._task()
        task.commit_sha = "a" * 40
        self._run(task, stats={"additions": 25, "deletions": 10, "total": 35})
        self.assertEqual(task.additions, 25)
        self.assertIsNotNone(task.change_stats_recorded_at)

    def test_api_stats_invalid_keeps_null(self):
        task = self._task()
        task.commit_sha = "a" * 40
        self._run(task, stats={"additions": 25, "deletions": 10, "total": 99})
        self.assertEqual(task.additions, 0)
        self.assertIsNone(task.change_stats_recorded_at)

    def test_api_stats_none_keeps_null(self):
        task = self._task()
        task.commit_sha = "a" * 40
        self._run(task, stats=None)
        self.assertEqual(task.additions, 0)
        self.assertIsNone(task.change_stats_recorded_at)


class TaskStatsRoutesTests(unittest.TestCase):
    def _make_task(self, **kwargs):
        task = MagicMock()
        task.id = kwargs.get("id", 1)
        task.project_id = 1
        task.additions = kwargs.get("additions", 0)
        task.deletions = kwargs.get("deletions", 0)
        task.total_changes = kwargs.get("total_changes", 0)
        task.change_stats_recorded_at = kwargs.get("change_stats_recorded_at")
        return task

    def _get_client(self, task, *, merge_request_iid=None):
        from app.database import get_db
        from app.dependencies.auth import get_optional_current_user, require_authenticated_user
        from app.dependencies.project_access import ProjectAccessScope, require_project_access_scope
        from app.main import app

        issue = MagicMock()
        issue.merge_request_iid = merge_request_iid
        mock_issue_result = MagicMock()
        mock_issue_result.scalar_one_or_none.return_value = issue

        mock_result = MagicMock()
        mock_result.scalar_one_or_none.return_value = task

        mock_db = MagicMock()
        mock_db.execute = AsyncMock(return_value=mock_result)
        mock_db.commit = AsyncMock()

        access_scope = ProjectAccessScope(is_unrestricted=True, accessible_projects=[])

        async def override_db():
            yield mock_db

        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[get_optional_current_user] = lambda: None
        app.dependency_overrides[require_authenticated_user] = lambda: MagicMock()
        app.dependency_overrides[require_project_access_scope] = lambda: access_scope
        return TestClient(app, raise_server_exceptions=False), app, mock_db

    def tearDown(self):
        from app.main import app

        app.dependency_overrides.clear()

    def test_get_returns_persisted_values_when_recorded(self):
        task = self._make_task(
            additions=50, deletions=10, total_changes=60, change_stats_recorded_at=utcnow()
        )
        client, _, _ = self._get_client(task)
        r = client.get("/api/tasks/1/stats")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"additions": 50, "deletions": 10, "total": 60})

    def test_get_returns_persisted_zeros_when_recorded(self):
        task = self._make_task(change_stats_recorded_at=utcnow())
        client, _, _ = self._get_client(task)
        r = client.get("/api/tasks/1/stats")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json(), {"additions": 0, "deletions": 0, "total": 0})

    def test_patch_rejects_invalid_triple(self):
        task = self._make_task()
        client, _, _ = self._get_client(task)
        r = client.patch("/api/tasks/1/stats?additions=5&deletions=2&total=99")
        self.assertEqual(r.status_code, 400)

    def test_patch_sets_recorded_at(self):
        task = self._make_task()
        client, _, _ = self._get_client(task)
        r = client.patch("/api/tasks/1/stats?additions=5&deletions=2&total=7")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(task.additions, 5)
        self.assertIsNotNone(task.change_stats_recorded_at)


if __name__ == "__main__":
    unittest.main()
