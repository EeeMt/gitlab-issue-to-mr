# System Data Cleanup Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a platform-admin Maintenance action that cleans issue-scoped system data, optionally older than N days, with an explicit force mode for stale active tasks.

**Architecture:** Put deletion rules in a focused backend service under `app.core.system_data_cleanup`, expose it through an admin-only config maintenance endpoint, then add typed frontend API and a Maintenance panel card. Keep database deletion transactional, with Docker/file cleanup reported as best-effort result fields.

**Tech Stack:** FastAPI, SQLAlchemy async ORM, Pydantic, Vue 3 Composition API, Naive UI, Vitest, Python unit tests.

---

## File Map

- Create `backend/app/core/system_data_cleanup.py`: service, request-independent result dataclasses, database deletion, container stop, archive/workspace cleanup.
- Create `backend/app/api/maintenance.py`: Pydantic request/response models and `POST /config/maintenance/cleanup-system-data`.
- Modify `backend/app/main.py`: import and include the maintenance router under `/api`, requiring authenticated users at router include and admin users at endpoint level.
- Create `backend/tests/unit/test_system_data_cleanup.py`: real async SQLite tests for cleanup service behavior.
- Create `backend/tests/unit/test_maintenance_api.py`: API-level tests for request validation and endpoint delegation.
- Modify `frontend/src/api/index.ts`: cleanup request/response interfaces and `cleanupSystemData()` helper.
- Modify `frontend/src/api/api.spec.ts`: helper test for endpoint and payload.
- Modify `frontend/src/views/config/MaintenancePanel.vue`: add cleanup controls, confirmation, API call, and summary message.
- Modify `frontend/src/views/config/MaintenancePanel.spec.ts`: render, payload, force, and summary tests.
- Modify `frontend/src/i18n/messages/en.ts` and `frontend/src/i18n/messages/zh-CN.ts`: labels, confirmation text, success/error messages.
- Modify `frontend/src/test/mocks/api.ts`: add mock cleanup API function.

## Task 1: Backend Cleanup Service Tests

**Files:**
- Create: `backend/tests/unit/test_system_data_cleanup.py`
- Later implementation target: `backend/app/core/system_data_cleanup.py`

- [ ] **Step 1: Write failing service tests**

Create `backend/tests/unit/test_system_data_cleanup.py` with async SQLite setup and these tests:

```python
import os
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

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
)


class SystemDataCleanupServiceTests(unittest.IsolatedAsyncioTestCase):
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

    async def _seed_issue(self, session, *, issue_id, created_at, task_statuses, archive_dir: Path | None = None):
        issue = Issue(
            id=issue_id,
            title=f"Issue {issue_id}",
            project_id=100 + issue_id,
            status="open",
            created_at=created_at,
            updated_at=created_at,
        )
        session.add(issue)
        await session.flush()
        task_ids = []
        for index, status in enumerate(task_statuses, start=1):
            task_id = issue_id * 100 + index
            task_ids.append(task_id)
            task = Task(
                id=task_id,
                issue_id=issue_id,
                project_id=issue.project_id,
                user_prompt=f"Task {task_id}",
                status=status,
                created_at=created_at,
                updated_at=created_at,
            )
            session.add(task)
            await session.flush()
            session.add(TaskLog(task_id=task_id, message="log"))
            session.add(TaskPayload(task_id=task_id, payload_kind="tool_input", content=b"{}", char_count=2, byte_count=2))
            session.add(TaskRawLogChunk(task_id=task_id, sequence_no=1, content=b"log", char_count=3, byte_count=3))
            session.add(TaskIngestCursor(task_id=task_id, stream_name="event_jsonl"))
            if archive_dir is not None:
                archive_path = archive_dir / f"task-{task_id}.tar.gz"
                archive_path.write_bytes(b"archive")
                session.add(TaskRunArchive(task_id=task_id, archive_name=archive_path.name, archive_path=str(archive_path), archive_size_bytes=7))
            session.add(TaskUsageLedger(task_id=task_id, user_id=1, task_status=str(status.value), completed_at=created_at, timezone_day=created_at.date(), timezone_week_start=created_at.date()))
            session.add(MattermostNotificationDelivery(task_id=task_id, profile_id=1, event_type="task_completed", status="sent", target_summary="channel"))
        if task_ids:
            session.add(IssueExecutionLock(issue_id=issue_id, task_id=task_ids[0]))
        session.add(WebhookEvent(event_type="merge_request", project_id=issue.project_id, issue_id=issue_id, result="issue_closed"))
        return task_ids

    async def _count(self, session, model):
        return await session.scalar(select(func.count()).select_from(model))

    async def test_default_cleanup_deletes_inactive_issue_data_and_files(self):
        from app.core.system_data_cleanup import cleanup_system_data

        async with self.Session() as session:
            archive_dir = Path(os.environ.get("PYTEST_TMPDIR", "/tmp"))
            old = datetime.utcnow() - timedelta(days=40)
            task_ids = await self._seed_issue(session, issue_id=1, created_at=old, task_statuses=[TaskStatus.COMPLETED], archive_dir=archive_dir)
            await session.commit()

            result = await cleanup_system_data(session, older_than_days=30, force=False, workspace_root="")

            self.assertEqual(result.deleted_issues, 1)
            self.assertEqual(result.deleted_tasks, 1)
            self.assertEqual(result.skipped_active_issues, 0)
            self.assertEqual(result.deleted_archives, 1)
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
            old = datetime.utcnow() - timedelta(days=40)
            await self._seed_issue(session, issue_id=2, created_at=old, task_statuses=[TaskStatus.PENDING, TaskStatus.COMPLETED])
            await session.commit()

            result = await cleanup_system_data(session, older_than_days=30, force=False, workspace_root="")

            self.assertEqual(result.deleted_issues, 0)
            self.assertEqual(result.deleted_tasks, 0)
            self.assertEqual(result.skipped_active_issues, 1)
            self.assertEqual(result.skipped_active_tasks, 1)
            self.assertEqual(await self._count(session, Issue), 1)
            self.assertEqual(await self._count(session, Task), 2)

    async def test_force_cleanup_includes_active_issues_and_stops_running_containers(self):
        from app.core.system_data_cleanup import cleanup_system_data

        async with self.Session() as session:
            old = datetime.utcnow() - timedelta(days=40)
            await self._seed_issue(session, issue_id=3, created_at=old, task_statuses=[TaskStatus.RUNNING])
            await session.commit()
            container = MagicMock()
            docker = MagicMock()
            docker.client.containers.get.return_value = container

            with patch("app.core.system_data_cleanup.get_docker_client", return_value=docker):
                result = await cleanup_system_data(session, older_than_days=30, force=True, workspace_root="")

            self.assertEqual(result.deleted_issues, 1)
            self.assertEqual(result.deleted_tasks, 1)
            self.assertEqual(result.skipped_active_issues, 0)
            docker.client.containers.get.assert_called_once_with("codify-301-issue3")
            container.stop.assert_called_once_with(timeout=5)

    async def test_force_cleanup_records_container_stop_errors(self):
        from app.core.system_data_cleanup import cleanup_system_data

        async with self.Session() as session:
            old = datetime.utcnow() - timedelta(days=40)
            await self._seed_issue(session, issue_id=4, created_at=old, task_statuses=[TaskStatus.RUNNING])
            await session.commit()
            docker = MagicMock()
            docker.client.containers.get.side_effect = RuntimeError("missing docker")

            with patch("app.core.system_data_cleanup.get_docker_client", return_value=docker):
                result = await cleanup_system_data(session, older_than_days=30, force=True, workspace_root="")

            self.assertEqual(result.deleted_issues, 1)
            self.assertEqual(result.container_cleanup_errors[0]["task_id"], 401)
            self.assertIn("missing docker", result.container_cleanup_errors[0]["error"])

    async def test_retention_filter_keeps_recent_issues(self):
        from app.core.system_data_cleanup import cleanup_system_data

        async with self.Session() as session:
            recent = datetime.utcnow() - timedelta(days=2)
            await self._seed_issue(session, issue_id=5, created_at=recent, task_statuses=[TaskStatus.COMPLETED])
            await session.commit()

            result = await cleanup_system_data(session, older_than_days=30, force=False, workspace_root="")

            self.assertEqual(result.deleted_issues, 0)
            self.assertEqual(await self._count(session, Issue), 1)
```

- [ ] **Step 2: Run service tests to verify RED**

Run: `cd backend && python -m pytest tests/unit/test_system_data_cleanup.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'app.core.system_data_cleanup'`.

## Task 2: Backend Cleanup Service Implementation

**Files:**
- Create: `backend/app/core/system_data_cleanup.py`
- Test: `backend/tests/unit/test_system_data_cleanup.py`

- [ ] **Step 1: Implement the service**

Create `backend/app/core/system_data_cleanup.py`:

```python
from __future__ import annotations

import asyncio
import os
import shutil
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.docker_client import get_docker_client
from app.models import (
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
)


ACTIVE_TASK_STATUSES = {TaskStatus.PENDING, TaskStatus.QUEUED, TaskStatus.RUNNING}


@dataclass(slots=True)
class SystemDataCleanupResult:
    deleted_issues: int = 0
    deleted_tasks: int = 0
    skipped_active_issues: int = 0
    skipped_active_tasks: int = 0
    deleted_archives: int = 0
    missing_archives: int = 0
    deleted_workspaces: int = 0
    container_cleanup_errors: list[dict[str, Any]] = field(default_factory=list)
    file_cleanup_errors: list[dict[str, Any]] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "deleted_issues": self.deleted_issues,
            "deleted_tasks": self.deleted_tasks,
            "skipped_active_issues": self.skipped_active_issues,
            "skipped_active_tasks": self.skipped_active_tasks,
            "deleted_archives": self.deleted_archives,
            "missing_archives": self.missing_archives,
            "deleted_workspaces": self.deleted_workspaces,
            "container_cleanup_errors": self.container_cleanup_errors,
            "file_cleanup_errors": self.file_cleanup_errors,
        }


def _status_value(status: TaskStatus | str) -> str:
    return status.value if isinstance(status, TaskStatus) else str(status)


def _issue_workspace_path(workspace_root: str, *, project_id: int, issue_id: int) -> str:
    return os.path.join(workspace_root, f"project-{project_id}", f"issue-{issue_id}")


async def _stop_running_containers(tasks: list[Task], result: SystemDataCleanupResult) -> None:
    running_tasks = [task for task in tasks if task.status == TaskStatus.RUNNING]
    if not running_tasks:
        return
    docker = get_docker_client()
    for task in running_tasks:
        container_name = f"codify-{task.id}-issue{task.issue_id}"
        try:
            container = await asyncio.to_thread(docker.client.containers.get, container_name)
            await asyncio.to_thread(container.stop, timeout=5)
        except Exception as exc:
            result.container_cleanup_errors.append({
                "task_id": task.id,
                "container_name": container_name,
                "error": str(exc),
            })


def _cleanup_archive_files(paths: list[str], result: SystemDataCleanupResult) -> None:
    for archive_path in paths:
        if not archive_path or not os.path.exists(archive_path):
            result.missing_archives += 1
            continue
        try:
            os.remove(archive_path)
            result.deleted_archives += 1
        except Exception as exc:
            result.file_cleanup_errors.append({
                "kind": "archive",
                "path": archive_path,
                "error": str(exc),
            })


def _cleanup_workspaces(paths: list[str], result: SystemDataCleanupResult) -> None:
    for workspace_path in paths:
        if not workspace_path or not os.path.exists(workspace_path):
            continue
        try:
            shutil.rmtree(workspace_path)
            result.deleted_workspaces += 1
        except Exception as exc:
            result.file_cleanup_errors.append({
                "kind": "workspace",
                "path": workspace_path,
                "error": str(exc),
            })


async def cleanup_system_data(
    db: AsyncSession,
    *,
    older_than_days: int | None,
    force: bool,
    workspace_root: str,
    now: datetime | None = None,
) -> SystemDataCleanupResult:
    result = SystemDataCleanupResult()
    cutoff = None
    if older_than_days is not None:
        cutoff = (now or datetime.utcnow()) - timedelta(days=older_than_days)

    issue_stmt = select(Issue)
    if cutoff is not None:
        issue_stmt = issue_stmt.where(Issue.created_at < cutoff)
    issues = list((await db.execute(issue_stmt)).scalars().all())
    if not issues:
        return result

    issue_ids = [issue.id for issue in issues]
    tasks = list((await db.execute(select(Task).where(Task.issue_id.in_(issue_ids)))).scalars().all())
    tasks_by_issue: dict[int, list[Task]] = {}
    for task in tasks:
        if task.issue_id is not None:
            tasks_by_issue.setdefault(task.issue_id, []).append(task)

    selected_issues: list[Issue] = []
    for issue in issues:
        issue_tasks = tasks_by_issue.get(issue.id, [])
        active_tasks = [task for task in issue_tasks if _status_value(task.status) in {status.value for status in ACTIVE_TASK_STATUSES}]
        if active_tasks and not force:
            result.skipped_active_issues += 1
            result.skipped_active_tasks += len(active_tasks)
            continue
        selected_issues.append(issue)

    if not selected_issues:
        return result

    selected_issue_ids = [issue.id for issue in selected_issues]
    selected_tasks = [task for task in tasks if task.issue_id in selected_issue_ids]
    selected_task_ids = [task.id for task in selected_tasks]
    result.deleted_issues = len(selected_issue_ids)
    result.deleted_tasks = len(selected_task_ids)

    if force:
        await _stop_running_containers(selected_tasks, result)

    archive_paths: list[str] = []
    if selected_task_ids:
        archives = list((await db.execute(select(TaskRunArchive).where(TaskRunArchive.task_id.in_(selected_task_ids)))).scalars().all())
        archive_paths = [archive.archive_path for archive in archives]

    workspace_paths = []
    if workspace_root:
        workspace_paths = [
            _issue_workspace_path(workspace_root, project_id=issue.project_id, issue_id=issue.id)
            for issue in selected_issues
        ]

    if selected_task_ids:
        for model in (
            TaskLog,
            TaskPayload,
            TaskRawLogChunk,
            TaskIngestCursor,
            TaskRunArchive,
            TaskUsageLedger,
            MattermostNotificationDelivery,
        ):
            await db.execute(delete(model).where(model.task_id.in_(selected_task_ids)))
        await db.execute(delete(Task).where(Task.id.in_(selected_task_ids)))

    await db.execute(delete(IssueExecutionLock).where(IssueExecutionLock.issue_id.in_(selected_issue_ids)))
    await db.execute(update(WebhookEvent).where(WebhookEvent.issue_id.in_(selected_issue_ids)).values(issue_id=None))
    await db.execute(delete(Issue).where(Issue.id.in_(selected_issue_ids)))
    await db.commit()

    _cleanup_archive_files(archive_paths, result)
    _cleanup_workspaces(workspace_paths, result)
    return result
```

- [ ] **Step 2: Run service tests to verify GREEN**

Run: `cd backend && python -m pytest tests/unit/test_system_data_cleanup.py -q`

Expected: PASS.

- [ ] **Step 3: Commit backend service**

Run:

```bash
git add backend/app/core/system_data_cleanup.py backend/tests/unit/test_system_data_cleanup.py
git commit -m "feat: add system data cleanup service"
```

## Task 3: Backend Maintenance API

**Files:**
- Create: `backend/app/api/maintenance.py`
- Modify: `backend/app/main.py`
- Create: `backend/tests/unit/test_maintenance_api.py`

- [ ] **Step 1: Write failing API tests**

Create `backend/tests/unit/test_maintenance_api.py`:

```python
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi import HTTPException


class MaintenanceApiTests(unittest.IsolatedAsyncioTestCase):
    async def test_cleanup_system_data_endpoint_delegates_to_service(self):
        from app.api.maintenance import CleanupSystemDataRequest, cleanup_system_data_endpoint

        db = MagicMock()
        service_result = MagicMock()
        service_result.to_dict.return_value = {
            "deleted_issues": 1,
            "deleted_tasks": 2,
            "skipped_active_issues": 0,
            "skipped_active_tasks": 0,
            "deleted_archives": 2,
            "missing_archives": 0,
            "deleted_workspaces": 1,
            "container_cleanup_errors": [],
            "file_cleanup_errors": [],
        }

        with patch("app.api.maintenance.get_effective_settings") as settings, \
             patch("app.api.maintenance.cleanup_system_data", new=AsyncMock(return_value=service_result)) as cleanup:
            settings.return_value.worker_workspace_host_path = "/workspaces"
            response = await cleanup_system_data_endpoint(
                body=CleanupSystemDataRequest(older_than_days=30, force=True),
                db=db,
                _current_user=MagicMock(),
            )

        cleanup.assert_awaited_once_with(db, older_than_days=30, force=True, workspace_root="/workspaces")
        self.assertEqual(response.deleted_issues, 1)
        self.assertEqual(response.deleted_tasks, 2)

    async def test_cleanup_system_data_request_rejects_zero_retention(self):
        from app.api.maintenance import CleanupSystemDataRequest

        with self.assertRaises(ValueError):
            CleanupSystemDataRequest(older_than_days=0, force=False)
```

- [ ] **Step 2: Run API tests to verify RED**

Run: `cd backend && python -m pytest tests/unit/test_maintenance_api.py -q`

Expected: FAIL with `ModuleNotFoundError: No module named 'app.api.maintenance'`.

- [ ] **Step 3: Implement API route and register router**

Create `backend/app/api/maintenance.py`:

```python
from typing import Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_effective_settings
from app.core.system_data_cleanup import cleanup_system_data
from app.database import get_db
from app.dependencies.auth import require_admin_user
from app.models import User


router = APIRouter()


class CleanupSystemDataRequest(BaseModel):
    older_than_days: int | None = Field(default=None, ge=1)
    force: bool = False


class CleanupSystemDataResponse(BaseModel):
    deleted_issues: int
    deleted_tasks: int
    skipped_active_issues: int
    skipped_active_tasks: int
    deleted_archives: int
    missing_archives: int
    deleted_workspaces: int
    container_cleanup_errors: list[dict[str, Any]]
    file_cleanup_errors: list[dict[str, Any]]


@router.post("/config/maintenance/cleanup-system-data", response_model=CleanupSystemDataResponse)
async def cleanup_system_data_endpoint(
    body: CleanupSystemDataRequest,
    db: AsyncSession = Depends(get_db),
    _current_user: User = Depends(require_admin_user),
) -> CleanupSystemDataResponse:
    settings = get_effective_settings()
    result = await cleanup_system_data(
        db,
        older_than_days=body.older_than_days,
        force=body.force,
        workspace_root=settings.worker_workspace_host_path,
    )
    return CleanupSystemDataResponse(**result.to_dict())
```

Modify `backend/app/main.py` imports and router registration:

```python
from app.api import admin_users, auth, issues, tasks, containers, stats, config, config_integration, config_runtime, maintenance, mattermost, oidc, project_webhooks, prompt_templates, projects, providers, usage_limits, webhook_handler
```

Add near the other config routers:

```python
app.include_router(
    maintenance.router,
    prefix="/api",
    tags=["config"],
    dependencies=[Depends(require_authenticated_user)],
)
```

- [ ] **Step 4: Run API tests to verify GREEN**

Run: `cd backend && python -m pytest tests/unit/test_maintenance_api.py -q`

Expected: PASS.

- [ ] **Step 5: Run backend focused tests**

Run: `cd backend && python -m pytest tests/unit/test_system_data_cleanup.py tests/unit/test_maintenance_api.py -q`

Expected: PASS.

- [ ] **Step 6: Commit backend API**

Run:

```bash
git add backend/app/api/maintenance.py backend/app/main.py backend/tests/unit/test_maintenance_api.py
git commit -m "feat: expose system data cleanup API"
```

## Task 4: Frontend API Helper

**Files:**
- Modify: `frontend/src/api/index.ts`
- Modify: `frontend/src/api/api.spec.ts`

- [ ] **Step 1: Write failing API helper test**

In `frontend/src/api/api.spec.ts`, add `cleanupSystemData` to the import list and add this test:

```typescript
describe('cleanupSystemData', () => {
  it('posts cleanup options to the maintenance endpoint', async () => {
    const response = {
      deleted_issues: 1,
      deleted_tasks: 2,
      skipped_active_issues: 0,
      skipped_active_tasks: 0,
      deleted_archives: 2,
      missing_archives: 0,
      deleted_workspaces: 1,
      container_cleanup_errors: [],
      file_cleanup_errors: []
    }
    mockAxiosPost.mockResolvedValue({ data: response })

    const result = await cleanupSystemData({ older_than_days: 30, force: true })

    expect(result).toEqual(response)
    expect(mockAxiosPost).toHaveBeenCalledWith('/config/maintenance/cleanup-system-data', {
      older_than_days: 30,
      force: true
    })
  })
})
```

- [ ] **Step 2: Run frontend API test to verify RED**

Run: `cd frontend && npm test -- src/api/api.spec.ts --run`

Expected: FAIL because `cleanupSystemData` is not exported.

- [ ] **Step 3: Implement API helper**

Add to `frontend/src/api/index.ts` near config API helpers:

```typescript
export interface CleanupSystemDataRequest {
  older_than_days?: number | null
  force: boolean
}

export interface CleanupSystemDataResult {
  deleted_issues: number
  deleted_tasks: number
  skipped_active_issues: number
  skipped_active_tasks: number
  deleted_archives: number
  missing_archives: number
  deleted_workspaces: number
  container_cleanup_errors: Array<{ task_id: number; container_name: string; error: string }>
  file_cleanup_errors: Array<{ kind: string; path: string; error: string }>
}

export async function cleanupSystemData(request: CleanupSystemDataRequest): Promise<CleanupSystemDataResult> {
  const response = await api.post('/config/maintenance/cleanup-system-data', request)
  return response.data
}
```

- [ ] **Step 4: Run frontend API test to verify GREEN**

Run: `cd frontend && npm test -- src/api/api.spec.ts --run`

Expected: PASS.

- [ ] **Step 5: Commit frontend API helper**

Run:

```bash
git add frontend/src/api/index.ts frontend/src/api/api.spec.ts
git commit -m "feat: add system cleanup frontend API"
```

## Task 5: Maintenance Panel UI

**Files:**
- Modify: `frontend/src/views/config/MaintenancePanel.vue`
- Modify: `frontend/src/views/config/MaintenancePanel.spec.ts`
- Modify: `frontend/src/i18n/messages/en.ts`
- Modify: `frontend/src/i18n/messages/zh-CN.ts`
- Modify: `frontend/src/test/mocks/api.ts`

- [ ] **Step 1: Write failing Maintenance panel tests**

Update the Naive UI mock in `MaintenancePanel.spec.ts` to include `NInputNumber`, `NSwitch`, `NPopconfirm`, and `NAlert`, mock `cleanupSystemData`, and add tests:

```typescript
it('renders system data cleanup controls', () => {
  const wrapper = mountComponent()

  expect(wrapper.text()).toContain('config.systemDataCleanup')
  expect(wrapper.text()).toContain('config.cleanupOlderThanDays')
  expect(wrapper.text()).toContain('config.forceCleanupActiveTasks')
})

it('submits cleanup payload with force disabled by default', async () => {
  mockApi.cleanupSystemData.mockResolvedValue({
    deleted_issues: 1,
    deleted_tasks: 2,
    skipped_active_issues: 0,
    skipped_active_tasks: 0,
    deleted_archives: 2,
    missing_archives: 0,
    deleted_workspaces: 1,
    container_cleanup_errors: [],
    file_cleanup_errors: []
  })
  const wrapper = mountComponent()

  await wrapper.find('[data-test="cleanup-system-data-button"]').trigger('click')

  expect(mockApi.cleanupSystemData).toHaveBeenCalledWith({
    older_than_days: null,
    force: false
  })
})

it('submits cleanup payload with retention and force enabled', async () => {
  mockApi.cleanupSystemData.mockResolvedValue({
    deleted_issues: 0,
    deleted_tasks: 0,
    skipped_active_issues: 0,
    skipped_active_tasks: 0,
    deleted_archives: 0,
    missing_archives: 0,
    deleted_workspaces: 0,
    container_cleanup_errors: [],
    file_cleanup_errors: []
  })
  const wrapper = mountComponent()

  await wrapper.find('[data-test="cleanup-older-than-days-input"]').setValue('30')
  await wrapper.find('[data-test="force-cleanup-active-switch"]').setValue(true)
  await wrapper.find('[data-test="cleanup-system-data-button"]').trigger('click')

  expect(mockApi.cleanupSystemData).toHaveBeenCalledWith({
    older_than_days: 30,
    force: true
  })
})
```

- [ ] **Step 2: Run panel test to verify RED**

Run: `cd frontend && npm test -- src/views/config/MaintenancePanel.spec.ts --run`

Expected: FAIL because cleanup controls and `cleanupSystemData` do not exist yet.

- [ ] **Step 3: Implement Maintenance panel UI**

Modify `MaintenancePanel.vue`:

```vue
<template>
  <div class="config-layout__main">
    <!-- existing config-actions card stays unchanged -->

    <n-card id="system-data-cleanup" class="config-form-card" :bordered="false">
      <template #header>
        <div class="config-card-header">
          <div>
            <div class="config-card-header__title">{{ t('config.systemDataCleanup') }}</div>
            <div class="config-card-header__subtitle">{{ t('config.systemDataCleanupSubtitle') }}</div>
          </div>
        </div>
      </template>

      <div class="config-form__section">
        <n-form-item :label="t('config.cleanupOlderThanDays')">
          <n-input-number
            v-model:value="cleanupOlderThanDays"
            data-test="cleanup-older-than-days-input"
            :min="1"
            clearable
            :placeholder="t('config.cleanupOlderThanDaysPlaceholder')"
          />
        </n-form-item>
        <div class="config-inline-toggle">
          <div class="config-inline-toggle__content">
            <div class="config-inline-toggle__label">{{ t('config.forceCleanupActiveTasks') }}</div>
            <div class="config-inline-toggle__hint">{{ t('config.forceCleanupActiveTasksHint') }}</div>
          </div>
          <n-switch v-model:value="forceCleanupActiveTasks" data-test="force-cleanup-active-switch" />
        </div>
        <n-alert v-if="forceCleanupActiveTasks" type="warning" :bordered="false">
          {{ t('config.forceCleanupActiveTasksWarning') }}
        </n-alert>
        <n-popconfirm
          :positive-text="t('config.cleanSystemData')"
          :negative-text="t('common.cancel')"
          @positive-click="handleCleanupSystemData"
        >
          <template #trigger>
            <n-button
              data-test="cleanup-system-data-button"
              type="error"
              secondary
              :loading="cleanupLoading"
              :disabled="isBusy"
            >
              {{ t('config.cleanSystemData') }}
            </n-button>
          </template>
          {{ forceCleanupActiveTasks ? t('config.confirmForceCleanSystemData') : t('config.confirmCleanSystemData') }}
        </n-popconfirm>
      </div>
    </n-card>
  </div>
</template>
```

Add script state and handler:

```typescript
import { computed, ref } from 'vue'
import { NAlert, NButton, NCard, NFormItem, NInputNumber, NPopconfirm, NSpace, NSwitch, useMessage } from 'naive-ui'
import { cleanupSystemData } from '../../api'

const message = useMessage()
const cleanupOlderThanDays = ref<number | null>(null)
const forceCleanupActiveTasks = ref(false)
const cleanupLoading = ref(false)

async function handleCleanupSystemData() {
  cleanupLoading.value = true
  try {
    const result = await cleanupSystemData({
      older_than_days: cleanupOlderThanDays.value,
      force: forceCleanupActiveTasks.value
    })
    message.success(t('config.systemDataCleanupSuccess', {
      issues: result.deleted_issues,
      tasks: result.deleted_tasks,
      skipped: result.skipped_active_issues
    }))
  } catch (error: any) {
    message.error(error?.response?.data?.detail || t('config.systemDataCleanupFailed'))
  } finally {
    cleanupLoading.value = false
  }
}
```

Add `cleanupLoading.value` to `isBusy`.

- [ ] **Step 4: Add i18n strings and test mock**

Add English config keys:

```typescript
systemDataCleanup: 'System Data Cleanup',
systemDataCleanupSubtitle: 'Delete old issue-scoped system records and their task data.',
cleanupOlderThanDays: 'Clean data older than N days',
cleanupOlderThanDaysPlaceholder: 'Leave empty to clean all eligible data',
forceCleanupActiveTasks: 'Force cleanup active tasks',
forceCleanupActiveTasksHint: 'Also delete pending, queued, and running tasks when their state is stale.',
forceCleanupActiveTasksWarning: 'Force cleanup deletes active task records and attempts to stop running containers.',
cleanSystemData: 'Clean system data',
confirmCleanSystemData: 'Clean eligible issue data? This cannot be undone.',
confirmForceCleanSystemData: 'Force clean eligible issue data, including active tasks? Running containers will be stopped best-effort.',
systemDataCleanupSuccess: 'Cleanup finished: {issues} issue(s), {tasks} task(s) deleted, {skipped} active issue(s) skipped.',
systemDataCleanupFailed: 'Failed to clean system data',
```

Add Chinese config keys:

```typescript
systemDataCleanup: '系统数据清理',
systemDataCleanupSubtitle: '按 Issue 删除旧的系统记录及其任务数据。',
cleanupOlderThanDays: '清理 N 天以前的数据',
cleanupOlderThanDaysPlaceholder: '留空表示清理全部符合条件的数据',
forceCleanupActiveTasks: '强制清理活跃任务',
forceCleanupActiveTasksHint: '当任务状态已不可信时，也删除 pending、queued 和 running 任务。',
forceCleanupActiveTasksWarning: '强制清理会删除活跃任务记录，并尽力停止正在运行的容器。',
cleanSystemData: '清理系统数据',
confirmCleanSystemData: '确认清理符合条件的 Issue 数据吗？此操作不可撤销。',
confirmForceCleanSystemData: '确认强制清理符合条件的数据，包括活跃任务吗？运行中的容器会尽力停止。',
systemDataCleanupSuccess: '清理完成：已删除 {issues} 个 Issue、{tasks} 个任务，跳过 {skipped} 个活跃 Issue。',
systemDataCleanupFailed: '清理系统数据失败',
```

Add to `frontend/src/test/mocks/api.ts`:

```typescript
cleanupSystemData: vi.fn<() => Promise<any>>(),
```

- [ ] **Step 5: Run panel test to verify GREEN**

Run: `cd frontend && npm test -- src/views/config/MaintenancePanel.spec.ts --run`

Expected: PASS.

- [ ] **Step 6: Commit Maintenance UI**

Run:

```bash
git add frontend/src/views/config/MaintenancePanel.vue frontend/src/views/config/MaintenancePanel.spec.ts frontend/src/i18n/messages/en.ts frontend/src/i18n/messages/zh-CN.ts frontend/src/test/mocks/api.ts
git commit -m "feat: add system cleanup maintenance UI"
```

## Task 6: Final Verification

**Files:**
- Verify all files changed by prior tasks.

- [ ] **Step 1: Run backend focused verification**

Run: `cd backend && python -m pytest tests/unit/test_system_data_cleanup.py tests/unit/test_maintenance_api.py -q`

Expected: PASS.

- [ ] **Step 2: Run frontend focused verification**

Run: `cd frontend && npm test -- src/api/api.spec.ts src/views/config/MaintenancePanel.spec.ts --run`

Expected: PASS.

- [ ] **Step 3: Run status and diff review**

Run: `git status --short`

Expected: only intentional committed changes or a clean tree.

Run: `git log --oneline -5`

Expected: includes commits for design, plan, backend service, backend API, frontend API, and UI.
