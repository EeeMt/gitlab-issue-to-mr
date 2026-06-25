# Worker Profiles Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add configurable worker profiles, issue-level default worker/provider settings, and task-level worker runtime snapshots.

**Architecture:** Add worker profile tables and a focused backend domain module that resolves defaults, validates profiles, snapshots runtime fields, and decrypts snapshot env for execution. Task creation/editing and CI auto-repair consume issue defaults and persist task snapshots; worker execution reads snapshots instead of mutable profile rows. Frontend adds profile management plus worker/provider defaults on issue and task surfaces.

**Tech Stack:** FastAPI, Pydantic, SQLAlchemy async, Alembic, pytest, Vue 3, Naive UI, vue-i18n, Vitest.

---

## File Structure

Backend:

- Create `backend/alembic/versions/052_worker_profiles.py` for schema and migration seed from legacy worker config.
- Modify `backend/app/models.py` with `WorkerProfile`, `WorkerProfileEnvironmentVariable`, `TaskWorkerProfileSnapshot`, `Issue.default_worker_profile_id`, `Issue.default_provider_id`, and `Task.worker_profile_id`.
- Create `backend/app/core/worker_profiles.py` for validation, serialization, default resolution, snapshot creation/rebuild, and runtime snapshot loading.
- Create `backend/app/api/worker_profiles.py` for admin profile CRUD and duplicate/default/disable actions.
- Modify `backend/app/main.py` to register the worker profile router.
- Modify `backend/app/api/issues.py` to read/write issue default worker/provider.
- Modify `backend/app/api/task_schemas.py` and `backend/app/api/tasks.py` to accept `worker_profile_id`, resolve defaults, persist snapshots, and serialize worker metadata.
- Modify `backend/app/core/ci_failure_collector.py` or the current CI auto-repair task creation path to use issue default worker/provider and fail closed when invalid.
- Modify `backend/app/core/worker_runtime.py` so `build_container_volumes()` can accept snapshot mounts.
- Modify `backend/app/core/worker_task_lifecycle.py` so `create_execute_container()` reads `TaskWorkerRuntime` from snapshot and uses snapshot image/env/mounts/scripts.
- Add/modify targeted tests under `backend/tests/unit/`.

Frontend:

- Modify `frontend/src/api/index.ts` with worker profile, issue default, task worker fields, and API functions.
- Modify `frontend/src/components/config/WorkerSettingsPanel.vue` and `frontend/src/components/config/WorkerSettingsPanel.spec.ts` into a profile manager while preserving compact mount/env rows.
- Modify `frontend/src/views/CreateIssue.vue` and `frontend/src/views/CreateIssue.spec.ts` to set default worker/provider.
- Modify `frontend/src/views/IssueView.vue` and `frontend/src/views/IssueView.spec.ts` to edit issue defaults.
- Modify `frontend/src/components/TaskFormDrawer.vue` and `frontend/src/components/TaskFormDrawer.spec.ts` to select worker and use worker run-instruction defaults.
- Modify `frontend/src/components/TaskMetadataPanel.vue` and related specs to show worker name/image.
- Modify `frontend/src/i18n/messages/en.ts` and `frontend/src/i18n/messages/zh-CN.ts`.

Docs:

- Update `docs/worker-volume-mounts.md` after runtime path changes.

---

### Task 1: Add Backend Models and Migration

**Files:**
- Create: `backend/alembic/versions/052_worker_profiles.py`
- Modify: `backend/app/models.py`
- Test: `backend/tests/unit/test_worker_profiles_migration.py`

- [ ] **Step 1: Write migration tests**

Create `backend/tests/unit/test_worker_profiles_migration.py` with tests that inspect the migration source and pin the important schema/seed choices:

```python
from pathlib import Path


MIGRATION = (
    Path(__file__).resolve().parents[2]
    / "alembic"
    / "versions"
    / "052_worker_profiles.py"
)


def test_worker_profiles_migration_defines_expected_tables_and_columns():
    content = MIGRATION.read_text(encoding="utf-8")

    assert 'revision: str = "052_worker_profiles"' in content
    assert 'down_revision: Union[str, None] = "051_fix_retry_source_ondelete"' in content
    assert 'op.create_table("worker_profiles"' in content
    assert 'op.create_table("worker_profile_environment_variables"' in content
    assert 'op.create_table("task_worker_profile_snapshots"' in content
    assert 'op.add_column("issues", sa.Column("default_worker_profile_id"' in content
    assert 'op.add_column("issues", sa.Column("default_provider_id"' in content
    assert 'op.add_column("tasks", sa.Column("worker_profile_id"' in content


def test_worker_profiles_migration_seeds_default_worker_from_legacy_config():
    content = MIGRATION.read_text(encoding="utf-8")

    assert "Default Worker" in content
    assert "worker_image" in content
    assert "worker_volume_mounts" in content
    assert "worker_pre_script" in content
    assert "worker_post_script" in content
    assert "default_execute_run_instruction_template" in content
    assert "default_plan_run_instruction_template" in content
    assert "ci_auto_repair_run_instruction_template" in content
    assert "worker_environment_variables" in content
    assert "default_provider_id" in content
```

- [ ] **Step 2: Run migration tests to verify they fail**

Run:

```bash
backend/.venv/bin/python -m pytest backend/tests/unit/test_worker_profiles_migration.py -q
```

Expected: FAIL because `052_worker_profiles.py` does not exist.

- [ ] **Step 3: Add SQLAlchemy models**

Modify `backend/app/models.py`.

Add imports if needed:

```python
from sqlalchemy import JSON
```

Add relationships to `AIProvider`, `Issue`, and `Task` where those classes are defined:

```python
# In AIProvider
default_for_issues: Mapped[list["Issue"]] = relationship(
    "Issue",
    back_populates="default_provider",
    foreign_keys="Issue.default_provider_id",
)
```

```python
# In Issue
default_worker_profile_id: Mapped[int | None] = mapped_column(
    Integer,
    ForeignKey("worker_profiles.id", ondelete="SET NULL"),
    nullable=True,
    index=True,
)
default_provider_id: Mapped[int | None] = mapped_column(
    Integer,
    ForeignKey("ai_providers.id", ondelete="SET NULL"),
    nullable=True,
    index=True,
)

default_worker_profile: Mapped["WorkerProfile | None"] = relationship(
    "WorkerProfile",
    foreign_keys=[default_worker_profile_id],
)
default_provider: Mapped["AIProvider | None"] = relationship(
    "AIProvider",
    foreign_keys=[default_provider_id],
    back_populates="default_for_issues",
)
```

```python
# In Task
worker_profile_id: Mapped[int | None] = mapped_column(
    Integer,
    ForeignKey("worker_profiles.id", ondelete="SET NULL"),
    nullable=True,
    index=True,
)

worker_profile: Mapped["WorkerProfile | None"] = relationship(
    "WorkerProfile",
    foreign_keys=[worker_profile_id],
)
worker_profile_snapshot: Mapped["TaskWorkerProfileSnapshot | None"] = relationship(
    "TaskWorkerProfileSnapshot",
    back_populates="task",
    uselist=False,
    cascade="all, delete-orphan",
)
```

Add new model classes near `WorkerEnvironmentVariable`:

```python
class WorkerProfile(Base):
    """Editable worker runtime profile."""

    __tablename__ = "worker_profiles"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    name: Mapped[str] = mapped_column(String(100), nullable=False, unique=True)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    is_default: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    image: Mapped[str] = mapped_column(String(255), nullable=False)
    volume_mounts: Mapped[list[dict]] = mapped_column(JSON, nullable=False, default=list)
    pre_script: Mapped[str] = mapped_column(Text, nullable=False, default="")
    post_script: Mapped[str] = mapped_column(Text, nullable=False, default="")
    default_execute_run_instruction_template: Mapped[str] = mapped_column(Text, nullable=False)
    default_plan_run_instruction_template: Mapped[str] = mapped_column(Text, nullable=False)
    ci_auto_repair_run_instruction_template: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=utcnow,
        onupdate=utcnow,
    )

    environment_variables: Mapped[list["WorkerProfileEnvironmentVariable"]] = relationship(
        "WorkerProfileEnvironmentVariable",
        back_populates="profile",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index(
            "uq_worker_profiles_default",
            "is_default",
            unique=True,
            postgresql_where=text("is_default = true"),
        ),
    )
```

```python
class WorkerProfileEnvironmentVariable(Base):
    """Custom environment variable scoped to one worker profile."""

    __tablename__ = "worker_profile_environment_variables"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    worker_profile_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("worker_profiles.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    key: Mapped[str] = mapped_column(String(255), nullable=False)
    value: Mapped[str] = mapped_column(Text, nullable=False)
    is_secret: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=utcnow,
        onupdate=utcnow,
    )

    profile: Mapped[WorkerProfile] = relationship(
        "WorkerProfile",
        back_populates="environment_variables",
    )

    __table_args__ = (
        Index("uq_worker_profile_environment_key", "worker_profile_id", "key", unique=True),
    )
```

```python
class TaskWorkerProfileSnapshot(Base):
    """Task-level immutable worker runtime configuration snapshot."""

    __tablename__ = "task_worker_profile_snapshots"

    task_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("tasks.id", ondelete="CASCADE"),
        primary_key=True,
    )
    worker_profile_id: Mapped[int | None] = mapped_column(
        Integer,
        ForeignKey("worker_profiles.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    profile_name: Mapped[str] = mapped_column(String(100), nullable=False)
    image: Mapped[str] = mapped_column(String(255), nullable=False)
    volume_mounts: Mapped[list[dict]] = mapped_column(JSON, nullable=False, default=list)
    environment_variables: Mapped[list[dict]] = mapped_column(JSON, nullable=False, default=list)
    pre_script: Mapped[str] = mapped_column(Text, nullable=False, default="")
    post_script: Mapped[str] = mapped_column(Text, nullable=False, default="")
    default_execute_run_instruction_template: Mapped[str] = mapped_column(Text, nullable=False)
    default_plan_run_instruction_template: Mapped[str] = mapped_column(Text, nullable=False)
    ci_auto_repair_run_instruction_template: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime,
        nullable=False,
        default=utcnow,
        onupdate=utcnow,
    )

    task: Mapped[Task] = relationship("Task", back_populates="worker_profile_snapshot")
    worker_profile: Mapped[WorkerProfile | None] = relationship("WorkerProfile")
```

- [ ] **Step 4: Add migration**

Create `backend/alembic/versions/052_worker_profiles.py`:

```python
"""add worker profiles

Revision ID: 052_worker_profiles
Revises: 051_fix_retry_source_ondelete
Create Date: 2026-06-25
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy import table, column


revision: str = "052_worker_profiles"
down_revision: Union[str, None] = "051_fix_retry_source_ondelete"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def _config_value(conn, key: str, default):
    result = conn.execute(
        sa.text("SELECT value FROM system_config WHERE key = :key"),
        {"key": key},
    ).scalar()
    return default if result is None else result


def upgrade() -> None:
    op.create_table(
        "worker_profiles",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(length=100), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("image", sa.String(length=255), nullable=False),
        sa.Column("volume_mounts", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
        sa.Column("pre_script", sa.Text(), nullable=False, server_default=""),
        sa.Column("post_script", sa.Text(), nullable=False, server_default=""),
        sa.Column("default_execute_run_instruction_template", sa.Text(), nullable=False),
        sa.Column("default_plan_run_instruction_template", sa.Text(), nullable=False),
        sa.Column("ci_auto_repair_run_instruction_template", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("name", name="uq_worker_profiles_name"),
    )
    op.create_index(
        "uq_worker_profiles_default",
        "worker_profiles",
        ["is_default"],
        unique=True,
        postgresql_where=sa.text("is_default = true"),
    )

    op.create_table(
        "worker_profile_environment_variables",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("worker_profile_id", sa.Integer(), nullable=False),
        sa.Column("key", sa.String(length=255), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("is_secret", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["worker_profile_id"],
            ["worker_profiles.id"],
            ondelete="CASCADE",
        ),
    )
    op.create_index(
        "uq_worker_profile_environment_key",
        "worker_profile_environment_variables",
        ["worker_profile_id", "key"],
        unique=True,
    )
    op.create_index(
        "ix_worker_profile_environment_variables_worker_profile_id",
        "worker_profile_environment_variables",
        ["worker_profile_id"],
    )

    op.add_column(
        "issues",
        sa.Column("default_worker_profile_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "issues",
        sa.Column("default_provider_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "tasks",
        sa.Column("worker_profile_id", sa.Integer(), nullable=True),
    )

    op.create_foreign_key(
        "issues_default_worker_profile_id_fkey",
        "issues",
        "worker_profiles",
        ["default_worker_profile_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "issues_default_provider_id_fkey",
        "issues",
        "ai_providers",
        ["default_provider_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_foreign_key(
        "tasks_worker_profile_id_fkey",
        "tasks",
        "worker_profiles",
        ["worker_profile_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_issues_default_worker_profile_id", "issues", ["default_worker_profile_id"])
    op.create_index("ix_issues_default_provider_id", "issues", ["default_provider_id"])
    op.create_index("ix_tasks_worker_profile_id", "tasks", ["worker_profile_id"])

    op.create_table(
        "task_worker_profile_snapshots",
        sa.Column("task_id", sa.Integer(), primary_key=True),
        sa.Column("worker_profile_id", sa.Integer(), nullable=True),
        sa.Column("profile_name", sa.String(length=100), nullable=False),
        sa.Column("image", sa.String(length=255), nullable=False),
        sa.Column("volume_mounts", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
        sa.Column("environment_variables", sa.JSON(), nullable=False, server_default=sa.text("'[]'::json")),
        sa.Column("pre_script", sa.Text(), nullable=False, server_default=""),
        sa.Column("post_script", sa.Text(), nullable=False, server_default=""),
        sa.Column("default_execute_run_instruction_template", sa.Text(), nullable=False),
        sa.Column("default_plan_run_instruction_template", sa.Text(), nullable=False),
        sa.Column("ci_auto_repair_run_instruction_template", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["task_id"], ["tasks.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["worker_profile_id"], ["worker_profiles.id"], ondelete="SET NULL"),
    )
    op.create_index(
        "ix_task_worker_profile_snapshots_worker_profile_id",
        "task_worker_profile_snapshots",
        ["worker_profile_id"],
    )

    conn = op.get_bind()
    default_provider_id = conn.execute(
        sa.text("SELECT id FROM ai_providers WHERE is_default = true AND is_disabled = false LIMIT 1")
    ).scalar()

    settings_defaults = {
        "worker_image": "codify-worker:latest",
        "worker_volume_mounts": "",
        "worker_pre_script": "",
        "worker_post_script": "",
        "default_execute_run_instruction_template": "",
        "default_plan_run_instruction_template": "",
        "ci_auto_repair_run_instruction_template": "",
    }
    worker_profile_table = table(
        "worker_profiles",
        column("name"),
        column("description"),
        column("enabled"),
        column("is_default"),
        column("image"),
        column("volume_mounts"),
        column("pre_script"),
        column("post_script"),
        column("default_execute_run_instruction_template"),
        column("default_plan_run_instruction_template"),
        column("ci_auto_repair_run_instruction_template"),
    )
    import json

    raw_mounts = _config_value(conn, "worker_volume_mounts", settings_defaults["worker_volume_mounts"])
    try:
        mounts = json.loads(raw_mounts) if raw_mounts else []
        if not isinstance(mounts, list):
            mounts = []
    except json.JSONDecodeError:
        mounts = []

    conn.execute(
        worker_profile_table.insert().values(
            name="Default Worker",
            description="Migrated default worker profile",
            enabled=True,
            is_default=True,
            image=_config_value(conn, "worker_image", settings_defaults["worker_image"]),
            volume_mounts=mounts,
            pre_script=_config_value(conn, "worker_pre_script", ""),
            post_script=_config_value(conn, "worker_post_script", ""),
            default_execute_run_instruction_template=_config_value(
                conn,
                "default_execute_run_instruction_template",
                "",
            ),
            default_plan_run_instruction_template=_config_value(
                conn,
                "default_plan_run_instruction_template",
                "",
            ),
            ci_auto_repair_run_instruction_template=_config_value(
                conn,
                "ci_auto_repair_run_instruction_template",
                "",
            ),
        )
    )
    default_worker_id = conn.execute(
        sa.text("SELECT id FROM worker_profiles WHERE is_default = true LIMIT 1")
    ).scalar()

    conn.execute(
        sa.text(
            "INSERT INTO worker_profile_environment_variables "
            "(worker_profile_id, key, value, is_secret, created_at, updated_at) "
            "SELECT :profile_id, key, value, is_secret, created_at, updated_at "
            "FROM worker_environment_variables"
        ),
        {"profile_id": default_worker_id},
    )
    conn.execute(
        sa.text("UPDATE issues SET default_worker_profile_id = :profile_id"),
        {"profile_id": default_worker_id},
    )
    if default_provider_id is not None:
        conn.execute(
            sa.text("UPDATE issues SET default_provider_id = :provider_id"),
            {"provider_id": default_provider_id},
        )


def downgrade() -> None:
    op.drop_table("task_worker_profile_snapshots")
    op.drop_index("ix_tasks_worker_profile_id", table_name="tasks")
    op.drop_constraint("tasks_worker_profile_id_fkey", "tasks", type_="foreignkey")
    op.drop_column("tasks", "worker_profile_id")
    op.drop_index("ix_issues_default_provider_id", table_name="issues")
    op.drop_index("ix_issues_default_worker_profile_id", table_name="issues")
    op.drop_constraint("issues_default_provider_id_fkey", "issues", type_="foreignkey")
    op.drop_constraint("issues_default_worker_profile_id_fkey", "issues", type_="foreignkey")
    op.drop_column("issues", "default_provider_id")
    op.drop_column("issues", "default_worker_profile_id")
    op.drop_index("ix_worker_profile_environment_variables_worker_profile_id", table_name="worker_profile_environment_variables")
    op.drop_index("uq_worker_profile_environment_key", table_name="worker_profile_environment_variables")
    op.drop_table("worker_profile_environment_variables")
    op.drop_index("uq_worker_profiles_default", table_name="worker_profiles")
    op.drop_table("worker_profiles")
```

- [ ] **Step 5: Run migration tests**

Run:

```bash
backend/.venv/bin/python -m pytest backend/tests/unit/test_worker_profiles_migration.py -q
```

Expected: PASS.

- [ ] **Step 6: Commit schema work**

```bash
git add backend/app/models.py backend/alembic/versions/052_worker_profiles.py backend/tests/unit/test_worker_profiles_migration.py
git commit -m "feat: add worker profile schema"
```

---

### Task 2: Add Worker Profile Domain Module and API

**Files:**
- Create: `backend/app/core/worker_profiles.py`
- Create: `backend/app/api/worker_profiles.py`
- Modify: `backend/app/main.py`
- Test: `backend/tests/unit/test_worker_profiles_core.py`
- Test: `backend/tests/unit/test_worker_profiles_api.py`

- [ ] **Step 1: Write core tests**

Create `backend/tests/unit/test_worker_profiles_core.py`:

```python
import pytest

from app.core.worker_profiles import (
    WorkerProfileValidationError,
    build_worker_profile_environment_map,
    parse_worker_profile_mounts,
    select_snapshot_run_instruction_template,
    validate_worker_profile_mounts,
)


def test_validate_worker_profile_mounts_normalizes_mode():
    mounts = validate_worker_profile_mounts([
        {"host_path": "/cache/m2", "container_path": "/home/codify/.m2", "mode": "rw"},
        {"host_path": "/certs/ca.crt", "container_path": "/etc/ssl/certs/custom-ca.crt"},
    ])

    assert mounts == [
        {"host_path": "/cache/m2", "container_path": "/home/codify/.m2", "mode": "rw"},
        {"host_path": "/certs/ca.crt", "container_path": "/etc/ssl/certs/custom-ca.crt", "mode": "ro"},
    ]


def test_validate_worker_profile_mounts_rejects_bad_mode():
    with pytest.raises(WorkerProfileValidationError, match="mount mode"):
        validate_worker_profile_mounts([
            {"host_path": "/cache", "container_path": "/cache", "mode": "bad"},
        ])


def test_parse_worker_profile_mounts_accepts_legacy_json_string():
    assert parse_worker_profile_mounts('[{"host_path":"/a","container_path":"/b","mode":"rw"}]') == [
        {"host_path": "/a", "container_path": "/b", "mode": "rw"},
    ]


def test_build_worker_profile_environment_map_decrypts_secret(monkeypatch):
    rows = [
        {"key": "PLAIN_VALUE", "value": "plain", "is_secret": False},
        {"key": "SECRET_VALUE", "value": "encrypted", "is_secret": True},
    ]
    monkeypatch.setattr(
        "app.core.worker_profiles.decrypt_config_secret",
        lambda value: f"decrypted:{value}",
    )

    assert build_worker_profile_environment_map(rows) == {
        "PLAIN_VALUE": "plain",
        "SECRET_VALUE": "decrypted:encrypted",
    }


def test_select_snapshot_run_instruction_template_uses_ci_template_for_ci_repair():
    snapshot = type(
        "Snapshot",
        (),
        {
            "default_execute_run_instruction_template": "execute {{user_prompt}}",
            "default_plan_run_instruction_template": "plan {{user_prompt}}",
            "ci_auto_repair_run_instruction_template": "repair {{issue_title}}",
        },
    )()

    assert select_snapshot_run_instruction_template(
        snapshot,
        task_mode="execute",
        trigger_source="ci_auto_repair",
    ) == "repair {{issue_title}}"
```

- [ ] **Step 2: Run core tests to verify they fail**

Run:

```bash
backend/.venv/bin/python -m pytest backend/tests/unit/test_worker_profiles_core.py -q
```

Expected: FAIL because `app.core.worker_profiles` does not exist.

- [ ] **Step 3: Implement `backend/app/core/worker_profiles.py`**

Create the module:

```python
"""Worker profile validation, serialization, default resolution, and task snapshots."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.config import get_effective_settings
from app.core.config_crypto import decrypt_config_secret, encrypt_config_secret
from app.core.task_prompt import (
    TaskPromptValidationError,
    validate_run_instruction_template,
)
from app.core.worker_environment_variables import validate_worker_environment_variable_key
from app.models import (
    AIProvider,
    Issue,
    Task,
    TaskWorkerProfileSnapshot,
    WorkerProfile,
    WorkerProfileEnvironmentVariable,
)


class WorkerProfileValidationError(ValueError):
    """Raised when a worker profile payload is invalid."""


@dataclass(frozen=True)
class TaskWorkerRuntime:
    """Resolved task worker runtime loaded from a task snapshot."""

    image: str
    volume_mounts: list[dict[str, str]]
    environment: dict[str, str]
    pre_script: str
    post_script: str


def validate_worker_profile_mounts(raw_mounts: Any) -> list[dict[str, str]]:
    """Validate and normalize worker profile mount entries."""
    if raw_mounts in (None, ""):
        return []
    if not isinstance(raw_mounts, list):
        raise WorkerProfileValidationError("volume_mounts must be a list")

    normalized: list[dict[str, str]] = []
    seen_container_paths: set[str] = set()
    for mount in raw_mounts:
        if not isinstance(mount, Mapping):
            raise WorkerProfileValidationError("volume mount entries must be objects")
        host_path = str(mount.get("host_path") or "").strip()
        container_path = str(mount.get("container_path") or "").strip()
        mode = str(mount.get("mode") or "ro").strip()
        if not host_path or not container_path:
            raise WorkerProfileValidationError("volume mounts require host_path and container_path")
        if mode not in {"ro", "rw"}:
            raise WorkerProfileValidationError("volume mount mode must be ro or rw")
        if container_path in seen_container_paths:
            raise WorkerProfileValidationError(f"duplicate container mount path: {container_path}")
        seen_container_paths.add(container_path)
        normalized.append(
            {"host_path": host_path, "container_path": container_path, "mode": mode}
        )
    return normalized


def parse_worker_profile_mounts(value: Any) -> list[dict[str, str]]:
    """Parse legacy JSON string or profile JSON list into normalized mounts."""
    if isinstance(value, str):
        if not value.strip():
            return []
        try:
            value = json.loads(value)
        except json.JSONDecodeError as exc:
            raise WorkerProfileValidationError("volume_mounts must be valid JSON") from exc
    return validate_worker_profile_mounts(value)


def validate_profile_templates(
    *,
    execute_template: str,
    plan_template: str,
    ci_template: str,
) -> tuple[str, str, str]:
    """Validate and normalize the three worker run-instruction templates."""
    try:
        return (
            validate_run_instruction_template(execute_template),
            validate_run_instruction_template(plan_template),
            validate_run_instruction_template(ci_template),
        )
    except TaskPromptValidationError as exc:
        raise WorkerProfileValidationError(str(exc)) from exc


def serialize_profile_environment_variable_for_api(
    row: WorkerProfileEnvironmentVariable,
) -> dict[str, Any]:
    return {
        "id": row.id,
        "key": row.key,
        "value": None if row.is_secret else row.value,
        "is_secret": row.is_secret,
        "value_configured": bool(row.value),
    }


def _profile_env_to_snapshot(row: WorkerProfileEnvironmentVariable) -> dict[str, Any]:
    return {
        "key": row.key,
        "value": row.value,
        "is_secret": row.is_secret,
    }


def build_worker_profile_environment_map(rows: Iterable[Mapping[str, Any]]) -> dict[str, str]:
    """Build container env from snapshot environment rows."""
    env: dict[str, str] = {}
    for row in rows:
        key = validate_worker_environment_variable_key(str(row["key"]))
        value = str(row.get("value") or "")
        if bool(row.get("is_secret")):
            value = decrypt_config_secret(value)
        env[key] = value
    return env


async def get_default_worker_profile(db: AsyncSession) -> WorkerProfile | None:
    result = await db.execute(
        select(WorkerProfile)
        .where(WorkerProfile.is_default == True, WorkerProfile.enabled == True)
        .options(selectinload(WorkerProfile.environment_variables))
    )
    return result.scalar_one_or_none()


async def get_default_provider(db: AsyncSession) -> AIProvider | None:
    result = await db.execute(
        select(AIProvider).where(AIProvider.is_default == True, AIProvider.is_disabled == False)
    )
    return result.scalar_one_or_none()


async def resolve_worker_profile_for_issue(
    db: AsyncSession,
    issue: Issue,
    explicit_worker_profile_id: int | None = None,
    *,
    allow_system_default: bool = True,
) -> WorkerProfile:
    """Resolve explicit, issue default, then system default worker profile."""
    candidate_id = explicit_worker_profile_id or getattr(issue, "default_worker_profile_id", None)
    profile: WorkerProfile | None = None
    if candidate_id is not None:
        profile = await db.get(
            WorkerProfile,
            candidate_id,
            options=[selectinload(WorkerProfile.environment_variables)],
        )
    elif allow_system_default:
        profile = await get_default_worker_profile(db)

    if profile is None:
        raise WorkerProfileValidationError("No worker profile is configured for this issue")
    if not profile.enabled:
        raise WorkerProfileValidationError(f"Worker profile '{profile.name}' is disabled")
    return profile


async def resolve_provider_for_issue(
    db: AsyncSession,
    issue: Issue,
    explicit_provider_id: int | None = None,
    *,
    allow_system_default: bool = True,
) -> AIProvider:
    """Resolve explicit, issue default, then system default provider."""
    candidate_id = explicit_provider_id or getattr(issue, "default_provider_id", None)
    provider = await db.get(AIProvider, candidate_id) if candidate_id is not None else None
    if provider is None and allow_system_default:
        provider = await get_default_provider(db)
    if provider is None:
        raise WorkerProfileValidationError("No enabled AI provider is configured for this issue")
    if provider.is_disabled:
        raise WorkerProfileValidationError(f"AI provider '{provider.name}' is disabled")
    return provider


def snapshot_from_profile(task: Task, profile: WorkerProfile) -> TaskWorkerProfileSnapshot:
    """Build a task snapshot from a loaded worker profile."""
    snapshot = TaskWorkerProfileSnapshot(
        task_id=task.id,
        worker_profile_id=profile.id,
        profile_name=profile.name,
        image=profile.image,
        volume_mounts=list(profile.volume_mounts or []),
        environment_variables=[
            _profile_env_to_snapshot(row) for row in profile.environment_variables
        ],
        pre_script=profile.pre_script or "",
        post_script=profile.post_script or "",
        default_execute_run_instruction_template=profile.default_execute_run_instruction_template,
        default_plan_run_instruction_template=profile.default_plan_run_instruction_template,
        ci_auto_repair_run_instruction_template=profile.ci_auto_repair_run_instruction_template,
    )
    return snapshot


async def replace_task_worker_snapshot(
    db: AsyncSession,
    task: Task,
    profile: WorkerProfile,
) -> TaskWorkerProfileSnapshot:
    """Replace one task's worker snapshot with a profile-derived snapshot."""
    existing = await db.get(TaskWorkerProfileSnapshot, task.id)
    if existing is not None:
        await db.delete(existing)
        await db.flush()
    snapshot = snapshot_from_profile(task, profile)
    db.add(snapshot)
    task.worker_profile_id = profile.id
    await db.flush()
    return snapshot


def select_snapshot_run_instruction_template(
    snapshot: TaskWorkerProfileSnapshot,
    *,
    task_mode: str,
    trigger_source: str = "manual",
) -> str:
    if trigger_source == "ci_auto_repair":
        return validate_run_instruction_template(snapshot.ci_auto_repair_run_instruction_template)
    if task_mode == "plan":
        return validate_run_instruction_template(snapshot.default_plan_run_instruction_template)
    return validate_run_instruction_template(snapshot.default_execute_run_instruction_template)


async def load_task_worker_runtime(db: AsyncSession, task: Task) -> TaskWorkerRuntime:
    snapshot = await db.get(TaskWorkerProfileSnapshot, task.id)
    if snapshot is None:
        raise WorkerProfileValidationError(f"Task {task.id} has no worker profile snapshot")
    return TaskWorkerRuntime(
        image=snapshot.image,
        volume_mounts=parse_worker_profile_mounts(snapshot.volume_mounts),
        environment=build_worker_profile_environment_map(snapshot.environment_variables),
        pre_script=snapshot.pre_script or "",
        post_script=snapshot.post_script or "",
    )


async def replace_profile_environment_variables(
    db: AsyncSession,
    profile: WorkerProfile,
    items: list[Mapping[str, Any]],
) -> None:
    existing = {row.key: row for row in profile.environment_variables}
    seen: set[str] = set()
    for item in items:
        key = validate_worker_environment_variable_key(str(item.get("key") or "").strip())
        if key in seen:
            raise WorkerProfileValidationError(f"Duplicate worker environment variable key: {key}")
        seen.add(key)
        is_secret = bool(item.get("is_secret"))
        value = str(item.get("value") or "")
        row = existing.get(key)
        if is_secret and value == "" and row is not None and row.is_secret:
            stored_value = row.value
        elif is_secret:
            if value == "":
                raise WorkerProfileValidationError(f"Secret worker environment variable {key} needs a value")
            stored_value = encrypt_config_secret(value)
        else:
            stored_value = value
        if row is None:
            db.add(
                WorkerProfileEnvironmentVariable(
                    worker_profile_id=profile.id,
                    key=key,
                    value=stored_value,
                    is_secret=is_secret,
                )
            )
        else:
            row.value = stored_value
            row.is_secret = is_secret
    for row in list(profile.environment_variables):
        if row.key not in seen:
            await db.delete(row)
    await db.flush()


async def set_default_worker_profile(db: AsyncSession, profile: WorkerProfile) -> None:
    if not profile.enabled:
        raise WorkerProfileValidationError("Disabled worker profiles cannot be default")
    await db.execute(update(WorkerProfile).values(is_default=False))
    profile.is_default = True
    await db.flush()
```

- [ ] **Step 4: Write API tests**

Create `backend/tests/unit/test_worker_profiles_api.py`:

```python
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.worker_profiles import (
    WorkerProfileCreateRequest,
    WorkerProfileEnvironmentVariableRequest,
    create_worker_profile,
    set_default_worker_profile_endpoint,
)


@pytest.mark.asyncio
async def test_create_worker_profile_rejects_duplicate_env_keys():
    db = MagicMock()
    db.add = MagicMock()
    db.flush = AsyncMock()

    request = WorkerProfileCreateRequest(
        name="Java Worker",
        image="codify-worker-java:latest",
        volume_mounts=[],
        environment_variables=[
            WorkerProfileEnvironmentVariableRequest(key="MAVEN_OPTS", value="-Xmx1g"),
            WorkerProfileEnvironmentVariableRequest(key="MAVEN_OPTS", value="-Xmx2g"),
        ],
        default_execute_run_instruction_template="Execute {{user_prompt}}",
        default_plan_run_instruction_template="Plan {{user_prompt}}",
        ci_auto_repair_run_instruction_template="Repair {{issue_title}}",
    )

    with pytest.raises(Exception) as exc:
        await create_worker_profile(request, db=db, _current_user=SimpleNamespace(id=1))
    assert "Duplicate worker environment variable key" in str(exc.value)


@pytest.mark.asyncio
async def test_set_default_rejects_disabled_profile():
    profile = MagicMock()
    profile.enabled = False
    profile.name = "Disabled Worker"

    db = MagicMock()
    db.get = AsyncMock(return_value=profile)

    with pytest.raises(Exception) as exc:
        await set_default_worker_profile_endpoint(
            profile_id=10,
            db=db,
            _current_user=SimpleNamespace(id=1),
        )
    assert "Disabled worker profiles cannot be default" in str(exc.value)
```

- [ ] **Step 5: Run API tests to verify they fail**

Run:

```bash
backend/.venv/bin/python -m pytest backend/tests/unit/test_worker_profiles_api.py -q
```

Expected: FAIL because API module does not exist.

- [ ] **Step 6: Implement `backend/app/api/worker_profiles.py`**

Create the router:

```python
"""Worker profile management API."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.task_prompt import (
    BUILT_IN_CI_AUTO_REPAIR_RUN_INSTRUCTION_TEMPLATE,
    BUILT_IN_EXECUTE_RUN_INSTRUCTION_TEMPLATE,
    BUILT_IN_PLAN_RUN_INSTRUCTION_TEMPLATE,
)
from app.core.worker_profiles import (
    WorkerProfileValidationError,
    parse_worker_profile_mounts,
    replace_profile_environment_variables,
    serialize_profile_environment_variable_for_api,
    set_default_worker_profile,
    validate_profile_templates,
)
from app.database import get_db
from app.dependencies.auth import require_admin_user
from app.models import WorkerProfile


router = APIRouter(prefix="/worker-profiles", tags=["worker-profiles"])


class WorkerProfileEnvironmentVariableRequest(BaseModel):
    id: int | None = None
    key: str
    value: str = ""
    is_secret: bool = False


class WorkerProfileRequestBase(BaseModel):
    name: str | None = None
    description: str | None = None
    enabled: bool | None = None
    image: str | None = None
    volume_mounts: list[dict[str, Any]] | None = None
    environment_variables: list[WorkerProfileEnvironmentVariableRequest] | None = None
    pre_script: str | None = None
    post_script: str | None = None
    default_execute_run_instruction_template: str | None = None
    default_plan_run_instruction_template: str | None = None
    ci_auto_repair_run_instruction_template: str | None = None


class WorkerProfileCreateRequest(WorkerProfileRequestBase):
    name: str
    image: str
    volume_mounts: list[dict[str, Any]] = Field(default_factory=list)
    environment_variables: list[WorkerProfileEnvironmentVariableRequest] = Field(default_factory=list)
    default_execute_run_instruction_template: str = BUILT_IN_EXECUTE_RUN_INSTRUCTION_TEMPLATE
    default_plan_run_instruction_template: str = BUILT_IN_PLAN_RUN_INSTRUCTION_TEMPLATE
    ci_auto_repair_run_instruction_template: str = BUILT_IN_CI_AUTO_REPAIR_RUN_INSTRUCTION_TEMPLATE


class WorkerProfileUpdateRequest(WorkerProfileRequestBase):
    pass


def _http_profile_error(exc: WorkerProfileValidationError) -> HTTPException:
    return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc))


def _serialize_profile(profile: WorkerProfile) -> dict[str, Any]:
    return {
        "id": profile.id,
        "name": profile.name,
        "description": profile.description,
        "enabled": profile.enabled,
        "is_default": profile.is_default,
        "image": profile.image,
        "volume_mounts": profile.volume_mounts or [],
        "environment_variables": [
            serialize_profile_environment_variable_for_api(row)
            for row in profile.environment_variables
        ],
        "pre_script": profile.pre_script,
        "post_script": profile.post_script,
        "default_execute_run_instruction_template": profile.default_execute_run_instruction_template,
        "default_plan_run_instruction_template": profile.default_plan_run_instruction_template,
        "ci_auto_repair_run_instruction_template": profile.ci_auto_repair_run_instruction_template,
        "created_at": profile.created_at,
        "updated_at": profile.updated_at,
    }


async def _load_profile_or_404(db: AsyncSession, profile_id: int) -> WorkerProfile:
    profile = await db.get(
        WorkerProfile,
        profile_id,
        options=[selectinload(WorkerProfile.environment_variables)],
    )
    if profile is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Worker profile not found")
    return profile


@router.get("")
async def list_worker_profiles(
    db: AsyncSession = Depends(get_db),
    _current_user=Depends(require_admin_user),
):
    result = await db.execute(
        select(WorkerProfile)
        .options(selectinload(WorkerProfile.environment_variables))
        .order_by(WorkerProfile.is_default.desc(), WorkerProfile.name.asc())
    )
    return [_serialize_profile(profile) for profile in result.scalars().all()]


@router.post("")
async def create_worker_profile(
    request: WorkerProfileCreateRequest,
    db: AsyncSession = Depends(get_db),
    _current_user=Depends(require_admin_user),
):
    try:
        name = request.name.strip()
        if not name:
            raise WorkerProfileValidationError("Worker profile name cannot be blank")
        image = request.image.strip()
        if not image:
            raise WorkerProfileValidationError("Worker profile image cannot be blank")
        execute_template, plan_template, ci_template = validate_profile_templates(
            execute_template=request.default_execute_run_instruction_template,
            plan_template=request.default_plan_run_instruction_template,
            ci_template=request.ci_auto_repair_run_instruction_template,
        )
        profile = WorkerProfile(
            name=name,
            description=request.description,
            enabled=True if request.enabled is None else request.enabled,
            is_default=False,
            image=image,
            volume_mounts=parse_worker_profile_mounts(request.volume_mounts),
            pre_script=request.pre_script or "",
            post_script=request.post_script or "",
            default_execute_run_instruction_template=execute_template,
            default_plan_run_instruction_template=plan_template,
            ci_auto_repair_run_instruction_template=ci_template,
        )
        db.add(profile)
        await db.flush()
        await replace_profile_environment_variables(
            db,
            profile,
            [item.model_dump() for item in request.environment_variables],
        )
        await db.commit()
        await db.refresh(profile, attribute_names=["environment_variables"])
        return _serialize_profile(profile)
    except WorkerProfileValidationError as exc:
        await db.rollback()
        raise _http_profile_error(exc) from exc


@router.patch("/{profile_id}")
async def update_worker_profile(
    profile_id: int,
    request: WorkerProfileUpdateRequest,
    db: AsyncSession = Depends(get_db),
    _current_user=Depends(require_admin_user),
):
    profile = await _load_profile_or_404(db, profile_id)
    try:
        fields = request.model_fields_set
        if "name" in fields and request.name is not None:
            profile.name = request.name.strip()
            if not profile.name:
                raise WorkerProfileValidationError("Worker profile name cannot be blank")
        if "description" in fields:
            profile.description = request.description
        if "enabled" in fields and request.enabled is not None:
            if profile.is_default and request.enabled is False:
                raise WorkerProfileValidationError("Default worker profile cannot be disabled")
            profile.enabled = request.enabled
        if "image" in fields and request.image is not None:
            profile.image = request.image.strip()
            if not profile.image:
                raise WorkerProfileValidationError("Worker profile image cannot be blank")
        if "volume_mounts" in fields and request.volume_mounts is not None:
            profile.volume_mounts = parse_worker_profile_mounts(request.volume_mounts)
        if "pre_script" in fields:
            profile.pre_script = request.pre_script or ""
        if "post_script" in fields:
            profile.post_script = request.post_script or ""
        if {
            "default_execute_run_instruction_template",
            "default_plan_run_instruction_template",
            "ci_auto_repair_run_instruction_template",
        } & fields:
            execute_template, plan_template, ci_template = validate_profile_templates(
                execute_template=(
                    request.default_execute_run_instruction_template
                    if request.default_execute_run_instruction_template is not None
                    else profile.default_execute_run_instruction_template
                ),
                plan_template=(
                    request.default_plan_run_instruction_template
                    if request.default_plan_run_instruction_template is not None
                    else profile.default_plan_run_instruction_template
                ),
                ci_template=(
                    request.ci_auto_repair_run_instruction_template
                    if request.ci_auto_repair_run_instruction_template is not None
                    else profile.ci_auto_repair_run_instruction_template
                ),
            )
            profile.default_execute_run_instruction_template = execute_template
            profile.default_plan_run_instruction_template = plan_template
            profile.ci_auto_repair_run_instruction_template = ci_template
        if "environment_variables" in fields and request.environment_variables is not None:
            await replace_profile_environment_variables(
                db,
                profile,
                [item.model_dump() for item in request.environment_variables],
            )
        await db.commit()
        await db.refresh(profile, attribute_names=["environment_variables"])
        return _serialize_profile(profile)
    except WorkerProfileValidationError as exc:
        await db.rollback()
        raise _http_profile_error(exc) from exc


@router.post("/{profile_id}/set-default")
async def set_default_worker_profile_endpoint(
    profile_id: int,
    db: AsyncSession = Depends(get_db),
    _current_user=Depends(require_admin_user),
):
    profile = await _load_profile_or_404(db, profile_id)
    try:
        await set_default_worker_profile(db, profile)
        await db.commit()
        await db.refresh(profile, attribute_names=["environment_variables"])
        return _serialize_profile(profile)
    except WorkerProfileValidationError as exc:
        await db.rollback()
        raise _http_profile_error(exc) from exc


@router.post("/{profile_id}/disable")
async def disable_worker_profile(
    profile_id: int,
    db: AsyncSession = Depends(get_db),
    _current_user=Depends(require_admin_user),
):
    profile = await _load_profile_or_404(db, profile_id)
    if profile.is_default:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Default worker profile cannot be disabled",
        )
    profile.enabled = False
    await db.commit()
    await db.refresh(profile, attribute_names=["environment_variables"])
    return _serialize_profile(profile)


@router.post("/{profile_id}/duplicate")
async def duplicate_worker_profile(
    profile_id: int,
    db: AsyncSession = Depends(get_db),
    _current_user=Depends(require_admin_user),
):
    source = await _load_profile_or_404(db, profile_id)
    copy = WorkerProfile(
        name=f"{source.name} Copy",
        description=source.description,
        enabled=True,
        is_default=False,
        image=source.image,
        volume_mounts=list(source.volume_mounts or []),
        pre_script=source.pre_script,
        post_script=source.post_script,
        default_execute_run_instruction_template=source.default_execute_run_instruction_template,
        default_plan_run_instruction_template=source.default_plan_run_instruction_template,
        ci_auto_repair_run_instruction_template=source.ci_auto_repair_run_instruction_template,
    )
    db.add(copy)
    await db.flush()
    for row in source.environment_variables:
        db.add(
            WorkerProfileEnvironmentVariable(
                worker_profile_id=copy.id,
                key=row.key,
                value=row.value,
                is_secret=row.is_secret,
            )
        )
    await db.commit()
    await db.refresh(copy, attribute_names=["environment_variables"])
    return _serialize_profile(copy)
```

- [ ] **Step 7: Register router**

Modify imports in `backend/app/main.py`:

```python
from app.api import (
    admin_users,
    announcement,
    auth,
    ci_failures,
    config,
    config_integration,
    config_runtime,
    containers,
    issues,
    maintenance,
    mattermost,
    oidc,
    project_webhooks,
    projects,
    prompt_templates,
    providers,
    stats,
    tasks,
    usage_limits,
    webhook_handler,
    worker_profiles,
)
```

Add router registration near other config/admin routes:

```python
app.include_router(
    worker_profiles.router,
    prefix="/api",
    tags=["worker-profiles"],
    dependencies=[Depends(require_admin_user)],
)
```

- [ ] **Step 8: Run profile tests**

Run:

```bash
backend/.venv/bin/python -m pytest backend/tests/unit/test_worker_profiles_core.py backend/tests/unit/test_worker_profiles_api.py -q
```

Expected: PASS.

- [ ] **Step 9: Commit profile API**

```bash
git add backend/app/core/worker_profiles.py backend/app/api/worker_profiles.py backend/app/main.py backend/tests/unit/test_worker_profiles_core.py backend/tests/unit/test_worker_profiles_api.py
git commit -m "feat: add worker profile API"
```

---

### Task 3: Add Issue Defaults and Task Snapshot Integration

**Files:**
- Modify: `backend/app/api/issues.py`
- Modify: `backend/app/api/task_schemas.py`
- Modify: `backend/app/api/tasks.py`
- Modify: `backend/app/core/task_prompt.py`
- Test: `backend/tests/unit/test_issue_worker_defaults.py`
- Test: `backend/tests/unit/test_task_worker_profile_selection.py`

- [ ] **Step 1: Write issue default tests**

Create `backend/tests/unit/test_issue_worker_defaults.py`:

```python
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.issues import CreateIssueRequest, create_issue


@pytest.mark.asyncio
async def test_create_issue_persists_current_default_worker_and_provider():
    request = CreateIssueRequest(
        title="Add profile defaults",
        project_id=100,
        description="Use issue defaults",
    )

    db = MagicMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.refresh = AsyncMock()
    current_user = SimpleNamespace(id=7, username="alice")

    default_worker = SimpleNamespace(id=11)
    default_provider = SimpleNamespace(id=22)

    with patch("app.api.issues.get_default_worker_profile", new=AsyncMock(return_value=default_worker)), \
         patch("app.api.issues.get_default_provider", new=AsyncMock(return_value=default_provider)), \
         patch("app.api.issues.build_issue_workspace_paths", return_value=None):
        await create_issue(body=request, db=db, current_user=current_user)

    issue = db.add.call_args.args[0]
    assert issue.default_worker_profile_id == 11
    assert issue.default_provider_id == 22
```

- [ ] **Step 2: Write task selection tests**

Create `backend/tests/unit/test_task_worker_profile_selection.py`:

```python
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.api.tasks import CreateTaskRequest, create_task
from app.dependencies.project_access import ProjectAccessScope
from app.models import TaskStatus


@pytest.mark.asyncio
async def test_create_task_uses_issue_default_worker_and_provider_when_omitted():
    request = CreateTaskRequest(
        issue_id=1,
        user_prompt="Implement worker profiles",
        priority=1,
    )
    issue = MagicMock()
    issue.id = 1
    issue.project_id = 101
    issue.description = "Implement worker profiles"
    issue.status = "open"
    issue.default_worker_profile_id = 33
    issue.default_provider_id = 44

    worker_profile = MagicMock()
    worker_profile.id = 33
    worker_profile.name = "Java Worker"
    worker_profile.enabled = True
    worker_profile.default_execute_run_instruction_template = "Execute {{user_prompt}}"
    worker_profile.default_plan_run_instruction_template = "Plan {{user_prompt}}"
    worker_profile.ci_auto_repair_run_instruction_template = "Repair {{issue_title}}"

    provider = MagicMock()
    provider.id = 44
    provider.is_disabled = False

    db = MagicMock()
    db.add = MagicMock()
    db.commit = AsyncMock()
    db.flush = AsyncMock()
    db.get = AsyncMock(return_value=issue)

    async def refresh(task):
        task.id = 88
        task.status = TaskStatus.PENDING
        task.created_at = datetime(2026, 6, 25, 9, 0, 0)
        task.updated_at = datetime(2026, 6, 25, 9, 0, 0)

    db.refresh = AsyncMock(side_effect=refresh)
    access_scope = ProjectAccessScope(is_unrestricted=True, accessible_projects=[])
    current_user = SimpleNamespace(id=7, gitlab_user_id=77, username="alice", display_name=None, email=None)

    with patch("app.api.tasks.resolve_worker_profile_for_issue", new=AsyncMock(return_value=worker_profile)), \
         patch("app.api.tasks.resolve_provider_for_issue", new=AsyncMock(return_value=provider)), \
         patch("app.api.tasks.replace_task_worker_snapshot", new=AsyncMock(return_value=worker_profile)), \
         patch("app.api.tasks.select_snapshot_run_instruction_template", return_value="Execute {{user_prompt}}"), \
         patch("app.api.tasks.get_project_metadata", new=AsyncMock(return_value={})), \
         patch("app.api.tasks.get_usage_quota_service", return_value=MagicMock(raise_if_over_limit=AsyncMock())):
        await create_task(request=request, db=db, current_user=current_user, access_scope=access_scope)

    task = db.add.call_args.args[0]
    assert task.worker_profile_id == 33
    assert task.provider_id == 44


@pytest.mark.asyncio
async def test_create_task_rejects_disabled_issue_default_worker():
    request = CreateTaskRequest(issue_id=1, user_prompt="x", priority=1)
    issue = MagicMock(id=1, project_id=101, description="x", status="open")
    db = MagicMock()
    db.get = AsyncMock(return_value=issue)
    access_scope = ProjectAccessScope(is_unrestricted=True, accessible_projects=[])

    with patch(
        "app.api.tasks.resolve_worker_profile_for_issue",
        new=AsyncMock(side_effect=ValueError("Worker profile 'Old' is disabled")),
    ):
        with pytest.raises(Exception) as exc:
            await create_task(
                request=request,
                db=db,
                current_user=SimpleNamespace(id=7),
                access_scope=access_scope,
            )
    assert "disabled" in str(exc.value)
```

- [ ] **Step 3: Run tests to verify they fail**

Run:

```bash
backend/.venv/bin/python -m pytest backend/tests/unit/test_issue_worker_defaults.py backend/tests/unit/test_task_worker_profile_selection.py -q
```

Expected: FAIL because APIs do not yet use worker defaults.

- [ ] **Step 4: Update task schemas**

Modify `backend/app/api/task_schemas.py`:

```python
class UpdateTaskRequest(BaseModel):
    user_prompt: str | None = None
    priority: int | None = None
    provider_id: int | None = None
    worker_profile_id: int | None = None
    require_changes: bool | None = None
    task_mode: Literal["execute", "plan"] | None = None
    run_instruction_template: str | None = Field(
        default=None, max_length=MAX_RUN_INSTRUCTION_TEMPLATE_LENGTH
    )
```

Update docstring to say `worker_profile_id` may be `null` to restore the issue default.

Modify `CreateTaskRequest`:

```python
class CreateTaskRequest(BaseModel):
    issue_id: int
    user_prompt: str | None = None
    priority: int = 0
    delay_seconds: int | None = None
    scheduled_datetime: datetime | None = None
    provider_id: int | None = None
    worker_profile_id: int | None = None
    require_changes: bool | None = True
    task_mode: Literal["execute", "plan"] = "execute"
    run_instruction_template: str | None = Field(
        default=None, max_length=MAX_RUN_INSTRUCTION_TEMPLATE_LENGTH
    )
```

- [ ] **Step 5: Update issue API**

Modify `backend/app/api/issues.py`.

Add imports:

```python
from app.core.worker_profiles import get_default_provider, get_default_worker_profile
from app.models import AIProvider, WorkerProfile
```

Add request fields:

```python
class CreateIssueRequest(BaseModel):
    title: str
    description: str | None = None
    project_id: int
    base_branch: str | None = None
    target_branch: str | None = None
    delete_branch_on_close: bool = True
    ci_auto_repair_enabled: bool = False
    default_worker_profile_id: int | None = None
    default_provider_id: int | None = None


class UpdateIssueRequest(BaseModel):
    title: str | None = None
    description: str | None = None
    status: str | None = None
    ci_auto_repair_enabled: bool | None = None
    default_worker_profile_id: int | None = None
    default_provider_id: int | None = None
```

Add helper:

```python
async def _resolve_issue_default_worker_id(db: AsyncSession, explicit_id: int | None) -> int | None:
    if explicit_id is not None:
        profile = await db.get(WorkerProfile, explicit_id)
        if profile is None or not profile.enabled:
            raise HTTPException(status_code=422, detail="Default worker profile is not available")
        return profile.id
    profile = await get_default_worker_profile(db)
    return profile.id if profile else None


async def _resolve_issue_default_provider_id(db: AsyncSession, explicit_id: int | None) -> int | None:
    if explicit_id is not None:
        provider = await db.get(AIProvider, explicit_id)
        if provider is None or provider.is_disabled:
            raise HTTPException(status_code=422, detail="Default AI provider is not available")
        return provider.id
    provider = await get_default_provider(db)
    return provider.id if provider else None
```

Update `_serialize_issue()`:

```python
"default_worker_profile_id": issue.default_worker_profile_id,
"default_provider_id": issue.default_provider_id,
"default_worker_profile_name": (
    issue.default_worker_profile.name if getattr(issue, "default_worker_profile", None) else None
),
"default_provider_name": (
    issue.default_provider.name if getattr(issue, "default_provider", None) else None
),
```

Update `create_issue()` before constructing `Issue`:

```python
default_worker_profile_id = await _resolve_issue_default_worker_id(
    db,
    body.default_worker_profile_id,
)
default_provider_id = await _resolve_issue_default_provider_id(
    db,
    body.default_provider_id,
)
```

Set fields on `Issue`:

```python
default_worker_profile_id=default_worker_profile_id,
default_provider_id=default_provider_id,
```

Update `get_issue()` and `update_issue()` query options:

```python
.options(
    selectinload(Issue.tasks),
    selectinload(Issue.default_worker_profile),
    selectinload(Issue.default_provider),
)
```

Update `update_issue()`:

```python
if "default_worker_profile_id" in body.model_fields_set:
    issue.default_worker_profile_id = await _resolve_issue_default_worker_id(
        db,
        body.default_worker_profile_id,
    )
if "default_provider_id" in body.model_fields_set:
    issue.default_provider_id = await _resolve_issue_default_provider_id(
        db,
        body.default_provider_id,
    )
```

- [ ] **Step 6: Update task create/edit**

Modify `backend/app/api/tasks.py`.

Add imports:

```python
from app.core.worker_profiles import (
    WorkerProfileValidationError,
    replace_task_worker_snapshot,
    resolve_provider_for_issue,
    resolve_worker_profile_for_issue,
    select_snapshot_run_instruction_template,
)
```

In `create_task()`, remove the old "provider_id is required" block. Replace with:

```python
try:
    worker_profile = await resolve_worker_profile_for_issue(
        db,
        issue,
        request.worker_profile_id,
    )
    provider = await resolve_provider_for_issue(
        db,
        issue,
        request.provider_id,
    )
except WorkerProfileValidationError as exc:
    raise HTTPException(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        detail=str(exc),
    ) from exc
```

Set task fields:

```python
provider_id=provider.id,
worker_profile_id=worker_profile.id,
```

After `await db.flush()` and before prompt rendering:

```python
snapshot = await replace_task_worker_snapshot(db, task, worker_profile)
template = request.run_instruction_template
if template is None:
    template = select_snapshot_run_instruction_template(
        snapshot,
        task_mode=task.task_mode,
        trigger_source=task.trigger_source or "manual",
    )
```

In `update_task()`, when `"worker_profile_id"` or `"provider_id"` is in `updated_fields`, resolve against the issue:

```python
issue = await db.get(Issue, task.issue_id)
if issue is None:
    raise HTTPException(status_code=404, detail="Issue not found")

if "worker_profile_id" in updated_fields:
    try:
        worker_profile = await resolve_worker_profile_for_issue(
            db,
            issue,
            request.worker_profile_id,
        )
    except WorkerProfileValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    task.worker_profile_id = worker_profile.id
    snapshot = await replace_task_worker_snapshot(db, task, worker_profile)
else:
    snapshot = await db.get(TaskWorkerProfileSnapshot, task.id)
```

For provider update:

```python
if "provider_id" in updated_fields:
    try:
        provider = await resolve_provider_for_issue(db, issue, request.provider_id)
    except WorkerProfileValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    task.provider_id = provider.id
```

Update prompt template fallback:

```python
if template is None:
    if snapshot is None:
        raise HTTPException(status_code=422, detail="Task has no worker profile snapshot")
    template = select_snapshot_run_instruction_template(
        snapshot,
        task_mode=task.task_mode or "execute",
        trigger_source=task.trigger_source or "manual",
    )
```

Include `"worker_profile_id"` in `render_context_changed`.

- [ ] **Step 7: Update task serialization**

In `_serialize_task()` inside `backend/app/api/tasks.py`, include:

```python
"worker_profile_id": task.worker_profile_id,
"worker_profile_name": (
    task.worker_profile_snapshot.profile_name
    if getattr(task, "worker_profile_snapshot", None)
    else (task.worker_profile.name if getattr(task, "worker_profile", None) else None)
),
"worker_image": (
    task.worker_profile_snapshot.image
    if getattr(task, "worker_profile_snapshot", None)
    else None
),
"worker_snapshot_created_at": (
    task.worker_profile_snapshot.created_at.isoformat()
    if getattr(task, "worker_profile_snapshot", None) and task.worker_profile_snapshot.created_at
    else None
),
```

Add `selectinload(Task.worker_profile_snapshot)` and `selectinload(Task.worker_profile)` to the `select(Task)` statements used by `get_task()`, `list_tasks()`, `get_task_with_access_check()`, and `update_task()` in `backend/app/api/tasks.py`.

- [ ] **Step 8: Run backend task/issue tests**

Run:

```bash
backend/.venv/bin/python -m pytest backend/tests/unit/test_issue_worker_defaults.py backend/tests/unit/test_task_worker_profile_selection.py backend/tests/unit/test_task_analytics_api.py::test_create_task_persists_manual_initiator_metadata -q
```

Expected: PASS.

- [ ] **Step 9: Commit task/issue integration**

```bash
git add backend/app/api/issues.py backend/app/api/task_schemas.py backend/app/api/tasks.py backend/tests/unit/test_issue_worker_defaults.py backend/tests/unit/test_task_worker_profile_selection.py
git commit -m "feat: apply worker profiles to issues and tasks"
```

---

### Task 4: Wire Worker Runtime to Task Snapshots

**Files:**
- Modify: `backend/app/core/worker_runtime.py`
- Modify: `backend/app/core/worker_task_lifecycle.py`
- Test: `backend/tests/unit/test_worker_profile_runtime.py`

- [ ] **Step 1: Write runtime tests**

Create `backend/tests/unit/test_worker_profile_runtime.py`:

```python
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.worker_runtime import build_container_volumes
from app.core.worker_task_lifecycle import create_execute_container


def test_build_container_volumes_uses_snapshot_mounts_last(tmp_path):
    settings = SimpleNamespace(worker_workspace_host_path="", worker_volume_mounts_parsed=[])
    issue = SimpleNamespace(id=1, session_storage_path="")
    task = SimpleNamespace(id=2)

    volumes = build_container_volumes(
        settings,
        issue,
        task=task,
        custom_mounts=[
            {"host_path": str(tmp_path / "cache"), "container_path": "/cache", "mode": "rw"},
        ],
    )

    assert volumes[str(tmp_path / "cache")] == {"bind": "/cache", "mode": "rw"}


@pytest.mark.asyncio
async def test_create_execute_container_uses_snapshot_runtime(tmp_path):
    task = MagicMock()
    task.id = 12
    task.project_id = 100
    task.ci_failure_run_id = None
    task.trigger_source = "manual"
    task.rendered_prompt = "Prompt"
    issue = MagicMock()
    issue.merge_request_iid = None
    issue.merge_request_url = None
    issue.target_branch = "main"

    worker = MagicMock()
    worker.gitlab.ensure_project_label = MagicMock()
    worker._create_mr_if_needed = MagicMock(return_value=(None, None))
    worker._write_previous_task_summaries_file = AsyncMock()
    worker._prepare_container_inputs = AsyncMock(return_value=({"TASK_ID": "12"}, "main"))
    worker._build_container_volumes = MagicMock(return_value={"/cache": {"bind": "/cache", "mode": "rw"}})
    worker._get_container_name = MagicMock(return_value="codify-12-issue1")
    worker.docker.pull_image = MagicMock()
    worker.docker.create_container = MagicMock(return_value=SimpleNamespace(id="container-1"))

    runtime = SimpleNamespace(
        image="custom-worker:latest",
        volume_mounts=[{"host_path": "/cache", "container_path": "/cache", "mode": "rw"}],
        environment={"CUSTOM_ENV": "value"},
        pre_script="echo pre",
        post_script="echo post",
    )
    settings = SimpleNamespace(worker_skip_image_pull=False, worker_network="bridge")
    db = MagicMock()
    db.commit = AsyncMock()
    db.get = AsyncMock(return_value=None)

    with patch("app.core.worker_task_lifecycle.load_task_worker_runtime", new=AsyncMock(return_value=runtime)), \
         patch("app.core.worker_task_lifecycle.build_issue_workspace_paths", return_value=SimpleNamespace(runtime_path=str(tmp_path))), \
         patch("app.core.worker_task_lifecycle.materialize_task_prompt"), \
         patch("app.core.worker_task_lifecycle.materialize_worker_custom_scripts"):
        container = await create_execute_container(
            worker,
            db,
            settings=settings,
            task=task,
            issue=issue,
            sudo_gl=None,
        )

    assert container.id == "container-1"
    worker.docker.pull_image.assert_called_once_with("custom-worker:latest", force=False)
    worker.docker.create_container.assert_called_once()
    assert worker.docker.create_container.call_args.kwargs["image"] == "custom-worker:latest"
```

- [ ] **Step 2: Run runtime tests to verify they fail**

Run:

```bash
backend/.venv/bin/python -m pytest backend/tests/unit/test_worker_profile_runtime.py -q
```

Expected: FAIL because runtime functions do not accept snapshot mounts/runtime.

- [ ] **Step 3: Update `build_container_volumes()`**

Modify signature in `backend/app/core/worker_runtime.py`:

```python
def build_container_volumes(
    settings: Any,
    issue: Issue | None = None,
    *,
    task: Task | None = None,
    custom_mounts: list[dict] | None = None,
) -> dict:
```

Replace the custom mount loop:

```python
for mount in custom_mounts if custom_mounts is not None else settings.worker_volume_mounts_parsed:
    host_path = mount.get("host_path")
    container_path = mount.get("container_path")
    mode = mount.get("mode", "ro")
    if host_path and container_path:
        volumes[host_path] = {"bind": container_path, "mode": mode}
```

- [ ] **Step 4: Add snapshot script materialization helper**

Modify `backend/app/core/worker_runtime.py`:

```python
def materialize_worker_custom_scripts_from_snapshot(
    runtime_path: str | os.PathLike[str],
    *,
    pre_script: str = "",
    post_script: str = "",
) -> None:
    runtime_dir = Path(runtime_path)
    runtime_dir.mkdir(parents=True, exist_ok=True)
    script_specs = (
        (pre_script, runtime_dir / _WORKER_PRE_SCRIPT_FILENAME),
        (post_script, runtime_dir / _WORKER_POST_SCRIPT_FILENAME),
    )
    for script_content, script_path in script_specs:
        if not isinstance(script_content, str) or not script_content.strip():
            script_path.unlink(missing_ok=True)
            continue
        script_text = script_content if script_content.endswith("\n") else f"{script_content}\n"
        script_path.write_text(script_text, encoding="utf-8")
        script_path.chmod(0o700)
```

- [ ] **Step 5: Update `create_execute_container()`**

Modify imports in `backend/app/core/worker_task_lifecycle.py`:

```python
from app.core.worker_profiles import load_task_worker_runtime
from app.core.worker_runtime import (
    materialize_task_prompt,
    materialize_worker_custom_scripts_from_snapshot,
)
```

Inside `create_execute_container()` after `task_id = task.id`:

```python
worker_runtime = await load_task_worker_runtime(db, task)
```

Replace image usage:

```python
if not settings.worker_skip_image_pull:
    try:
        worker.docker.pull_image(worker_runtime.image, force=False)
    except Exception as e:
        logger.warning(f"Failed to pull image: {e}, using existing local image if available")
```

Replace custom script materialization:

```python
materialize_worker_custom_scripts_from_snapshot(
    workspace_paths.runtime_path,
    pre_script=worker_runtime.pre_script,
    post_script=worker_runtime.post_script,
)
```

Pass env/mounts:

```python
environment, _target_branch = await worker._prepare_container_inputs(
    db,
    task,
    issue,
    mr_iid,
    custom_environment=worker_runtime.environment,
)
volumes = worker._build_container_volumes(
    settings,
    issue,
    task=task,
    custom_mounts=worker_runtime.volume_mounts,
)
container = worker.docker.create_container(
    image=worker_runtime.image,
    command="",
    environment=environment,
    volumes=volumes if volumes else None,
    network=settings.worker_network,
    name=container_name,
)
```

Update `prepare_container_inputs()` in both `backend/app/core/worker_task_lifecycle.py` and `backend/app/core/worker.py` compatibility wrapper to accept `custom_environment`:

```python
async def prepare_container_inputs(
    worker,
    db: AsyncSession,
    task: Task,
    issue: Issue | None,
    mr_iid: int | None,
    *,
    custom_environment: dict[str, str] | None = None,
):
    target_branch = issue.target_branch if issue else None
    provider = await worker._resolve_provider(db, task)
    custom_environment_rows = await list_worker_environment_variables(db)
    persisted_environment = build_worker_environment_map(custom_environment_rows)
    merged_environment = {**persisted_environment, **(custom_environment or {})}
    author_name, author_email = await worker._resolve_commit_author(db, task)
    environment = worker._build_container_env(
        task,
        issue,
        mr_iid,
        target_branch,
        provider=provider,
        author_name=author_name,
        author_email=author_email,
        custom_environment=merged_environment,
    )
```

This preserves legacy global worker env temporarily and lets snapshot env override it for new tasks.

- [ ] **Step 6: Run runtime tests**

Run:

```bash
backend/.venv/bin/python -m pytest backend/tests/unit/test_worker_profile_runtime.py backend/tests/unit/test_worker_coverage.py -k "custom_scripts or container_volumes" -q
```

Expected: PASS.

- [ ] **Step 7: Commit runtime wiring**

```bash
git add backend/app/core/worker_runtime.py backend/app/core/worker_task_lifecycle.py backend/app/core/worker.py backend/tests/unit/test_worker_profile_runtime.py
git commit -m "feat: run workers from profile snapshots"
```

---

### Task 5: Wire CI Auto-Repair to Issue Defaults

**Files:**
- Modify: `backend/app/core/ci_failure_collector.py`
- Modify: `backend/app/api/tasks.py`
- Test: `backend/tests/unit/test_ci_auto_repair_worker_defaults.py`

- [ ] **Step 1: Write CI default test**

Create `backend/tests/unit/test_ci_auto_repair_worker_defaults.py`:

```python
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


@pytest.mark.asyncio
async def test_process_ci_failure_run_uses_issue_default_worker_and_provider(tmp_path):
    from app.core.ci_failure_collector import process_ci_failure_run

    issue = MagicMock()
    issue.id = 1
    issue.project_id = 100
    issue.default_worker_profile_id = 11
    issue.default_provider_id = 22
    issue.ci_auto_repair_enabled = True
    issue.status = "open"
    issue.title = "Fix CI"

    run = MagicMock()
    run.id = 5
    run.issue_id = issue.id
    run.project_id = issue.project_id
    run.status = "collected"
    run.bundle_path = str(tmp_path)
    run.created_at = datetime(2026, 6, 25, 9, 0, 0)

    worker_profile = MagicMock()
    worker_profile.id = 11
    worker_profile.enabled = True
    provider = MagicMock()
    provider.id = 22
    provider.is_disabled = False

    db = MagicMock()
    db.add = MagicMock()
    db.flush = AsyncMock()
    db.commit = AsyncMock()
    db.rollback = AsyncMock()
    db.get = AsyncMock(side_effect=[run, issue])
    db.execute = AsyncMock()

    with patch("app.core.ci_failure_collector.resolve_worker_profile_for_issue", new=AsyncMock(return_value=worker_profile)), \
         patch("app.core.ci_failure_collector.resolve_provider_for_issue", new=AsyncMock(return_value=provider)), \
         patch("app.core.ci_failure_collector.replace_task_worker_snapshot", new=AsyncMock()), \
         patch("app.core.ci_failure_collector.select_snapshot_run_instruction_template", return_value="Repair {{issue_title}}"), \
         patch("app.core.ci_failure_collector.render_and_store_task_prompt"), \
         patch("app.core.ci_failure_collector._count_ci_auto_repair_attempts", new=AsyncMock(return_value=(0, {}))), \
         patch("app.core.ci_failure_collector.get_project_metadata", new=AsyncMock(return_value={})), \
         patch("app.core.ci_failure_collector.append_ci_failure_log", new=AsyncMock()):
        await process_ci_failure_run(
            db=db,
            run_id=run.id,
            settings=SimpleNamespace(ci_auto_repair_max_attempts=2),
        )

    task = db.add.call_args.args[0]
    assert task.worker_profile_id == 11
    assert task.provider_id == 22
```

- [ ] **Step 2: Run CI default test to verify it fails**

Run:

```bash
backend/.venv/bin/python -m pytest backend/tests/unit/test_ci_auto_repair_worker_defaults.py -q
```

Expected: FAIL until the actual function is adjusted and imports exist.

- [ ] **Step 3: Update CI auto-repair task creation**

In the function located in Step 1, import and use:

```python
from app.core.worker_profiles import (
    WorkerProfileValidationError,
    replace_task_worker_snapshot,
    resolve_provider_for_issue,
    resolve_worker_profile_for_issue,
    select_snapshot_run_instruction_template,
)
```

Before creating the repair task:

```python
try:
    worker_profile = await resolve_worker_profile_for_issue(
        db,
        issue,
        None,
        allow_system_default=False,
    )
    provider = await resolve_provider_for_issue(
        db,
        issue,
        None,
        allow_system_default=False,
    )
except WorkerProfileValidationError as exc:
    raise RuntimeError(f"CI auto-repair cannot start: {exc}") from exc
```

When constructing `Task`:

```python
provider_id=provider.id,
worker_profile_id=worker_profile.id,
trigger_source="ci_auto_repair",
```

After flush:

```python
snapshot = await replace_task_worker_snapshot(db, task, worker_profile)
template = select_snapshot_run_instruction_template(
    snapshot,
    task_mode=task.task_mode,
    trigger_source="ci_auto_repair",
)
render_and_store_task_prompt(
    task,
    issue,
    await get_project_metadata(issue.project_id),
    template,
)
```

- [ ] **Step 4: Run CI tests**

Run:

```bash
backend/.venv/bin/python -m pytest backend/tests/unit/test_ci_auto_repair_worker_defaults.py backend/tests/unit/test_task_analytics_api.py::test_retry_task_persists_manual_initiator_metadata -q
```

Expected: PASS.

- [ ] **Step 5: Commit CI auto-repair integration**

```bash
git add backend/app/core/ci_failure_collector.py backend/app/api/tasks.py backend/tests/unit/test_ci_auto_repair_worker_defaults.py
git commit -m "feat: use issue defaults for ci repair workers"
```

---

### Task 6: Add Frontend API Types and Worker Profile Client

**Files:**
- Modify: `frontend/src/api/index.ts`
- Test: compile-time via `npx vue-tsc --noEmit`

- [ ] **Step 1: Add frontend types**

Modify `frontend/src/api/index.ts`.

Add fields to `Issue`:

```ts
default_worker_profile_id: number | null
default_provider_id: number | null
default_worker_profile_name?: string | null
default_provider_name?: string | null
```

Add fields to `CreateIssueRequest`:

```ts
default_worker_profile_id?: number | null
default_provider_id?: number | null
```

Add fields to `Task`:

```ts
worker_profile_id: number | null
worker_profile_name?: string | null
worker_image?: string | null
worker_snapshot_created_at?: string | null
```

Change `CreateTaskRequest` provider and worker:

```ts
provider_id?: number | null
worker_profile_id?: number | null
```

Add field to `UpdateTaskRequest`:

```ts
worker_profile_id?: number | null
```

Add new interfaces:

```ts
export interface WorkerProfileEnvironmentVariable {
  id?: number
  key: string
  value: string | null
  is_secret: boolean
  value_configured: boolean
}

export interface WorkerProfileEnvironmentVariableUpdate {
  id?: number
  key: string
  value: string
  is_secret: boolean
}

export interface WorkerProfileMount {
  host_path: string
  container_path: string
  mode: 'ro' | 'rw'
}

export interface WorkerProfile {
  id: number
  name: string
  description: string | null
  enabled: boolean
  is_default: boolean
  image: string
  volume_mounts: WorkerProfileMount[]
  environment_variables: WorkerProfileEnvironmentVariable[]
  pre_script: string
  post_script: string
  default_execute_run_instruction_template: string
  default_plan_run_instruction_template: string
  ci_auto_repair_run_instruction_template: string
  created_at: string
  updated_at: string
}

export interface WorkerProfilePayload {
  name?: string
  description?: string | null
  enabled?: boolean
  image?: string
  volume_mounts?: WorkerProfileMount[]
  environment_variables?: WorkerProfileEnvironmentVariableUpdate[]
  pre_script?: string
  post_script?: string
  default_execute_run_instruction_template?: string
  default_plan_run_instruction_template?: string
  ci_auto_repair_run_instruction_template?: string
}
```

- [ ] **Step 2: Add API functions**

Add:

```ts
export async function getWorkerProfiles(): Promise<WorkerProfile[]> {
  const response = await api.get('/worker-profiles')
  return response.data
}

export async function createWorkerProfile(payload: WorkerProfilePayload): Promise<WorkerProfile> {
  const response = await api.post('/worker-profiles', payload)
  return response.data
}

export async function updateWorkerProfile(
  profileId: number,
  payload: WorkerProfilePayload
): Promise<WorkerProfile> {
  const response = await api.patch(`/worker-profiles/${profileId}`, payload)
  return response.data
}

export async function setDefaultWorkerProfile(profileId: number): Promise<WorkerProfile> {
  const response = await api.post(`/worker-profiles/${profileId}/set-default`)
  return response.data
}

export async function disableWorkerProfile(profileId: number): Promise<WorkerProfile> {
  const response = await api.post(`/worker-profiles/${profileId}/disable`)
  return response.data
}

export async function duplicateWorkerProfile(profileId: number): Promise<WorkerProfile> {
  const response = await api.post(`/worker-profiles/${profileId}/duplicate`)
  return response.data
}
```

- [ ] **Step 3: Run type check**

Run:

```bash
cd frontend && npx vue-tsc --noEmit
```

Expected: PASS. If TypeScript reports missing required task fields in test fixtures, update those fixtures in the reported spec files by adding `worker_profile_id: null`, `worker_profile_name: null`, `worker_image: null`, and `worker_snapshot_created_at: null`.

- [ ] **Step 4: Commit frontend API types**

```bash
git add frontend/src/api/index.ts frontend/src/**/*.spec.ts
git commit -m "feat: add worker profile frontend API"
```

---

### Task 7: Convert Worker Settings UI to Profile Manager

**Files:**
- Modify: `frontend/src/components/config/WorkerSettingsPanel.vue`
- Modify: `frontend/src/components/config/WorkerSettingsPanel.spec.ts`
- Modify: `frontend/src/i18n/messages/en.ts`
- Modify: `frontend/src/i18n/messages/zh-CN.ts`

- [ ] **Step 1: Update Worker settings tests**

Modify `frontend/src/components/config/WorkerSettingsPanel.spec.ts` to mock worker profile APIs and assert:

```ts
it('loads worker profiles and selects the default profile', async () => {
  mockApi.getWorkerProfiles.mockResolvedValue([
    {
      id: 1,
      name: 'Default Worker',
      description: null,
      enabled: true,
      is_default: true,
      image: 'codify-worker:latest',
      volume_mounts: [],
      environment_variables: [],
      pre_script: '',
      post_script: '',
      default_execute_run_instruction_template: 'Execute {{user_prompt}}',
      default_plan_run_instruction_template: 'Plan {{user_prompt}}',
      ci_auto_repair_run_instruction_template: 'Repair {{issue_title}}',
      created_at: '2026-06-25T00:00:00',
      updated_at: '2026-06-25T00:00:00'
    }
  ])

  const wrapper = mountPanel()
  await flushPromises()

  expect(mockApi.getWorkerProfiles).toHaveBeenCalled()
  expect(wrapper.text()).toContain('Default Worker')
  expect(wrapper.vm.workerFormValue.image).toBe('codify-worker:latest')
})

it('saves changes to the selected worker profile', async () => {
  await mountLoadedPanel()
  wrapper.vm.workerFormValue.image = 'codify-worker-java:latest'
  await wrapper.vm.handleSaveWorker()

  expect(mockApi.updateWorkerProfile).toHaveBeenCalledWith(
    1,
    expect.objectContaining({
      image: 'codify-worker-java:latest'
    })
  )
})
```

Use the existing spec helpers and extend the `vi.mock('../../api')` object with:

```ts
getWorkerProfiles: vi.fn(),
createWorkerProfile: vi.fn(),
updateWorkerProfile: vi.fn(),
setDefaultWorkerProfile: vi.fn(),
disableWorkerProfile: vi.fn(),
duplicateWorkerProfile: vi.fn(),
```

- [ ] **Step 2: Run Worker settings spec to verify it fails**

Run:

```bash
cd frontend && npx vitest run --config vitest.config.ts src/components/config/WorkerSettingsPanel.spec.ts
```

Expected: FAIL until component uses worker profile APIs.

- [ ] **Step 3: Update WorkerSettingsPanel imports**

In `frontend/src/components/config/WorkerSettingsPanel.vue`, replace runtime config worker imports with profile APIs:

```ts
import {
  getRunInstructionTemplateBuiltIns,
  getWorkerProfiles,
  updateWorkerProfile,
  createWorkerProfile,
  duplicateWorkerProfile,
  setDefaultWorkerProfile,
  disableWorkerProfile,
  type RunInstructionTemplateBuiltIns,
  type WorkerProfile,
  type WorkerProfileEnvironmentVariable,
  type WorkerProfileEnvironmentVariableUpdate,
  type WorkerProfileMount
} from '../../api'
```

- [ ] **Step 4: Replace form state with profile-backed state**

Use:

```ts
const workerProfiles = ref<WorkerProfile[]>([])
const selectedProfileId = ref<number | null>(null)

type WorkerFormValue = {
  name: string
  description: string | null
  enabled: boolean
  is_default: boolean
  image: string
  mounts: WorkerProfileMount[]
  environment_variables: EnvironmentVariableFormItem[]
  worker_pre_script: string
  worker_post_script: string
  default_execute_run_instruction_template: string
  default_plan_run_instruction_template: string
  ci_auto_repair_run_instruction_template: string
}
```

Map profile to form:

```ts
function mapProfileToWorkerFormValue(profile: WorkerProfile): WorkerFormValue {
  return {
    name: profile.name,
    description: profile.description,
    enabled: profile.enabled,
    is_default: profile.is_default,
    image: profile.image,
    mounts: profile.volume_mounts.map((mount) => ({ ...mount })),
    environment_variables: parseEnvironmentVariables(profile.environment_variables),
    worker_pre_script: profile.pre_script || '',
    worker_post_script: profile.post_script || '',
    default_execute_run_instruction_template: profile.default_execute_run_instruction_template || '',
    default_plan_run_instruction_template: profile.default_plan_run_instruction_template || '',
    ci_auto_repair_run_instruction_template: profile.ci_auto_repair_run_instruction_template || ''
  }
}
```

Save payload:

```ts
await updateWorkerProfile(selectedProfileId.value, {
  name: workerFormValue.value.name,
  description: workerFormValue.value.description,
  enabled: workerFormValue.value.enabled,
  image: workerFormValue.value.image,
  volume_mounts: workerFormValue.value.mounts.filter(m => m.host_path && m.container_path),
  environment_variables: serializeEnvironmentVariables(workerFormValue.value.environment_variables),
  pre_script: workerFormValue.value.worker_pre_script,
  post_script: workerFormValue.value.worker_post_script,
  default_execute_run_instruction_template: workerFormValue.value.default_execute_run_instruction_template,
  default_plan_run_instruction_template: workerFormValue.value.default_plan_run_instruction_template,
  ci_auto_repair_run_instruction_template: workerFormValue.value.ci_auto_repair_run_instruction_template
})
```

- [ ] **Step 5: Update template layout**

Add a compact profile list above the existing editor:

```vue
<div class="worker-profile-layout">
  <aside class="worker-profile-list">
    <button
      v-for="profile in workerProfiles"
      :key="profile.id"
      class="worker-profile-list__item"
      :class="{ 'worker-profile-list__item--active': profile.id === selectedProfileId }"
      @click="selectProfile(profile.id)"
    >
      <span>{{ profile.name }}</span>
      <n-tag v-if="profile.is_default" size="small" type="success" :bordered="false">
        {{ t('config.defaultWorkerProfile') }}
      </n-tag>
      <n-tag v-if="!profile.enabled" size="small" type="warning" :bordered="false">
        {{ t('config.disabled') }}
      </n-tag>
      <small>{{ profile.image }}</small>
    </button>
  </aside>
  <section class="worker-profile-editor">
    <!-- Keep existing compact mount/env/script/run-instruction sections here. -->
  </section>
</div>
```

Add profile metadata fields before mount section:

```vue
<n-grid :cols="isMobile ? 1 : 2" :x-gap="16" :y-gap="8">
  <n-gi>
    <n-form-item :label="t('config.workerProfileName')">
      <n-input v-model:value="workerFormValue.name" />
    </n-form-item>
  </n-gi>
  <n-gi>
    <n-form-item :label="t('config.workerProfileImage')">
      <n-input v-model:value="workerFormValue.image" />
    </n-form-item>
  </n-gi>
</n-grid>
```

- [ ] **Step 6: Add i18n keys**

Add to both locale files:

```ts
workerProfiles: 'Worker Profiles',
workerProfileName: 'Profile name',
workerProfileImage: 'Worker image',
defaultWorkerProfile: 'Default',
duplicateWorkerProfile: 'Duplicate',
setDefaultWorkerProfile: 'Set default',
disableWorkerProfile: 'Disable',
createWorkerProfile: 'Create profile',
```

Chinese:

```ts
workerProfiles: 'Worker 配置',
workerProfileName: '配置名称',
workerProfileImage: 'Worker 镜像',
defaultWorkerProfile: '默认',
duplicateWorkerProfile: '复制配置',
setDefaultWorkerProfile: '设为默认',
disableWorkerProfile: '禁用',
createWorkerProfile: '新建配置',
```

- [ ] **Step 7: Run Worker settings spec**

Run:

```bash
cd frontend && npx vitest run --config vitest.config.ts src/components/config/WorkerSettingsPanel.spec.ts
```

Expected: PASS.

- [ ] **Step 8: Commit Worker settings UI**

```bash
git add frontend/src/components/config/WorkerSettingsPanel.vue frontend/src/components/config/WorkerSettingsPanel.spec.ts frontend/src/i18n/messages/en.ts frontend/src/i18n/messages/zh-CN.ts
git commit -m "feat: manage worker profiles in config"
```

---

### Task 8: Add Issue and Task Worker Selection UI

**Files:**
- Modify: `frontend/src/views/CreateIssue.vue`
- Modify: `frontend/src/views/CreateIssue.spec.ts`
- Modify: `frontend/src/views/IssueView.vue`
- Modify: `frontend/src/views/IssueView.spec.ts`
- Modify: `frontend/src/components/TaskFormDrawer.vue`
- Modify: `frontend/src/components/TaskFormDrawer.spec.ts`
- Modify: `frontend/src/components/TaskMetadataPanel.vue`
- Modify: `frontend/src/i18n/messages/en.ts`
- Modify: `frontend/src/i18n/messages/zh-CN.ts`

- [ ] **Step 1: Update TaskFormDrawer tests**

Add to `frontend/src/components/TaskFormDrawer.spec.ts`:

```ts
it('creates task with selected worker profile', async () => {
  mockApi.getWorkerProfiles.mockResolvedValue([
    {
      id: 3,
      name: 'Java Worker',
      enabled: true,
      is_default: true,
      image: 'worker-java:latest',
      volume_mounts: [],
      environment_variables: [],
      pre_script: '',
      post_script: '',
      default_execute_run_instruction_template: 'Execute {{user_prompt}}',
      default_plan_run_instruction_template: 'Plan {{user_prompt}}',
      ci_auto_repair_run_instruction_template: 'Repair {{issue_title}}',
      created_at: '',
      updated_at: ''
    }
  ])

  const wrapper = await mountDrawer({ mode: 'create', issueId: 1 })
  await flushPromises()
  wrapper.vm.taskMode = 'execute'
  wrapper.vm.selectedWorkerProfileId = 3
  wrapper.vm.selectedProviderId = 7
  wrapper.vm.runInstructionTemplate = 'Execute {{user_prompt}}'
  await wrapper.vm.handleCreate()

  expect(mockApi.createTask).toHaveBeenCalledWith(
    expect.objectContaining({ worker_profile_id: 3 })
  )
})

it('keeps manually edited run instruction when worker changes', async () => {
  const wrapper = await mountDrawer({ mode: 'create', issueId: 1 })
  wrapper.vm.runInstructionTemplate = 'Custom instruction'
  wrapper.vm.runInstructionDirty = true
  wrapper.vm.handleWorkerProfileChange(4)
  expect(wrapper.vm.runInstructionTemplate).toBe('Custom instruction')
})
```

- [ ] **Step 2: Run TaskFormDrawer spec to verify it fails**

Run:

```bash
cd frontend && npx vitest run --config vitest.config.ts src/components/TaskFormDrawer.spec.ts
```

Expected: FAIL until worker profile select exists.

- [ ] **Step 3: Add worker profile loading to TaskFormDrawer**

Modify imports:

```ts
getWorkerProfiles,
type WorkerProfile,
```

Add state:

```ts
const workerProfiles = ref<WorkerProfile[]>([])
const selectedWorkerProfileId = ref<number | null>(null)
const selectableWorkerProfiles = computed(() =>
  workerProfiles.value.filter((profile) => {
    if (profile.enabled) return true
    return props.mode === 'edit' && profile.id === props.task?.worker_profile_id
  })
)
const workerProfileOptions = computed(() =>
  selectableWorkerProfiles.value.map(profile => ({
    label: `${profile.name} (${profile.image})${profile.is_default ? ' ★' : ''}`,
    value: profile.id,
    disabled: !profile.enabled
  }))
)
```

Add loader:

```ts
async function loadWorkerProfiles() {
  try {
    workerProfiles.value = await getWorkerProfiles()
  } catch { /* non-critical */ }
}
```

Call in `onMounted()`:

```ts
void loadWorkerProfiles()
```

Set defaults when drawer opens:

```ts
selectedWorkerProfileId.value = props.task?.worker_profile_id ?? null
```

For create mode, after profiles load:

```ts
if (props.mode === 'create' && selectedWorkerProfileId.value === null) {
  selectedWorkerProfileId.value =
    workerProfiles.value.find(profile => profile.is_default && profile.enabled)?.id ?? null
}
```

Add change handler:

```ts
function handleWorkerProfileChange(profileId: number | null) {
  selectedWorkerProfileId.value = profileId
  const profile = workerProfiles.value.find(item => item.id === profileId)
  if (!profile || !taskMode.value || runInstructionDirty.value) return
  runInstructionTemplate.value =
    taskMode.value === 'plan'
      ? profile.default_plan_run_instruction_template
      : profile.default_execute_run_instruction_template
  initialRunInstructionTemplate.value = runInstructionTemplate.value
  invalidateRunInstructionPreview()
}
```

Use selected profile in restore:

```ts
function restoreRunInstructionDefault() {
  if (!taskMode.value) return
  const selectedProfile = workerProfiles.value.find(item => item.id === selectedWorkerProfileId.value)
  const content = selectedProfile
    ? (taskMode.value === 'plan'
        ? selectedProfile.default_plan_run_instruction_template
        : selectedProfile.default_execute_run_instruction_template)
    : runInstructionDefaults.value?.[taskMode.value].content
  if (!content) return
  runInstructionTemplate.value = content
  runInstructionDirty.value = true
  invalidateRunInstructionPreview()
}
```

Include in create payload:

```ts
if (selectedWorkerProfileId.value !== null) req.worker_profile_id = selectedWorkerProfileId.value
```

Include in edit payload:

```ts
if ((selectedWorkerProfileId.value ?? null) !== (orig.worker_profile_id ?? null)) {
  payload.worker_profile_id = selectedWorkerProfileId.value
}
```

- [ ] **Step 4: Add worker select template**

Near provider selection:

```vue
<n-form-item :label="t('createTask.workerProfile')">
  <n-select
    v-model:value="selectedWorkerProfileId"
    :options="workerProfileOptions"
    :placeholder="t('createTask.selectWorkerProfile')"
    clearable
    @update:value="handleWorkerProfileChange"
  />
</n-form-item>
```

- [ ] **Step 5: Add issue create default controls**

In `frontend/src/views/CreateIssue.vue`, import `getWorkerProfiles`, `getProviders`, and add state:

```ts
const workerProfiles = ref<WorkerProfile[]>([])
const providers = ref<AIProvider[]>([])
const defaultWorkerProfileId = ref<number | null>(null)
const defaultProviderId = ref<number | null>(null)
```

Load and set defaults:

```ts
async function loadExecutionDefaults() {
  const [workerResult, providerResult] = await Promise.allSettled([
    getWorkerProfiles(),
    getProviders()
  ])
  if (workerResult.status === 'fulfilled') {
    workerProfiles.value = workerResult.value.filter(profile => profile.enabled)
    defaultWorkerProfileId.value =
      workerProfiles.value.find(profile => profile.is_default)?.id ?? null
  }
  if (providerResult.status === 'fulfilled') {
    providers.value = providerResult.value.filter(provider => !provider.is_disabled)
    defaultProviderId.value =
      providers.value.find(provider => provider.is_default)?.id ?? null
  }
}
```

Include in create issue payload:

```ts
default_worker_profile_id: defaultWorkerProfileId.value,
default_provider_id: defaultProviderId.value,
```

Add compact controls near branch/runtime options:

```vue
<n-form-item :label="t('createTask.defaultWorkerProfile')">
  <n-select v-model:value="defaultWorkerProfileId" :options="workerProfileOptions" />
</n-form-item>
<n-form-item :label="t('createTask.defaultProvider')">
  <n-select v-model:value="defaultProviderId" :options="providerOptions" />
</n-form-item>
```

- [ ] **Step 6: Add issue detail default controls**

In `frontend/src/views/IssueView.vue`, add a compact settings section or reuse existing execution controls. Update via existing `updateIssue()` API payload:

```ts
await updateIssue(issue.value.id, {
  default_worker_profile_id: issueDefaultWorkerProfileId.value,
  default_provider_id: issueDefaultProviderId.value
})
```

Use the same `getWorkerProfiles()` and `getProviders()` options.

- [ ] **Step 7: Add task metadata display**

In `frontend/src/components/TaskMetadataPanel.vue`, add rows:

```vue
<div v-if="task.worker_profile_name || task.worker_profile_id" class="metadata-row">
  <span>{{ t('taskView.workerProfile') }}</span>
  <span>{{ task.worker_profile_name || `#${task.worker_profile_id}` }}</span>
</div>
<div v-if="task.worker_image" class="metadata-row">
  <span>{{ t('taskView.workerImage') }}</span>
  <span>{{ task.worker_image }}</span>
</div>
```

- [ ] **Step 8: Add i18n keys**

Add:

```ts
createTask: {
  workerProfile: 'Worker',
  selectWorkerProfile: 'Select worker',
  defaultWorkerProfile: 'Default Worker',
  defaultProvider: 'Default AI Provider'
}
taskView: {
  workerProfile: 'Worker',
  workerImage: 'Worker image'
}
```

Chinese:

```ts
createTask: {
  workerProfile: 'Worker',
  selectWorkerProfile: '选择 Worker',
  defaultWorkerProfile: '默认 Worker',
  defaultProvider: '默认 AI Provider'
}
taskView: {
  workerProfile: 'Worker',
  workerImage: 'Worker 镜像'
}
```

- [ ] **Step 9: Run frontend tests**

Run:

```bash
cd frontend && npx vitest run --config vitest.config.ts src/components/TaskFormDrawer.spec.ts src/views/CreateIssue.spec.ts src/views/IssueView.spec.ts
```

Expected: PASS after fixture updates.

- [ ] **Step 10: Commit task/issue UI**

```bash
git add frontend/src/components/TaskFormDrawer.vue frontend/src/components/TaskFormDrawer.spec.ts frontend/src/views/CreateIssue.vue frontend/src/views/CreateIssue.spec.ts frontend/src/views/IssueView.vue frontend/src/views/IssueView.spec.ts frontend/src/components/TaskMetadataPanel.vue frontend/src/i18n/messages/en.ts frontend/src/i18n/messages/zh-CN.ts
git commit -m "feat: select workers on issues and tasks"
```

---

### Task 9: Documentation and Compatibility Cleanup

**Files:**
- Modify: `docs/worker-volume-mounts.md`
- Modify: `docs/USER_GUIDE.zh-CN.md`
- Test: `git diff --check`

- [ ] **Step 1: Update worker volume docs**

In `docs/worker-volume-mounts.md`, add a section after custom mounts:

```markdown
## Worker Profiles

New tasks no longer read custom mounts, custom environment variables, worker scripts, or run-instruction defaults directly from the global runtime config. They resolve a Worker Profile at task creation time and store a task-level worker snapshot.

Runtime volume order remains:

1. issue workspace mounts
2. Claude session/runtime/shared mounts
3. task worker snapshot custom mounts

The old global Worker fields are kept as migration source and compatibility surface for one release. New execution paths read `task_worker_profile_snapshots`.
```

- [ ] **Step 2: Update Chinese user guide**

In `docs/USER_GUIDE.zh-CN.md`, add concise text under configuration/task creation:

```markdown
### Worker 配置

管理员可以在系统配置中维护多个 Worker 配置。每个配置包含镜像、挂载、环境变量、运行前/运行后脚本和运行指令模板。

需求可以设置默认 Worker 和默认 AI Provider。新任务默认使用需求级设置，也可以在创建任务时覆盖。任务创建后会保存 Worker 快照，后续修改 Worker 配置不会影响已经创建的任务。
```

- [ ] **Step 3: Run docs diff check**

Run:

```bash
git diff --check -- docs/worker-volume-mounts.md docs/USER_GUIDE.zh-CN.md
```

Expected: PASS.

- [ ] **Step 4: Commit docs**

```bash
git add docs/worker-volume-mounts.md docs/USER_GUIDE.zh-CN.md
git commit -m "docs: document worker profiles"
```

---

### Task 10: Final Verification

**Files:**
- No planned source edits unless verification exposes defects.

- [ ] **Step 1: Run backend targeted tests**

Run:

```bash
backend/.venv/bin/python -m pytest \
  backend/tests/unit/test_worker_profiles_migration.py \
  backend/tests/unit/test_worker_profiles_core.py \
  backend/tests/unit/test_worker_profiles_api.py \
  backend/tests/unit/test_issue_worker_defaults.py \
  backend/tests/unit/test_task_worker_profile_selection.py \
  backend/tests/unit/test_worker_profile_runtime.py \
  backend/tests/unit/test_ci_auto_repair_worker_defaults.py \
  -q
```

Expected: PASS.

- [ ] **Step 2: Run broader backend worker/task regression slice**

Run:

```bash
backend/.venv/bin/python -m pytest \
  backend/tests/unit/test_task_analytics_api.py \
  backend/tests/unit/test_worker_coverage.py \
  backend/tests/unit/test_worker_coverage_ext.py \
  -q
```

Expected: PASS.

- [ ] **Step 3: Run frontend targeted tests**

Run:

```bash
cd frontend && npx vitest run --config vitest.config.ts \
  src/components/config/WorkerSettingsPanel.spec.ts \
  src/components/TaskFormDrawer.spec.ts \
  src/views/CreateIssue.spec.ts \
  src/views/IssueView.spec.ts
```

Expected: PASS.

- [ ] **Step 4: Run frontend typecheck and build**

Run:

```bash
cd frontend && npx vue-tsc --noEmit
cd frontend && npm run build
```

Expected: PASS.

- [ ] **Step 5: Run final diff check**

Run:

```bash
git diff --check
```

Expected: PASS.

- [ ] **Step 6: Final review**

Run:

```bash
git status -sb
git log --oneline -10
```

Expected: working tree contains only intentional follow-up changes, and the recent commits correspond to the task boundaries in this plan.
