"""Mock E2E tests for the GitLab webhook endpoint.

Tests the full HTTP → FastAPI → SQLite cycle for the ``POST /api/webhook/gitlab``
endpoint.  Only external dependencies (GitLab API) are mocked — the actual SQL
queries, webhook secret verification, user resolution, task creation, and HTTP
routing all execute for real against an in-memory SQLite database.

Endpoint under test:
  POST /api/webhook/gitlab

Key flows tested:
  - Webhook secret verification (global and per-project)
  - Issue note → @ai-bot command parsing → Task creation
  - MR note handling (continue-on-branch)
  - Cancel / Status commands
  - User resolution (create-or-match)
  - Edge cases: system notes, unsupported events, duplicate notes, etc.
"""

from __future__ import annotations

import os
import pytest
from unittest.mock import MagicMock, patch

from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, select
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    create_async_engine,
    async_sessionmaker,
)
from sqlalchemy.pool import StaticPool

# Ensure a usable encryption key is available for secret config persistence
os.environ.setdefault("CONFIG_ENCRYPTION_KEY", "test-webhook-e2e-key-32chars!!")

from app.database import get_db
from app.dependencies.auth import (
    get_optional_current_user,
    require_admin_user,
    require_authenticated_user,
)
from app.dependencies.project_access import (
    ProjectAccessScope,
    require_project_access_scope,
)
from app.main import app
from app.models import Base, Task, TaskStatus, User, ProjectWebhookConfig
from app.core.config_crypto import encrypt_config_secret


# ---------------------------------------------------------------------------
# Payload builders
# ---------------------------------------------------------------------------


def _make_issue_note_payload(
    *,
    note_body="@ai-bot implement the login feature",
    project_id=123,
    issue_id=456,
    issue_iid=7,
    note_id=1001,
    system=False,
    user_id=42,
    username="testuser",
    user_name="Test User",
    noteable_type="Issue",
):
    """Build a GitLab webhook payload for an issue note event."""
    return {
        "object_kind": "note",
        "event_type": "note",
        "user": {
            "id": user_id,
            "username": username,
            "name": user_name,
            "email": f"{username}@example.com",
        },
        "project": {
            "id": project_id,
            "name": "test-project",
            "path_with_namespace": "group/test-project",
        },
        "object_attributes": {
            "id": note_id,
            "note": note_body,
            "noteable_type": noteable_type,
            "system": system,
        },
        "issue": {
            "id": issue_id,
            "iid": issue_iid,
            "title": "Test Issue",
        },
    }


def _make_mr_note_payload(
    *,
    note_body="@ai-bot continue working on this",
    project_id=123,
    mr_iid=10,
    note_id=2001,
    system=False,
    user_id=42,
    username="testuser",
    user_name="Test User",
):
    """Build a GitLab webhook payload for a merge-request note event."""
    return {
        "object_kind": "note",
        "event_type": "note",
        "user": {
            "id": user_id,
            "username": username,
            "name": user_name,
            "email": f"{username}@example.com",
        },
        "project": {
            "id": project_id,
            "name": "test-project",
            "path_with_namespace": "group/test-project",
        },
        "object_attributes": {
            "id": note_id,
            "note": note_body,
            "noteable_type": "MergeRequest",
            "system": system,
        },
        "merge_request": {
            "iid": mr_iid,
            "title": "Test MR",
            "state": "opened",
        },
    }


def _make_push_payload(*, project_id=123):
    """Build a non-note event payload (push)."""
    return {
        "object_kind": "push",
        "event_type": "push",
        "project": {
            "id": project_id,
            "name": "test-project",
        },
    }


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
async def _test_engine():
    """In-memory SQLite async engine with all tables created."""
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )

    @event.listens_for(engine.sync_engine, "connect")
    def _register_pg_compat(dbapi_conn, connection_record):
        dbapi_conn.create_function("pg_advisory_xact_lock", 1, lambda _key: None)

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest.fixture()
async def session_factory(_test_engine):
    """Async session factory bound to the test engine."""
    return async_sessionmaker(
        _test_engine, class_=AsyncSession, expire_on_commit=False
    )


@pytest.fixture()
async def db_session(session_factory):
    """Session for direct data manipulation inside tests (seeding / assertions)."""
    async with session_factory() as session:
        yield session


@pytest.fixture()
def _mock_admin_user():
    """A mock admin user returned by admin-gated auth overrides."""
    user = MagicMock()
    user.id = 1
    user.username = "testadmin"
    user.gitlab_user_id = 100
    user.platform_role = "platform_admin"
    return user


@pytest.fixture()
async def client(session_factory, _mock_admin_user):
    """``httpx.AsyncClient`` wired to the FastAPI app with auth overrides."""

    async def _override_get_db():
        async with session_factory() as session:
            try:
                yield session
                await session.commit()
            except Exception:
                await session.rollback()
                raise

    access_scope = ProjectAccessScope(
        is_unrestricted=True, accessible_projects=[]
    )

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_optional_current_user] = lambda: None
    app.dependency_overrides[require_authenticated_user] = lambda: None
    app.dependency_overrides[require_admin_user] = lambda: _mock_admin_user
    app.dependency_overrides[require_project_access_scope] = lambda: access_scope

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


@pytest.fixture(autouse=True)
def _isolate_runtime_config():
    """Save / restore module-level _runtime_config between tests."""
    from app.config import _runtime_config

    saved = dict(_runtime_config)
    yield
    _runtime_config.clear()
    _runtime_config.update(saved)


@pytest.fixture()
def mock_gitlab():
    """Patch ``get_gitlab_client`` in the webhook module with a mock client.

    The mock is pre-configured with sensible defaults for:
    - ``get_issue()`` → returns a title + description dict
    - ``get_project()`` → returns a project-like object with ``default_branch``
    - ``create_note()`` / ``create_mr_note()`` → no-op
    - ``get_mr_by_iid()`` → returns an open MR dict
    """
    mock_client = MagicMock()

    # Issue lookup
    mock_client.get_issue.return_value = {
        "title": "Test Issue Title",
        "description": "Detailed issue description for testing.",
    }

    # Project lookup (for default branch resolution)
    mock_project = MagicMock()
    mock_project.default_branch = "main"
    mock_client.get_project.return_value = mock_project

    # Note creation (used by status/notification)
    mock_client.create_note.return_value = {"id": 9999}
    mock_client.create_mr_note.return_value = {"id": 9998}

    # MR lookup
    mock_client.get_mr_by_iid.return_value = {
        "state": "opened",
        "title": "Test MR Title",
        "source_branch": "codify/issue-7",
        "target_branch": "main",
    }

    with patch("app.api.webhook.get_gitlab_client", return_value=mock_client):
        yield mock_client


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _set_global_secret(secret: str) -> None:
    """Set the global GitLab webhook secret via runtime config."""
    from app.config import _runtime_config
    _runtime_config["gitlab_webhook_secret"] = secret


WEBHOOK_URL = "/api/webhook/gitlab"
GLOBAL_SECRET = "test-global-webhook-secret"


# ═══════════════════════════════════════════════════════════════════════════
# 1. Webhook Secret Verification
# ═══════════════════════════════════════════════════════════════════════════


class TestWebhookSecretVerification:
    """Verify token-based authentication on the webhook endpoint."""

    async def test_missing_token_when_secret_configured(self, client):
        """401 when global secret is set but X-Gitlab-Token header is missing."""
        _set_global_secret(GLOBAL_SECRET)
        payload = _make_issue_note_payload()
        resp = await client.post(WEBHOOK_URL, json=payload)
        assert resp.status_code == 401
        assert "Missing X-Gitlab-Token" in resp.json()["detail"]

    async def test_wrong_token_when_secret_configured(self, client):
        """401 when X-Gitlab-Token does not match the global secret."""
        _set_global_secret(GLOBAL_SECRET)
        payload = _make_issue_note_payload()
        resp = await client.post(
            WEBHOOK_URL,
            json=payload,
            headers={"X-Gitlab-Token": "wrong-secret"},
        )
        assert resp.status_code == 401
        assert "Invalid X-Gitlab-Token" in resp.json()["detail"]

    async def test_correct_global_token(self, client, mock_gitlab):
        """200 when X-Gitlab-Token matches the global secret."""
        _set_global_secret(GLOBAL_SECRET)
        payload = _make_issue_note_payload()
        resp = await client.post(
            WEBHOOK_URL,
            json=payload,
            headers={"X-Gitlab-Token": GLOBAL_SECRET},
        )
        assert resp.status_code == 200

    async def test_no_secret_configured_accepts_any_request(self, client, mock_gitlab):
        """200 when no global or per-project secret is configured (open mode)."""
        # Don't set any secret — verification is skipped
        payload = _make_issue_note_payload()
        resp = await client.post(WEBHOOK_URL, json=payload)
        assert resp.status_code == 200

    async def test_per_project_secret_overrides_global(self, client, db_session, mock_gitlab):
        """Per-project secret takes precedence over the global secret."""
        _set_global_secret(GLOBAL_SECRET)

        per_project_secret = "per-project-secret-value"
        encrypted = encrypt_config_secret(per_project_secret)
        db_session.add(ProjectWebhookConfig(
            project_id=123,
            secret_encrypted=encrypted,
        ))
        await db_session.commit()

        payload = _make_issue_note_payload(project_id=123)

        # Global secret should be rejected
        resp = await client.post(
            WEBHOOK_URL,
            json=payload,
            headers={"X-Gitlab-Token": GLOBAL_SECRET},
        )
        assert resp.status_code == 401

        # Per-project secret should be accepted
        resp = await client.post(
            WEBHOOK_URL,
            json=payload,
            headers={"X-Gitlab-Token": per_project_secret},
        )
        assert resp.status_code == 200

    async def test_per_project_secret_without_global(self, client, db_session, mock_gitlab):
        """Per-project secret works when no global secret is configured."""
        per_project_secret = "project-only-secret"
        encrypted = encrypt_config_secret(per_project_secret)
        db_session.add(ProjectWebhookConfig(
            project_id=123,
            secret_encrypted=encrypted,
        ))
        await db_session.commit()

        payload = _make_issue_note_payload(project_id=123)

        # Missing token → 401
        resp = await client.post(WEBHOOK_URL, json=payload)
        assert resp.status_code == 401

        # Correct per-project token → 200
        resp = await client.post(
            WEBHOOK_URL,
            json=payload,
            headers={"X-Gitlab-Token": per_project_secret},
        )
        assert resp.status_code == 200

    async def test_unknown_project_falls_back_to_global(self, client, mock_gitlab):
        """A project without a per-project secret falls back to the global one."""
        _set_global_secret(GLOBAL_SECRET)
        # Project 999 has no per-project config
        payload = _make_issue_note_payload(project_id=999)
        resp = await client.post(
            WEBHOOK_URL,
            json=payload,
            headers={"X-Gitlab-Token": GLOBAL_SECRET},
        )
        assert resp.status_code == 200


# ═══════════════════════════════════════════════════════════════════════════
# 2. Webhook Payload Parsing
# ═══════════════════════════════════════════════════════════════════════════


class TestWebhookPayloadParsing:
    """Verify correct routing and parsing of incoming webhook payloads."""

    async def test_push_event_ignored(self, client, mock_gitlab):
        """Non-note events are acknowledged but ignored."""
        payload = _make_push_payload()
        resp = await client.post(WEBHOOK_URL, json=payload)
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ignored"
        assert "not supported" in body["reason"]

    async def test_system_note_ignored(self, client, mock_gitlab):
        """System-generated notes (e.g. 'closed issue') are ignored."""
        payload = _make_issue_note_payload(system=True)
        resp = await client.post(WEBHOOK_URL, json=payload)
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ignored"
        assert "system note" in body["reason"]

    async def test_no_ai_bot_mention_ignored(self, client, mock_gitlab):
        """A regular comment without @ai-bot is ignored."""
        payload = _make_issue_note_payload(note_body="Just a regular comment, nothing to see here.")
        resp = await client.post(WEBHOOK_URL, json=payload)
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ignored"
        assert "no @ai-bot command" in body["reason"]

    async def test_unsupported_noteable_type_ignored(self, client, mock_gitlab):
        """A note on an unsupported noteable type (e.g. Snippet) is ignored."""
        payload = _make_issue_note_payload(noteable_type="Snippet")
        resp = await client.post(WEBHOOK_URL, json=payload)
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ignored"
        assert "noteable_type" in body["reason"]

    async def test_empty_note_body_no_command(self, client, mock_gitlab):
        """An empty comment body results in 'no @ai-bot command'."""
        payload = _make_issue_note_payload(note_body="")
        resp = await client.post(WEBHOOK_URL, json=payload)
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ignored"

    async def test_valid_issue_note_creates_task(self, client, mock_gitlab, db_session):
        """An issue note with @ai-bot command creates a task."""
        payload = _make_issue_note_payload(note_body="@ai-bot implement the login feature")
        resp = await client.post(WEBHOOK_URL, json=payload)
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "success"
        assert "task_id" in body

        # Verify task was persisted
        result = await db_session.execute(select(Task))
        tasks = result.scalars().all()
        assert len(tasks) == 1
        assert tasks[0].project_id == 123
        assert tasks[0].issue_iid == 7
        assert tasks[0].note_id == 1001

    async def test_ci_bot_alias_accepted(self, client, mock_gitlab, db_session):
        """The @ci-bot alias is accepted the same as @ai-bot."""
        payload = _make_issue_note_payload(note_body="@ci-bot implement this feature")
        resp = await client.post(WEBHOOK_URL, json=payload)
        assert resp.status_code == 200
        assert resp.json()["status"] == "success"

    async def test_ci_underscore_bot_alias_accepted(self, client, mock_gitlab, db_session):
        """The @ci_bot alias is also accepted."""
        payload = _make_issue_note_payload(note_body="@ci_bot fix this bug", note_id=1099)
        resp = await client.post(WEBHOOK_URL, json=payload)
        assert resp.status_code == 200
        assert resp.json()["status"] == "success"


# ═══════════════════════════════════════════════════════════════════════════
# 3. Task Creation
# ═══════════════════════════════════════════════════════════════════════════


class TestTaskCreation:
    """Verify Task records created by the webhook handler."""

    async def test_task_fields_populated_correctly(self, client, mock_gitlab, db_session):
        """All core task fields are set from the webhook payload."""
        payload = _make_issue_note_payload(
            note_body="@ai-bot build the API endpoint",
            project_id=123,
            issue_id=456,
            issue_iid=7,
            note_id=3001,
            user_id=42,
            username="coder",
        )
        resp = await client.post(WEBHOOK_URL, json=payload)
        assert resp.status_code == 200
        task_id = resp.json()["task_id"]

        result = await db_session.execute(select(Task).where(Task.id == task_id))
        task = result.scalar_one()

        assert task.project_id == 123
        assert task.issue_id == 456
        assert task.issue_iid == 7
        assert task.note_id == 3001
        assert task.status == TaskStatus.PENDING
        assert task.branch_name == "codify/issue-7"
        assert task.initiator_gitlab_user_id == 42
        assert task.initiator_username == "coder"
        assert task.target_branch == "main"  # from mock_gitlab.get_project().default_branch

    async def test_prompt_includes_issue_context(self, client, mock_gitlab, db_session):
        """When user gives an explicit prompt, issue context is appended."""
        payload = _make_issue_note_payload(
            note_body="@ai-bot add unit tests for the parser",
            note_id=3002,
        )
        resp = await client.post(WEBHOOK_URL, json=payload)
        assert resp.status_code == 200

        result = await db_session.execute(select(Task).where(Task.note_id == 3002))
        task = result.scalar_one()

        # Prompt should contain both user instruction and issue context
        assert "add unit tests for the parser" in task.user_prompt
        assert "Test Issue Title" in task.user_prompt

    async def test_generic_prompt_uses_issue_details(self, client, mock_gitlab, db_session):
        """A bare @ai-bot trigger uses the issue title/description as the prompt."""
        payload = _make_issue_note_payload(
            note_body="@ai-bot",
            note_id=3003,
        )
        resp = await client.post(WEBHOOK_URL, json=payload)
        assert resp.status_code == 200

        result = await db_session.execute(select(Task).where(Task.note_id == 3003))
        task = result.scalar_one()

        assert "Test Issue Title" in task.user_prompt
        assert "Detailed issue description" in task.user_prompt

    async def test_priority_parameter_parsed(self, client, mock_gitlab, db_session):
        """@ai-bot priority=high sets high priority on the task."""
        payload = _make_issue_note_payload(
            note_body="@ai-bot priority=high build the feature",
            note_id=3004,
        )
        resp = await client.post(WEBHOOK_URL, json=payload)
        assert resp.status_code == 200
        assert resp.json()["priority"] == 2  # PRIORITY_HIGH

        result = await db_session.execute(select(Task).where(Task.note_id == 3004))
        task = result.scalar_one()
        assert task.priority == 2

    async def test_target_branch_parameter(self, client, mock_gitlab, db_session):
        """@ai-bot target=develop overrides the project default branch."""
        payload = _make_issue_note_payload(
            note_body="@ai-bot target=develop implement feature",
            note_id=3005,
        )
        resp = await client.post(WEBHOOK_URL, json=payload)
        assert resp.status_code == 200

        result = await db_session.execute(select(Task).where(Task.note_id == 3005))
        task = result.scalar_one()
        assert task.target_branch == "develop"

    async def test_duplicate_note_id_returns_duplicate(self, client, mock_gitlab, db_session):
        """Sending the same note_id twice is idempotent — second call returns 'duplicate'."""
        payload = _make_issue_note_payload(note_id=3006)
        resp1 = await client.post(WEBHOOK_URL, json=payload)
        assert resp1.status_code == 200
        assert resp1.json()["status"] == "success"

        resp2 = await client.post(WEBHOOK_URL, json=payload)
        assert resp2.status_code == 200
        assert resp2.json()["status"] == "duplicate"

        # Only one task should exist
        result = await db_session.execute(select(Task).where(Task.note_id == 3006))
        tasks = result.scalars().all()
        assert len(tasks) == 1

    async def test_task_default_status_is_pending(self, client, mock_gitlab, db_session):
        """Newly created tasks start with PENDING status."""
        payload = _make_issue_note_payload(note_id=3007)
        resp = await client.post(WEBHOOK_URL, json=payload)
        assert resp.status_code == 200

        result = await db_session.execute(select(Task).where(Task.note_id == 3007))
        task = result.scalar_one()
        assert task.status == TaskStatus.PENDING

    async def test_gitlab_issue_fetch_failure_uses_original_prompt(
        self, client, mock_gitlab, db_session
    ):
        """When GitLab issue fetch fails, the original user prompt is kept."""
        mock_gitlab.get_issue.side_effect = Exception("GitLab unreachable")

        payload = _make_issue_note_payload(
            note_body="@ai-bot fix the login bug",
            note_id=3008,
        )
        resp = await client.post(WEBHOOK_URL, json=payload)
        assert resp.status_code == 200

        result = await db_session.execute(select(Task).where(Task.note_id == 3008))
        task = result.scalar_one()
        assert "fix the login bug" in task.user_prompt

    async def test_gitlab_project_fetch_failure_uses_default_branch(
        self, client, mock_gitlab, db_session
    ):
        """When GitLab project fetch fails, system default branch is used."""
        mock_gitlab.get_project.side_effect = Exception("GitLab unreachable")

        payload = _make_issue_note_payload(
            note_body="@ai-bot implement search",
            note_id=3009,
        )
        resp = await client.post(WEBHOOK_URL, json=payload)
        assert resp.status_code == 200

        result = await db_session.execute(select(Task).where(Task.note_id == 3009))
        task = result.scalar_one()
        # Falls back to settings.default_target_branch (which defaults to "main")
        assert task.target_branch is not None


# ═══════════════════════════════════════════════════════════════════════════
# 4. User Resolution
# ═══════════════════════════════════════════════════════════════════════════


class TestUserResolution:
    """Verify the webhook resolves / creates User records for initiators."""

    async def test_new_user_created_on_first_webhook(self, client, mock_gitlab, db_session):
        """A new GitLab user in the webhook payload gets a User record created."""
        payload = _make_issue_note_payload(
            user_id=500,
            username="newdev",
            user_name="New Developer",
            note_id=4001,
        )
        resp = await client.post(WEBHOOK_URL, json=payload)
        assert resp.status_code == 200

        result = await db_session.execute(
            select(User).where(User.gitlab_user_id == 500)
        )
        user = result.scalar_one()
        assert user.username == "newdev"
        assert user.display_name == "New Developer"
        assert user.auth_provider == "gitlab_oidc"
        assert user.platform_role == "viewer"

    async def test_existing_user_matched(self, client, mock_gitlab, db_session):
        """An existing user (by gitlab_user_id) is re-used, not duplicated."""
        # Pre-create the user
        existing = User(
            username="existingdev",
            display_name="Existing Dev",
            gitlab_user_id=600,
            auth_provider="gitlab_oidc",
            platform_role="platform_user",
        )
        db_session.add(existing)
        await db_session.commit()
        await db_session.refresh(existing)
        existing_id = existing.id

        payload = _make_issue_note_payload(
            user_id=600,
            username="existingdev",
            note_id=4002,
        )
        resp = await client.post(WEBHOOK_URL, json=payload)
        assert resp.status_code == 200

        task_id = resp.json()["task_id"]
        result = await db_session.execute(select(Task).where(Task.id == task_id))
        task = result.scalar_one()
        assert task.initiator_user_id == existing_id

        # No duplicate user created
        result = await db_session.execute(
            select(User).where(User.gitlab_user_id == 600)
        )
        users = result.scalars().all()
        assert len(users) == 1

    async def test_user_without_username_gets_fallback(self, client, mock_gitlab, db_session):
        """A webhook user missing 'username' gets a generated fallback name."""
        payload = _make_issue_note_payload(note_id=4003)
        # Remove username from the payload
        payload["user"]["username"] = None
        resp = await client.post(WEBHOOK_URL, json=payload)
        assert resp.status_code == 200

        result = await db_session.execute(
            select(User).where(User.gitlab_user_id == 42)
        )
        user = result.scalar_one()
        assert user.username == "gitlab_user_42"

    async def test_task_links_to_created_user(self, client, mock_gitlab, db_session):
        """The created task's initiator_user_id references the resolved User."""
        payload = _make_issue_note_payload(user_id=700, username="linker", note_id=4004)
        resp = await client.post(WEBHOOK_URL, json=payload)
        assert resp.status_code == 200

        task_id = resp.json()["task_id"]
        result = await db_session.execute(select(Task).where(Task.id == task_id))
        task = result.scalar_one()
        assert task.initiator_user_id is not None
        assert task.initiator_gitlab_user_id == 700

        result = await db_session.execute(
            select(User).where(User.id == task.initiator_user_id)
        )
        user = result.scalar_one()
        assert user.gitlab_user_id == 700


# ═══════════════════════════════════════════════════════════════════════════
# 5. Cancel & Status Commands
# ═══════════════════════════════════════════════════════════════════════════


class TestCancelCommand:
    """Verify @ai-bot cancel handling."""

    async def test_cancel_running_task(self, client, mock_gitlab, db_session):
        """Cancel marks a RUNNING task as CANCELLED."""
        # Create a running task first
        task = Task(
            project_id=123, issue_id=456, issue_iid=7, note_id=5000,
            user_prompt="test", status=TaskStatus.RUNNING,
            branch_name="codify/issue-7",
        )
        db_session.add(task)
        await db_session.commit()
        await db_session.refresh(task)

        payload = _make_issue_note_payload(note_body="@ai-bot cancel", note_id=5001)
        resp = await client.post(WEBHOOK_URL, json=payload)
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "success"
        assert "cancelled" in body["message"].lower() or "Cancelled" in body["message"]

        await db_session.refresh(task)
        assert task.status == TaskStatus.CANCELLED

    async def test_cancel_pending_tasks(self, client, mock_gitlab, db_session):
        """Cancel marks PENDING / QUEUED tasks as CANCELLED."""
        task1 = Task(
            project_id=123, issue_id=456, issue_iid=7, note_id=5010,
            user_prompt="test1", status=TaskStatus.PENDING,
            branch_name="codify/issue-7",
        )
        task2 = Task(
            project_id=123, issue_id=456, issue_iid=7, note_id=5011,
            user_prompt="test2", status=TaskStatus.QUEUED,
            branch_name="codify/issue-7",
        )
        db_session.add_all([task1, task2])
        await db_session.commit()

        payload = _make_issue_note_payload(note_body="@ai-bot cancel", note_id=5012)
        resp = await client.post(WEBHOOK_URL, json=payload)
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "success"
        assert "2" in body["message"]

    async def test_cancel_no_tasks_found(self, client, mock_gitlab):
        """Cancel when no running/pending tasks → ignored."""
        payload = _make_issue_note_payload(note_body="@ai-bot cancel", note_id=5020)
        resp = await client.post(WEBHOOK_URL, json=payload)
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ignored"


class TestStatusCommand:
    """Verify @ai-bot status handling."""

    async def test_status_returns_latest_task(self, client, mock_gitlab, db_session):
        """Status returns info about the latest task for the issue."""
        task = Task(
            project_id=123, issue_id=456, issue_iid=7, note_id=6000,
            user_prompt="test", status=TaskStatus.COMPLETED,
            branch_name="codify/issue-7",
            merge_request_url="https://gitlab.example.com/mr/1",
        )
        db_session.add(task)
        await db_session.commit()
        await db_session.refresh(task)

        payload = _make_issue_note_payload(note_body="@ai-bot status", note_id=6001)
        resp = await client.post(WEBHOOK_URL, json=payload)
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "success"
        assert body["task"]["status"] == "completed"

    async def test_status_no_tasks_found(self, client, mock_gitlab):
        """Status when no tasks exist → ignored."""
        payload = _make_issue_note_payload(note_body="@ai-bot status", note_id=6010)
        resp = await client.post(WEBHOOK_URL, json=payload)
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ignored"

    async def test_status_failed_task_includes_error(self, client, mock_gitlab, db_session):
        """Status for a failed task includes the error message."""
        task = Task(
            project_id=123, issue_id=456, issue_iid=7, note_id=6020,
            user_prompt="test", status=TaskStatus.FAILED,
            branch_name="codify/issue-7",
            error_message="Container exited with code 1",
        )
        db_session.add(task)
        await db_session.commit()

        payload = _make_issue_note_payload(note_body="@ai-bot status", note_id=6021)
        resp = await client.post(WEBHOOK_URL, json=payload)
        assert resp.status_code == 200
        body = resp.json()
        assert body["task"]["error"] == "Container exited with code 1"


# ═══════════════════════════════════════════════════════════════════════════
# 6. MR Comment Handling
# ═══════════════════════════════════════════════════════════════════════════


class TestMRCommentHandling:
    """Verify webhook handling for notes on merge requests."""

    async def test_mr_comment_creates_task_on_existing_branch(
        self, client, mock_gitlab, db_session
    ):
        """An @ai-bot command on an MR creates a task continuing on the parent branch."""
        # First, create a completed parent task linked to this MR
        parent = Task(
            project_id=123, issue_id=456, issue_iid=7, note_id=7000,
            user_prompt="original", status=TaskStatus.COMPLETED,
            branch_name="codify/issue-7",
            merge_request_iid=10,
            target_branch="main",
        )
        db_session.add(parent)
        await db_session.commit()

        payload = _make_mr_note_payload(
            note_body="@ai-bot fix the test failures",
            mr_iid=10,
            note_id=7001,
        )
        resp = await client.post(WEBHOOK_URL, json=payload)
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "success"
        assert "task_id" in body

        result = await db_session.execute(select(Task).where(Task.note_id == 7001))
        task = result.scalar_one()
        assert task.branch_name == "codify/issue-7"  # continues parent branch
        assert task.merge_request_iid == 10
        assert task.target_branch == "main"

    async def test_mr_comment_no_parent_task(self, client, mock_gitlab):
        """MR comment with no associated task returns a helpful message."""
        payload = _make_mr_note_payload(note_id=7010, mr_iid=99)
        resp = await client.post(WEBHOOK_URL, json=payload)
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ignored"
        assert "No completed task found" in body["reason"]

    async def test_mr_comment_parent_still_running(self, client, mock_gitlab, db_session):
        """MR comment when parent task is still running → wait message."""
        parent = Task(
            project_id=123, issue_id=456, issue_iid=7, note_id=7020,
            user_prompt="running", status=TaskStatus.RUNNING,
            branch_name="codify/issue-7",
            merge_request_iid=10,
        )
        db_session.add(parent)
        await db_session.commit()

        payload = _make_mr_note_payload(note_id=7021, mr_iid=10)
        resp = await client.post(WEBHOOK_URL, json=payload)
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ignored"
        assert "still" in body["reason"].lower()

    async def test_mr_comment_no_ai_bot_ignored(self, client, mock_gitlab):
        """An MR comment without @ai-bot mention is ignored."""
        payload = _make_mr_note_payload(note_body="LGTM, great work!", note_id=7030)
        resp = await client.post(WEBHOOK_URL, json=payload)
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "ignored"

    async def test_mr_cancel_command(self, client, mock_gitlab, db_session):
        """@ai-bot cancel on an MR cancels the associated running task."""
        task = Task(
            project_id=123, issue_id=456, issue_iid=7, note_id=7040,
            user_prompt="test", status=TaskStatus.RUNNING,
            branch_name="codify/issue-7",
            merge_request_iid=10,
        )
        db_session.add(task)
        await db_session.commit()
        await db_session.refresh(task)

        payload = _make_mr_note_payload(
            note_body="@ai-bot cancel",
            mr_iid=10,
            note_id=7041,
        )
        resp = await client.post(WEBHOOK_URL, json=payload)
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "success"

        await db_session.refresh(task)
        assert task.status == TaskStatus.CANCELLED


# ═══════════════════════════════════════════════════════════════════════════
# 7. Edge Cases
# ═══════════════════════════════════════════════════════════════════════════


class TestEdgeCases:
    """Assorted edge cases and error-handling paths."""

    async def test_invalid_json_body(self, client):
        """Non-JSON request body returns 400."""
        resp = await client.post(
            WEBHOOK_URL,
            content=b"this is not json",
            headers={"Content-Type": "application/json"},
        )
        assert resp.status_code == 400
        assert "Invalid JSON" in resp.json()["detail"]

    async def test_missing_required_fields_for_issue_comment(self, client, mock_gitlab):
        """Webhook with missing project/issue ids returns 400."""
        payload = _make_issue_note_payload()
        # Remove critical fields
        payload["project"]["id"] = None
        payload["issue"]["id"] = None
        payload["issue"]["iid"] = None

        resp = await client.post(WEBHOOK_URL, json=payload)
        assert resp.status_code == 400
        assert "Missing required fields" in resp.json()["detail"]

    async def test_very_long_prompt(self, client, mock_gitlab, db_session):
        """A very long prompt text is stored successfully."""
        long_text = "x" * 10_000
        payload = _make_issue_note_payload(
            note_body=f"@ai-bot {long_text}",
            note_id=8001,
        )
        resp = await client.post(WEBHOOK_URL, json=payload)
        assert resp.status_code == 200
        assert resp.json()["status"] == "success"

        result = await db_session.execute(select(Task).where(Task.note_id == 8001))
        task = result.scalar_one()
        assert len(task.user_prompt) >= 10_000

    async def test_special_characters_in_prompt(self, client, mock_gitlab, db_session):
        """Special characters (unicode, quotes, backticks) are preserved."""
        special_prompt = '@ai-bot 实现登录功能 with "quotes" and `backticks` & <tags>'
        payload = _make_issue_note_payload(
            note_body=special_prompt,
            note_id=8002,
        )
        resp = await client.post(WEBHOOK_URL, json=payload)
        assert resp.status_code == 200
        assert resp.json()["status"] == "success"

        result = await db_session.execute(select(Task).where(Task.note_id == 8002))
        task = result.scalar_one()
        assert "实现登录功能" in task.user_prompt

    async def test_missing_user_in_payload(self, client, mock_gitlab, db_session):
        """Webhook without a user object still creates a task (user optional)."""
        payload = _make_issue_note_payload(note_id=8003)
        payload.pop("user", None)  # Remove user entirely
        resp = await client.post(WEBHOOK_URL, json=payload)
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "success"

        result = await db_session.execute(select(Task).where(Task.note_id == 8003))
        task = result.scalar_one()
        assert task.initiator_user_id is None
        assert task.initiator_gitlab_user_id is None

    async def test_payload_with_no_project_id(self, client):
        """Webhook with missing project.id but a configured secret still verifies token."""
        _set_global_secret(GLOBAL_SECRET)
        payload = {
            "object_kind": "push",
            "project": {},  # No ID
        }
        # Should still require token (falls back to global)
        resp = await client.post(WEBHOOK_URL, json=payload)
        assert resp.status_code == 401

    async def test_colon_format_ai_bot_command(self, client, mock_gitlab, db_session):
        """The '@ai-bot: prompt' format (with colon) is accepted."""
        payload = _make_issue_note_payload(
            note_body="@ai-bot: please implement the dashboard",
            note_id=8004,
        )
        resp = await client.post(WEBHOOK_URL, json=payload)
        assert resp.status_code == 200
        assert resp.json()["status"] == "success"

        result = await db_session.execute(select(Task).where(Task.note_id == 8004))
        task = result.scalar_one()
        assert "implement the dashboard" in task.user_prompt
