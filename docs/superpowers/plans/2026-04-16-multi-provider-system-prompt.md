# Multi AI Provider + System Prompt — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the single-provider Anthropic config with a multi-provider system supporting named providers, per-task provider selection, and `--append-system-prompt` for Claude CLI.

**Architecture:** New `ai_providers` table with CRUD API. Task gains `provider_id` FK. Worker resolves provider from task → default → legacy fallback. Frontend gets new "AI Providers" Config tab, provider selector in task creation, and metadata display.

**Tech Stack:** FastAPI + SQLAlchemy (async) + Alembic, Vue 3 + NaiveUI, Docker entrypoint (bash)

---

## File Map

### New Files
| File | Purpose |
|------|---------|
| `backend/app/api/providers.py` | Provider CRUD API endpoints |
| `backend/tests/unit/test_providers_api.py` | Provider API unit tests |
| `frontend/src/components/config/AIProvidersPanel.vue` | AI Providers Config tab content |

### Modified Files
| File | Change |
|------|--------|
| `backend/alembic/versions/027_add_ai_providers.py` | Migration: create `ai_providers` table, add `tasks.provider_id` FK |
| `backend/app/models.py` | New `AIProvider` model, add `Task.provider_id` column + relationship |
| `backend/app/main.py` | Register providers router |
| `backend/app/core/task_helpers.py` | Add `provider_name` to task serialization |
| `backend/app/api/tasks.py` | Accept `provider_id` in create_task |
| `backend/app/api/task_schemas.py` | Add `provider_id` to CreateTaskRequest |
| `backend/app/core/worker.py` | `_resolve_provider()` + update `_build_container_env()` |
| `backend/app/api/config_runtime.py` | Legacy compat: read/write default provider fields |
| `deploy/ci-claude.sh` | Already supports `APPEND_SYSTEM_PROMPT` ✅ — no change needed |
| `deploy/entrypoint.sh` | Pass `APPEND_SYSTEM_PROMPT` env var |
| `frontend/src/api/index.ts` | Add `AIProvider` interface + CRUD API functions + `provider_id` to `CreateTaskRequest` and `Task` |
| `frontend/src/views/Config.vue` | Add AI Providers tab |
| `frontend/src/components/config/WorkerSettingsPanel.vue` | Remove AI provider fields, add redirect note |
| `frontend/src/views/IssueView.vue` | Add provider selector to create-task form |
| `frontend/src/views/CreateTask.vue` | Add provider selector |
| `frontend/src/components/TaskMetadataPanel.vue` | Show provider name row |
| `frontend/src/i18n/messages/en.ts` | Provider i18n keys |
| `frontend/src/i18n/messages/zh-CN.ts` | Provider i18n keys (Chinese) |

---

### Task 1: Alembic Migration — Create `ai_providers` Table + `tasks.provider_id` FK

**Files:**
- Create: `backend/alembic/versions/027_add_ai_providers.py`

- [ ] **Step 1: Create migration file**

```python
"""add ai_providers table and tasks.provider_id FK

Revision ID: 027_add_ai_providers
Revises: 026_add_filter_indexes
Create Date: 2026-04-16
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "027_add_ai_providers"
down_revision: Union[str, None] = "026_add_filter_indexes"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. Create ai_providers table
    op.create_table(
        "ai_providers",
        sa.Column("id", sa.Integer, primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(100), nullable=False, unique=True),
        sa.Column("base_url", sa.Text, nullable=False),
        sa.Column("api_key", sa.Text, nullable=True),
        sa.Column("model", sa.String(200), nullable=False),
        sa.Column("max_turns", sa.Integer, nullable=False, server_default="20"),
        sa.Column("system_prompt", sa.Text, nullable=True),
        sa.Column("is_default", sa.Boolean, nullable=False, server_default="false"),
        sa.Column("created_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime, nullable=False, server_default=sa.func.now()),
    )

    # 2. Add provider_id FK to tasks
    op.add_column("tasks", sa.Column("provider_id", sa.Integer, nullable=True))
    op.create_foreign_key(
        "fk_tasks_provider_id",
        "tasks",
        "ai_providers",
        ["provider_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_tasks_provider_id", "tasks", ["provider_id"])

    # 3. Data migration: copy current system_config anthropic_* entries into a default provider
    conn = op.get_bind()

    # Read current settings from system_config
    rows = conn.execute(
        sa.text("SELECT key, value, value_type FROM system_config WHERE key IN "
                "('anthropic_base_url', 'anthropic_api_key', 'anthropic_model', 'claude_max_turns')")
    ).fetchall()

    config = {}
    for row in rows:
        config[row[0]] = row[1]

    # Only create default provider if there's at least a base_url or model configured
    base_url = config.get("anthropic_base_url", "http://localhost:11434/v1")
    api_key = config.get("anthropic_api_key")  # Already encrypted in system_config
    model = config.get("anthropic_model", "claude-sonnet-4-20250514")
    max_turns_str = config.get("claude_max_turns", "20")
    try:
        max_turns = int(max_turns_str)
    except (ValueError, TypeError):
        max_turns = 20

    conn.execute(
        sa.text(
            "INSERT INTO ai_providers (name, base_url, api_key, model, max_turns, is_default, created_at, updated_at) "
            "VALUES (:name, :base_url, :api_key, :model, :max_turns, :is_default, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
        ),
        {
            "name": "default",
            "base_url": base_url,
            "api_key": api_key,  # Preserve encrypted value as-is
            "model": model,
            "max_turns": max_turns,
            "is_default": True,
        },
    )


def downgrade() -> None:
    op.drop_index("ix_tasks_provider_id", table_name="tasks")
    op.drop_constraint("fk_tasks_provider_id", "tasks", type_="foreignkey")
    op.drop_column("tasks", "provider_id")
    op.drop_table("ai_providers")
```

- [ ] **Step 2: Verify migration applies**

Run: `cd backend && alembic upgrade head`
Expected: Migration applies successfully, `ai_providers` table created with one "default" row.

- [ ] **Step 3: Verify downgrade works**

Run: `cd backend && alembic downgrade -1 && alembic upgrade head`
Expected: Clean downgrade/upgrade cycle.

- [ ] **Step 4: Commit**

```bash
git add backend/alembic/versions/027_add_ai_providers.py
git commit -m "feat: add ai_providers table and tasks.provider_id FK migration"
```

---

### Task 2: Backend Model — `AIProvider` + Task `provider_id`

**Files:**
- Modify: `backend/app/models.py`

- [ ] **Step 1: Add AIProvider model after Issue class (after line 87)**

In `backend/app/models.py`, add the `AIProvider` model between the `Issue` class and the `Task` class. Insert after the `Issue.__table_args__` closing parenthesis (line 86):

```python
class AIProvider(Base):
    """Named AI provider configuration."""

    __tablename__ = "ai_providers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    base_url: Mapped[str] = mapped_column(Text, nullable=False)
    api_key: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    model: Mapped[str] = mapped_column(String(200), nullable=False)
    max_turns: Mapped[int] = mapped_column(Integer, nullable=False, default=20)
    system_prompt: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    tasks: Mapped[List["Task"]] = relationship("Task", back_populates="provider")
```

- [ ] **Step 2: Add provider_id column and relationship to Task model**

In the `Task` class, after the `issue_id` FK block (after line 99), add:

```python
    # AI Provider
    provider_id: Mapped[Optional[int]] = mapped_column(
        Integer, ForeignKey("ai_providers.id", ondelete="SET NULL"), nullable=True, index=True
    )
```

In the Task relationships section (around line 160), add:

```python
    provider: Mapped[Optional["AIProvider"]] = relationship("AIProvider", back_populates="tasks")
```

- [ ] **Step 3: Verify import**

Run: `cd backend && python -c "from app.models import AIProvider, Task; print('OK')"`
Expected: `OK`

- [ ] **Step 4: Commit**

```bash
git add backend/app/models.py
git commit -m "feat: add AIProvider model and Task.provider_id relationship"
```

---

### Task 3: Backend API — Provider CRUD Endpoints

**Files:**
- Create: `backend/app/api/providers.py`
- Modify: `backend/app/main.py`

- [ ] **Step 1: Create providers API module**

Create `backend/app/api/providers.py`:

```python
"""AI Provider CRUD API endpoints."""

import logging
import re
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, field_validator
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config_crypto import decrypt_config_secret, encrypt_config_secret, ConfigEncryptionError
from app.database import get_db
from app.models import AIProvider, Task, TaskStatus

logger = logging.getLogger(__name__)
router = APIRouter()

_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_-]{0,99}$")


# ── Schemas ────────────────────────────────────────────────────────────────────

class ProviderResponse(BaseModel):
    id: int
    name: str
    base_url: str
    api_key_configured: bool
    model: str
    max_turns: int
    system_prompt: Optional[str]
    is_default: bool
    created_at: str
    updated_at: str


class CreateProviderRequest(BaseModel):
    name: str
    base_url: str
    api_key: Optional[str] = None
    model: str
    max_turns: int = 20
    system_prompt: Optional[str] = None

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: str) -> str:
        if not _NAME_RE.match(v):
            raise ValueError(
                "Name must be 1-100 characters, alphanumeric/hyphens/underscores, "
                "starting with alphanumeric"
            )
        return v

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, v: str) -> str:
        if not v.startswith(("http://", "https://")):
            raise ValueError("Base URL must start with http:// or https://")
        return v

    @field_validator("model")
    @classmethod
    def validate_model(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("Model name cannot be empty")
        return v.strip()

    @field_validator("max_turns")
    @classmethod
    def validate_max_turns(cls, v: int) -> int:
        if v < 1 or v > 1000:
            raise ValueError("Max turns must be between 1 and 1000")
        return v

    @field_validator("system_prompt")
    @classmethod
    def validate_system_prompt(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and len(v) > 10000:
            raise ValueError("System prompt must be 10000 characters or fewer")
        return v


class UpdateProviderRequest(BaseModel):
    name: Optional[str] = None
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    clear_api_key: bool = False
    model: Optional[str] = None
    max_turns: Optional[int] = None
    system_prompt: Optional[str] = None
    clear_system_prompt: bool = False

    @field_validator("name")
    @classmethod
    def validate_name(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not _NAME_RE.match(v):
            raise ValueError(
                "Name must be 1-100 characters, alphanumeric/hyphens/underscores, "
                "starting with alphanumeric"
            )
        return v

    @field_validator("base_url")
    @classmethod
    def validate_base_url(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not v.startswith(("http://", "https://")):
            raise ValueError("Base URL must start with http:// or https://")
        return v

    @field_validator("model")
    @classmethod
    def validate_model(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and not v.strip():
            raise ValueError("Model name cannot be empty")
        return v.strip() if v else v

    @field_validator("max_turns")
    @classmethod
    def validate_max_turns(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and (v < 1 or v > 1000):
            raise ValueError("Max turns must be between 1 and 1000")
        return v

    @field_validator("system_prompt")
    @classmethod
    def validate_system_prompt(cls, v: Optional[str]) -> Optional[str]:
        if v is not None and len(v) > 10000:
            raise ValueError("System prompt must be 10000 characters or fewer")
        return v


# ── Helpers ────────────────────────────────────────────────────────────────────

def _serialize_provider(provider: AIProvider) -> dict:
    return {
        "id": provider.id,
        "name": provider.name,
        "base_url": provider.base_url,
        "api_key_configured": provider.api_key is not None and provider.api_key != "",
        "model": provider.model,
        "max_turns": provider.max_turns,
        "system_prompt": provider.system_prompt,
        "is_default": provider.is_default,
        "created_at": provider.created_at.isoformat(),
        "updated_at": provider.updated_at.isoformat(),
    }


def _decrypt_provider_api_key(provider: AIProvider) -> str:
    """Decrypt a provider's stored API key. Returns empty string if none."""
    if not provider.api_key:
        return ""
    try:
        return decrypt_config_secret(provider.api_key)
    except ConfigEncryptionError:
        # If decryption fails, the value might be stored in plaintext (legacy migration)
        return provider.api_key


# ── Endpoints ──────────────────────────────────────────────────────────────────

@router.get("/providers")
async def list_providers(db: AsyncSession = Depends(get_db)):
    """List all AI providers."""
    result = await db.execute(
        select(AIProvider).order_by(AIProvider.is_default.desc(), AIProvider.id)
    )
    providers = result.scalars().all()
    return [_serialize_provider(p) for p in providers]


@router.get("/providers/{provider_id}")
async def get_provider(provider_id: int, db: AsyncSession = Depends(get_db)):
    """Get a single AI provider."""
    provider = await db.get(AIProvider, provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")
    return _serialize_provider(provider)


@router.post("/providers", status_code=status.HTTP_201_CREATED)
async def create_provider(
    request: CreateProviderRequest,
    db: AsyncSession = Depends(get_db),
):
    """Create a new AI provider."""
    # Check name uniqueness
    existing = await db.execute(
        select(AIProvider).where(AIProvider.name == request.name)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Provider with name '{request.name}' already exists",
        )

    # Determine if this should be the default (first provider)
    count_result = await db.execute(select(func.count(AIProvider.id)))
    is_first = count_result.scalar() == 0

    # Encrypt API key if provided
    encrypted_key = None
    if request.api_key:
        try:
            encrypted_key = encrypt_config_secret(request.api_key)
        except ConfigEncryptionError as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to encrypt API key: {e}",
            )

    provider = AIProvider(
        name=request.name,
        base_url=request.base_url,
        api_key=encrypted_key,
        model=request.model,
        max_turns=request.max_turns,
        system_prompt=request.system_prompt,
        is_default=is_first,
    )
    db.add(provider)
    await db.commit()
    await db.refresh(provider)

    logger.info(f"Created AI provider '{provider.name}' (id={provider.id}, default={provider.is_default})")
    return _serialize_provider(provider)


@router.patch("/providers/{provider_id}")
async def update_provider(
    provider_id: int,
    request: UpdateProviderRequest,
    db: AsyncSession = Depends(get_db),
):
    """Update an existing AI provider."""
    provider = await db.get(AIProvider, provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")

    # Check name uniqueness if changing
    if request.name is not None and request.name != provider.name:
        existing = await db.execute(
            select(AIProvider).where(AIProvider.name == request.name)
        )
        if existing.scalar_one_or_none():
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Provider with name '{request.name}' already exists",
            )
        provider.name = request.name

    if request.base_url is not None:
        provider.base_url = request.base_url

    if request.model is not None:
        provider.model = request.model

    if request.max_turns is not None:
        provider.max_turns = request.max_turns

    # Handle API key update/clear
    if request.clear_api_key:
        provider.api_key = None
    elif request.api_key is not None:
        try:
            provider.api_key = encrypt_config_secret(request.api_key)
        except ConfigEncryptionError as e:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to encrypt API key: {e}",
            )

    # Handle system_prompt update/clear
    if request.clear_system_prompt:
        provider.system_prompt = None
    elif request.system_prompt is not None:
        provider.system_prompt = request.system_prompt

    await db.commit()
    await db.refresh(provider)

    logger.info(f"Updated AI provider '{provider.name}' (id={provider.id})")
    return _serialize_provider(provider)


@router.delete("/providers/{provider_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_provider(
    provider_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Delete an AI provider."""
    provider = await db.get(AIProvider, provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")

    # Check if this is the last provider
    count_result = await db.execute(select(func.count(AIProvider.id)))
    total = count_result.scalar()
    if total <= 1:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Cannot delete the only provider — at least one must exist",
        )

    # Check for active tasks using this provider
    active_count_result = await db.execute(
        select(func.count(Task.id)).where(
            Task.provider_id == provider_id,
            Task.status.in_([TaskStatus.PENDING, TaskStatus.QUEUED, TaskStatus.RUNNING]),
        )
    )
    active_count = active_count_result.scalar()
    if active_count > 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot delete provider — {active_count} active task(s) reference it",
        )

    was_default = provider.is_default
    await db.delete(provider)

    # If we deleted the default, promote the lowest-ID remaining provider
    if was_default:
        result = await db.execute(
            select(AIProvider).order_by(AIProvider.id).limit(1)
        )
        new_default = result.scalar_one_or_none()
        if new_default:
            new_default.is_default = True
            logger.info(f"Promoted provider '{new_default.name}' to default after deletion")

    await db.commit()
    logger.info(f"Deleted AI provider id={provider_id}")


@router.post("/providers/{provider_id}/set-default")
async def set_default_provider(
    provider_id: int,
    db: AsyncSession = Depends(get_db),
):
    """Set a provider as the system default."""
    provider = await db.get(AIProvider, provider_id)
    if not provider:
        raise HTTPException(status_code=404, detail="Provider not found")

    if provider.is_default:
        return _serialize_provider(provider)

    # Clear all defaults
    result = await db.execute(select(AIProvider).where(AIProvider.is_default == True))
    for p in result.scalars().all():
        p.is_default = False

    provider.is_default = True
    await db.commit()
    await db.refresh(provider)

    logger.info(f"Set provider '{provider.name}' (id={provider.id}) as default")
    return _serialize_provider(provider)
```

- [ ] **Step 2: Register router in main.py**

In `backend/app/main.py`, add `providers` to the import on line 202:

```python
from app.api import admin_users, auth, issues, tasks, containers, stats, config, config_integration, config_runtime, mattermost, oidc, project_webhooks, prompt_templates, projects, providers
```

Then add the router include after the `config_runtime` router (after line 252):

```python
app.include_router(
    providers.router,
    prefix="/api",
    tags=["providers"],
    dependencies=[Depends(require_admin_user)],
)
```

- [ ] **Step 3: Verify endpoint registration**

Run: `cd backend && python -c "from app.main import app; routes = [r.path for r in app.routes]; print([r for r in routes if 'provider' in r])"`
Expected: List containing `/api/providers`, `/api/providers/{provider_id}`, etc.

- [ ] **Step 4: Commit**

```bash
git add backend/app/api/providers.py backend/app/main.py
git commit -m "feat: add provider CRUD API endpoints"
```

---

### Task 4: Backend — Provider Resolution in Worker

**Files:**
- Modify: `backend/app/core/worker.py`
- Modify: `deploy/entrypoint.sh`

- [ ] **Step 1: Add `_resolve_provider()` method to WorkerExecutor**

In `backend/app/core/worker.py`, add the import at the top (near line 11):

```python
from app.models import AIProvider
```

Add `_decrypt_provider_api_key` import:

```python
from app.api.providers import _decrypt_provider_api_key
```

Add the method to the `WorkerExecutor` class, before `_build_container_env` (before line 476):

```python
    async def _resolve_provider(self, db: AsyncSession, task: Task) -> AIProvider:
        """Resolve the AI provider for a task.

        Resolution chain: task.provider_id → default provider → legacy settings.
        """
        from sqlalchemy import select

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
            api_key=settings.anthropic_api_key,  # Not encrypted — raw from env
            model=settings.anthropic_model,
            max_turns=settings.claude_max_turns,
            system_prompt=None,
        )
```

- [ ] **Step 2: Update `_build_container_env()` to use resolved provider**

Change the method signature to accept a `provider` parameter, and update the body. Replace the current `_build_container_env` method (lines 476-517) with:

```python
    def _build_container_env(
        self,
        task: Task,
        issue: Issue,
        mr_iid: Optional[int],
        target_branch: Optional[str],
        provider: "AIProvider",
    ) -> dict[str, str]:
        """Build environment variables for the worker container."""
        settings = get_settings()

        # Decrypt provider API key
        api_key = _decrypt_provider_api_key(provider) if provider.id else (provider.api_key or "")

        environment = {
            "GITLAB_URL": settings.gitlab_url,
            "GITLAB_TOKEN": settings.gitlab_bot_token,
            "PROJECT_ID": str(task.project_id),
            "BRANCH_NAME": issue.branch_name,
            "USER_PROMPT": task.user_prompt,
            "TARGET_BRANCH": target_branch or "",
            "ANTHROPIC_BASE_URL": provider.base_url,
            "ANTHROPIC_API_KEY": api_key,
            "ANTHROPIC_MODEL": provider.model,
            "CLAUDE_MAX_TURNS": str(provider.max_turns),
            "TASK_ID": str(task.id),
            "TASK_TIMEOUT": str(settings.task_timeout),
            "ISSUE_ID": str(issue.id),
            "ISSUE_TITLE": issue.title or "",
        }

        # System prompt for Claude CLI
        if provider.system_prompt:
            environment["APPEND_SYSTEM_PROMPT"] = provider.system_prompt

        # Pass session ID for resume
        if issue.claude_session_id:
            environment["RESUME_SESSION"] = issue.claude_session_id

        if issue.base_branch:
            environment["BASE_BRANCH"] = issue.base_branch

        if mr_iid:
            environment["MR_IID"] = str(mr_iid)

        if settings.custom_ca_bundle:
            environment["CUSTOM_CA_BUNDLE"] = settings.custom_ca_bundle

        return environment
```

- [ ] **Step 3: Update all callers of `_build_container_env()`**

Search for all calls to `_build_container_env` in `worker.py` and update them to pass the resolved `provider`. There is one call site — find it and add `provider=provider` argument. The `_resolve_provider` call should happen earlier in `execute_task` where the DB session is available, and the provider should be passed through to `_build_container_env`.

Find the `execute_task` method and add provider resolution after the task/issue are loaded:

```python
        provider = await self._resolve_provider(db, task)
```

Then pass `provider=provider` to `_build_container_env()`.

- [ ] **Step 4: Update `entrypoint.sh` to pass APPEND_SYSTEM_PROMPT**

In `deploy/entrypoint.sh`, after line 25 (the `ANTHROPIC_MODEL` line), add:

```bash
APPEND_SYSTEM_PROMPT="${APPEND_SYSTEM_PROMPT:-}"
```

And in the echo block (around line 42), add:

```bash
echo "System Prompt:  $([ -n "$APPEND_SYSTEM_PROMPT" ] && echo 'set (${#APPEND_SYSTEM_PROMPT} chars)' || echo 'none')"
```

Then around line 449 where exports happen, add:

```bash
export APPEND_SYSTEM_PROMPT
```

Note: `ci-claude.sh` already reads `APPEND_SYSTEM_PROMPT` env var and passes it as `--append-system-prompt` to the Claude CLI. No change needed there.

- [ ] **Step 5: Commit**

```bash
git add backend/app/core/worker.py deploy/entrypoint.sh
git commit -m "feat: worker resolves AI provider per-task, passes system prompt"
```

---

### Task 5: Backend — Task Creation with `provider_id`

**Files:**
- Modify: `backend/app/api/task_schemas.py`
- Modify: `backend/app/api/tasks.py`
- Modify: `backend/app/core/task_helpers.py`

- [ ] **Step 1: Add `provider_id` to CreateTaskRequest**

In `backend/app/api/task_schemas.py`, add to `CreateTaskRequest` (line 42, before `@model_validator`):

```python
    provider_id: Optional[int] = None
```

- [ ] **Step 2: Validate `provider_id` in create_task endpoint**

In `backend/app/api/tasks.py`, in the `create_task` function (around line 818), add after the prompt validation:

```python
    # Validate provider_id if provided
    if request.provider_id is not None:
        from app.models import AIProvider
        provider = await db.get(AIProvider, request.provider_id)
        if not provider:
            raise HTTPException(status_code=404, detail="Provider not found")
```

And add `provider_id` to the Task constructor (around line 845):

```python
    task = Task(
        issue_id=issue.id,
        project_id=issue.project_id,
        user_prompt=prompt,
        initiator_user_id=current_user.id if current_user is not None else None,
        initiator_gitlab_user_id=current_user.gitlab_user_id if current_user is not None else None,
        initiator_username=current_user.username if current_user is not None else None,
        priority=request.priority,
        scheduled_at=scheduled_at,
        provider_id=request.provider_id,
    )
```

- [ ] **Step 3: Add `provider_id` and `provider_name` to task serialization**

In `backend/app/core/task_helpers.py`, in `_serialize_task()`, add after `"merge_request_title"` (around line 52):

```python
        "provider_id": task.provider_id,
        "provider_name": None,
```

Then after the issue serialization block (after line 75), add provider name resolution:

```python
    # Add provider name if loaded
    provider = None
    try:
        insp = sa_inspect(task)
        if "provider" not in insp.unloaded:
            provider = task.provider
    except Exception:
        pass
    if provider is not None:
        data["provider_name"] = provider.name
```

- [ ] **Step 4: Commit**

```bash
git add backend/app/api/task_schemas.py backend/app/api/tasks.py backend/app/core/task_helpers.py
git commit -m "feat: support provider_id in task creation and serialization"
```

---

### Task 6: Backend — Legacy Config Compatibility

**Files:**
- Modify: `backend/app/api/config_runtime.py`

- [ ] **Step 1: Update `_serialize_runtime_config` to read from default provider**

In `backend/app/api/config_runtime.py`, the GET endpoint should still return `anthropic_*` fields. These should reflect the default provider when one exists. This is a read-path change.

The current implementation reads from `get_effective_settings()` which already merges system_config. Since the migration preserves system_config entries, the legacy GET will continue to work. However, we want future writes to also update the default provider.

- [ ] **Step 2: Update PATCH to sync changes to default provider**

In the PATCH handler for runtime config, after saving `anthropic_*` values to system_config, also update the default provider. Add a helper function:

```python
async def _sync_anthropic_to_default_provider(
    db: AsyncSession,
    updates: dict,
) -> None:
    """Sync anthropic_* runtime config changes to the default AI provider."""
    from app.models import AIProvider
    result = await db.execute(
        select(AIProvider).where(AIProvider.is_default == True)
    )
    provider = result.scalar_one_or_none()
    if not provider:
        return

    if "anthropic_base_url" in updates:
        provider.base_url = updates["anthropic_base_url"]
    if "anthropic_model" in updates:
        provider.model = updates["anthropic_model"]
    if "claude_max_turns" in updates:
        provider.max_turns = updates["claude_max_turns"]
    if "anthropic_api_key" in updates:
        from app.core.config_crypto import encrypt_config_secret
        provider.api_key = encrypt_config_secret(updates["anthropic_api_key"])
    if updates.get("clear_anthropic_api_key"):
        provider.api_key = None
```

Call this function at the end of the PATCH handler, before the final commit.

- [ ] **Step 3: Commit**

```bash
git add backend/app/api/config_runtime.py
git commit -m "feat: legacy runtime config syncs anthropic settings to default provider"
```

---

### Task 7: Backend Unit Tests — Provider CRUD

**Files:**
- Create: `backend/tests/unit/test_providers_api.py`

- [ ] **Step 1: Create test file**

```python
#!/usr/bin/env python3
"""Unit tests for AI Provider API endpoints."""

import os
import sys
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

from starlette.requests import Request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from fastapi.testclient import TestClient
from app.main import app
from app.database import get_db
from app.config import get_settings, reset_runtime_config
from app.dependencies.auth import require_authenticated_context
from app.runtime_config import reset_runtime_config_sync_state


def _make_provider(
    id=1,
    name="test-provider",
    base_url="http://localhost:11434/v1",
    api_key=None,
    model="claude-sonnet-4-20250514",
    max_turns=20,
    system_prompt=None,
    is_default=False,
):
    from datetime import datetime
    from app.models import AIProvider
    p = AIProvider(
        name=name,
        base_url=base_url,
        api_key=api_key,
        model=model,
        max_turns=max_turns,
        system_prompt=system_prompt,
        is_default=is_default,
    )
    p.id = id
    p.created_at = datetime(2026, 1, 1)
    p.updated_at = datetime(2026, 1, 1)
    return p


class ProviderListTests(unittest.TestCase):
    def setUp(self):
        self._orig_key = os.environ.get("CONFIG_ENCRYPTION_KEY")
        os.environ["CONFIG_ENCRYPTION_KEY"] = "unit-test-config-key"
        get_settings.cache_clear()
        reset_runtime_config()
        reset_runtime_config_sync_state()

        self.client = TestClient(app)
        self.mock_db = MagicMock()
        self.mock_db.execute = AsyncMock()
        self.mock_db.get = AsyncMock(return_value=None)
        self.mock_db.commit = AsyncMock()
        self.mock_db.flush = AsyncMock()
        self.mock_db.add = MagicMock()
        self.mock_db.refresh = AsyncMock()
        self.mock_db.delete = AsyncMock()
        app.dependency_overrides[get_db] = lambda: self.mock_db

        async def mock_auth_context(request: Request, auth_context=None):
            return SimpleNamespace(
                user=SimpleNamespace(id=1, username="admin", platform_role="platform_admin"),
                session=None,
                gitlab_access_token=None,
                gitlab_refresh_token=None,
            )
        app.dependency_overrides[require_authenticated_context] = mock_auth_context

    def tearDown(self):
        app.dependency_overrides.clear()
        if self._orig_key is not None:
            os.environ["CONFIG_ENCRYPTION_KEY"] = self._orig_key
        else:
            os.environ.pop("CONFIG_ENCRYPTION_KEY", None)
        get_settings.cache_clear()
        reset_runtime_config()

    def test_list_providers_empty(self):
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = []
        self.mock_db.execute = AsyncMock(return_value=mock_result)

        resp = self.client.get("/api/providers")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), [])

    def test_list_providers_returns_serialized(self):
        provider = _make_provider(is_default=True, api_key="encrypted-key")
        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [provider]
        self.mock_db.execute = AsyncMock(return_value=mock_result)

        resp = self.client.get("/api/providers")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["name"], "test-provider")
        self.assertTrue(data[0]["api_key_configured"])
        self.assertTrue(data[0]["is_default"])
        self.assertNotIn("api_key", data[0])


class ProviderCreateTests(unittest.TestCase):
    def setUp(self):
        self._orig_key = os.environ.get("CONFIG_ENCRYPTION_KEY")
        os.environ["CONFIG_ENCRYPTION_KEY"] = "unit-test-config-key"
        get_settings.cache_clear()
        reset_runtime_config()
        reset_runtime_config_sync_state()

        self.client = TestClient(app)
        self.mock_db = MagicMock()
        self.mock_db.execute = AsyncMock()
        self.mock_db.get = AsyncMock(return_value=None)
        self.mock_db.commit = AsyncMock()
        self.mock_db.flush = AsyncMock()
        self.mock_db.add = MagicMock()
        self.mock_db.refresh = AsyncMock()
        app.dependency_overrides[get_db] = lambda: self.mock_db

        async def mock_auth_context(request: Request, auth_context=None):
            return SimpleNamespace(
                user=SimpleNamespace(id=1, username="admin", platform_role="platform_admin"),
                session=None,
                gitlab_access_token=None,
                gitlab_refresh_token=None,
            )
        app.dependency_overrides[require_authenticated_context] = mock_auth_context

    def tearDown(self):
        app.dependency_overrides.clear()
        if self._orig_key is not None:
            os.environ["CONFIG_ENCRYPTION_KEY"] = self._orig_key
        else:
            os.environ.pop("CONFIG_ENCRYPTION_KEY", None)
        get_settings.cache_clear()
        reset_runtime_config()

    def test_create_provider_invalid_name(self):
        resp = self.client.post("/api/providers", json={
            "name": "invalid name with spaces",
            "base_url": "http://localhost:11434/v1",
            "model": "test-model",
        })
        self.assertEqual(resp.status_code, 422)

    def test_create_provider_invalid_base_url(self):
        resp = self.client.post("/api/providers", json={
            "name": "test",
            "base_url": "ftp://not-http",
            "model": "test-model",
        })
        self.assertEqual(resp.status_code, 422)

    def test_create_provider_max_turns_out_of_range(self):
        resp = self.client.post("/api/providers", json={
            "name": "test",
            "base_url": "http://localhost:11434/v1",
            "model": "test-model",
            "max_turns": 0,
        })
        self.assertEqual(resp.status_code, 422)

    def test_create_provider_duplicate_name_409(self):
        existing = _make_provider()
        mock_result_name = MagicMock()
        mock_result_name.scalar_one_or_none.return_value = existing

        self.mock_db.execute = AsyncMock(return_value=mock_result_name)

        resp = self.client.post("/api/providers", json={
            "name": "test-provider",
            "base_url": "http://localhost:11434/v1",
            "model": "test-model",
        })
        self.assertEqual(resp.status_code, 409)


class ProviderDeleteTests(unittest.TestCase):
    def setUp(self):
        self._orig_key = os.environ.get("CONFIG_ENCRYPTION_KEY")
        os.environ["CONFIG_ENCRYPTION_KEY"] = "unit-test-config-key"
        get_settings.cache_clear()
        reset_runtime_config()
        reset_runtime_config_sync_state()

        self.client = TestClient(app)
        self.mock_db = MagicMock()
        self.mock_db.execute = AsyncMock()
        self.mock_db.get = AsyncMock(return_value=None)
        self.mock_db.commit = AsyncMock()
        self.mock_db.flush = AsyncMock()
        self.mock_db.add = MagicMock()
        self.mock_db.refresh = AsyncMock()
        self.mock_db.delete = AsyncMock()
        app.dependency_overrides[get_db] = lambda: self.mock_db

        async def mock_auth_context(request: Request, auth_context=None):
            return SimpleNamespace(
                user=SimpleNamespace(id=1, username="admin", platform_role="platform_admin"),
                session=None,
                gitlab_access_token=None,
                gitlab_refresh_token=None,
            )
        app.dependency_overrides[require_authenticated_context] = mock_auth_context

    def tearDown(self):
        app.dependency_overrides.clear()
        if self._orig_key is not None:
            os.environ["CONFIG_ENCRYPTION_KEY"] = self._orig_key
        else:
            os.environ.pop("CONFIG_ENCRYPTION_KEY", None)
        get_settings.cache_clear()
        reset_runtime_config()

    def test_delete_nonexistent_404(self):
        self.mock_db.get = AsyncMock(return_value=None)
        resp = self.client.delete("/api/providers/999")
        self.assertEqual(resp.status_code, 404)

    def test_delete_last_provider_409(self):
        provider = _make_provider()
        self.mock_db.get = AsyncMock(return_value=provider)

        mock_count = MagicMock()
        mock_count.scalar.return_value = 1  # Only provider
        self.mock_db.execute = AsyncMock(return_value=mock_count)

        resp = self.client.delete("/api/providers/1")
        self.assertEqual(resp.status_code, 409)
        self.assertIn("only provider", resp.json()["detail"])


class ProviderSetDefaultTests(unittest.TestCase):
    def setUp(self):
        self._orig_key = os.environ.get("CONFIG_ENCRYPTION_KEY")
        os.environ["CONFIG_ENCRYPTION_KEY"] = "unit-test-config-key"
        get_settings.cache_clear()
        reset_runtime_config()
        reset_runtime_config_sync_state()

        self.client = TestClient(app)
        self.mock_db = MagicMock()
        self.mock_db.execute = AsyncMock()
        self.mock_db.get = AsyncMock(return_value=None)
        self.mock_db.commit = AsyncMock()
        self.mock_db.refresh = AsyncMock()
        app.dependency_overrides[get_db] = lambda: self.mock_db

        async def mock_auth_context(request: Request, auth_context=None):
            return SimpleNamespace(
                user=SimpleNamespace(id=1, username="admin", platform_role="platform_admin"),
                session=None,
                gitlab_access_token=None,
                gitlab_refresh_token=None,
            )
        app.dependency_overrides[require_authenticated_context] = mock_auth_context

    def tearDown(self):
        app.dependency_overrides.clear()
        if self._orig_key is not None:
            os.environ["CONFIG_ENCRYPTION_KEY"] = self._orig_key
        else:
            os.environ.pop("CONFIG_ENCRYPTION_KEY", None)
        get_settings.cache_clear()
        reset_runtime_config()

    def test_set_default_nonexistent_404(self):
        self.mock_db.get = AsyncMock(return_value=None)
        resp = self.client.post("/api/providers/999/set-default")
        self.assertEqual(resp.status_code, 404)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run tests**

Run: `cd backend && python -m pytest tests/unit/test_providers_api.py -v`
Expected: All tests pass.

- [ ] **Step 3: Commit**

```bash
git add backend/tests/unit/test_providers_api.py
git commit -m "test: add provider CRUD API unit tests"
```

---

### Task 8: Frontend — API Types + Functions

**Files:**
- Modify: `frontend/src/api/index.ts`

- [ ] **Step 1: Add AIProvider interface**

After the `Branch` interface (around line 160), add:

```typescript
export interface AIProvider {
  id: number
  name: string
  base_url: string
  api_key_configured: boolean
  model: string
  max_turns: number
  system_prompt: string | null
  is_default: boolean
  created_at: string
  updated_at: string
}

export interface CreateProviderRequest {
  name: string
  base_url: string
  api_key?: string
  model: string
  max_turns?: number
  system_prompt?: string
}

export interface UpdateProviderRequest {
  name?: string
  base_url?: string
  api_key?: string
  clear_api_key?: boolean
  model?: string
  max_turns?: number
  system_prompt?: string | null
  clear_system_prompt?: boolean
}
```

- [ ] **Step 2: Add `provider_id` and `provider_name` to Task interface**

In the `Task` interface (around line 134, before `created_at`), add:

```typescript
  provider_id: number | null
  provider_name?: string | null
```

- [ ] **Step 3: Add `provider_id` to CreateTaskRequest**

In `CreateTaskRequest` (around line 168), add:

```typescript
  provider_id?: number | null
```

- [ ] **Step 4: Add provider CRUD API functions**

After the `getBranches` function (around line 1016), add:

```typescript
export async function getProviders(): Promise<AIProvider[]> {
  const { data } = await api.get('/providers')
  return data
}

export async function getProvider(id: number): Promise<AIProvider> {
  const { data } = await api.get(`/providers/${id}`)
  return data
}

export async function createProvider(request: CreateProviderRequest): Promise<AIProvider> {
  const { data } = await api.post('/providers', request)
  return data
}

export async function updateProvider(id: number, request: UpdateProviderRequest): Promise<AIProvider> {
  const { data } = await api.patch(`/providers/${id}`, request)
  return data
}

export async function deleteProvider(id: number): Promise<void> {
  await api.delete(`/providers/${id}`)
}

export async function setDefaultProvider(id: number): Promise<AIProvider> {
  const { data } = await api.post(`/providers/${id}/set-default`)
  return data
}
```

- [ ] **Step 5: Build to verify types**

Run: `cd frontend && npm run build`
Expected: Build succeeds with no type errors.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/api/index.ts
git commit -m "feat: add AI provider types and API functions"
```

---

### Task 9: Frontend — i18n Keys

**Files:**
- Modify: `frontend/src/i18n/messages/en.ts`
- Modify: `frontend/src/i18n/messages/zh-CN.ts`

- [ ] **Step 1: Add provider i18n keys to English**

In the `config` section of `en.ts`, add a `providers` subsection:

```typescript
    providers: {
      title: 'AI Providers',
      subtitle: 'Manage AI model providers for task execution',
      create: 'Add Provider',
      edit: 'Edit Provider',
      name: 'Name',
      nameHint: 'Unique identifier (alphanumeric, hyphens, underscores)',
      baseUrl: 'Base URL',
      baseUrlHint: 'API endpoint URL (e.g. http://host.docker.internal:11434/v1)',
      model: 'Model',
      modelHint: 'Model identifier (e.g. claude-sonnet-4-20250514)',
      maxTurns: 'Max Turns',
      maxTurnsHint: 'Maximum agentic turns per task (1-1000)',
      apiKey: 'API Key',
      apiKeyHint: 'Leave blank to keep existing key',
      apiKeyConfigured: 'API key configured',
      apiKeyNotConfigured: 'No API key',
      systemPrompt: 'System Prompt',
      systemPromptHint: 'System instructions appended to each Claude CLI invocation',
      isDefault: 'Default',
      setDefault: 'Set as Default',
      deleteConfirm: 'Delete this provider?',
      deleteBlocked: 'Cannot delete — active tasks reference this provider',
      deleteLast: 'Cannot delete the only provider',
      systemDefault: 'System Default',
      providerLabel: 'AI Provider',
      selectProvider: 'Select a provider',
      created: 'Provider created',
      updated: 'Provider updated',
      deleted: 'Provider deleted',
      defaultSet: 'Default provider updated',
      movedNotice: 'AI provider settings have moved to the AI Providers tab.',
    },
```

Also add to the `taskView` section:

```typescript
    provider: 'AI Provider',
```

- [ ] **Step 2: Add provider i18n keys to Chinese**

Add the same structure in `zh-CN.ts`:

```typescript
    providers: {
      title: 'AI 模型服务',
      subtitle: '管理用于任务执行的 AI 模型服务',
      create: '添加服务',
      edit: '编辑服务',
      name: '名称',
      nameHint: '唯一标识符（字母数字、连字符、下划线）',
      baseUrl: '接口地址',
      baseUrlHint: 'API 接口地址（例如 http://host.docker.internal:11434/v1）',
      model: '模型',
      modelHint: '模型标识符（例如 claude-sonnet-4-20250514）',
      maxTurns: '最大轮次',
      maxTurnsHint: '每任务最大代理轮次（1-1000）',
      apiKey: 'API 密钥',
      apiKeyHint: '留空保持现有密钥',
      apiKeyConfigured: 'API 密钥已配置',
      apiKeyNotConfigured: '未配置 API 密钥',
      systemPrompt: '系统提示词',
      systemPromptHint: '附加到每次 Claude CLI 调用的系统指令',
      isDefault: '默认',
      setDefault: '设为默认',
      deleteConfirm: '确认删除此服务？',
      deleteBlocked: '无法删除 — 仍有活跃任务使用此服务',
      deleteLast: '无法删除唯一的服务',
      systemDefault: '系统默认',
      providerLabel: 'AI 模型服务',
      selectProvider: '选择服务',
      created: '服务已创建',
      updated: '服务已更新',
      deleted: '服务已删除',
      defaultSet: '默认服务已更新',
      movedNotice: 'AI 模型服务设置已移至「AI 模型服务」选项卡。',
    },
```

Also add to `taskView`:

```typescript
    provider: 'AI 模型服务',
```

- [ ] **Step 3: Build to verify**

Run: `cd frontend && npm run build`
Expected: Build succeeds.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/i18n/messages/en.ts frontend/src/i18n/messages/zh-CN.ts
git commit -m "feat: add AI provider i18n keys for en and zh-CN"
```

---

### Task 10: Frontend — AI Providers Config Panel

**Files:**
- Create: `frontend/src/components/config/AIProvidersPanel.vue`
- Modify: `frontend/src/views/Config.vue`
- Modify: `frontend/src/components/config/WorkerSettingsPanel.vue`

- [ ] **Step 1: Create AIProvidersPanel component**

Create `frontend/src/components/config/AIProvidersPanel.vue` with:

1. **Provider list** — NDataTable with columns: Name, Model, Base URL, Default (badge), System Prompt (truncated), Actions
2. **Add Provider button** — opens NDrawer with provider form
3. **Edit** — same drawer, pre-populated
4. **Delete** — NPopconfirm, calls deleteProvider API
5. **Set Default** — button in actions column

The component should:
- Fetch providers on mount via `getProviders()`
- Use `useMessage()` for notifications
- Drawer form with NForm for create/edit
- Validation rules matching backend (name pattern, URL prefix, max_turns range)
- API key field shows configured status badge when editing
- After CRUD operations, re-fetch the list

Key template structure:

```vue
<template>
  <n-space vertical :size="16">
    <n-card :title="t('config.providers.title')">
      <template #header-extra>
        <n-button type="primary" @click="openCreateDrawer">
          {{ t('config.providers.create') }}
        </n-button>
      </template>

      <n-data-table
        :columns="columns"
        :data="providers"
        :loading="loading"
      />
    </n-card>

    <n-drawer v-model:show="drawerVisible" :width="480">
      <n-drawer-content :title="isEditing ? t('config.providers.edit') : t('config.providers.create')">
        <!-- Provider form: name, base_url, model, max_turns, api_key, system_prompt -->
        <template #footer>
          <n-button type="primary" @click="saveProvider" :loading="saving">
            {{ t('common.save') }}
          </n-button>
        </template>
      </n-drawer-content>
    </n-drawer>
  </n-space>
</template>
```

Use the existing patterns from `WorkerSettingsPanel.vue` and `PromptTemplatesPanel` for form validation, API calls, and error handling.

- [ ] **Step 2: Add AI Providers tab to Config.vue**

In `frontend/src/views/Config.vue`, add a new tab-pane after the "worker" tab (around line 58):

```vue
            <n-tab-pane name="ai-providers" :tab="t('config.providers.title')">
              <AIProvidersPanel :is-mobile="isMobile" />
            </n-tab-pane>
```

Import the component in the script section:

```typescript
import AIProvidersPanel from '../components/config/AIProvidersPanel.vue'
```

- [ ] **Step 3: Remove AI provider fields from WorkerSettingsPanel**

In `frontend/src/components/config/WorkerSettingsPanel.vue`:

1. Replace the AI Provider form card (lines 4-113) with a simple info note:

```vue
    <n-card size="small">
      <n-alert type="info" :show-icon="true">
        {{ t('config.providers.movedNotice') }}
      </n-alert>
    </n-card>
```

2. Remove the AI-related form data (`aiFormValue`, `aiRules`), save handlers, and related imports that are no longer needed.

- [ ] **Step 4: Build to verify**

Run: `cd frontend && npm run build`
Expected: Build succeeds with no type errors.

- [ ] **Step 5: Commit**

```bash
git add frontend/src/components/config/AIProvidersPanel.vue frontend/src/views/Config.vue frontend/src/components/config/WorkerSettingsPanel.vue
git commit -m "feat: add AI Providers Config tab, remove from WorkerSettings"
```

---

### Task 11: Frontend — Provider Selector in Task Creation

**Files:**
- Modify: `frontend/src/views/IssueView.vue`
- Modify: `frontend/src/views/CreateTask.vue`

- [ ] **Step 1: Add provider selector to IssueView create-task form**

In `IssueView.vue`, in the create-task form section:

1. Import `getProviders` from the API:
```typescript
import { getProviders, type AIProvider } from '../api'
```

2. Add state:
```typescript
const providers = ref<AIProvider[]>([])
const selectedProviderId = ref<number | null>(null)
```

3. Fetch providers on mount:
```typescript
onMounted(async () => {
  // ...existing code...
  providers.value = await getProviders()
})
```

4. Add NSelect for provider before the submit button:
```vue
<n-form-item :label="t('config.providers.providerLabel')">
  <n-select
    v-model:value="selectedProviderId"
    :options="providerOptions"
    clearable
    :placeholder="t('config.providers.systemDefault')"
  />
</n-form-item>
```

5. Compute options:
```typescript
const providerOptions = computed(() =>
  providers.value.map(p => ({
    label: `${p.name} (${p.model})${p.is_default ? ' ★' : ''}`,
    value: p.id,
  }))
)
```

6. Pass `provider_id` in the create task request:
```typescript
provider_id: selectedProviderId.value,
```

- [ ] **Step 2: Add provider selector to CreateTask.vue**

Same pattern as IssueView — add `getProviders` import, state, fetch, NSelect, and include `provider_id` in the request body.

- [ ] **Step 3: Build to verify**

Run: `cd frontend && npm run build`
Expected: Build succeeds.

- [ ] **Step 4: Commit**

```bash
git add frontend/src/views/IssueView.vue frontend/src/views/CreateTask.vue
git commit -m "feat: add provider selector to task creation forms"
```

---

### Task 12: Frontend — Provider Display in TaskMetadataPanel

**Files:**
- Modify: `frontend/src/components/TaskMetadataPanel.vue`

- [ ] **Step 1: Add provider metadata row**

In `TaskMetadataPanel.vue`, add a new metadata row after the "Source" row (around line 51). Add after the retry source row:

```vue
    <div v-if="task.provider_name || task.provider_id" class="metadata-row">
      <span class="metadata-label">
        <n-icon size="14" class="metadata-label-icon"><ServerOutline /></n-icon>
        {{ t('taskView.provider') }}
      </span>
      <span class="metadata-value">
        {{ task.provider_name || t('config.providers.systemDefault') }}
      </span>
    </div>
```

Import `ServerOutline` from `@vicons/ionicons5`.

- [ ] **Step 2: Build to verify**

Run: `cd frontend && npm run build`
Expected: Build succeeds.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/components/TaskMetadataPanel.vue
git commit -m "feat: show AI provider name in task metadata panel"
```

---

### Task 13: Full Build + Backend Tests + Commit

**Files:** All modified files

- [ ] **Step 1: Run backend unit tests**

Run: `cd backend && python -m pytest tests/unit/ -v --tb=short`
Expected: All tests pass, including new `test_providers_api.py`.

- [ ] **Step 2: Run frontend build**

Run: `cd frontend && npm run build`
Expected: Build succeeds with no errors.

- [ ] **Step 3: Run frontend unit tests**

Run: `cd frontend && npx vitest run --reporter=verbose`
Expected: All existing tests pass. Some may need minor updates if they snapshot task objects (add `provider_id: null, provider_name: null` to test fixtures).

- [ ] **Step 4: Fix any test failures**

Address any failures from steps 1-3. Common fixes:
- Task test fixtures need `provider_id: null` added
- Frontend mock data needs `provider_id` and `provider_name` fields

- [ ] **Step 5: Final commit**

```bash
git add -A
git commit -m "feat: multi AI provider + system prompt support

- New ai_providers table with CRUD API
- Task creation supports provider_id selection
- Worker resolves provider per task (task → default → legacy)
- System prompt passed via APPEND_SYSTEM_PROMPT to Claude CLI
- New AI Providers Config tab in frontend
- Provider selector in task creation forms
- TaskMetadataPanel shows provider name
- Legacy runtime config API syncs with default provider
- Unit tests for provider CRUD"
```

---

## Dependency Graph

```
Task 1 (Migration) ─────────────────────────┐
Task 2 (Model) ←── Task 1                   │
Task 3 (API) ←── Task 2                     │
Task 4 (Worker) ←── Task 2                  │
Task 5 (Task Creation) ←── Task 2, Task 3   │
Task 6 (Legacy Compat) ←── Task 3           │
Task 7 (Backend Tests) ←── Task 3           │
Task 8 (Frontend Types) ←── Task 5          │
Task 9 (i18n) ── independent                │
Task 10 (Config Panel) ←── Task 8, Task 9   │
Task 11 (Task Forms) ←── Task 8, Task 9     │
Task 12 (Metadata) ←── Task 8, Task 9       │
Task 13 (Verification) ←── ALL              │
```

Recommended execution order: 1 → 2 → 3+4 (parallel) → 5+6 (parallel) → 7 → 8+9 (parallel) → 10+11+12 (parallel) → 13
