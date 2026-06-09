# Usage Management Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build user-level usage management for token totals and task counts, with system defaults, per-user overrides, admin management UI, a current-user top bar indicator, and quota enforcement at task creation plus pre-execution.

**Architecture:** Add a dedicated quota subsystem instead of extending `users` or reusing analytics. Persist policy rows and task-level usage ledger rows in the backend, expose explicit usage APIs, enforce limits through a shared service in task creation and scheduler start, and render the data in a new admin page plus a reusable current-user indicator component.

**Tech Stack:** FastAPI, Async SQLAlchemy, Alembic, pytest/unittest, Vue 3, Naive UI, vue-i18n, Vitest

---

## File Structure

### Backend

- Create: `backend/alembic/versions/033_add_usage_limits.py`
  - Adds the quota policy and task usage ledger tables.
- Modify: `backend/app/models.py`
  - Defines `UsageLimitPolicy` and `TaskUsageLedger`.
- Create: `backend/app/core/usage_limits.py`
  - Shared quota resolution, usage aggregation, over-limit payload generation, and ledger upsert logic.
- Create: `backend/app/api/usage_limits.py`
  - Current-user usage summary endpoint and admin usage management endpoints.
- Modify: `backend/app/main.py`
  - Registers the new usage limits router.
- Modify: `backend/app/api/tasks.py`
  - Rejects task creation when the initiator is already over quota.
- Modify: `backend/app/scheduler.py`
  - Re-checks quota immediately before setting a task to `RUNNING`; fails the task before start if over limit.
- Modify: `backend/app/core/worker.py`
  - Writes or updates the task usage ledger when finished tasks have usage stats.

### Backend tests

- Create: `backend/tests/unit/test_usage_limits_models.py`
  - Smoke tests for the new ORM models.
- Create: `backend/tests/unit/test_usage_limits_service.py`
  - Effective-limit resolution, window math, unlimited handling, and ledger idempotency.
- Create: `backend/tests/unit/test_usage_limits_api.py`
  - Current-user summary and admin usage management endpoints.
- Modify: `backend/tests/unit/test_tasks_api.py`
  - Create-task rejection when usage is already exceeded.
- Modify: `backend/tests/unit/test_scheduler.py`
  - Execution-time rejection before a task starts running.
- Modify: `backend/tests/unit/test_worker_coverage.py`
  - Ledger upsert after finished tasks with token stats.

### Frontend

- Modify: `frontend/src/api/index.ts`
  - Adds usage types and client functions.
- Modify: `frontend/src/api/api.spec.ts`
  - Covers the new client functions.
- Create: `frontend/src/components/CurrentUserUsageIndicator.vue`
  - Small top-bar icon + hover summary for the current user.
- Create: `frontend/src/components/CurrentUserUsageIndicator.spec.ts`
  - Tests indicator rendering and hover content.
- Modify: `frontend/src/App.vue`
  - Mounts the top bar indicator and adds the new admin navigation item.
- Modify: `frontend/src/App.spec.ts`
  - Covers the top bar indicator integration.
- Modify: `frontend/src/router/index.ts`
  - Registers the new admin-only usage management route.
- Create: `frontend/src/views/UsageManagement.vue`
  - Admin page for system defaults, per-user overrides, and usage visibility.
- Create: `frontend/src/views/UsageManagement.spec.ts`
  - Covers page loading, editing, and saving behavior.
- Modify: `frontend/src/views/CreateTask.vue`
  - Shows current-user quota state and friendly over-limit feedback.
- Modify: `frontend/src/views/CreateTask.spec.ts`
  - Covers warning display and structured over-limit error handling.
- Modify: `frontend/src/i18n/messages/en.ts`
  - Adds English copy for usage management and top bar messaging.
- Modify: `frontend/src/i18n/messages/zh-CN.ts`
  - Adds Simplified Chinese copy for usage management and top bar messaging.

## Task 1: Add the quota persistence layer

**Files:**
- Create: `backend/alembic/versions/033_add_usage_limits.py`
- Modify: `backend/app/models.py`
- Test: `backend/tests/unit/test_usage_limits_models.py`

- [ ] **Step 1: Write the failing ORM model test**

```python
import unittest
from datetime import date

from app.models import UsageLimitPolicy, TaskUsageLedger


class UsageLimitModelsTests(unittest.TestCase):
    def test_usage_limit_policy_keeps_per_field_modes(self):
        policy = UsageLimitPolicy(
            scope_type="user",
            user_id=7,
            daily_tokens_mode="inherit",
            daily_tokens_value=None,
            weekly_tokens_mode="custom",
            weekly_tokens_value=500000,
            daily_tasks_mode="unlimited",
            daily_tasks_value=None,
            weekly_tasks_mode="custom",
            weekly_tasks_value=20,
        )

        self.assertEqual(policy.scope_type, "user")
        self.assertEqual(policy.weekly_tokens_value, 500000)
        self.assertEqual(policy.daily_tasks_mode, "unlimited")

    def test_task_usage_ledger_tracks_calendar_keys(self):
        ledger = TaskUsageLedger(
            task_id=11,
            user_id=7,
            task_status="completed",
            timezone_day=date(2026, 4, 27),
            timezone_week_start=date(2026, 4, 27),
            input_tokens=800,
            output_tokens=400,
            total_tokens=1200,
            task_count=1,
        )

        self.assertEqual(ledger.total_tokens, 1200)
        self.assertEqual(ledger.task_count, 1)
```

- [ ] **Step 2: Run the new model test to verify it fails**

Run: `cd backend && pytest tests/unit/test_usage_limits_models.py -v`

Expected: FAIL with `ImportError` or `AttributeError` because `UsageLimitPolicy` and `TaskUsageLedger` do not exist yet.

- [ ] **Step 3: Add the new SQLAlchemy models to `backend/app/models.py`**

```python
class UsageLimitPolicy(Base):
    __tablename__ = "usage_limit_policies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    scope_type: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    user_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=True, index=True
    )

    daily_tokens_mode: Mapped[str] = mapped_column(String(16), nullable=False, default="custom")
    daily_tokens_value: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    weekly_tokens_mode: Mapped[str] = mapped_column(String(16), nullable=False, default="custom")
    weekly_tokens_value: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    daily_tasks_mode: Mapped[str] = mapped_column(String(16), nullable=False, default="custom")
    daily_tasks_value: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    weekly_tasks_mode: Mapped[str] = mapped_column(String(16), nullable=False, default="custom")
    weekly_tasks_value: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )


class TaskUsageLedger(Base):
    __tablename__ = "task_usage_ledger"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    task_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False, unique=True, index=True
    )
    user_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True
    )
    task_status: Mapped[str] = mapped_column(String(32), nullable=False)
    completed_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, index=True)
    timezone_day: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    timezone_week_start: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    input_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    total_tokens: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    task_count: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )
```

- [ ] **Step 4: Add the Alembic migration**

```python
def upgrade() -> None:
    op.create_table(
        "usage_limit_policies",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("scope_type", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=True),
        sa.Column("daily_tokens_mode", sa.String(length=16), nullable=False),
        sa.Column("daily_tokens_value", sa.Integer(), nullable=True),
        sa.Column("weekly_tokens_mode", sa.String(length=16), nullable=False),
        sa.Column("weekly_tokens_value", sa.Integer(), nullable=True),
        sa.Column("daily_tasks_mode", sa.String(length=16), nullable=False),
        sa.Column("daily_tasks_value", sa.Integer(), nullable=True),
        sa.Column("weekly_tasks_mode", sa.String(length=16), nullable=False),
        sa.Column("weekly_tasks_value", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
    )
    op.create_index("ix_usage_limit_policies_scope_type", "usage_limit_policies", ["scope_type"])
    op.create_index("ix_usage_limit_policies_user_id", "usage_limit_policies", ["user_id"])

    op.create_table(
        "task_usage_ledger",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("task_id", sa.Integer(), sa.ForeignKey("tasks.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("task_status", sa.String(length=32), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=False),
        sa.Column("timezone_day", sa.Date(), nullable=False),
        sa.Column("timezone_week_start", sa.Date(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("task_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), nullable=False),
        sa.UniqueConstraint("task_id", name="uq_task_usage_ledger_task_id"),
    )
```

- [ ] **Step 5: Run the ORM model test to verify it passes**

Run: `cd backend && pytest tests/unit/test_usage_limits_models.py -v`

Expected: PASS with both model smoke tests green.

- [ ] **Step 6: Commit the persistence-layer change**

```bash
git add backend/alembic/versions/033_add_usage_limits.py backend/app/models.py backend/tests/unit/test_usage_limits_models.py
git commit -m "feat: add usage limit persistence"
```

## Task 2: Implement the quota service and ledger helpers

**Files:**
- Create: `backend/app/core/usage_limits.py`
- Test: `backend/tests/unit/test_usage_limits_service.py`

- [ ] **Step 1: Write the failing service tests**

```python
import unittest
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

from app.core.usage_limits import (
    UsageQuotaService,
    UsageLimitExceeded,
)


class UsageQuotaServiceTests(unittest.IsolatedAsyncioTestCase):
    async def test_resolve_effective_limits_merges_system_and_user_modes(self):
        db = MagicMock()
        service = UsageQuotaService()

        limits = await service.resolve_effective_limits(
            db,
            user_id=7,
            system_row=MagicMock(
                daily_tokens_mode="custom",
                daily_tokens_value=100000,
                weekly_tokens_mode="custom",
                weekly_tokens_value=500000,
                daily_tasks_mode="custom",
                daily_tasks_value=5,
                weekly_tasks_mode="custom",
                weekly_tasks_value=20,
            ),
            user_row=MagicMock(
                daily_tokens_mode="inherit",
                daily_tokens_value=None,
                weekly_tokens_mode="custom",
                weekly_tokens_value=250000,
                daily_tasks_mode="unlimited",
                daily_tasks_value=None,
                weekly_tasks_mode="inherit",
                weekly_tasks_value=None,
            ),
        )

        self.assertEqual(limits["daily_tokens"].value, 100000)
        self.assertEqual(limits["weekly_tokens"].value, 250000)
        self.assertTrue(limits["daily_tasks"].is_unlimited)

    async def test_check_limits_raises_for_exceeded_item(self):
        db = MagicMock()
        service = UsageQuotaService()

        with self.assertRaises(UsageLimitExceeded) as ctx:
            await service.raise_if_over_limit(
                db,
                user_id=7,
                scope="create",
                now=datetime(2026, 4, 27, 10, 0, tzinfo=UTC),
                effective_limits={
                    "daily_tokens": MagicMock(is_unlimited=False, value=1000),
                },
                usage_totals={
                    "daily_tokens": 1200,
                },
            )

        self.assertEqual(ctx.exception.scope, "create")
        self.assertEqual(ctx.exception.exceeded_items[0]["metric"], "tokens")
```

- [ ] **Step 2: Run the new service tests to verify they fail**

Run: `cd backend && pytest tests/unit/test_usage_limits_service.py -v`

Expected: FAIL because `backend/app/core/usage_limits.py` and `UsageQuotaService` do not exist yet.

- [ ] **Step 3: Implement `UsageQuotaService` and the over-limit exception**

```python
@dataclass(frozen=True)
class ResolvedUsageLimit:
    mode: str
    value: int | None

    @property
    def is_unlimited(self) -> bool:
        return self.mode == "unlimited"


class UsageLimitExceeded(Exception):
    def __init__(self, *, scope: str, exceeded_items: list[dict[str, object]]) -> None:
        self.scope = scope
        self.exceeded_items = exceeded_items
        super().__init__("usage_limit_exceeded")


class UsageQuotaService:
    async def resolve_effective_limits(self, db: AsyncSession, user_id: int, **overrides) -> dict[str, ResolvedUsageLimit]:
        system_row = overrides.get("system_row") or await self._load_system_policy(db)
        user_row = overrides.get("user_row") or await self._load_user_policy(db, user_id)
        return {
            "daily_tokens": self._resolve_item(system_row, user_row, "daily_tokens"),
            "weekly_tokens": self._resolve_item(system_row, user_row, "weekly_tokens"),
            "daily_tasks": self._resolve_item(system_row, user_row, "daily_tasks"),
            "weekly_tasks": self._resolve_item(system_row, user_row, "weekly_tasks"),
        }

    async def raise_if_over_limit(self, db: AsyncSession, user_id: int, scope: str, **overrides) -> None:
        limits = overrides.get("effective_limits") or await self.resolve_effective_limits(db, user_id)
        usage = overrides.get("usage_totals") or await self.get_current_usage_totals(db, user_id)
        exceeded_items = self._build_exceeded_items(limits, usage, scope)
        if exceeded_items:
            raise UsageLimitExceeded(scope=scope, exceeded_items=exceeded_items)
```

- [ ] **Step 4: Add the ledger upsert helper and window calculation helpers**

```python
async def upsert_task_usage_ledger(db: AsyncSession, task: Task, *, now: datetime | None = None) -> None:
    if task.initiator_user_id is None or task.completed_at is None:
        return
    if task.input_tokens is None and task.output_tokens is None:
        return

    completed_at = task.completed_at
    total_tokens = int(task.input_tokens or 0) + int(task.output_tokens or 0)
    timezone_day, timezone_week_start = _calendar_keys_for_datetime(completed_at)

    existing = await _get_task_usage_row(db, task.id)
    if existing is None:
        existing = TaskUsageLedger(task_id=task.id, user_id=task.initiator_user_id)
        db.add(existing)

    existing.task_status = task.status.value if hasattr(task.status, "value") else str(task.status)
    existing.completed_at = completed_at
    existing.timezone_day = timezone_day
    existing.timezone_week_start = timezone_week_start
    existing.input_tokens = int(task.input_tokens or 0)
    existing.output_tokens = int(task.output_tokens or 0)
    existing.total_tokens = total_tokens
    existing.task_count = 1
```

- [ ] **Step 5: Run the service test file to verify it passes**

Run: `cd backend && pytest tests/unit/test_usage_limits_service.py -v`

Expected: PASS with effective-limit resolution and exceeded-item logic covered.

- [ ] **Step 6: Commit the quota service**

```bash
git add backend/app/core/usage_limits.py backend/tests/unit/test_usage_limits_service.py
git commit -m "feat: add usage quota service"
```

## Task 3: Add backend usage management APIs

**Files:**
- Create: `backend/app/api/usage_limits.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/unit/test_usage_limits_api.py`

- [ ] **Step 1: Write the failing API tests**

```python
import unittest
from unittest.mock import AsyncMock, MagicMock, patch

from fastapi.testclient import TestClient

from app.main import app


class UsageLimitsAPITests(unittest.TestCase):
    def test_get_usage_me_returns_current_user_summary(self):
        with patch("app.api.usage_limits.build_current_user_usage_summary", new=AsyncMock(return_value={
            "user_id": 7,
            "usage": {"daily_tokens": 1200, "weekly_tokens": 3200, "daily_tasks": 1, "weekly_tasks": 3},
            "limits": {"daily_tokens": {"mode": "custom", "value": 5000}},
            "reset_at": {"daily": "2026-04-28T00:00:00+08:00", "weekly": "2026-05-04T00:00:00+08:00"},
            "is_over_limit": False,
        })):
            client = TestClient(app, raise_server_exceptions=False)
            response = client.get("/api/usage/me")

        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.json()["user_id"], 7)

    def test_patch_admin_usage_limit_user_updates_override(self):
        client = TestClient(app, raise_server_exceptions=False)
        response = client.patch(
            "/api/admin/usage-limits/users/7",
            json={
                "daily_tokens": {"mode": "custom", "value": 100000},
                "weekly_tokens": {"mode": "inherit", "value": None},
                "daily_tasks": {"mode": "unlimited", "value": None},
                "weekly_tasks": {"mode": "custom", "value": 20},
            },
        )
        self.assertNotEqual(response.status_code, 404)
```

- [ ] **Step 2: Run the API tests to verify they fail**

Run: `cd backend && pytest tests/unit/test_usage_limits_api.py -v`

Expected: FAIL because `/api/usage/me` and `/api/admin/usage-limits/...` do not exist yet.

- [ ] **Step 3: Implement `backend/app/api/usage_limits.py`**

```python
router = APIRouter()


@router.get("/usage/me", response_model=CurrentUserUsageSummaryResponse)
async def get_my_usage_summary(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_authenticated_user),
):
    return await build_current_user_usage_summary(db, current_user)


@router.get("/admin/usage-limits/users", response_model=list[AdminUsageLimitUserRow])
async def list_admin_usage_users(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin_user),
):
    return await list_usage_limit_users(db)


@router.patch("/admin/usage-limits/users/{user_id}", response_model=AdminUsageLimitUserRow)
async def update_admin_usage_user(
    user_id: int,
    payload: AdminUsageLimitUserUpdateRequest,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_admin_user),
):
    return await update_usage_limit_user(db, user_id, payload)
```

- [ ] **Step 4: Register the router in `backend/app/main.py`**

```python
app.include_router(
    usage_limits.router,
    prefix="/api",
    tags=["usage-limits"],
    dependencies=[Depends(require_authenticated_user)],
)
```

- [ ] **Step 5: Run the API tests to verify the routes pass**

Run: `cd backend && pytest tests/unit/test_usage_limits_api.py -v`

Expected: PASS with current-user and admin usage routes returning JSON payloads instead of 404s.

- [ ] **Step 6: Commit the API layer**

```bash
git add backend/app/api/usage_limits.py backend/app/main.py backend/tests/unit/test_usage_limits_api.py
git commit -m "feat: add usage limit api"
```

## Task 4: Enforce quotas in task creation and scheduler start

**Files:**
- Modify: `backend/app/api/tasks.py`
- Modify: `backend/app/scheduler.py`
- Modify: `backend/app/core/worker.py`
- Modify: `backend/tests/unit/test_tasks_api.py`
- Modify: `backend/tests/unit/test_scheduler.py`
- Modify: `backend/tests/unit/test_worker_coverage.py`

- [ ] **Step 1: Add a failing create-task API test**

```python
def test_create_task_returns_409_when_usage_limit_exceeded(self):
    from app.core.usage_limits import UsageLimitExceeded

    client, app, mock_db = self._get_client_with_issue()
    with patch(
        "app.api.tasks.get_usage_quota_service",
        return_value=MagicMock(
            raise_if_over_limit=AsyncMock(
                side_effect=UsageLimitExceeded(
                    scope="create",
                    exceeded_items=[{
                        "metric": "tokens",
                        "window": "daily",
                        "used": 120000,
                        "limit": 100000,
                        "reset_at": "2026-04-28T00:00:00+08:00",
                    }],
                )
            )
        ),
    ):
        response = client.post("/api/tasks", json={"issue_id": 1, "user_prompt": "Ship it"})

    self.assertEqual(response.status_code, 409)
    self.assertEqual(response.json()["detail"]["reason"], "usage_limit_exceeded")
```

- [ ] **Step 2: Add a failing scheduler and worker test**

```python
async def test_scheduler_marks_task_failed_when_execute_quota_fails(self):
    scheduler = Scheduler()
    task = _make_task(id=9, status=TaskStatus.QUEUED)
    db = _make_db(task)

    with patch(
        "app.scheduler.get_usage_quota_service",
        return_value=MagicMock(
            raise_if_over_limit=AsyncMock(
                side_effect=UsageLimitExceeded(
                    scope="execute",
                    exceeded_items=[{"metric": "tasks", "window": "daily", "used": 6, "limit": 5, "reset_at": "2026-04-28T00:00:00+08:00"}],
                )
            )
        ),
    ):
        await scheduler._execute_task(db, task)

    self.assertEqual(task.status, TaskStatus.FAILED)


async def test_worker_upserts_usage_ledger_for_finished_task(self):
    task = _make_task(id=3, status=TaskStatus.COMPLETED, input_tokens=100, output_tokens=50)
    db = _make_db(task)

    with patch("app.core.worker.upsert_task_usage_ledger", new=AsyncMock()) as mock_upsert:
        await mock_upsert(db, task)

    mock_upsert.assert_awaited()
```

- [ ] **Step 3: Run the modified backend tests to verify they fail**

Run: `cd backend && pytest tests/unit/test_tasks_api.py tests/unit/test_scheduler.py tests/unit/test_worker_coverage.py -k "usage or quota" -v`

Expected: FAIL because task creation does not yet reject over-quota users and the scheduler does not yet fail tasks before start.

- [ ] **Step 4: Wire create-time rejection into `backend/app/api/tasks.py`**

```python
quota_service = get_usage_quota_service()
try:
    await quota_service.raise_if_over_limit(
        db,
        user_id=current_user.id,
        scope="create",
    )
except UsageLimitExceeded as exc:
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail={
            "reason": "usage_limit_exceeded",
            "scope": exc.scope,
            "exceeded_items": exc.exceeded_items,
        },
    ) from exc
```

- [ ] **Step 5: Add execution-time failure before `RUNNING` in `backend/app/scheduler.py`, and ledger upsert in `backend/app/core/worker.py`**

```python
try:
    await get_usage_quota_service().raise_if_over_limit(
        db,
        user_id=task.initiator_user_id,
        scope="execute",
    )
except UsageLimitExceeded as exc:
    task.status = TaskStatus.FAILED
    task.error_message = json.dumps({
        "reason": "usage_limit_exceeded",
        "scope": exc.scope,
        "exceeded_items": exc.exceeded_items,
    })
    task.completed_at = utcnow()
    await db.commit()
    return

task.status = TaskStatus.RUNNING
task.started_at = utcnow()
await db.commit()
```

```python
if task.completed_at is not None:
    await upsert_task_usage_ledger(db, task)
```

- [ ] **Step 6: Run the focused backend tests again**

Run: `cd backend && pytest tests/unit/test_tasks_api.py tests/unit/test_scheduler.py tests/unit/test_worker_coverage.py -k "usage or quota" -v`

Expected: PASS with create-time rejection, scheduler pre-start failure, and ledger writes covered.

- [ ] **Step 7: Commit the enforcement changes**

```bash
git add backend/app/api/tasks.py backend/app/scheduler.py backend/app/core/worker.py backend/tests/unit/test_tasks_api.py backend/tests/unit/test_scheduler.py backend/tests/unit/test_worker_coverage.py
git commit -m "feat: enforce usage limits on tasks"
```

## Task 5: Add frontend API contracts and the current-user top bar indicator

**Files:**
- Modify: `frontend/src/api/index.ts`
- Modify: `frontend/src/api/api.spec.ts`
- Create: `frontend/src/components/CurrentUserUsageIndicator.vue`
- Create: `frontend/src/components/CurrentUserUsageIndicator.spec.ts`
- Modify: `frontend/src/App.vue`
- Modify: `frontend/src/App.spec.ts`
- Modify: `frontend/src/i18n/messages/en.ts`
- Modify: `frontend/src/i18n/messages/zh-CN.ts`

- [ ] **Step 1: Write the failing frontend API and indicator tests**

```ts
it('calls /api/usage/me', async () => {
  mockAxiosGet.mockResolvedValue({ data: { user_id: 7, is_over_limit: false } })

  const result = await getMyUsageSummary()

  expect(mockAxiosGet).toHaveBeenCalledWith('/usage/me')
  expect(result.user_id).toBe(7)
})
```

```ts
it('renders the usage indicator with current totals', async () => {
  const wrapper = mount(CurrentUserUsageIndicator, {
    props: {
      summary: {
        usage: { daily_tokens: 1200, weekly_tokens: 3200, daily_tasks: 1, weekly_tasks: 3 },
        limits: { daily_tokens: { mode: 'custom', value: 5000 } },
        reset_at: { daily: '2026-04-28T00:00:00+08:00', weekly: '2026-05-04T00:00:00+08:00' },
        severity: 'normal',
      },
    },
  })

  expect(wrapper.text()).toContain('1200')
})
```

- [ ] **Step 2: Run the frontend tests to verify they fail**

Run: `cd frontend && npx vitest run src/api/api.spec.ts src/components/CurrentUserUsageIndicator.spec.ts src/App.spec.ts`

Expected: FAIL because `getMyUsageSummary` and `CurrentUserUsageIndicator.vue` do not exist yet.

- [ ] **Step 3: Add usage summary types and client functions in `frontend/src/api/index.ts`**

```ts
export type UsageLimitMode = 'inherit' | 'custom' | 'unlimited'

export interface UsageLimitItem {
  mode: UsageLimitMode
  value: number | null
}

export interface CurrentUserUsageSummary {
  user_id: number
  usage: {
    daily_tokens: number
    weekly_tokens: number
    daily_tasks: number
    weekly_tasks: number
  }
  limits: Record<string, UsageLimitItem>
  reset_at: {
    daily: string
    weekly: string
  }
  is_over_limit: boolean
  severity: 'normal' | 'near_limit' | 'over_limit'
}

export async function getMyUsageSummary(): Promise<CurrentUserUsageSummary> {
  const response = await api.get('/usage/me')
  return response.data
}

export interface AdminUsageLimitDefault {
  daily_tokens: UsageLimitItem
  weekly_tokens: UsageLimitItem
  daily_tasks: UsageLimitItem
  weekly_tasks: UsageLimitItem
}

export interface AdminUsageLimitUser {
  user_id: number
  username: string
  display_name: string | null
  usage: CurrentUserUsageSummary['usage']
  limits: Record<string, UsageLimitItem>
  overrides: Record<string, UsageLimitItem>
  reset_at: CurrentUserUsageSummary['reset_at']
}

export async function getAdminUsageLimitDefault(): Promise<AdminUsageLimitDefault> {
  const response = await api.get('/admin/usage-limits/default')
  return response.data
}

export async function updateAdminUsageLimitDefault(payload: AdminUsageLimitDefault): Promise<AdminUsageLimitDefault> {
  const response = await api.patch('/admin/usage-limits/default', payload)
  return response.data
}

export async function getAdminUsageLimitUsers(): Promise<AdminUsageLimitUser[]> {
  const response = await api.get('/admin/usage-limits/users')
  return response.data
}

export async function updateAdminUsageLimitUser(
  userId: number,
  payload: Record<string, UsageLimitItem>
): Promise<AdminUsageLimitUser> {
  const response = await api.patch(`/admin/usage-limits/users/${userId}`, payload)
  return response.data
}
```

- [ ] **Step 4: Implement `CurrentUserUsageIndicator.vue` and mount it in `frontend/src/App.vue`**

```vue
<n-popover trigger="hover" placement="bottom-end">
  <template #trigger>
    <n-button tertiary circle class="usage-indicator" :class="`usage-indicator--${summary.severity}`">
      <template #icon>
        <n-icon :component="PieChartOutline" />
      </template>
    </n-button>
  </template>

  <div class="usage-indicator__panel">
    <div>{{ t('usageIndicator.dailyTokens') }}: {{ summary.usage.daily_tokens }}</div>
    <div>{{ t('usageIndicator.weeklyTokens') }}: {{ summary.usage.weekly_tokens }}</div>
    <div>{{ t('usageIndicator.dailyTasks') }}: {{ summary.usage.daily_tasks }}</div>
    <div>{{ t('usageIndicator.weeklyTasks') }}: {{ summary.usage.weekly_tasks }}</div>
  </div>
</n-popover>
```

```vue
<CurrentUserUsageIndicator
  v-if="showUserToolbar && currentUsageSummary"
  :summary="currentUsageSummary"
  class="app-shell__usage-indicator"
/>
```

```ts
import { PieChartOutline } from '@vicons/ionicons5'
import CurrentUserUsageIndicator from './components/CurrentUserUsageIndicator.vue'
```

- [ ] **Step 5: Run the frontend tests again**

Run: `cd frontend && npx vitest run src/api/api.spec.ts src/components/CurrentUserUsageIndicator.spec.ts src/App.spec.ts`

Expected: PASS with the new API call and top bar indicator integration covered.

- [ ] **Step 6: Commit the top bar usage indicator work**

```bash
git add frontend/src/api/index.ts frontend/src/api/api.spec.ts frontend/src/components/CurrentUserUsageIndicator.vue frontend/src/components/CurrentUserUsageIndicator.spec.ts frontend/src/App.vue frontend/src/App.spec.ts frontend/src/i18n/messages/en.ts frontend/src/i18n/messages/zh-CN.ts
git commit -m "feat: add current user usage indicator"
```

## Task 6: Build the admin usage page and create-task feedback

**Files:**
- Modify: `frontend/src/router/index.ts`
- Create: `frontend/src/views/UsageManagement.vue`
- Create: `frontend/src/views/UsageManagement.spec.ts`
- Modify: `frontend/src/App.vue`
- Modify: `frontend/src/views/CreateTask.vue`
- Modify: `frontend/src/views/CreateTask.spec.ts`
- Modify: `frontend/src/i18n/messages/en.ts`
- Modify: `frontend/src/i18n/messages/zh-CN.ts`

- [ ] **Step 1: Write the failing page and create-task tests**

```ts
it('loads usage defaults and users on mount', async () => {
  ;(mockApi.getAdminUsageLimitUsers as Mock).mockResolvedValue([])
  ;(mockApi.getAdminUsageLimitDefault as Mock).mockResolvedValue({
    daily_tokens: { mode: 'custom', value: 5000 },
    weekly_tokens: { mode: 'custom', value: 20000 },
    daily_tasks: { mode: 'custom', value: 3 },
    weekly_tasks: { mode: 'custom', value: 12 },
  })

  const wrapper = mount(UsageManagement)
  await flushPromises()

  expect(mockApi.getAdminUsageLimitUsers).toHaveBeenCalledTimes(1)
  expect(mockApi.getAdminUsageLimitDefault).toHaveBeenCalledTimes(1)
  expect(wrapper.find('[data-testid="usage-management-page"]').exists()).toBe(true)
})
```

```ts
it('renders structured over-limit feedback from createTask', async () => {
  ;(mockApi.createTask as Mock).mockRejectedValue({
    apiError: {
      status: 409,
      detail: {
        reason: 'usage_limit_exceeded',
        exceeded_items: [{ metric: 'tokens', window: 'daily', used: 120000, limit: 100000 }],
      },
    },
  })

  const wrapper = mountWithRouter()
  await flushPromises()
  await wrapper.vm.handleSubmit()

  expect(mockMessage.error).toHaveBeenCalled()
})
```

- [ ] **Step 2: Run the frontend tests to verify they fail**

Run: `cd frontend && npx vitest run src/views/UsageManagement.spec.ts src/views/CreateTask.spec.ts`

Expected: FAIL because `UsageManagement.vue` and the new create-task feedback state do not exist yet.

- [ ] **Step 3: Implement `UsageManagement.vue` and register the route/menu entry**

```ts
{
  path: '/usage-management',
  name: 'UsageManagement',
  component: () => import('../views/UsageManagement.vue'),
  meta: { requiresAuth: true, requiresAdmin: true }
}
```

```vue
<PageHeader :title="t('usageManagement.title')" :subtitle="t('usageManagement.subtitle')" />

<n-card data-testid="usage-default-card">
  <!-- system default editors -->
</n-card>

<n-card data-testid="usage-users-card">
  <!-- user list with effective limits, usage totals, and inherit/custom/unlimited editors -->
</n-card>
```

```ts
adminItems.push(buildMenuItem('nav.usageManagement', 'UsageManagement', PieChartOutline))
menuLabels.UsageManagement = 'nav.usageManagement'
```

- [ ] **Step 4: Implement current-user warnings and structured error rendering in `frontend/src/views/CreateTask.vue`**

```ts
const usageSummary = ref<CurrentUserUsageSummary | null>(null)

onMounted(async () => {
  usageSummary.value = await getMyUsageSummary()
})

function buildUsageExceededMessage(detail: any) {
  return detail.exceeded_items
    .map((item: any) => `${item.window}:${item.metric} ${item.used}/${item.limit}`)
    .join(' | ')
}

async function handleSubmit() {
  try {
    await createTask(payload)
  } catch (error: any) {
    if (error.apiError?.detail?.reason === 'usage_limit_exceeded') {
      message.error(buildUsageExceededMessage(error.apiError.detail))
      return
    }
    throw error
  }
}
```

- [ ] **Step 5: Add the new i18n keys in both locale files**

```ts
nav: {
  usageManagement: 'Usage Management',
},
usageManagement: {
  title: 'Usage Management',
  subtitle: 'View user usage, system defaults, and per-user overrides.',
},
usageIndicator: {
  dailyTokens: 'Daily tokens',
  weeklyTokens: 'Weekly tokens',
  dailyTasks: 'Daily tasks',
  weeklyTasks: 'Weekly tasks',
},
createTask: {
  usageWarningTitle: 'Usage limits apply',
  usageExceeded: 'You are already over your quota for {items}.',
}
```

- [ ] **Step 6: Run the page tests and the frontend build**

Run: `cd frontend && npx vitest run src/views/UsageManagement.spec.ts src/views/CreateTask.spec.ts && npm run build`

Expected: PASS for both Vitest files, then a successful Vue type-check and production build.

- [ ] **Step 7: Commit the admin page and create-task UX**

```bash
git add frontend/src/router/index.ts frontend/src/views/UsageManagement.vue frontend/src/views/UsageManagement.spec.ts frontend/src/views/CreateTask.vue frontend/src/views/CreateTask.spec.ts frontend/src/App.vue frontend/src/i18n/messages/en.ts frontend/src/i18n/messages/zh-CN.ts
git commit -m "feat: add usage management ui"
```

## Task 7: Run the focused backend and frontend regression sweep

**Files:**
- Modify: `backend/tests/unit/test_usage_limits_models.py`
- Modify: `backend/tests/unit/test_usage_limits_service.py`
- Modify: `backend/tests/unit/test_usage_limits_api.py`
- Modify: `backend/tests/unit/test_tasks_api.py`
- Modify: `backend/tests/unit/test_scheduler.py`
- Modify: `backend/tests/unit/test_worker_coverage.py`
- Modify: `frontend/src/api/api.spec.ts`
- Modify: `frontend/src/components/CurrentUserUsageIndicator.spec.ts`
- Modify: `frontend/src/App.spec.ts`
- Modify: `frontend/src/views/UsageManagement.spec.ts`
- Modify: `frontend/src/views/CreateTask.spec.ts`

- [ ] **Step 1: Run the focused backend suite**

Run: `cd backend && pytest tests/unit/test_usage_limits_models.py tests/unit/test_usage_limits_service.py tests/unit/test_usage_limits_api.py tests/unit/test_tasks_api.py tests/unit/test_scheduler.py tests/unit/test_worker_coverage.py -v`

Expected: PASS with quota persistence, service behavior, API responses, create-time rejection, scheduler pre-start failure, and ledger writes all covered.

- [ ] **Step 2: Run the focused frontend suite**

Run: `cd frontend && npx vitest run src/api/api.spec.ts src/components/CurrentUserUsageIndicator.spec.ts src/App.spec.ts src/views/UsageManagement.spec.ts src/views/CreateTask.spec.ts`

Expected: PASS with API client, top bar indicator, admin page, and create-task feedback covered.

- [ ] **Step 3: Run the frontend production build one more time**

Run: `cd frontend && npm run build`

Expected: PASS with `vue-tsc` and Vite build completing successfully.

- [ ] **Step 4: Commit the verification sweep**

```bash
git add backend/tests/unit/test_usage_limits_models.py backend/tests/unit/test_usage_limits_service.py backend/tests/unit/test_usage_limits_api.py backend/tests/unit/test_tasks_api.py backend/tests/unit/test_scheduler.py backend/tests/unit/test_worker_coverage.py frontend/src/api/api.spec.ts frontend/src/components/CurrentUserUsageIndicator.spec.ts frontend/src/App.spec.ts frontend/src/views/UsageManagement.spec.ts frontend/src/views/CreateTask.spec.ts
git commit -m "test: verify usage management flow"
```

## Self-Review

### Spec coverage

- **Dedicated admin page** → Task 6
- **Top bar usage indicator** → Task 5
- **System defaults + per-user overrides + unlimited mode** → Tasks 1, 2, 3, and 6
- **Create-time enforcement** → Task 4
- **Execute-time enforcement with FAILED result** → Task 4
- **Task-granularity accounting only** → Tasks 1 and 2
- **Friendly structured feedback** → Tasks 3, 4, and 6

### Placeholder scan

- No `TBD`, `TODO`, or “implement later” placeholders remain.
- Each code-changing step includes a concrete code block.
- Each test-running step includes an exact command and expected result.

### Type consistency

- Backend naming is consistent around `UsageLimitPolicy`, `TaskUsageLedger`, `UsageQuotaService`, and `UsageLimitExceeded`.
- Frontend naming is consistent around `CurrentUserUsageSummary`, `CurrentUserUsageIndicator`, and `UsageManagement`.
- API naming is consistent around `/api/usage/me` and `/api/admin/usage-limits/...`.
